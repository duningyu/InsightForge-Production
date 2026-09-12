from __future__ import annotations

from typing import Any

import pytest

from app.errors import StructuredOutputContractError, StructuredRuntimeUnavailableError
from app.services.generation_contracts import GenerationContractError


PRIVATE_MARKERS = (
    "stage-b-private-input",
    "bearer stage-b-secret",
    "traceback (most recent call last)",
    "jsondecodeerror",
    "validationerror",
    "runtimeerror: stage-b-provider-secret",
)
DENIED_KEYS = {
    "rawresponse",
    "providerpayload",
    "providerraw",
    "authorization",
    "apikey",
    "debugprompt",
    "systemprompt",
    "prompt",
    "prompts",
    "traceback",
    "exception",
    "exceptiondump",
    "preservedinput",
    "safediagnostic",
}


def _walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}.{key}", key, item
            yield from _walk(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk(item, f"{path}[{index}]")


def _assert_safe_failure(payload: dict[str, Any]) -> None:
    for path, key, _value in _walk(payload):
        normalized = "".join(character for character in str(key).lower() if character.isalnum())
        assert normalized not in DENIED_KEYS, f"denied key at {path}: {payload!r}"
    rendered = str(payload).lower()
    for marker in PRIVATE_MARKERS:
        assert marker not in rendered, payload
    assert payload["error_code"]
    assert payload.get("message") or payload.get("detail")
    assert payload["content_written"] is False
    assert payload["retryable"] is True
    assert payload["recovery_actions"]


def _project(client) -> str:
    response = client.post(
        "/api/projects/quick-start",
        json={
            "idea": "帮小型便利店减少缺货",
            "target_user": None,
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["project_id"]


class _FailingReferenceRuntime:
    def __init__(self, error):
        self.error = error

    def generate_ai_reference(self, _context):
        raise self.error


class _FakeRuntimeRouter:
    mode = "fake"

    def __init__(self, error):
        self.runtime = _FailingReferenceRuntime(error)

    def for_project(self, *_args, **_kwargs):
        return self.runtime


@pytest.mark.parametrize(
    "error",
    (
        StructuredOutputContractError(
            preserved_input={
                "raw_response": "stage-b-private-input",
                "authorization": "Bearer stage-b-secret",
                "traceback": "Traceback (most recent call last): JSONDecodeError ValidationError",
            }
        ),
        GenerationContractError("SURFACE_SCHEMA_FAILED"),
        StructuredRuntimeUnavailableError(
            "RuntimeError: stage-b-provider-secret; Authorization: Bearer stage-b-secret"
        ),
    ),
    ids=("parse_failure", "schema_failure", "provider_failure"),
)
def test_generation_error_handler_exposes_only_safe_failure_semantics(
    client, monkeypatch, error
):
    project_id = _project(client)

    monkeypatch.setattr(client.app.state, "structured_runtime", _FakeRuntimeRouter(error))
    response = client.post(
        f"/api/projects/{project_id}/ai-reference",
        json={"idempotency_key": f"stage-b-{type(error).__name__}"},
    )

    assert response.status_code == 503, response.text
    _assert_safe_failure(response.json())
