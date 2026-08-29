from __future__ import annotations

import hashlib

import pytest


def prepare_snapshot(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    project_id = quick.json()["project_id"]
    client.post(
        f"/api/projects/{project_id}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "确认"},
    )
    candidates = client.post(f"/api/projects/{project_id}/solutions/generate").json()["candidates"]
    selected = next(item for item in candidates if item["mechanism"] == "rule_based")
    snapshot = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": "先验证最低数据依赖方案",
            "human_confirmed": True,
        },
    ).json()
    return project_id, snapshot


def add_supporting_source(client, project_id: str, claim_id: str, *, title: str, text: str):
    source = client.app.state.sources.add_source(
        project_id=project_id,
        title=title,
        source_type="implementation_evidence",
        authority=0.8,
        content=text,
        filename=f"{title}.txt",
    )
    db = client.app.state.db
    chunk = db.fetch_one(
        "SELECT * FROM source_chunks WHERE source_id=? ORDER BY chunk_index LIMIT 1",
        (source["id"],),
    )
    result = client.app.state.project_claims.persist_relation(
        project_id=project_id,
        claim_id=claim_id,
        source_id=source["id"],
        chunk_id=chunk["id"],
        relation="supports",
        directness="direct",
        scope_fit="fit",
        recency_state="current",
        retrieval_run_id=None,
        analysis_version="source-lifecycle-test-v1",
        evidence_span=text,
        reason="实现证据直接支持可行性",
    )
    return source, chunk, result


def material_feasibility_claim(client, project_id: str):
    return client.app.state.db.fetch_one(
        """
        SELECT pc.* FROM project_claims pc
        JOIN decision_claim_links dcl ON dcl.claim_id=pc.id
        WHERE pc.project_id=? AND pc.claim_type='feasibility' AND pc.criticality='critical'
          AND pc.status='active' AND dcl.role='assumption'
        ORDER BY pc.created_at,pc.id LIMIT 1
        """,
        (project_id,),
    )


def test_archive_wrong_project_source_pair_fails_closed(client):
    project_a, _ = prepare_snapshot(client)
    project_b, _ = prepare_snapshot(client)
    claim = material_feasibility_claim(client, project_a)
    source, _chunk, _ = add_supporting_source(
        client, project_a, claim["id"], title="scope-source", text="库存查询接口已经完成验证。"
    )

    response = client.post(f"/api/projects/{project_b}/sources/{source['id']}/archive")
    assert response.status_code in {404, 422}
    row = client.app.state.db.fetch_one("SELECT status FROM sources WHERE id=?", (source["id"],))
    assert row["status"] == "active"
    assert client.app.state.db.fetch_one(
        "SELECT active FROM project_claim_evidence_links WHERE claim_id=? AND source_id=?",
        (claim["id"], source["id"]),
    )["active"] == 1


def test_archive_deactivates_links_recomputes_stale_and_creates_material_proposal(client):
    project_id, snapshot = prepare_snapshot(client)
    claim = material_feasibility_claim(client, project_id)
    source, _chunk, persisted = add_supporting_source(
        client, project_id, claim["id"], title="archive-source", text="库存查询接口已经完成验证。"
    )
    assert persisted["claim_status"] == "limited_support"
    snapshot_before = client.get(f"/api/project-snapshots/{snapshot['id']}").json()

    response = client.post(f"/api/projects/{project_id}/sources/{source['id']}/archive")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"]["status"] == "archived"
    assert payload["affected_claims"][0]["before"] == "limited_support"
    assert payload["affected_claims"][0]["after"] == "stale"
    assert payload["proposal_ids"]

    db = client.app.state.db
    assert db.fetch_one(
        "SELECT active FROM project_claim_evidence_links WHERE claim_id=? AND source_id=?",
        (claim["id"], source["id"]),
    )["active"] == 0
    assert db.fetch_one("SELECT verification_status FROM project_claims WHERE id=?", (claim["id"],))["verification_status"] == "stale"
    assert client.app.state.artifact_health.get("project_snapshot", snapshot["id"])["health_status"] == "stale_evidence"
    snapshot_after = client.get(f"/api/project-snapshots/{snapshot['id']}").json()
    assert snapshot_after["content_sha256"] == snapshot_before["content_sha256"]


def test_archive_one_of_two_support_sources_recomputes_to_limited_support(client):
    project_id, _snapshot = prepare_snapshot(client)
    claim = material_feasibility_claim(client, project_id)
    source1, _c1, _ = add_supporting_source(
        client, project_id, claim["id"], title="support-1", text="库存查询接口已完成第一轮验证。"
    )
    _source2, _c2, second = add_supporting_source(
        client, project_id, claim["id"], title="support-2", text="库存查询接口已完成第二轮独立验证。"
    )
    assert second["claim_status"] == "supported"

    response = client.post(f"/api/projects/{project_id}/sources/{source1['id']}/archive")
    assert response.status_code == 200, response.text
    assert client.app.state.db.fetch_one(
        "SELECT verification_status FROM project_claims WHERE id=?", (claim["id"],)
    )["verification_status"] == "limited_support"


def test_restore_revalidates_and_reactivates_valid_links(client):
    project_id, _snapshot = prepare_snapshot(client)
    claim = material_feasibility_claim(client, project_id)
    source, _chunk, _ = add_supporting_source(
        client, project_id, claim["id"], title="restore-valid", text="库存接口能够稳定返回当前库存。"
    )
    archived = client.post(f"/api/projects/{project_id}/sources/{source['id']}/archive")
    assert archived.status_code == 200

    restored = client.post(f"/api/projects/{project_id}/sources/{source['id']}/restore")
    assert restored.status_code == 200, restored.text
    payload = restored.json()
    assert payload["source"]["status"] == "active"
    assert payload["invalid_links"] == []
    assert client.app.state.db.fetch_one(
        "SELECT active FROM project_claim_evidence_links WHERE claim_id=? AND source_id=?",
        (claim["id"], source["id"]),
    )["active"] == 1
    assert client.app.state.db.fetch_one(
        "SELECT verification_status FROM project_claims WHERE id=?", (claim["id"],)
    )["verification_status"] == "limited_support"


def test_restore_keeps_old_link_inactive_when_source_identity_or_span_changed(client):
    project_id, _snapshot = prepare_snapshot(client)
    claim = material_feasibility_claim(client, project_id)
    source, chunk, _ = add_supporting_source(
        client, project_id, claim["id"], title="restore-changed", text="原始证据：库存接口可以运行。"
    )
    assert client.post(f"/api/projects/{project_id}/sources/{source['id']}/archive").status_code == 200

    changed = "替换后的来源内容，不再包含原始证据。"
    changed_sha = hashlib.sha256(changed.encode("utf-8")).hexdigest()
    db = client.app.state.db
    db.execute("UPDATE sources SET content=?,sha256=? WHERE id=?", (changed, changed_sha, source["id"]))
    db.execute("UPDATE source_chunks SET content=? WHERE id=?", (changed, chunk["id"]))

    restored = client.post(f"/api/projects/{project_id}/sources/{source['id']}/restore")
    assert restored.status_code == 200, restored.text
    payload = restored.json()
    assert payload["source"]["status"] == "active"
    assert len(payload["invalid_links"]) == 1
    assert payload["invalid_links"][0]["reason"] in {"SOURCE_VERSION_CHANGED", "EVIDENCE_SPAN_NOT_FOUND"}
    assert db.fetch_one(
        "SELECT active FROM project_claim_evidence_links WHERE claim_id=? AND source_id=?",
        (claim["id"], source["id"]),
    )["active"] == 0
    assert db.fetch_one("SELECT verification_status FROM project_claims WHERE id=?", (claim["id"],))["verification_status"] == "stale"


def test_archive_failure_during_impact_rolls_back_source_and_links(client, monkeypatch):
    project_id, _snapshot = prepare_snapshot(client)
    claim = material_feasibility_claim(client, project_id)
    source, _chunk, _ = add_supporting_source(
        client, project_id, claim["id"], title="rollback", text="库存接口验证通过。"
    )

    def fail_impact(*args, **kwargs):
        raise RuntimeError("injected impact failure")

    monkeypatch.setattr(client.app.state.impact, "resolve_claim_change_tx", fail_impact)
    with pytest.raises(RuntimeError, match="injected impact failure"):
        client.app.state.sources.archive(project_id, source["id"], actor="test")

    db = client.app.state.db
    assert db.fetch_one("SELECT status FROM sources WHERE id=?", (source["id"],))["status"] == "active"
    assert db.fetch_one(
        "SELECT active FROM project_claim_evidence_links WHERE claim_id=? AND source_id=?",
        (claim["id"], source["id"]),
    )["active"] == 1
    assert db.fetch_one("SELECT verification_status FROM project_claims WHERE id=?", (claim["id"],))["verification_status"] == "limited_support"
