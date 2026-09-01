from __future__ import annotations

import json
from pathlib import Path
import pytest

from app.db import Database
from app.main import create_app
from app.services.ai_runtime import build_structured_runtime
from app.services.ai_runtime import ManagedQwenStructuredRuntime
from app.errors import BetaDailyLimitReached
from app.services.legacy_migration import LegacyMigrationService


def test_managed_qwen_runtime_is_real_provider_runtime_and_has_no_demo_fallback(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = build_structured_runtime(
        mode="managed_qwen",
        model="qwen3.7-flash",
        api_key="test-managed-secret",
    )
    assert runtime.mode == "managed_qwen"
    assert runtime.provider == "qwen"
    assert runtime.model == "qwen3.7-flash"
    assert runtime.provider != "fixture"


def test_managed_quota_guard_runs_before_provider_adapter():
    adapter_calls = []

    def adapter_factory(**_kwargs):
        adapter_calls.append(True)
        raise AssertionError("provider adapter must not be constructed after quota denial")

    def deny(_operation):
        raise BetaDailyLimitReached(
            operation="solution_generation", limit=3, used=3, reset_at="tomorrow"
        )

    runtime = ManagedQwenStructuredRuntime(
        model="qwen3.7-flash",
        api_key="test-managed-secret",
        adapter_factory=adapter_factory,
        before_provider_call=deny,
    )
    from app.schemas import IdeaBriefDraft

    try:
        runtime.design_solutions(
            IdeaBriefDraft(
                original_idea="idea",
                target_user="user",
                problem="problem",
                desired_outcome="outcome",
                unknowns=[],
                provenance={},
            )
        )
    except BetaDailyLimitReached:
        pass
    assert adapter_calls == []


def test_legacy_migration_creates_unconfirmed_brief_idempotently(tmp_path: Path):
    db = Database(tmp_path / "legacy.sqlite3")
    db.init_schema()
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        ("legacy", "Legacy", "Legacy summary", "active", "2026-09-01", "2026-09-01"),
    )
    db.execute(
        """
        INSERT INTO project_canvas(
            project_id,version,problem,target_users,goals_json,non_goals_json,
            success_metrics_json,constraints_json,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "legacy", 1, "A concrete problem", "A concrete user",
            json.dumps(["A measurable outcome"]), "[]", "[]", "[]",
            "2026-09-01", "2026-09-01",
        ),
    )
    service = LegacyMigrationService(db)
    service.migrate_project("legacy")
    service.migrate_project("legacy")
    brief = db.fetch_one(
        "SELECT confirmation_status FROM idea_briefs WHERE project_id=?",
        ("legacy",),
    )
    assert brief["confirmation_status"] == "inferred"
    assert db.fetch_one(
        "SELECT COUNT(*) AS n FROM idea_briefs WHERE project_id=?", ("legacy",)
    )["n"] == 1


def test_managed_beta_settings_are_read_only_and_do_not_expose_provider_controls(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.setenv("BETA_MANAGED_MODE", "true")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", "beta_001")
    monkeypatch.setenv("MANAGED_QWEN_API_KEY", "test-managed-secret")
    client = create_app(database_path=tmp_path / "managed.sqlite3", seed=False)
    from fastapi.testclient import TestClient

    with TestClient(client) as test_client:
        settings = test_client.get("/api/settings/model-profiles")
        assert settings.status_code == 200
        body = settings.json()
        assert len(body) == 1
        assert body[0]["provider"] == "qwen"
        assert body[0]["model_id"] == "qwen3.7-flash"
        assert "api_key" not in json.dumps(body)
    assert test_client.post(
            "/api/settings/model-profiles",
            json={"display_name": "x", "provider": "qwen", "model_id": "x"},
        ).status_code == 409


def test_zero_candidate_recovery_is_not_reported_as_201_success(client, monkeypatch):
    project_id = "project_zero_candidate_recovery"
    recovery = {
        "error_code": "MODEL_OUTPUT_SCHEMA_INVALID",
        "message": "模型暂时无法完成生成，你的输入已保留。",
        "recovery_actions": ["稍后重试"],
        "preserved_input": {"original_idea": "sanitized"},
    }
    monkeypatch.setattr(
        client.app.state.solution_design,
        "generate",
        lambda _project_id, actor: recovery,
    )

    response = client.post(f"/api/projects/{project_id}/solutions/generate")

    assert response.status_code == 503
    assert response.json() == recovery
    assert "candidates" not in response.json()


def test_zero_candidate_solution_run_cannot_remain_successful(db):
    from app.schemas import SolutionSetDraft
    from app.services.solution_design import SolutionDesignService

    project_id = "project_zero_candidate_run"
    now = "2026-09-01T00:00:00+00:00"
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, "Zero candidate", "Zero candidate", "active", now, now),
    )
    db.execute(
        """
        INSERT INTO idea_briefs(
            id, project_id, version, original_idea, target_user, problem,
            desired_outcome, known_resources_json, constraints_json, unknowns_json,
            provenance_json, confirmation_status, created_at
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
        """,
        (
            "brief_zero_candidate", project_id, "idea", "user", "problem", "outcome",
            "[]", "[]", "[]", "{}", now,
        ),
    )

    class EmptyRuntime:
        provider = "qwen"
        model = "qwen3.7-flash"
        prompt_version = "test"
        schema_version = "test"
        mode = "managed_qwen"
        model_rounds_used = 1
        max_model_rounds = 1
        max_tool_rounds = 0

        def design_solutions(self, _brief):
            return SolutionSetDraft.model_construct(candidates=[], llm_core_required=False)

    service = SolutionDesignService(db, EmptyRuntime())
    with pytest.raises(ValueError):
        service.generate(project_id, actor="tester")

    row = db.fetch_one(
        "SELECT status FROM solution_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    assert row["status"].startswith("failed_")
    assert db.fetch_one(
        "SELECT COUNT(*) AS n FROM solution_candidates WHERE project_id = ?", (project_id,)
    )["n"] == 0


def test_provider_503_returns_user_safe_retryable_error_without_success_run(db):
    from app.services.provider_adapters import ProviderCallError
    from app.services.ai_runtime import ManagedQwenStructuredRuntime
    from app.services.solution_design import SolutionDesignService

    project_id = "project_provider_503"
    now = "2026-09-01T00:00:00+00:00"
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, "Provider 503", "Provider 503", "active", now, now),
    )
    db.execute(
        """
        INSERT INTO idea_briefs(
            id, project_id, version, original_idea, target_user, problem,
            desired_outcome, known_resources_json, constraints_json, unknowns_json,
            provenance_json, confirmation_status, created_at
        ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'confirmed', ?)
        """,
        ("brief_provider_503", project_id, "idea", "user", "problem", "outcome", "[]", "[]", "[]", "{}", now),
    )

    class FailingAdapter:
        def design_solutions(self, _brief):
            raise ProviderCallError(
                "provider_error",
                "Provider request failed.",
                True,
                safe_diagnostic={
                    "provider_error_source": "UPSTREAM_HTTP_503",
                    "provider_error_code": "NO_UPSTREAM_ERROR_CODE",
                    "provider_http_status": 503,
                    "provider_exception_class": None,
                    "provider_failure_stage": "provider_http_response",
                    "provider_retryable": True,
                    "provider_retry_after_seconds_if_present": None,
                },
            )
        def close(self):
            pass

    runtime = ManagedQwenStructuredRuntime(
        model="qwen3.7-flash", api_key="test-managed-secret",
        adapter_factory=lambda **_kwargs: FailingAdapter(),
    )
    result = SolutionDesignService(db, runtime).generate(project_id, actor="tester")

    assert result["error_code"] == "MODEL_PROVIDER_ERROR"
    assert result["message"] == "AI 服务暂时繁忙，你的项目内容已保存，请稍后重试。"
    assert "稍后重试" in result["recovery_actions"]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM solution_runs WHERE project_id=?", (project_id,))["n"] == 0
    audit = db.fetch_one(
        "SELECT payload_json FROM audit_events WHERE action='solution_generation_recovery_required' AND entity_id=?",
        (project_id,),
    )
    payload = json.loads(audit["payload_json"])
    assert payload["provider_error_source"] == "UPSTREAM_HTTP_503"
    assert payload["provider_error_code"] == "NO_UPSTREAM_ERROR_CODE"
    assert "provider_error_details" not in json.dumps(result, ensure_ascii=False)
