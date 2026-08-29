from __future__ import annotations

import json
from pathlib import Path


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"


def _add_source(client, project_id: str, *, title: str, source_type: str, content: str) -> dict:
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
    return response.json()


def test_convenience_store_p0_end_to_end_preserves_history_and_blocks_stale_handoff(client):
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    expected_archive = fixture["_engineering_expectations"]["archive_stales_artifact_health"]
    contradiction = next(
        item for item in fixture["_evidence_cases"] if item["id"] == "convenience_problem_contradiction"
    )

    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]

    confirmed_brief = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认理解；不等于验证市场需求"},
    )
    assert confirmed_brief.status_code == 200, confirmed_brief.text

    generated = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert generated.status_code == 201, generated.text
    candidates = generated.json()["candidates"]
    rule = next(item for item in candidates if item["mechanism"] == "rule_based")

    selected = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [rule["id"]],
            "rationale": "先验证最低数据依赖的提醒方案",
            "human_confirmed": True,
        },
    )
    assert selected.status_code == 201, selected.text
    snapshot_v1 = selected.json()
    assert snapshot_v1["version"] == 1
    v1_sha = snapshot_v1["content_sha256"]

    user_problem_claim = next(
        item for item in client.get(f"/api/projects/{project_id}/claims").json()
        if item["claim_type"] == "user_problem"
    )
    real_source = _add_source(
        client,
        project_id,
        title="店主访谈 03",
        source_type="real_user_research",
        content=f"补货依赖人工经验并不是主要问题。{contradiction['evidence_span']}",
    )

    analyzed = client.post(
        f"/api/projects/{project_id}/evidence/analyze",
        json={"claim_ids": [user_problem_claim["id"]]},
    )
    assert analyzed.status_code == 200, analyzed.text
    assert analyzed.json()["changes"]
    assert analyzed.json()["changes"][0]["after"] == "contradicted"
    proposal_id = analyzed.json()["changes"][0]["impact"]["proposal_id"]
    assert proposal_id

    proposals = client.get(f"/api/projects/{project_id}/change-proposals").json()
    assert any(item["id"] == proposal_id and item["status"] == "open" for item in proposals)
    accepted = client.post(
        f"/api/change-proposals/{proposal_id}/accept",
        json={"human_confirmed": True, "note": "保留反向证据，更新正式项目版本"},
    )
    assert accepted.status_code == 200, accepted.text
    snapshot_v2 = accepted.json()["snapshot"]
    assert snapshot_v2["version"] == 2
    assert snapshot_v2["supersedes_snapshot_id"] == snapshot_v1["id"]
    assert snapshot_v2["content_sha256"] != v1_sha

    historical_v1 = client.get(f"/api/project-snapshots/{snapshot_v1['id']}").json()
    assert historical_v1["content_sha256"] == v1_sha
    db_v1 = client.app.state.db.fetch_one(
        "SELECT content_sha256 FROM project_snapshots WHERE id=?", (snapshot_v1["id"],)
    )
    assert db_v1["content_sha256"] == v1_sha

    public_source = _add_source(
        client,
        project_id,
        title="公开补货规则",
        source_type="public_source",
        content="公开资料记录：库存阈值提醒会比较当前库存与安全库存，并保留人工确认。",
    )
    _add_source(
        client,
        project_id,
        title="实现记录",
        source_type="implementation_evidence",
        content="实现证据：FastAPI 与 SQLite 已用于库存字段、补货规则 API 和自动测试。SQLite 已成功保存并读取库存字段。",
    )
    _add_source(
        client,
        project_id,
        title="模拟测试材料",
        source_type="simulated_research",
        content="模拟用户场景：人工构造测试者走查了库存查看流程；该材料仅用于模拟，不代表真实用户调研。",
    )

    versions: dict[str, str] = {}
    for doc_type in ("prd", "techdoc"):
        generated_doc = client.post(
            f"/api/projects/{project_id}/documents/generate",
            json={"doc_type": doc_type, "idempotency_key": f"golden-e2e-{doc_type}"},
        )
        assert generated_doc.status_code == 200, generated_doc.text
        doc = generated_doc.json()
        assert doc["validation_status"] == "passed", doc
        assert doc["artifact_health"]["health_status"] == "current"
        confirmed_doc = client.post(
            f"/api/document-versions/{doc['version_id']}/confirm",
            json={"actor": "golden_user", "note": "确认当前版本", "human_confirmed": True},
        )
        assert confirmed_doc.status_code == 200, confirmed_doc.text
        versions[doc_type] = doc["version_id"]

    ready_before = client.get(f"/api/projects/{project_id}/handoff/readiness")
    assert ready_before.status_code == 200
    assert ready_before.json()["ready"] is True, ready_before.json()

    archived = client.post(f"/api/projects/{project_id}/sources/{public_source['id']}/archive")
    assert archived.status_code == 200, archived.text
    for version_id in versions.values():
        document = client.get(f"/api/documents/{version_id}").json()
        assert document["artifact_health"]["health_status"] == expected_archive["expected_document_health"]

    ready_after = client.get(f"/api/projects/{project_id}/handoff/readiness")
    assert ready_after.status_code == 200
    assert ready_after.json()["ready"] is expected_archive["expected_handoff_ready"]
    assert any("unhealthy" in item["code"] for item in ready_after.json()["missing"])

    # Engineering metrics that are meaningful inside this frozen execution.
    assert client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS n FROM project_claim_evidence_links l JOIN project_claims c ON c.id=l.claim_id WHERE c.project_id<>?",
        (project_id,),
    )["n"] == 0
    assert client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS n FROM audit_events WHERE action='runtime_fallback'"
    )["n"] == 0
    assert client.app.state.db.fetch_one(
        "SELECT COUNT(*) AS n FROM project_snapshots WHERE id=? AND content_sha256<>?",
        (snapshot_v1["id"], v1_sha),
    )["n"] == 0
    assert real_source["source_type"] == "real_user_research"
