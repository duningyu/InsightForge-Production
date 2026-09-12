from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path

import pytest

from app.db import Database
from app.errors import StructuredRuntimeUnavailableError
from app.schemas import QuickStartRequest, SolutionCandidateDraft
from app.services.ai_runtime import DeterministicDemoRuntime
from app.services.legacy_migration import LegacyMigrationService
from app.services.solution_design import validate_solution_set


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"
V206_SCHEMA = Path(__file__).parent / "fixtures" / "v206_schema.sql"


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _quick_snapshot(client, idea: str = "帮小型便利店减少缺货") -> tuple[str, dict, list[dict]]:
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": idea, "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    confirmed = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认系统理解，不代表市场验证"},
    )
    assert confirmed.status_code == 200, confirmed.text
    generated = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert generated.status_code == 201, generated.text
    candidates = generated.json()["candidates"]
    selected = candidates[0]
    if idea == "帮小型便利店减少缺货":
        selected = next(item for item in candidates if item["mechanism"] == "rule_based")
    snapshot = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "先验证最低依赖的 MVP",
            "human_confirmed": True,
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    return project_id, snapshot.json(), candidates


def _source_chunk(client, project_id: str, *, source_type: str, content: str, title: str) -> tuple[dict, dict]:
    response = client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "title": title,
            "source_type": source_type,
            "authority": 0.8,
            "content": content,
            "filename": f"{title}.txt",
        },
    )
    assert response.status_code == 201, response.text
    source = response.json()
    chunk = client.app.state.db.fetch_one(
        "SELECT * FROM source_chunks WHERE source_id=? ORDER BY chunk_index,id LIMIT 1",
        (source["id"],),
    )
    assert chunk is not None
    return source, chunk


def _relation(client, project_id: str, claim: dict, source: dict, chunk: dict, *, relation: str, span: str):
    return client.app.state.project_claims.persist_relation(
        project_id=project_id,
        claim_id=claim["id"],
        source_id=source["id"],
        chunk_id=chunk["id"],
        relation=relation,
        directness="direct",
        scope_fit="fit",
        recency_state="current",
        retrieval_run_id=None,
        analysis_version="golden-v1",
        evidence_span=span,
        reason="frozen golden engineering case",
    )


def test_frozen_fixture_declares_exactly_ten_spec_engineering_cases():
    cases = _fixture()["_engineering_expectations"]
    assert len(cases) == 10
    assert sorted(case["spec_case"] for case in cases.values()) == list(range(1, 11))


def test_case_1_convenience_store_produces_domain_specific_non_llm_baseline(client):
    expected = _fixture()["_engineering_expectations"]["convenience_store_replenishment"]
    project_id, snapshot, candidates = _quick_snapshot(client, expected["idea"])
    assert {item["mechanism"] for item in candidates} == set(expected["expected_mechanisms"])
    assert snapshot["snapshot_origin"] == expected["expected_snapshot_origin"]
    assert snapshot["problem"]["verification_status"] == "unverified"
    audit = client.app.state.db.fetch_one(
        "SELECT payload_json FROM audit_events WHERE action='project_snapshot_confirmed' AND entity_id=?",
        (snapshot["id"],),
    )
    assert audit is not None
    assert json.loads(audit["payload_json"])["market_validation"] is expected["market_validation"]
    assert client.get(f"/api/projects/{project_id}/snapshot").status_code == 200


def test_case_2_non_ai_workflow_rejects_all_ai_overengineering():
    data = _fixture()
    expected = data["_engineering_expectations"]["non_ai_workflow_overengineering"]
    raw = copy.deepcopy(data["two_solution_workflow"]["solutions"])
    raw[0].update(
        mechanism="assistant",
        core_decision_logic="llm_generate_reimbursement",
        major_dependency="openai_api",
        requires_llm_runtime=True,
        requires_rag_runtime=False,
        requires_agent_runtime=True,
    )
    raw[1].update(
        mechanism="search_retrieval",
        core_decision_logic="rag_reimbursement_policy_answer",
        major_dependency="vector_retrieval",
        requires_llm_runtime=True,
        requires_rag_runtime=True,
        requires_agent_runtime=False,
    )
    candidates = [SolutionCandidateDraft.model_validate(item) for item in raw]
    candidates.append(candidates[0].model_copy(update={
        "title": "自动执行", "mechanism": "automation", "major_dependency": "agent_executor",
        "summary": "代理根据审批规则自动提交报销申请。",
        "user_flow": ["读取报销凭证", "代理核对规则", "自动提交申请"],
    }))
    assert len(validate_solution_set(candidates, llm_core_required=True)) == 3
    with pytest.raises(ValueError, match=expected["error_code"]):
        validate_solution_set(candidates, llm_core_required=expected["llm_core_required"])


def test_case_3_real_ambiguity_requires_only_one_clarification():
    expected = _fixture()["_engineering_expectations"]["one_clarification_for_real_ambiguity"]
    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    brief = runtime.interpret_idea(
        QuickStartRequest(idea=expected["idea"], target_user=None, resources=[], priority="fast_mvp")
    )
    assert brief.clarification_required is expected["clarification_required"]
    assert brief.clarification_question
    assert brief.clarification_question.count("？") <= expected["max_clarification_questions"]


def test_case_4_stage_b_rejects_two_solutions_without_padding():
    expected = _fixture()["_engineering_expectations"]["only_two_material_solutions"]
    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    brief = runtime.interpret_idea(
        QuickStartRequest(idea=expected["idea"], target_user=None, resources=[], priority="fast_mvp")
    )
    candidates = [SolutionCandidateDraft.model_validate(item) for item in _fixture()["two_solution_workflow"]["solutions"]]
    assert len(candidates) == expected["expected_solution_count"] == 2
    with pytest.raises(StructuredRuntimeUnavailableError, match="DETERMINISTIC_DEMO_UNSUPPORTED"):
        runtime.design_solutions(brief)
    with pytest.raises(ValueError, match="SOLUTION_SET_CARDINALITY_FAILED"):
        validate_solution_set(candidates, llm_core_required=False)


def test_case_5_independent_real_user_support_and_contradiction_become_conflict(client):
    expected = _fixture()["_engineering_expectations"]["conflicting_real_user_evidence"]
    project_id, _snapshot, _candidates = _quick_snapshot(client)
    claim = next(
        item for item in client.get(f"/api/projects/{project_id}/claims").json()
        if item["claim_type"] == expected["claim_type"]
    )
    support_source, support_chunk = _source_chunk(
        client, project_id, source_type="real_user_research",
        content=expected["support_span"], title="真实访谈支持",
    )
    contrad_source, contrad_chunk = _source_chunk(
        client, project_id, source_type="real_user_research",
        content=expected["contradict_span"], title="真实访谈反向",
    )
    first = _relation(
        client, project_id, claim, support_source, support_chunk,
        relation="supports", span=expected["support_span"],
    )
    assert first["claim_status"] == "limited_support"
    second = _relation(
        client, project_id, claim, contrad_source, contrad_chunk,
        relation="contradicts", span=expected["contradict_span"],
    )
    assert second["claim_status"] == expected["expected_status"]


def test_case_6_simulated_research_cannot_upgrade_project_claim_validation(client):
    expected = _fixture()["_engineering_expectations"]["simulated_research_cannot_validate"]
    project_id, _snapshot, _candidates = _quick_snapshot(client)
    claim = next(item for item in client.get(f"/api/projects/{project_id}/claims").json() if item["claim_type"] == "user_problem")
    span = "模拟测试者说补货提醒很有用。"
    source, chunk = _source_chunk(
        client, project_id, source_type=expected["source_type"], content=span, title="模拟访谈",
    )
    with pytest.raises(ValueError, match=expected["expected_error_code"]):
        _relation(client, project_id, claim, source, chunk, relation="supports", span=span)
    current = client.get(f"/api/projects/{project_id}/claims/{claim['id']}").json()
    assert current["verification_status"] == "unverified"


def test_case_7_implementation_evidence_supports_feasibility_but_not_value(client):
    expected = _fixture()["_engineering_expectations"]["implementation_evidence_scope"]
    project_id, _snapshot, _candidates = _quick_snapshot(client)
    claims = client.get(f"/api/projects/{project_id}/claims").json()
    feasibility = next(item for item in claims if item["claim_type"] == "feasibility")
    value = next(item for item in claims if item["claim_type"] == "value")
    span = "SQLite 已成功保存并读取库存字段。"
    source, chunk = _source_chunk(
        client, project_id, source_type=expected["source_type"], content=span, title="实现记录",
    )
    allowed = _relation(client, project_id, feasibility, source, chunk, relation="supports", span=span)
    assert allowed["claim_status"] == "limited_support"
    with pytest.raises(ValueError, match="SOURCE_TYPE_NOT_ADMISSIBLE"):
        _relation(client, project_id, value, source, chunk, relation="supports", span=span)


def test_case_9_cross_project_evidence_link_is_fail_closed(client):
    expected = _fixture()["_engineering_expectations"]["cross_project_evidence_attack"]
    project_a, _snapshot, _candidates = _quick_snapshot(client)
    project_b = client.post("/api/projects", json={"title": "Project B", "summary": "other"}).json()["id"]
    claim = next(item for item in client.get(f"/api/projects/{project_a}/claims").json() if item["claim_type"] == "user_problem")
    span = "跨项目资料不能进入另一个项目的 Claim。"
    foreign_source, foreign_chunk = _source_chunk(
        client, project_b, source_type="real_user_research", content=span, title="Foreign",
    )
    with pytest.raises(ValueError, match=expected["expected_error_code"]):
        _relation(client, project_a, claim, foreign_source, foreign_chunk, relation="supports", span=span)
    count = client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS n FROM project_claim_evidence_links WHERE claim_id=?", (claim["id"],)
    )["n"]
    assert count == expected["expected_cross_project_links"]


def test_case_10_legacy_v206_migration_is_idempotent_and_invents_no_evidence(tmp_path):
    expected = _fixture()["_engineering_expectations"]["legacy_2_0_6_migration"]
    path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(V206_SCHEMA.read_text(encoding="utf-8"))
    now = "2026-08-24T00:00:00+00:00"
    connection.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES ('legacy-golden','Legacy','旧版项目','active',?,?)",
        (now, now),
    )
    connection.execute(
        """
        INSERT INTO project_canvas(project_id,version,problem,target_users,goals_json,non_goals_json,success_metrics_json,constraints_json,created_at,updated_at)
        VALUES ('legacy-golden',1,'旧版用户问题','旧版目标用户','[\"完成 MVP\"]','[]','[\"完成一次验收\"]','[]',?,?)
        """,
        (now, now),
    )
    connection.commit()
    connection.close()
    db = Database(path)
    db.init_schema()
    migration = LegacyMigrationService(db)
    first = migration.migrate_project("legacy-golden")
    second = migration.migrate_project("legacy-golden")
    assert first is not None and second is not None
    assert first["id"] == second["id"]
    assert first["snapshot_origin"] == expected["expected_snapshot_origin"]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM project_claim_evidence_links")["n"] == expected["invented_evidence_links"]
    assert all(
        row["verification_status"] == "unverified"
        for row in db.fetch_all("SELECT verification_status FROM project_claims WHERE project_id='legacy-golden'")
    )


def test_deterministic_evidence_runtime_returns_only_frozen_exact_span_relation():
    fixture = _fixture()
    case = fixture["_evidence_cases"][0]
    runtime = DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    claim = {
        "id": "claim-demo",
        "claim_type": case["claim_type"],
        "statement": "补货依赖人工经验，可能不能及时发现需要补货的商品",
    }
    chunks = [{
        "source_id": "source-demo",
        "chunk_id": "chunk-demo",
        "source_type": case["source_type"],
        "content": f"店主原话：{case['evidence_span']} 其他说明。",
    }]
    relations = runtime.analyze_evidence(claim=claim, chunks=chunks)
    assert relations == [{
        "source_id": "source-demo",
        "chunk_id": "chunk-demo",
        "relation": case["relation"],
        "directness": case["directness"],
        "scope_fit": case["scope_fit"],
        "recency_state": case["recency_state"],
        "evidence_span": case["evidence_span"],
        "reason": case["reason"],
    }]
