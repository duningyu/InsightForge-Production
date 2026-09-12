from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from app.errors import StructuredRuntimeRecoveryError
from app.services.async_generation import AsyncRun


DENIED_KEYS = {
    "rawresponse",
    "providerpayload",
    "providerraw",
    "authorization",
    "authorizationheader",
    "apikey",
    "debugprompt",
    "systemprompt",
    "prompt",
    "prompts",
    "traceback",
    "exception",
    "exceptiondump",
}
PRIVATE_MARKERS = (
    "stage-b-raw-response-secret",
    "stage-b-provider-payload-secret",
    "stage-b-provider-raw-secret",
    "bearer stage-b-authorization-secret",
    "sk-stage-b-api-key-secret",
    "stage-b-debug-prompt-secret",
    "stage-b-system-prompt-secret",
    "traceback (most recent call last)",
    "jsondecodeerror",
    "validationerror",
    "valueerror: stage-b-exception-secret",
)


def _normalized_key(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _public_leaks(value: Any, *, path: str = "$") -> list[str]:
    leaks: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if _normalized_key(key) in DENIED_KEYS:
                leaks.append(f"denied key at {child_path}")
            leaks.extend(_public_leaks(item, path=child_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            leaks.extend(_public_leaks(item, path=f"{path}[{index}]"))
    elif isinstance(value, str):
        lowered = value.lower()
        for marker in PRIVATE_MARKERS:
            if marker in lowered:
                leaks.append(f"private marker {marker!r} at {path}")
    return leaks


def _assert_public_response(response) -> dict[str, Any]:
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert not _public_leaks(payload), payload
    return payload


def _quick_project(client) -> str:
    if client.app.state.beta_context.participant_id is None:
        client.app.state.beta_context = replace(
            client.app.state.beta_context,
            participant_id="stage-b-contract",
        )
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
    project_id = response.json()["project_id"]
    confirmed = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认理解"},
    )
    assert confirmed.status_code == 200, confirmed.text
    return project_id


def _leaky_failure() -> StructuredRuntimeRecoveryError:
    return StructuredRuntimeRecoveryError(
        error_code="PROVIDER_OUTPUT_PARSE_FAILED",
        message="生成内容无法安全解析，本次没有写入内容；可以重新生成。",
        recovery_actions=["重新生成"],
        preserved_input={
            "raw_response": "stage-b-raw-response-secret",
            "provider_payload": {"body": "stage-b-provider-payload-secret"},
            "provider_raw": "stage-b-provider-raw-secret",
            "authorization": "Bearer stage-b-authorization-secret",
            "api_key": "sk-stage-b-api-key-secret",
            "debug_prompt": "stage-b-debug-prompt-secret",
            "system_prompt": "stage-b-system-prompt-secret",
            "nested": {
                "traceback": "Traceback (most recent call last)",
                "errors": [
                    "JSONDecodeError",
                    "ValidationError",
                    "ValueError: stage-b-exception-secret",
                ],
            },
        },
        safe_diagnostic={"classification": "parse"},
    )


def _failed_async_run(project_id: str) -> AsyncRun:
    return AsyncRun(
        generation_run_id="stage-b-failed-run",
        generation_intent_id="stage-b-failed-intent",
        participant_id="default",
        project_id=project_id,
        status="FAILED",
        response=_leaky_failure().as_payload(),
        status_code=503,
        requested_model_preference=None,
        resolved_model_family=None,
        resolved_model_id=None,
        request_count=1,
        replay_count=0,
        provider_call_count=1,
        use_competitor_snapshot=False,
    )


class _FailingRuntime:
    mode = "fake"
    provider = "fake-provider"
    model = "fake-model"
    prompt_version = "stage-b-test"
    schema_version = "stage-b-test"
    model_rounds_used = 1
    max_model_rounds = 1
    max_tool_rounds = 0

    def generate_ai_reference(self, _context):
        raise _leaky_failure()

    def generate_evidence_guidance(self, _context):
        raise _leaky_failure()

    def design_solutions(self, _brief, **_kwargs):
        raise _leaky_failure()


class _FakeRuntimeRouter:
    mode = "fake"

    def __init__(self, runtime):
        self.runtime = runtime

    def for_project(self, *_args, **_kwargs):
        return self.runtime


def _confirm_snapshot(client, project_id: str) -> None:
    generated = client.post(
        f"/api/projects/{project_id}/solutions/generate",
        headers={"X-Idempotency-Key": "stage-b-document-prerequisite"},
    )
    assert generated.status_code == 201, generated.text
    selected = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [generated.json()["candidates"][0]["id"]],
            "rationale": "Stage B document failure prerequisite",
            "human_confirmed": True,
        },
    )
    assert selected.status_code == 201, selected.text


def test_stage_b_success_responses_recursively_exclude_private_generation_data(client, monkeypatch):
    project_id = _quick_project(client)

    ai_reference = client.post(
        f"/api/projects/{project_id}/ai-reference",
        json={"idempotency_key": "stage-b-ai-reference-success"},
    )
    evidence = client.post(
        f"/api/projects/{project_id}/evidence-guidance",
        json={"idempotency_key": "stage-b-evidence-success"},
    )
    solutions = client.post(
        f"/api/projects/{project_id}/solutions/generate",
        headers={"X-Idempotency-Key": "stage-b-solutions-success"},
    )
    assert ai_reference.status_code == 201, ai_reference.text
    assert evidence.status_code == 201, evidence.text
    assert solutions.status_code == 201, solutions.text

    candidate = solutions.json()["candidates"][0]
    selected = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [candidate["id"]],
            "rationale": "Stage B API contract fixture",
            "human_confirmed": True,
        },
    )
    assert selected.status_code == 201, selected.text
    document = client.post(
        f"/api/projects/{project_id}/documents/generate",
        json={
            "doc_type": "prd",
            "idempotency_key": "stage-b-document-success",
            "use_competitor_snapshot": False,
        },
    )
    assert document.status_code == 200, document.text

    completed_run = AsyncRun(
        generation_run_id="stage-b-success-run",
        generation_intent_id="stage-b-success-intent",
        participant_id="default",
        project_id=project_id,
        status="SUCCEEDED",
        response=solutions.json(),
        status_code=201,
        requested_model_preference=None,
        resolved_model_family=None,
        resolved_model_id=None,
        request_count=1,
        replay_count=0,
        provider_call_count=0,
        use_competitor_snapshot=False,
    )
    monkeypatch.setattr(
        client.app.state.async_generation_repository,
        "get",
        lambda *_args, **_kwargs: completed_run,
    )
    async_poll = client.get(
        f"/api/projects/{project_id}/solutions/generate/{completed_run.generation_run_id}"
    )
    assert async_poll.status_code == 200, async_poll.text

    for response in (ai_reference, evidence, solutions, document, async_poll):
        _assert_public_response(response)


@pytest.mark.parametrize(
    ("surface", "path_suffix", "request_kwargs", "write_count_sql"),
    (
        (
            "ai_reference",
            "ai-reference",
            {"json": {"idempotency_key": "stage-b-ai-reference-failure"}},
            "SELECT COUNT(*) AS n FROM ai_reference_results WHERE project_id=?",
        ),
        (
            "evidence_coach",
            "evidence-guidance",
            {"json": {"idempotency_key": "stage-b-evidence-failure"}},
            "SELECT COUNT(*) AS n FROM evidence_guidance_results WHERE project_id=?",
        ),
        (
            "solution_design",
            "solutions/generate",
            {"headers": {"X-Idempotency-Key": "stage-b-solutions-failure"}},
            "SELECT COUNT(*) AS n FROM solution_candidates WHERE project_id=?",
        ),
        (
            "document_loop",
            "documents/generate",
            {"json": {"doc_type": "prd", "idempotency_key": "stage-b-document-failure"}},
            "SELECT COUNT(*) AS n FROM document_versions WHERE project_id=?",
        ),
    ),
)
def test_stage_b_generation_failures_are_safe_actionable_and_do_not_write(
    client,
    monkeypatch,
    surface,
    path_suffix,
    request_kwargs,
    write_count_sql,
):
    project_id = _quick_project(client)
    if surface == "document_loop":
        _confirm_snapshot(client, project_id)

        def fail_document_generation(*_args, **_kwargs):
            raise _leaky_failure()

        monkeypatch.setattr(
            client.app.state.document_loop.generator,
            "generate",
            fail_document_generation,
        )
    else:
        router = _FakeRuntimeRouter(_FailingRuntime())
        monkeypatch.setattr(client.app.state, "structured_runtime", router)
        if surface == "solution_design":
            monkeypatch.setattr(client.app.state.solution_design, "runtime", router)
    before = client.app.state.db.fetch_one(write_count_sql, (project_id,))["n"]
    response = client.post(
        f"/api/projects/{project_id}/{path_suffix}",
        **request_kwargs,
    )
    after = client.app.state.db.fetch_one(write_count_sql, (project_id,))["n"]

    assert response.status_code == 503, response.text
    payload = _assert_public_response(response)
    assert payload["error_code"] == "PROVIDER_OUTPUT_PARSE_FAILED"
    assert payload["message"]
    assert payload["content_written"] is False
    assert payload["retryable"] is False
    assert payload["recovery_actions"] == ["检查输入和模型配置后重新生成"]
    assert after == before


def test_stage_b_async_failure_poll_recursively_sanitizes_stored_failure(client, monkeypatch):
    project_id = _quick_project(client)
    failed_run = _failed_async_run(project_id)
    monkeypatch.setattr(
        client.app.state.async_generation_repository,
        "get",
        lambda *_args, **_kwargs: failed_run,
    )

    response = client.get(
        f"/api/projects/{project_id}/solutions/generate/{failed_run.generation_run_id}"
    )

    assert response.status_code == 200, response.text
    payload = _assert_public_response(response)
    assert payload["status"] == "FAILED"
    assert payload["error_code"] == "PROVIDER_OUTPUT_PARSE_FAILED"
    assert payload["message"]
    assert payload["content_written"] is False
    assert payload["retryable"] is False
    assert payload["recovery_actions"] == ["检查输入和模型配置后重新生成"]


def test_stage_b_registers_no_public_debug_route(client):
    public_paths = [getattr(route, "path", "") for route in client.app.routes]
    assert not [path for path in public_paths if "debug" in path.lower()]


@pytest.mark.parametrize("boundary", ("exception", "sync_replay", "async_poll"))
@pytest.mark.parametrize(
    ("code", "expected_code", "message", "actions"),
    (
        ("MODEL_TIMEOUT", "MODEL_TIMEOUT", "所选模型响应超时；本次未生成可用内容，请稍后重试。", ["稍后重试"]),
        ("MODEL_PROVIDER_ERROR", "MODEL_PROVIDER_ERROR", "所选模型暂时无法完成生成；本次未生成可用内容，请稍后重试。", ["稍后重试", "检查所选模型配置"]),
        ("MODEL_OUTPUT_CONTRACT_FAILED", "MODEL_OUTPUT_CONTRACT_FAILED", "AI 返回的内容格式不符合要求，本次未生成可用内容；请检查输入和模型配置。", ["检查输入和模型配置后重新生成"]),
        ("UNKNOWN: sk-stage-b-api-key-secret", "MODEL_OUTPUT_CONTRACT_FAILED", "AI 返回的内容格式不符合要求，本次未生成可用内容；请检查输入和模型配置。", ["检查输入和模型配置后重新生成"]),
    ),
    ids=("timeout", "provider", "output_contract", "unknown"),
)
def test_public_failure_text_is_app_owned_on_every_boundary(
    client, monkeypatch, boundary, code, expected_code, message, actions
):
    # Copying any producer/stored message, action, or unknown code must fail.
    project_id = _quick_project(client)
    error = StructuredRuntimeRecoveryError(
        error_code=code,
        message=" | ".join(PRIVATE_MARKERS),
        recovery_actions=list(PRIVATE_MARKERS),
    )
    if boundary == "exception":
        def fail(*_args, **_kwargs):
            raise error

        runtime = _FailingRuntime()
        monkeypatch.setattr(runtime, "generate_ai_reference", fail)
        monkeypatch.setattr(client.app.state, "structured_runtime", _FakeRuntimeRouter(runtime))
        response = client.post(f"/api/projects/{project_id}/ai-reference", json={"idempotency_key": "hostile-text"})
        assert response.status_code == 503
    elif boundary == "sync_replay":
        guard = client.app.state.solution_generation_guard
        participant = client.app.state.beta_context.participant_id
        assert guard.begin(participant, project_id, "hostile-text").owner
        guard.complete(participant, project_id, "hostile-text", error.as_payload(), status_code=503)
        response = client.post(f"/api/projects/{project_id}/solutions/generate", headers={"X-Idempotency-Key": "hostile-text"})
        assert response.status_code == 503
    else:
        run = replace(_failed_async_run(project_id), response=error.as_payload())
        monkeypatch.setattr(client.app.state.async_generation_repository, "get", lambda *_args, **_kwargs: run)
        response = client.get(f"/api/projects/{project_id}/solutions/generate/{run.generation_run_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "FAILED"
    payload = _assert_public_response(response)
    assert payload["error_code"] == expected_code
    assert payload["message"] == message
    assert payload["recovery_actions"] == actions
    assert payload["content_written"] is False


@pytest.mark.parametrize(
    ("code", "retryable"),
    (
        ("MODEL_TIMEOUT", True),
        ("MODEL_PROVIDER_ERROR", True),
        ("MODEL_OUTPUT_CONTRACT_FAILED", False),
        ("PROVIDER_OUTPUT_PARSE_FAILED", False),
        ("MODEL_OUTPUT_SCHEMA_INVALID", False),
        ("MODEL_CREDENTIAL_MISSING", False),
        ("MODEL_CREDENTIAL_INVALID", False),
        ("MODEL_CONFIGURATION_INVALID", False),
        ("MODEL_CAPABILITY_UNAVAILABLE", False),
        ("ASYNC_GENERATION_CANCELLED", False),
    ),
)
def test_typed_retry_policy_survives_sync_and_async_replay(client, monkeypatch, code, retryable):
    from app.services.generation_contracts import GenerationContractError, failure_public

    project_id = _quick_project(client)
    error = (GenerationContractError("SURFACE_SCHEMA_FAILED") if code == "MODEL_OUTPUT_CONTRACT_FAILED"
             else StructuredRuntimeRecoveryError(error_code=code, message="不可信的说明", recovery_actions=["不可信的操作"]))

    def fail(*_args, **_kwargs):
        raise error

    runtime = _FailingRuntime()
    monkeypatch.setattr(runtime, "generate_ai_reference", fail)
    monkeypatch.setattr(client.app.state, "structured_runtime", _FakeRuntimeRouter(runtime))
    response = client.post(f"/api/projects/{project_id}/ai-reference", json={"idempotency_key": "typed-retry"})
    assert response.status_code == 503
    assert response.json()["retryable"] is retryable
    assert error.retryable is retryable

    # Legacy envelopes may omit the field or contain a now-incorrect True.
    for stored_flag in (None, True, False):
        stored = error.as_payload()
        if stored_flag is not None:
            stored["retryable"] = stored_flag
        expected = retryable and stored_flag is not False
        assert failure_public(stored)["retryable"] is expected
        run = replace(_failed_async_run(project_id), response=stored)
        monkeypatch.setattr(client.app.state.async_generation_repository, "get", lambda *_args, **_kwargs: run)
        poll = client.get(f"/api/projects/{project_id}/solutions/generate/{run.generation_run_id}")
        assert poll.status_code == 200
        assert poll.json()["retryable"] is expected

        guard = client.app.state.solution_generation_guard
        participant = client.app.state.beta_context.participant_id
        key = f"retry-{stored_flag}"
        assert guard.begin(participant, project_id, key).owner
        guard.complete(participant, project_id, key, stored, status_code=503)
        replay = client.post(f"/api/projects/{project_id}/solutions/generate", headers={"X-Idempotency-Key": key})
        assert replay.status_code == 503
        assert replay.json()["retryable"] is expected


@pytest.mark.parametrize(
    ("code", "retryable"),
    (
        ("MODEL_RATE_LIMITED", True), ("MODEL_NETWORK_ERROR", True),
        ("STRUCTURED_RUNTIME_UNAVAILABLE", True),
        ("SOLUTION_GENERATION_FAILED", True), ("ASYNC_GENERATION_FAILED", True),
        ("STAGE_A_FIXTURE_CONTROLLED_FAILURE", True),
        ("MODEL_QUOTA_EXHAUSTED", False), ("MODEL_NOT_FOUND", False),
        ("MODEL_MODEL_NOT_FOUND", False), ("MODEL_UNAUTHORIZED", False),
        ("MODEL_REQUEST_REJECTED", False), ("MODEL_INVALID_REQUEST", False),
        ("MODEL_UNSUPPORTED_PROTOCOL", False), ("MODEL_DISPATCH_CONTROL_INVALID", False),
        ("MODEL_STRUCTURED_OUTPUT_UNSUPPORTED", False), ("MODEL_UNSUPPORTED_FEATURE", False),
        ("CREDENTIAL_BACKEND_UNAVAILABLE", False), ("MODEL_ROUND_LIMIT_REACHED", False),
        ("LOCAL_GUIDANCE_REQUIRED", False), ("IDEMPOTENCY_MODEL_MISMATCH", False),
        ("SOLUTION_GENERATION_IN_PROGRESS", False),
    ),
)
def test_existing_failure_codes_keep_safe_identity_and_typed_retry_policy(code, retryable):
    from app.services.generation_contracts import failure_public

    # Closing the code set must retain every existing producer's public identity.
    error = StructuredRuntimeRecoveryError(
        error_code=code, message=" | ".join(PRIVATE_MARKERS), recovery_actions=list(PRIVATE_MARKERS)
    )
    for payload in (error.as_public_payload(), failure_public(error.as_payload())):
        assert not _public_leaks(payload)
        assert payload["error_code"] == code
        assert payload["retryable"] is retryable
        assert all(any("\u4e00" <= char <= "\u9fff" for char in text)
                   for text in (payload["message"], *payload["recovery_actions"]))
