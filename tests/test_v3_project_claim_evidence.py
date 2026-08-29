from __future__ import annotations

import sqlite3

import pytest

from app.db import utc_now
from app.services.project_claims import ProjectClaimService


def insert_project(db, project_id: str) -> None:
    now = utc_now()
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, project_id, project_id, "active", now, now),
    )


def insert_claim(
    db,
    *,
    project_id: str,
    claim_id: str,
    claim_type: str = "user_problem",
    scope_note: str = "当前测试样本范围",
    criticality: str = "critical",
) -> dict:
    now = utc_now()
    db.execute(
        """
        INSERT INTO project_claims(
            id, project_id, claim_type, statement, provenance, verification_status,
            criticality, scope_note, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'model_hypothesis', 'unverified', ?, ?, 'active', ?, ?)
        """,
        (claim_id, project_id, claim_type, f"claim {claim_id}", criticality, scope_note, now, now),
    )
    return db.fetch_one("SELECT * FROM project_claims WHERE id=?", (claim_id,))


def add_source(db, *, project_id: str, source_type: str, content: str, title: str) -> tuple[str, str]:
    source_id = db.add_source(
        project_id=project_id,
        title=title,
        source_type=source_type,
        authority=0.8,
        content=content,
        filename=f"{title}.txt",
    )
    chunk = db.fetch_one(
        "SELECT id FROM source_chunks WHERE source_id=? ORDER BY chunk_index LIMIT 1",
        (source_id,),
    )
    return source_id, chunk["id"]


def relation(
    *,
    project_id: str,
    claim_id: str,
    source_id: str,
    chunk_id: str,
    span: str,
    relation_type: str = "supports",
    directness: str = "direct",
) -> dict:
    return {
        "project_id": project_id,
        "claim_id": claim_id,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "relation": relation_type,
        "directness": directness,
        "scope_fit": "fit",
        "recency_state": "current",
        "retrieval_run_id": None,
        "analysis_version": "test-v1",
        "evidence_span": span,
        "reason": "test relation",
    }


def test_exact_span_must_exist_in_same_project_chunk(db):
    project = "project_span"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_span")
    source_id, chunk_id = add_source(
        db, project_id=project, source_type="real_user_research",
        content="我们不是忘记补货，主要是不知道应该补多少。", title="访谈1",
    )
    service = ProjectClaimService(db=db)
    good = relation(
        project_id=project, claim_id="claim_span", source_id=source_id, chunk_id=chunk_id,
        span="  我们不是忘记补货，主要是不知道应该补多少。  ",
    )
    assert service.validate_relation_proposal(**good)["evidence_span"].startswith("我们")

    bad = {**good, "evidence_span": "店主表示销量预测一定有效"}
    with pytest.raises(ValueError, match="EVIDENCE_SPAN_NOT_FOUND"):
        service.validate_relation_proposal(**bad)


def test_cross_project_source_or_chunk_is_rejected(db):
    insert_project(db, "project_a")
    insert_project(db, "project_b")
    insert_claim(db, project_id="project_a", claim_id="claim_a")
    source_id, chunk_id = add_source(
        db, project_id="project_b", source_type="real_user_research",
        content="另一个项目的访谈原文。", title="cross",
    )
    service = ProjectClaimService(db=db)
    with pytest.raises(ValueError, match="EVIDENCE_SCOPE_MISMATCH"):
        service.validate_relation_proposal(
            **relation(
                project_id="project_a", claim_id="claim_a", source_id=source_id,
                chunk_id=chunk_id, span="另一个项目的访谈原文。",
            )
        )


def test_simulated_research_never_upgrades_real_validation(db):
    project = "project_sim"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_sim")
    source_id, chunk_id = add_source(
        db, project_id=project, source_type="simulated_research",
        content="人工构造：用户说这个功能很好。", title="模拟访谈",
    )
    service = ProjectClaimService(db=db)
    with pytest.raises(ValueError, match="SOURCE_TYPE_NOT_ADMISSIBLE"):
        service.persist_relation(
            **relation(
                project_id=project, claim_id="claim_sim", source_id=source_id,
                chunk_id=chunk_id, span="人工构造：用户说这个功能很好。",
            )
        )
    assert db.fetch_one("SELECT verification_status FROM project_claims WHERE id='claim_sim'")["verification_status"] == "unverified"


def test_implementation_evidence_may_support_feasibility_but_not_user_value(db):
    project = "project_impl"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_feas", claim_type="feasibility")
    insert_claim(db, project_id=project, claim_id="claim_value", claim_type="value")
    source_id, chunk_id = add_source(
        db, project_id=project, source_type="implementation_evidence",
        content="接口测试通过，库存查询 API 已可运行。", title="实现报告",
    )
    service = ProjectClaimService(db=db)
    persisted = service.persist_relation(
        **relation(
            project_id=project, claim_id="claim_feas", source_id=source_id,
            chunk_id=chunk_id, span="接口测试通过，库存查询 API 已可运行。",
        )
    )
    assert persisted["claim_status"] == "limited_support"
    with pytest.raises(ValueError, match="SOURCE_TYPE_NOT_ADMISSIBLE"):
        service.persist_relation(
            **relation(
                project_id=project, claim_id="claim_value", source_id=source_id,
                chunk_id=chunk_id, span="接口测试通过，库存查询 API 已可运行。",
            )
        )


def test_two_independent_direct_sources_can_produce_supported_with_scope_notes(db):
    project = "project_two_support"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_two", scope_note="仅适用于当前两名受访者")
    service = ProjectClaimService(db=db)
    for idx in (1, 2):
        span = f"受访者{idx}明确表示不知道应该补多少。"
        source_id, chunk_id = add_source(
            db, project_id=project, source_type="real_user_research", content=span, title=f"访谈{idx}",
        )
        result = service.persist_relation(
            **relation(
                project_id=project, claim_id="claim_two", source_id=source_id,
                chunk_id=chunk_id, span=span,
            )
        )
    assert result["claim_status"] == "supported"
    assert db.fetch_one("SELECT verification_status FROM project_claims WHERE id='claim_two'")["verification_status"] == "supported"


def test_support_and_direct_contradiction_from_different_sources_produce_conflict(db):
    project = "project_conflict"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_conflict")
    service = ProjectClaimService(db=db)
    s1, c1 = add_source(db, project_id=project, source_type="real_user_research", content="我经常不知道补多少。", title="支持")
    s2, c2 = add_source(db, project_id=project, source_type="real_user_research", content="补多少从来不是问题。", title="反向")
    service.persist_relation(**relation(project_id=project, claim_id="claim_conflict", source_id=s1, chunk_id=c1, span="我经常不知道补多少。"))
    result = service.persist_relation(**relation(project_id=project, claim_id="claim_conflict", source_id=s2, chunk_id=c2, span="补多少从来不是问题。", relation_type="contradicts"))
    assert result["claim_status"] == "conflict"


def test_source_archived_between_analysis_and_commit_is_rejected(db):
    project = "project_race"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_race")
    source_id, chunk_id = add_source(
        db, project_id=project, source_type="real_user_research",
        content="这是一条可直接核对的访谈。", title="race",
    )
    service = ProjectClaimService(db=db)
    proposal = relation(
        project_id=project, claim_id="claim_race", source_id=source_id,
        chunk_id=chunk_id, span="这是一条可直接核对的访谈。",
    )
    assert service.validate_relation_proposal(**proposal)
    db.execute("UPDATE sources SET status='archived' WHERE id=?", (source_id,))
    with pytest.raises(ValueError, match="SOURCE_NOT_ACTIVE"):
        service.persist_relation(**proposal)
    assert db.fetch_one("SELECT 1 FROM project_claim_evidence_links WHERE claim_id='claim_race'") is None


def test_recompute_status_counts_sources_not_multiple_chunks(db):
    project = "project_independent"
    insert_project(db, project)
    insert_claim(db, project_id=project, claim_id="claim_independent")
    long_text = "A" * 450 + "直接支持这条判断。" + "B" * 450
    source_id, _ = add_source(db, project_id=project, source_type="real_user_research", content=long_text, title="长访谈")
    chunks = db.fetch_all("SELECT id,content FROM source_chunks WHERE source_id=? ORDER BY chunk_index", (source_id,))
    service = ProjectClaimService(db=db)
    usable = [row for row in chunks if "直接支持这条判断。" in row["content"]]
    assert usable
    service.persist_relation(**relation(project_id=project, claim_id="claim_independent", source_id=source_id, chunk_id=usable[0]["id"], span="直接支持这条判断。"))
    assert db.fetch_one("SELECT verification_status FROM project_claims WHERE id='claim_independent'")["verification_status"] == "limited_support"


class FakeEvidenceRuntime:
    mode = "llm_structured"
    provider = "test"
    model = "fake-evidence"
    prompt_version = "fake-v1"
    schema_version = "evidence-v1"

    def analyze_evidence(self, *, claim, chunks):
        assert chunks
        chunk = chunks[0]
        return [{
            "source_id": chunk["source_id"],
            "chunk_id": chunk["chunk_id"],
            "relation": "supports",
            "directness": "direct",
            "scope_fit": "fit",
            "recency_state": "current",
            "evidence_span": chunk["content"],
            "reason": "原文直接支持当前判断",
        }]


def _prepared_v3_project(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    project_id = quick.json()["project_id"]
    client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认理解"},
    )
    solutions = client.post(f"/api/projects/{project_id}/solutions/generate").json()["candidates"]
    selected = next(item for item in solutions if item["mechanism"] == "rule_based")
    client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "先验证低成本方案",
            "human_confirmed": True,
        },
    )
    return project_id


def test_project_claim_and_evidence_api_persists_validated_relation_and_trace(client):
    project_id = _prepared_v3_project(client)
    claims_response = client.get(f"/api/projects/{project_id}/claims")
    assert claims_response.status_code == 200, claims_response.text
    claims = claims_response.json()
    assert claims
    claim = next(item for item in claims if item["claim_type"] == "user_problem")
    detail = client.get(f"/api/projects/{project_id}/claims/{claim['id']}")
    assert detail.status_code == 200

    source = client.post(
        f"/api/projects/{project_id}/sources",
        json={
            "title": "店主访谈",
            "source_type": "real_user_research",
            "authority": 0.8,
            "content": claim["statement"],
            "filename": "interview.txt",
        },
    )
    assert source.status_code == 201
    client.app.state.project_claims.runtime = FakeEvidenceRuntime()

    analyzed = client.post(
        f"/api/projects/{project_id}/evidence/analyze",
        json={"claim_ids": [claim["id"]]},
    )
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert body["changes"]
    assert body["changes"][0]["after"] == "limited_support"

    impact = client.get(f"/api/projects/{project_id}/evidence/impact")
    assert impact.status_code == 200
    assert any(item["claim_id"] == claim["id"] and item["verification_status"] == "limited_support" for item in impact.json()["claims"])

    audit = client.app.state.db.fetch_one(
        "SELECT payload_json FROM audit_events WHERE action='project_evidence_analyzed' AND entity_id=? ORDER BY created_at DESC LIMIT 1",
        (claim["id"],),
    )
    import json
    trace = json.loads(audit["payload_json"])
    for key in (
        "provider", "model", "prompt_version", "schema_version", "component_version",
        "input_sha256", "output_sha256", "latency_ms", "status", "runtime_mode",
    ):
        assert key in trace
