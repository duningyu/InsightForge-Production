from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.capability_probe import CapabilityReport
from app.services.credential_store import CredentialStore


class MemoryCredentialBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


class FakeAdapter:
    def __init__(self, **configuration: object) -> None:
        self.configuration = configuration
        self.closed = False
        self.probe_calls = 0
        self.live_check_calls = 0

    def probe(self) -> CapabilityReport:
        self.probe_calls += 1
        return CapabilityReport(
            basic_chat="supported",
            structured_json="supported",
            function_calling="unknown",
            streaming="unknown",
            checked_at=datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc),
        )

    def live_check(self):
        from types import SimpleNamespace
        self.live_check_calls += 1
        payload = {
            "provider": str(self.configuration["provider"]),
            "status": "PASS",
            "model_requested": str(self.configuration["model"]),
            "model_returned": str(self.configuration["model"]),
            "latency_ms": 21,
            "content_received": True,
            "usage_available": True,
            "error_code": None,
            "safe_message": "Provider returned a valid minimal chat response.",
            "retryable": False,
            "secret_exposed": False,
        }
        return SimpleNamespace(as_dict=lambda: dict(payload))

    def close(self) -> None:
        self.closed = True


class BrokenCredentialBackend(MemoryCredentialBackend):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError(f"backend rejected {password}")


class StaleCredentialStore:
    def configured(self, _credential_ref: str | None) -> bool:
        return True

    def resolve(self, credential_ref: str) -> str:
        raise KeyError(credential_ref)


@pytest.fixture()
def model_api(tmp_path):
    from app.main import create_app

    backend = MemoryCredentialBackend()
    adapters: list[FakeAdapter] = []

    def adapter_factory(**configuration: object) -> FakeAdapter:
        adapter = FakeAdapter(**configuration)
        adapters.append(adapter)
        return adapter

    application = create_app(database_path=tmp_path / "model-api.sqlite3", seed=False)
    with TestClient(application) as client:
        service = getattr(application.state, "model_profiles", None)
        if service is not None:
            service.credential_store = CredentialStore(backend=backend)
            service.adapter_factory = adapter_factory
        yield client, backend, adapters


def _create_profile(client: TestClient, **overrides: object):
    payload: dict[str, object] = {
        "display_name": "Primary Qwen",
        "provider": "qwen",
        "model_id": "qwen-plus",
        "api_key": "first-secret",
    }
    payload.update(overrides)
    return client.post("/api/settings/model-profiles", json=payload)


def _assert_public_profile(profile: dict[str, object], *, credential_status: str = "configured") -> None:
    assert profile["credential_status"] == credential_status
    forbidden = {"api_key", "credential_ref", "masked_key", "masked_api_key", "key_fragment", "last_four"}
    assert forbidden.isdisjoint(profile)


def test_model_profile_crud_returns_only_sanitized_public_fields(model_api):
    client, _backend, _adapters = model_api

    created = _create_profile(client)
    assert created.status_code == 201
    profile = created.json()
    _assert_public_profile(profile)
    assert profile["provider"] == "qwen"
    assert profile["protocol"] == "openai_chat_completions"
    assert profile["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert profile["revision"] == 1

    listed = client.get("/api/settings/model-profiles")
    assert listed.status_code == 200
    assert listed.json() == [profile]

    updated = client.patch(
        f"/api/settings/model-profiles/{profile['id']}",
        json={"display_name": "Renamed Qwen", "model_id": "qwen-max"},
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Renamed Qwen"
    assert updated.json()["model_id"] == "qwen-max"
    assert updated.json()["revision"] == 2
    _assert_public_profile(updated.json())

    rejected = client.patch(
        f"/api/settings/model-profiles/{profile['id']}",
        json={"credential_ref": "not-a-public-field"},
    )
    assert rejected.status_code == 422

    deleted = client.delete(f"/api/settings/model-profiles/{profile['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/settings/model-profiles").json() == []


def test_update_omitted_or_empty_key_keeps_existing_and_nonempty_key_replaces_it(model_api):
    client, backend, _adapters = model_api
    created = _create_profile(client)
    profile_id = created.json()["id"]
    stored_key = next(iter(backend.values))
    assert backend.values[stored_key] == "first-secret"

    omitted = client.patch(
        f"/api/settings/model-profiles/{profile_id}", json={"display_name": "Omitted key"}
    )
    assert omitted.status_code == 200
    assert backend.values[stored_key] == "first-secret"

    empty = client.patch(
        f"/api/settings/model-profiles/{profile_id}", json={"api_key": ""}
    )
    assert empty.status_code == 200
    assert backend.values[stored_key] == "first-secret"

    replaced = client.patch(
        f"/api/settings/model-profiles/{profile_id}", json={"api_key": "replacement-secret"}
    )
    assert replaced.status_code == 200
    assert backend.values[stored_key] == "replacement-secret"
    _assert_public_profile(replaced.json())


def test_set_default_is_unique_and_rejects_default_profile_deletion(model_api):
    client, _backend, _adapters = model_api
    first_id = _create_profile(client, display_name="First").json()["id"]
    second_id = _create_profile(client, display_name="Second", api_key="second-secret").json()["id"]

    assert client.post(f"/api/settings/model-profiles/{first_id}/set-default").status_code == 200
    second_default = client.post(f"/api/settings/model-profiles/{second_id}/set-default")
    assert second_default.status_code == 200

    profiles = client.get("/api/settings/model-profiles").json()
    assert [(item["id"], item["is_default"]) for item in profiles] == [
        (first_id, False),
        (second_id, True),
    ]
    conflict = client.delete(f"/api/settings/model-profiles/{second_id}")
    assert conflict.status_code == 409


def test_disabled_profile_cannot_be_selected_as_default_or_project_override(model_api):
    client, _backend, _adapters = model_api
    disabled_id = _create_profile(client, display_name="Disabled", enabled=False).json()["id"]
    project_id = client.post("/api/projects", json={"title": "P", "summary": "S"}).json()["id"]

    default_response = client.post(f"/api/settings/model-profiles/{disabled_id}/set-default")
    assert default_response.status_code == 409
    override_response = client.put(
        f"/api/projects/{project_id}/model-profile", json={"profile_id": disabled_id}
    )
    assert override_response.status_code == 409


def test_project_override_blocks_deletion_until_explicitly_cleared(model_api):
    client, _backend, _adapters = model_api
    profile_id = _create_profile(client).json()["id"]
    project_id = client.post(
        "/api/projects", json={"title": "Override project", "summary": "Uses one profile"}
    ).json()["id"]

    selected = client.put(
        f"/api/projects/{project_id}/model-profile", json={"profile_id": profile_id}
    )
    assert selected.status_code == 200
    assert selected.json() == {"project_id": project_id, "profile_id": profile_id}
    assert client.delete(f"/api/settings/model-profiles/{profile_id}").status_code == 409

    cleared = client.put(
        f"/api/projects/{project_id}/model-profile", json={"profile_id": None}
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"project_id": project_id, "profile_id": None}
    assert client.delete(f"/api/settings/model-profiles/{profile_id}").status_code == 204


def test_connection_uses_injected_adapter_and_persists_capability_status(model_api):
    client, _backend, adapters = model_api
    # This test verifies connection-result persistence, not TTL expiry.
    # Keep the service clock inside the capability TTL relative to the
    # deterministic FakeAdapter.probe() timestamp.
    service = client.app.state.model_profiles
    service.clock = lambda: datetime(
        2026, 8, 28, 8, 0, 1, tzinfo=timezone.utc
    )

    profile_id = _create_profile(client).json()["id"]

    tested = client.post(f"/api/settings/model-profiles/{profile_id}/test")
    assert tested.status_code == 200
    body = tested.json()
    assert body["last_test_status"] == "passed"
    assert body["last_tested_at"] == "2026-08-28T08:00:00+00:00"
    assert body["capabilities"] == {
        "basic_chat": "supported",
        "structured_json": "supported",
        "function_calling": "unknown",
        "streaming": "unknown",
    }
    _assert_public_profile(body)
    assert len(adapters) == 1
    assert adapters[0].configuration["api_key"] == "first-secret"
    assert adapters[0].closed is True


def test_capabilities_expire_after_bounded_ttl_with_ui_safe_status(model_api):
    client, _backend, _adapters = model_api
    service = client.app.state.model_profiles
    service.clock = lambda: datetime(2026, 8, 29, 7, 59, 59, tzinfo=timezone.utc)
    profile_id = _create_profile(client).json()["id"]
    assert client.post(
        f"/api/settings/model-profiles/{profile_id}/test"
    ).status_code == 200

    fresh = client.get("/api/settings/model-profiles").json()[0]
    assert fresh["capabilities"]["basic_chat"] == "supported"
    assert fresh["last_test_status"] == "passed"

    service.clock = lambda: datetime(2026, 8, 29, 8, 0, 1, tzinfo=timezone.utc)
    expired = client.get("/api/settings/model-profiles").json()[0]
    assert expired["capabilities"] == {
        "basic_chat": "unknown",
        "structured_json": "unknown",
        "function_calling": "unknown",
        "streaming": "unknown",
    }
    assert expired["last_test_status"] == "expired"
    assert expired["capabilities_checked_at"] == "2026-08-28T08:00:00+00:00"


def test_relevant_profile_changes_invalidate_capability_results(model_api):
    client, _backend, _adapters = model_api
    service = client.app.state.model_profiles
    service.clock = lambda: datetime(2026, 8, 28, 8, 1, tzinfo=timezone.utc)

    profile_id = _create_profile(client).json()["id"]
    relevant_updates = [
        {"api_key": "replacement-secret"},
        {"model_id": "qwen-max"},
        {"provider": "deepseek"},
    ]
    for update in relevant_updates:
        assert client.post(
            f"/api/settings/model-profiles/{profile_id}/test"
        ).status_code == 200
        changed = client.patch(
            f"/api/settings/model-profiles/{profile_id}", json=update
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["capabilities"] == {}
        assert changed.json()["capabilities_checked_at"] is None
        assert changed.json()["last_test_status"] is None
        assert changed.json()["last_tested_at"] is None

    custom = _create_profile(
        client,
        display_name="Custom",
        provider="custom",
        protocol="openai_chat_completions",
        base_url="https://gateway-one.invalid/v1",
        model_id="custom-model",
        api_key="custom-secret",
    ).json()
    for update in (
        {"base_url": "https://gateway-two.invalid/v1"},
        {"protocol": "anthropic_messages"},
    ):
        assert client.post(
            f"/api/settings/model-profiles/{custom['id']}/test"
        ).status_code == 200
        changed = client.patch(
            f"/api/settings/model-profiles/{custom['id']}", json=update
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["capabilities"] == {}
        assert changed.json()["capabilities_checked_at"] is None


def test_preset_profile_api_rejects_endpoint_overrides_and_keeps_safe_audit_identity(
    model_api,
):
    client, _backend, _adapters = model_api
    sentinel_url = "https://sk-SENTINEL-ENDPOINT.invalid/v1"

    for override in (
        {"base_url": sentinel_url},
        {"protocol": "anthropic_messages"},
    ):
        rejected = _create_profile(client, **override)
        assert rejected.status_code == 422
        assert sentinel_url not in json.dumps(
            client.get("/api/audit").json(), ensure_ascii=False
        )

    created = _create_profile(client).json()
    for override in (
        {"base_url": sentinel_url},
        {"protocol": "anthropic_messages"},
    ):
        rejected = client.patch(
            f"/api/settings/model-profiles/{created['id']}", json=override
        )
        assert rejected.status_code == 422

    internal = client.app.state.db.fetch_one(
        "SELECT provider, protocol, base_url FROM model_profiles WHERE id = ?",
        (created["id"],),
    )
    assert internal == {
        "provider": "qwen",
        "protocol": "openai_chat_completions",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    audit = client.app.state.db.fetch_one(
        "SELECT payload_json FROM audit_events WHERE entity_id = ? ORDER BY created_at LIMIT 1",
        (created["id"],),
    )
    assert json.loads(audit["payload_json"])["provider"] == "qwen"
    assert sentinel_url not in audit["payload_json"]


def test_sentinel_key_never_reaches_json_sqlite_audit_or_logs(model_api, caplog):
    client, _backend, _adapters = model_api
    sentinel = "sk-SENTINEL-TASK4-NEVER-SERIALIZE"
    caplog.set_level(logging.DEBUG)
    responses = [
        _create_profile(client, api_key=sentinel),
    ]
    profile_id = responses[0].json()["id"]
    responses.extend(
        [
            client.patch(f"/api/settings/model-profiles/{profile_id}", json={"api_key": ""}),
            client.post(f"/api/settings/model-profiles/{profile_id}/test"),
            client.get("/api/settings/model-profiles"),
        ]
    )
    assert all(response.status_code < 400 for response in responses)
    assert sentinel not in json.dumps([response.json() for response in responses], ensure_ascii=False)

    database_path = client.app.state.db.path
    with sqlite3.connect(database_path) as connection:
        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        text_cells: list[str] = []
        for table_name in table_names:
            text_columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table_name}")')
                if str(row[2]).upper().startswith("TEXT")
            ]
            if text_columns:
                quoted_columns = ", ".join(f'"{column}"' for column in text_columns)
                for row in connection.execute(f'SELECT {quoted_columns} FROM "{table_name}"'):
                    text_cells.extend(str(value) for value in row if value is not None)
    assert all(sentinel not in cell for cell in text_cells)
    assert sentinel not in caplog.text

    audits = client.app.state.db.fetch_all(
        "SELECT action, payload_json FROM audit_events WHERE entity_type='model_profile' ORDER BY created_at"
    )
    assert audits
    for audit in audits:
        payload = json.loads(audit["payload_json"])
        assert set(payload) == {"provider", "model", "revision", "action"}
        assert payload["action"] == audit["action"]
        assert sentinel not in audit["payload_json"]


def test_credential_failures_return_only_safe_errors(model_api):
    client, _backend, _adapters = model_api
    sentinel = "sk-SENTINEL-BACKEND-FAILURE"
    client.app.state.model_profiles.credential_store = CredentialStore(
        backend=BrokenCredentialBackend()
    )

    unavailable = _create_profile(client, api_key=sentinel)
    assert unavailable.status_code == 503
    assert sentinel not in unavailable.text

    client.app.state.model_profiles.credential_store = CredentialStore(
        backend=MemoryCredentialBackend()
    )
    profile_id = _create_profile(client).json()["id"]
    client.app.state.model_profiles.credential_store = StaleCredentialStore()
    missing = client.post(f"/api/settings/model-profiles/{profile_id}/test")
    assert missing.status_code == 409
    assert "credential_ref" not in missing.text
    assert "insightforge:model-profile:" not in missing.text


def test_update_rejects_explicit_null_for_required_configuration(model_api):
    client, _backend, _adapters = model_api
    profile_id = _create_profile(client).json()["id"]

    response = client.patch(
        f"/api/settings/model-profiles/{profile_id}", json={"display_name": None}
    )
    assert response.status_code == 422


def test_profile_without_api_key_reports_missing_without_opening_a_backend(model_api):
    client, _backend, _adapters = model_api
    client.app.state.model_profiles._credential_store = None

    response = _create_profile(client, api_key="")
    assert response.status_code == 201
    _assert_public_profile(response.json(), credential_status="missing")


def test_stale_credential_can_be_repaired_by_explicit_replacement(model_api):
    client, backend, _adapters = model_api
    profile_id = _create_profile(client).json()["id"]
    backend.values.clear()

    replaced = client.patch(
        f"/api/settings/model-profiles/{profile_id}",
        json={"api_key": "replacement-after-stale-secret"},
    )

    assert replaced.status_code == 200
    assert replaced.json()["credential_status"] == "configured"
    assert list(backend.values.values()) == ["replacement-after-stale-secret"]


def test_stale_replacement_is_deleted_when_sqlite_update_rolls_back(model_api):
    client, backend, _adapters = model_api
    profile_id = _create_profile(client).json()["id"]
    backend.values.clear()
    client.app.state.db.execute(
        """CREATE TRIGGER fail_model_profile_update
        BEFORE UPDATE ON model_profiles
        BEGIN
            SELECT RAISE(ABORT, 'forced profile update failure');
        END"""
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced profile update failure"):
        client.app.state.model_profiles.update(
            profile_id,
            changes={"api_key": "replacement-that-must-be-removed"},
        )

    assert backend.values == {}
    assert client.app.state.db.fetch_one(
        "SELECT revision FROM model_profiles WHERE id = ?", (profile_id,)
    ) == {"revision": 1}


def test_selected_or_default_profile_cannot_be_disabled(model_api):
    client, _backend, _adapters = model_api
    project_profile_id = _create_profile(client, display_name="Project selected").json()["id"]
    default_profile_id = _create_profile(
        client, display_name="Default selected", api_key="default-secret"
    ).json()["id"]
    project_id = client.post(
        "/api/projects", json={"title": "Invariant", "summary": "Selected profile"}
    ).json()["id"]
    assert client.put(
        f"/api/projects/{project_id}/model-profile",
        json={"profile_id": project_profile_id},
    ).status_code == 200
    assert client.post(
        f"/api/settings/model-profiles/{default_profile_id}/set-default"
    ).status_code == 200

    for profile_id in (project_profile_id, default_profile_id):
        response = client.patch(
            f"/api/settings/model-profiles/{profile_id}", json={"enabled": False}
        )
        assert response.status_code == 409

    profiles = {item["id"]: item for item in client.get("/api/settings/model-profiles").json()}
    assert profiles[project_profile_id]["enabled"] is True
    assert profiles[default_profile_id]["enabled"] is True
    assert profiles[default_profile_id]["is_default"] is True


def test_referenced_and_default_delete_conflicts_leave_profiles_intact(model_api):
    client, _backend, _adapters = model_api
    referenced_id = _create_profile(client, display_name="Referenced").json()["id"]
    default_id = _create_profile(
        client, display_name="Default", api_key="default-secret"
    ).json()["id"]
    project_id = client.post(
        "/api/projects", json={"title": "References", "summary": "Deletion invariant"}
    ).json()["id"]
    client.put(
        f"/api/projects/{project_id}/model-profile", json={"profile_id": referenced_id}
    )
    client.post(f"/api/settings/model-profiles/{default_id}/set-default")

    assert client.delete(f"/api/settings/model-profiles/{referenced_id}").status_code == 409
    assert client.delete(f"/api/settings/model-profiles/{default_id}").status_code == 409
    remaining_ids = {
        item["id"] for item in client.get("/api/settings/model-profiles").json()
    }
    assert {referenced_id, default_id} <= remaining_ids


def test_model_profile_requests_do_not_coerce_input_types(model_api):
    client, _backend, _adapters = model_api
    create_response = _create_profile(client, enabled=1)
    assert create_response.status_code == 422

    profile_id = _create_profile(client).json()["id"]
    update_response = client.patch(
        f"/api/settings/model-profiles/{profile_id}", json={"enabled": 0}
    )
    assert update_response.status_code == 422

    project_id = client.post(
        "/api/projects", json={"title": "Strict", "summary": "Request typing"}
    ).json()["id"]
    override_response = client.put(
        f"/api/projects/{project_id}/model-profile", json={"profile_id": 123}
    )
    assert override_response.status_code == 422


@pytest.mark.parametrize("malformed_key", [
    ["sk-SENTINEL-MALFORMED-CREDENTIAL"],
    {"nested": {"value": "sk-SENTINEL-MALFORMED-CREDENTIAL"}},
])
@pytest.mark.parametrize("operation", ["create", "update"])
def test_malformed_api_key_validation_never_reflects_secret_input(
    model_api, caplog, malformed_key, operation
):
    client, _backend, _adapters = model_api
    sentinel = "sk-SENTINEL-MALFORMED-CREDENTIAL"
    caplog.set_level(logging.DEBUG)

    if operation == "create":
        response = _create_profile(client, api_key=malformed_key, enabled=1)
    else:
        profile_id = _create_profile(client).json()["id"]
        response = client.patch(
            f"/api/settings/model-profiles/{profile_id}",
            json={"api_key": malformed_key, "enabled": 1},
        )

    assert response.status_code == 422
    assert sentinel not in response.text
    errors = response.json()["detail"]
    credential_errors = [
        error for error in errors if "api_key" in error.get("loc", [])
    ]
    assert credential_errors
    assert all("input" not in error and "ctx" not in error for error in credential_errors)
    unrelated_errors = [
        error for error in errors if "enabled" in error.get("loc", [])
    ]
    assert unrelated_errors
    assert unrelated_errors[0]["input"] == 1
    assert sentinel not in caplog.text

    with sqlite3.connect(client.app.state.db.path) as connection:
        dump = "\n".join(connection.iterdump())
    assert sentinel not in dump


@pytest.mark.parametrize("field", ["display_name", "model_id"])
def test_create_rejects_whitespace_only_identity_fields(model_api, field):
    client, _backend, _adapters = model_api
    response = _create_profile(client, **{field: " \t\r\n "})
    assert response.status_code == 422
    assert client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS count FROM model_profiles"
    ) == {"count": 0}


@pytest.mark.parametrize("field", ["display_name", "model_id"])
def test_update_rejects_whitespace_only_identity_fields(model_api, field):
    client, _backend, _adapters = model_api
    created = _create_profile(client).json()

    response = client.patch(
        f"/api/settings/model-profiles/{created['id']}", json={field: "   "}
    )

    assert response.status_code == 422
    unchanged = client.get("/api/settings/model-profiles").json()[0]
    assert unchanged[field] == created[field]
    assert unchanged["revision"] == 1


@pytest.mark.parametrize("payload", [{}, {"api_key": ""}])
def test_noop_patch_does_not_create_revision_or_audit(model_api, payload):
    client, _backend, _adapters = model_api
    created = _create_profile(client).json()
    audit_count = client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS count FROM audit_events WHERE entity_id = ?",
        (created["id"],),
    )["count"]

    response = client.patch(
        f"/api/settings/model-profiles/{created['id']}", json=payload
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 1
    assert response.json()["updated_at"] == created["updated_at"]
    assert client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS count FROM model_profile_revisions WHERE profile_id = ?",
        (created["id"],),
    ) == {"count": 1}
    assert client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS count FROM audit_events WHERE entity_id = ?",
        (created["id"],),
    ) == {"count": audit_count}



def test_live_connection_requires_explicit_true_confirmation(model_api):
    client, _backend, adapters = model_api
    profile_id = _create_profile(client).json()["id"]

    rejected = client.post(
        f"/api/settings/model-profiles/{profile_id}/live-test",
        json={"confirm_live_call": False},
    )

    assert rejected.status_code == 422
    assert adapters == []


def test_live_connection_uses_exactly_one_live_check_and_persists_safe_operational_metadata(model_api):
    client, _backend, adapters = model_api
    profile_id = _create_profile(client).json()["id"]

    response = client.post(
        f"/api/settings/model-profiles/{profile_id}/live-test",
        json={"confirm_live_call": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "profile_id": profile_id,
        "provider": "qwen",
        "status": "PASS",
        "model_requested": "qwen-plus",
        "model_returned": "qwen-plus",
        "latency_ms": 21,
        "content_received": True,
        "usage_available": True,
        "error_code": None,
        "safe_message": "Provider returned a valid minimal chat response.",
        "retryable": False,
            "checked_at": body["checked_at"],
            "secret_exposed": False,
            "safe_diagnostic": None,
        }
    assert len(adapters) == 1
    assert adapters[0].live_check_calls == 1
    assert adapters[0].probe_calls == 0
    assert adapters[0].closed is True

    public = client.get("/api/settings/model-profiles").json()[0]
    assert public["last_live_test_status"] == "passed"
    assert public["last_live_latency_ms"] == 21
    assert public["last_live_error_code"] is None
    assert public["last_live_model_returned"] == "qwen-plus"
    assert public["last_live_tested_at"] == body["checked_at"]
    assert public["capabilities"] == {}
    assert public["last_test_status"] is None
    serialized = json.dumps({"response": body, "profile": public}, ensure_ascii=False)
    assert "first-secret" not in serialized


def test_live_connection_failure_is_returned_as_safe_result_not_raw_provider_exception(model_api):
    client, _backend, _adapters = model_api
    from types import SimpleNamespace

    class FailingLiveAdapter(FakeAdapter):
        def live_check(self):
            self.live_check_calls += 1
            payload = {
                "provider": str(self.configuration["provider"]),
                "status": "FAIL",
                "model_requested": str(self.configuration["model"]),
                "model_returned": None,
                "latency_ms": 19,
                "content_received": False,
                "usage_available": False,
                "error_code": "unauthorized",
                "safe_message": "Provider authentication was rejected.",
                "retryable": False,
                "secret_exposed": False,
            }
            return SimpleNamespace(as_dict=lambda: dict(payload))

    client.app.state.model_profiles.adapter_factory = FailingLiveAdapter
    profile_id = _create_profile(client).json()["id"]
    response = client.post(
        f"/api/settings/model-profiles/{profile_id}/live-test",
        json={"confirm_live_call": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAIL"
    assert body["error_code"] == "unauthorized"
    assert body["safe_message"] == "Provider authentication was rejected."
    assert body["secret_exposed"] is False
    public = client.get("/api/settings/model-profiles").json()[0]
    assert public["last_live_test_status"] == "failed"
    assert public["last_live_error_code"] == "unauthorized"
