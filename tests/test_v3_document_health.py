from __future__ import annotations


def _quick_project(client, *, with_snapshot: bool) -> str:
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    confirmed = client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认理解"},
    )
    assert confirmed.status_code == 200, confirmed.text
    if with_snapshot:
        generated = client.post(f"/api/projects/{project_id}/solutions/generate")
        assert generated.status_code == 201, generated.text
        candidate = next(item for item in generated.json()["candidates"] if item["mechanism"] == "rule_based")
        selected = client.post(
            f"/api/projects/{project_id}/solutions/select",
            json={
                "strategy": "single",
                "candidate_ids": [candidate["id"]],
                "rationale": "先做低数据依赖 MVP",
                "human_confirmed": True,
            },
        )
        assert selected.status_code == 201, selected.text
    return project_id


def _add_generation_sources(client, project_id: str) -> list[str]:
    created = []
    for title, source_type, content in (
        ("公开补货资料", "public_source", "便利店补货需要结合当前库存和商品周转情况进行判断。"),
        ("实现记录", "implementation_evidence", "FastAPI 与 SQLite 已能支持库存查询和规则判断的本地 MVP。"),
        ("模拟演示材料", "simulated_research", "这是人工构造的店主演示访谈，仅用于验证工作流。"),
    ):
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
        created.append(response.json()["id"])
    return created


def test_v3_document_generation_requires_current_snapshot(client):
    project_id = _quick_project(client, with_snapshot=False)
    response = client.post(
        f"/api/projects/{project_id}/documents/generate",
        json={"doc_type": "prd", "idempotency_key": "v3-no-snapshot"},
    )
    assert response.status_code == 422
    assert "snapshot" in response.json()["detail"].lower()


def test_v3_document_generation_records_snapshot_claim_source_dependencies_and_health(client):
    project_id = _quick_project(client, with_snapshot=True)
    _add_generation_sources(client, project_id)
    response = client.post(
        f"/api/projects/{project_id}/documents/generate",
        json={"doc_type": "prd", "idempotency_key": "v3-snapshot-aware-prd"},
    )
    assert response.status_code == 200, response.text
    version_id = response.json()["version_id"]
    db = client.app.state.db
    dependencies = db.fetch_all(
        "SELECT dependency_type,dependency_id FROM artifact_dependencies WHERE artifact_type='document_version' AND artifact_id=?",
        (version_id,),
    )
    dep_types = {row["dependency_type"] for row in dependencies}
    assert "project_snapshot" in dep_types
    assert "project_claim" in dep_types
    assert "source" in dep_types
    health = client.app.state.artifact_health.get("document_version", version_id)
    assert health["health_status"] == "current"


def test_confirm_and_deprecated_approve_share_human_gate_and_confirmation_audit(client):
    project_id = _quick_project(client, with_snapshot=True)
    _add_generation_sources(client, project_id)
    generated = client.post(
        f"/api/projects/{project_id}/documents/generate",
        json={"doc_type": "techdoc", "idempotency_key": "v3-confirm-techdoc"},
    )
    assert generated.status_code == 200, generated.text
    version_id = generated.json()["version_id"]
    client.app.state.db.execute(
        "UPDATE document_versions SET validation_status='passed' WHERE id=?", (version_id,)
    )

    denied = client.post(
        f"/api/document-versions/{version_id}/confirm",
        json={"actor": "pm", "note": "", "human_confirmed": False},
    )
    assert denied.status_code == 403

    confirmed = client.post(
        f"/api/document-versions/{version_id}/confirm",
        json={"actor": "pm", "note": "人工确认", "human_confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "approved"
    first_confirmed_at = confirmed.json()["approved_at"]

    alias = client.post(
        f"/api/documents/{version_id}/approve",
        json={"actor": "pm", "note": "旧接口重复调用", "human_confirmed": True},
    )
    assert alias.status_code == 200, alias.text
    assert alias.json()["approved_at"] == first_confirmed_at
    audits = client.app.state.db.fetch_all(
        "SELECT action FROM audit_events WHERE entity_type='document_version' AND entity_id=? ORDER BY created_at",
        (version_id,),
    )
    assert any(row["action"] == "document_version_confirmed" for row in audits)
    assert all(row["action"] != "document_version_approved" for row in audits)


def test_archiving_cited_source_marks_document_stale_without_mutating_historical_content(client):
    project_id = _quick_project(client, with_snapshot=True)
    _add_generation_sources(client, project_id)
    generated = client.post(
        f"/api/projects/{project_id}/documents/generate",
        json={"doc_type": "prd", "idempotency_key": "v3-stale-prd"},
    )
    assert generated.status_code == 200, generated.text
    version_id = generated.json()["version_id"]
    db = client.app.state.db
    db.execute("UPDATE document_versions SET validation_status='passed' WHERE id=?", (version_id,))
    confirmed = client.post(
        f"/api/document-versions/{version_id}/confirm",
        json={"actor": "pm", "note": "确认", "human_confirmed": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    before = db.fetch_one("SELECT content,approved_at FROM document_versions WHERE id=?", (version_id,))
    source_dep = db.fetch_one(
        "SELECT dependency_id FROM artifact_dependencies WHERE artifact_type='document_version' AND artifact_id=? AND dependency_type='source' ORDER BY dependency_id LIMIT 1",
        (version_id,),
    )
    assert source_dep is not None

    archived = client.post(f"/api/projects/{project_id}/sources/{source_dep['dependency_id']}/archive")
    assert archived.status_code == 200, archived.text
    after = db.fetch_one("SELECT content,approved_at FROM document_versions WHERE id=?", (version_id,))
    assert after == before
    health = client.app.state.artifact_health.get("document_version", version_id)
    assert health["health_status"] == "stale_evidence"

    fetched = client.get(f"/api/documents/{version_id}")
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["artifact_health"]["health_status"] == "stale_evidence"
    assert any(item["dependency_type"] == "source" for item in payload["dependencies"])
    assert any(item["dependency_type"] == "project_snapshot" for item in payload["dependencies"])
