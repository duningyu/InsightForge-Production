import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings
from app.errors import StructuredRuntimeRecoveryError
from app.main import create_app
from app.services.ai_runtime import DeterministicDemoRuntime
from app.services.async_generation import AsyncGenerationWorker, AsyncRun
from app.services.hybrid_runtime import HybridStructuredRuntime
from app.services.safe_fixture import StageASafeFixtureRuntime, safe_fixture_enabled
from app.services.solution_design import validate_solution_set


def test_safe_fixture_is_default_off_and_stage_a_scoped(monkeypatch):
    monkeypatch.delenv("INSIGHTFORGE_SAFE_FIXTURE_MODE", raising=False)
    settings = Settings.from_env()

    assert settings.safe_fixture_mode is False
    assert safe_fixture_enabled(settings) is False
    assert safe_fixture_enabled(
        replace(settings, safe_fixture_mode=True, beta_participant_id="railway_stage_a")
    ) is True
    assert safe_fixture_enabled(
        replace(settings, safe_fixture_mode=True, beta_participant_id="beta_003")
    ) is False
    assert safe_fixture_enabled(
        replace(settings, safe_fixture_mode=True, beta_participant_id="railway_stage_b")
    ) is False
    assert safe_fixture_enabled(
        replace(
            settings,
            safe_fixture_mode=True,
            beta_participant_id="railway_stage_a",
            accounts_enabled=True,
        )
    ) is False


def test_safe_fixture_returns_substantive_deterministic_outputs_without_provider():
    runtime = StageASafeFixtureRuntime()
    reference = runtime.generate_ai_reference({"idea": "求职进度管理助手"})
    evidence = runtime.generate_evidence_guidance({"idea": "求职进度管理助手"})
    solutions = runtime.design_solutions(runtime.synthetic_brief("求职进度管理助手"))

    assert runtime.provider == "safe_fixture"
    assert runtime.fixture_origin == "STAGE_A_SYNTHETIC"
    assert len(reference.possible_target_users) >= 3
    assert len(reference.missing_information) >= 3
    assert len(evidence.cards) == 3
    assert all(card.action_steps and card.acceptable_artifacts for card in evidence.cards)
    assert len(solutions.candidates) == 3
    assert {candidate.title for candidate in solutions.candidates} == {
        "极简卡片流",
        "时间轴提醒型",
        "自动聚合型",
    }
    assert len(validate_solution_set(solutions.candidates, llm_core_required=False)) == 3


def test_safe_fixture_solution_failure_is_fail_once_then_retry_success():
    runtime = StageASafeFixtureRuntime(scenario="solution_generation_fail_once")
    brief = runtime.synthetic_brief("求职进度管理助手")

    async def exercise():
        with pytest.raises(StructuredRuntimeRecoveryError) as caught:
            await runtime.async_design_solutions(brief)

        assert "项目内容已经保留" in caught.value.message
        assert caught.value.preserved_input["original_idea"] == "求职进度管理助手"

        result = await runtime.async_design_solutions(brief)
        assert len(result.candidates) == 3
        assert runtime.fixture_invocation_count == 2

    asyncio.run(exercise())


def test_hybrid_runtime_prefers_fixture_before_external_profile_resolution(db):
    runtime = StageASafeFixtureRuntime()
    hybrid = HybridStructuredRuntime(
        profile_service=None,
        local_runtime=DeterministicDemoRuntime(
            fixture_path=Path(__file__).parent / "fixtures" / "v3_golden_cases.json"
        ),
        fixture_runtime=runtime,
    )

    assert hybrid.for_project("synthetic-project").provider == "safe_fixture"


def test_hybrid_runtime_delegates_solution_generation_to_fixture(db):
    runtime = StageASafeFixtureRuntime()
    hybrid = HybridStructuredRuntime(
        profile_service=None,
        local_runtime=DeterministicDemoRuntime(
            fixture_path=Path(__file__).parent / "fixtures" / "v3_golden_cases.json"
        ),
        fixture_runtime=runtime,
    )

    result = hybrid.design_solutions(runtime.synthetic_brief("求职进度管理助手"), project_id="synthetic-project")

    assert result.candidates[0].title == "极简卡片流"
    assert runtime.fixture_invocation_count == 1


def test_app_rejects_fixture_outside_stage_a_scope(tmp_path):
    settings = replace(
        Settings(),
        safe_fixture_mode=True,
        beta_participant_id="beta_003",
    )

    with pytest.raises(RuntimeError, match="SAFE_FIXTURE_SCOPE_REJECTED"):
        create_app(database_path=tmp_path / "scope.sqlite3", seed=False, settings_override=settings)


def test_app_wires_fixture_runtime_for_stage_a(tmp_path):
    settings = replace(
        Settings(),
        safe_fixture_mode=True,
        beta_participant_id="railway_stage_a",
    )
    application = create_app(
        database_path=tmp_path / "stage_a.sqlite3", seed=False, settings_override=settings
    )

    from fastapi.testclient import TestClient

    with TestClient(application):
        runtime = application.state.structured_runtime.for_project("synthetic-project")
        assert runtime.provider == "safe_fixture"
        assert runtime.fixture_origin == "STAGE_A_SYNTHETIC"


def test_safe_fixture_async_generation_does_not_mark_provider_dispatch():
    run = AsyncRun(
        generation_run_id="run-1",
        generation_intent_id="intent-1",
        participant_id="railway_stage_a",
        project_id="project-1",
        status="RUNNING",
        response=None,
        status_code=None,
        requested_model_preference=None,
        resolved_model_family=None,
        resolved_model_id=None,
        request_count=1,
        replay_count=0,
        provider_call_count=0,
    )

    class Repository:
        def __init__(self):
            self.dispatches = 0
            self.finished = None

        def get(self, *_args):
            return run

        def mark_provider_call(self, _run_id):
            self.dispatches += 1

        def finish(self, *_args, **_kwargs):
            self.finished = True

    repository = Repository()
    worker = AsyncGenerationWorker(
        repository,
        executor=lambda _run: {"candidates": [{"id": "fixture"}]},
        provider_dispatch_allowed=lambda _run: False,
    )

    asyncio.run(worker._execute_run(run))

    assert repository.dispatches == 0
    assert repository.finished is True


@pytest.fixture()
def stage_a_client(monkeypatch, tmp_path):
    monkeypatch.setenv("INSIGHTFORGE_SAFE_FIXTURE_MODE", "true")
    monkeypatch.setenv("INSIGHTFORGE_SAFE_FIXTURE_SCENARIO", "success")
    monkeypatch.setenv("INSIGHTFORGE_ACCOUNTS_ENABLED", "false")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", "railway_stage_a")
    from fastapi.testclient import TestClient

    application = create_app(database_path=tmp_path / "stage_a_fixture.sqlite3", seed=False)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def stage_a_fail_once_client(monkeypatch, tmp_path):
    monkeypatch.setenv("INSIGHTFORGE_SAFE_FIXTURE_MODE", "true")
    monkeypatch.setenv("INSIGHTFORGE_SAFE_FIXTURE_SCENARIO", "solution_generation_fail_once")
    monkeypatch.setenv("INSIGHTFORGE_ACCOUNTS_ENABLED", "false")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", "railway_stage_a")
    from fastapi.testclient import TestClient

    application = create_app(database_path=tmp_path / "stage_a_fail_once.sqlite3", seed=False)
    with TestClient(application) as test_client:
        yield test_client


def test_stage_a_failure_fixture_uses_normal_route_and_retry(stage_a_fail_once_client):
    client = stage_a_fail_once_client
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "求职进度管理助手", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    assert client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认 Stage A 演示输入"},
    ).status_code == 200

    first = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert first.status_code == 503, first.text
    first_payload = first.json()
    assert first_payload["error_code"] == "STAGE_A_FIXTURE_CONTROLLED_FAILURE"
    assert "项目内容已经保留" in first_payload["message"]
    assert any("重新生成" in action for action in first_payload["recovery_actions"])
    assert first_payload["preserved_input"]["original_idea"] == "求职进度管理助手"

    retry = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert retry.status_code == 201, retry.text
    assert retry.json()["fixture_origin"] == "STAGE_A_SYNTHETIC"
    assert len(retry.json()["candidates"]) == 3
    assert client.app.state.structured_runtime.for_project(project_id).fixture_invocation_count == 2
    assert client.app.state.db.fetch_one("SELECT COUNT(*) AS n FROM provider_dispatch_permits")["n"] == 0


def test_stage_a_fixture_full_business_chain_uses_normal_routes(stage_a_client):
    client = stage_a_client
    quick = client.post(
        "/api/projects/quick-start",
        json={
            "idea": "求职进度管理助手",
            "target_user": None,
            "resources": [],
            "priority": "fast_mvp",
        },
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    assert client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认 Stage A 演示输入"},
    ).status_code == 200

    ai_reference = client.post(
        f"/api/projects/{project_id}/ai-reference",
        json={"idempotency_key": "stage-a-reference"},
    )
    assert ai_reference.status_code == 201, ai_reference.text
    assert ai_reference.json()["result"]["fixture_origin"] == "STAGE_A_SYNTHETIC"
    assert sum(len(ai_reference.json()["result"].get(category, [])) for category in (
        "possible_target_users", "possible_scenarios", "possible_user_problems",
        "missing_information", "mvp_thoughts", "questions_to_validate", "research_directions",
    )) >= 3

    evidence = client.post(
        f"/api/projects/{project_id}/evidence-guidance",
        json={"idempotency_key": "stage-a-evidence"},
    )
    assert evidence.status_code == 201, evidence.text
    assert evidence.json()["result"]["fixture_origin"] == "STAGE_A_SYNTHETIC"
    assert len(evidence.json()["result"]["cards"]) >= 3

    candidates = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert candidates.status_code == 201, candidates.text
    candidate_payload = candidates.json()
    assert candidate_payload["fixture_origin"] == "STAGE_A_SYNTHETIC"
    assert len(candidate_payload["candidates"]) == 3
    selected = candidate_payload["candidates"][1]
    snapshot = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "选择时间轴提醒型作为 Stage A 演示方案",
            "human_confirmed": True,
        },
    )
    assert snapshot.status_code == 201, snapshot.text

    for title, source_type, content in (
        ("招聘记录", "public_source", "用于验证候选人的真实求职进展。"),
        ("访谈记录", "implementation_evidence", "人工构造的访谈资料，仅用于 Stage A 演示。"),
        (
            "Stage A 合成访谈",
            "simulated_research",
            "这是人工构造的 Stage A 演示研究资料，不代表真实用户研究；用于验证文档校验链。",
        ),
    ):
        source = client.post(
            f"/api/projects/{project_id}/sources",
            json={
                "title": title,
                "source_type": source_type,
                "authority": 0.8,
                "content": content,
                "filename": f"{title}.txt",
            },
        )
        assert source.status_code == 201, source.text

    versions = {}
    for doc_type in ("prd", "techdoc"):
        generated = client.post(
            f"/api/projects/{project_id}/documents/generate",
            json={"doc_type": doc_type, "idempotency_key": f"stage-a-{doc_type}"},
        )
        assert generated.status_code == 200, generated.text
        version_id = generated.json()["version_id"]
        validated = client.post(f"/api/documents/{version_id}/validate")
        assert validated.status_code == 200, validated.text
        confirmed = client.post(
            f"/api/document-versions/{version_id}/confirm",
            json={"actor": "stage_a_operator", "note": "Stage A 演示确认", "human_confirmed": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        versions[doc_type] = confirmed.json()

    readiness = client.get(f"/api/projects/{project_id}/handoff/readiness")
    assert readiness.status_code == 200, readiness.text
    if not readiness.json()["ready"]:
        acknowledged = client.post(
            f"/api/projects/{project_id}/handoff/acknowledge-unresolved",
            json={"human_confirmed": True, "note": "保留未解决项并进入 Stage A 演示交接"},
        )
        assert acknowledged.status_code == 200, acknowledged.text
        readiness = client.get(f"/api/projects/{project_id}/handoff/readiness")
    assert readiness.json()["ready"] is True
    assert readiness.json()["documents"]["prd"]["version_id"] == versions["prd"]["id"]
    assert readiness.json()["documents"]["techdoc"]["version_id"] == versions["techdoc"]["id"]

    handoff = client.post(
        f"/api/projects/{project_id}/handoff/export",
        json={"target_client": "generic"},
    )
    assert handoff.status_code == 200, handoff.text
    assert handoff.headers["content-type"].startswith("application/zip")

    row = client.app.state.db.fetch_one("SELECT COUNT(*) AS n FROM provider_dispatch_permits")
    assert int(row["n"]) == 0
