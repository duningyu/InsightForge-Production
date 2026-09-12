from __future__ import annotations

import io
import json
import zipfile

from app.services.handoff import HandoffService


def quick_project(client, *, confirm: bool = True) -> str:
    response = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert response.status_code == 201, response.text
    project_id = response.json()["project_id"]
    if confirm:
        confirmed = client.post(
            f"/api/projects/{project_id}/idea-brief/confirm",
            json={"human_confirmed": True, "note": "理解准确"},
        )
        assert confirmed.status_code == 200, confirmed.text
    return project_id


def test_solution_generation_rejects_unconfirmed_idea_brief(client):
    project_id = quick_project(client, confirm=False)
    response = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert response.status_code == 409


def test_solution_generation_persists_run_and_domain_specific_candidates(client):
    project_id = quick_project(client)
    response = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["run"]["status"] == "completed"
    assert len(body["candidates"]) == 3
    mechanisms = {item["mechanism"] for item in body["candidates"]}
    assert "rule_based" in mechanisms
    assert {"prediction_based", "human_in_the_loop"} <= mechanisms
    assert not any("产品教练" in item["title"] for item in body["candidates"])
    assert not any("score" in item for item in body["candidates"])
    assert any(
        not item["requires_llm_runtime"]
        and not item["requires_rag_runtime"]
        and not item["requires_agent_runtime"]
        for item in body["candidates"]
    )

    run_row = client.app.state.db.fetch_one(
        "SELECT * FROM solution_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    assert run_row is not None
    assert run_row["provider"] == "fixture"
    assert run_row["model"]
    assert run_row["prompt_version"]
    assert run_row["schema_version"]
    assert run_row["generator_version"]
    assert len(run_row["input_sha256"]) == 64
    assert len(run_row["output_sha256"]) == 64

    candidate_rows = client.app.state.db.fetch_all(
        "SELECT * FROM solution_candidates WHERE run_id = ? ORDER BY created_at, id",
        (run_row["id"],),
    )
    assert len(candidate_rows) == 3
    assert {row["required_data_class"] for row in candidate_rows}
    assert {row["core_decision_logic"] for row in candidate_rows}


def test_solution_generation_records_runtime_trace_in_audit(client):
    project_id = quick_project(client)
    response = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert response.status_code == 201
    run_id = response.json()["run"]["id"]
    row = client.app.state.db.fetch_one(
        "SELECT payload_json FROM audit_events WHERE entity_type='solution_run' AND entity_id = ?",
        (run_id,),
    )
    assert row is not None
    payload = json.loads(row["payload_json"])
    for key in (
        "provider", "model", "prompt_version", "schema_version", "generator_version",
        "input_sha256", "output_sha256", "status", "runtime_mode",
    ):
        assert key in payload
    assert payload["runtime_mode"] == "deterministic_demo"


def test_solution_list_returns_latest_run_and_persisted_validator_dimensions(client):
    project_id = quick_project(client)
    generated = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert generated.status_code == 201
    response = client.get(f"/api/projects/{project_id}/solutions")
    assert response.status_code == 200
    body = response.json()
    assert body["latest_run"]["id"] == generated.json()["run"]["id"]
    assert len(body["candidates"]) == 3
    assert all(item["required_data_class"] for item in body["candidates"])
    assert all(item["major_dependency"] for item in body["candidates"])


def test_selected_solution_b_is_inherited_by_prd_techdoc_and_handoff(client):
    project_id = quick_project(client)
    generated = client.post(f"/api/projects/{project_id}/solutions/generate")
    assert generated.status_code == 201, generated.text
    candidates = generated.json()["candidates"]
    selected = candidates[1]
    rejected = candidates[0]
    rationale = "选择 B：先验证人工复核队列能否降低缺货判断遗漏。"
    snapshot_response = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={
            "strategy": "single",
            "candidate_ids": [selected["id"]],
            "rationale": rationale,
            "human_confirmed": True,
        },
    )
    assert snapshot_response.status_code == 201, snapshot_response.text
    snapshot = snapshot_response.json()
    assert snapshot["solution"]["title"] == selected["title"]

    # Local project-owned sources keep this path deterministic; no search or
    # provider call is needed to exercise document inheritance.
    for title, source_type, content in (
        ("公开资料", "public_source", "便利店补货需要查看库存和周转情况。"),
        ("实现证据", "implementation_evidence", "库存 API 与 SQLite 规则查询已经验证可以运行。"),
        ("模拟资料", "simulated_research", "人工构造的便利店访谈用于工作流测试。"),
    ):
        source = client.post(
            f"/api/projects/{project_id}/sources",
            json={"title": title, "source_type": source_type, "authority": 0.8, "content": content, "filename": f"{title}.txt"},
        )
        assert source.status_code == 201, source.text

    expected = {
        selected["title"],
        selected["summary"],
        selected["why_fit"],
        snapshot["problem"]["statement"],
        snapshot["target_user"]["primary"],
        rationale,
        selected["user_flow"][0],
        selected["features"][0],
    }
    documents = {}
    for doc_type in ("prd", "techdoc"):
        response = client.post(
            f"/api/projects/{project_id}/documents/generate",
            json={"doc_type": doc_type, "use_competitor_snapshot": False},
        )
        assert response.status_code == 200, response.text
        documents[doc_type] = response.json()
        content = documents[doc_type]["content"]
        assert content.strip()
        assert all(value in content for value in expected)
        assert rejected["title"] not in content

    for document in documents.values():
        version_id = document["version_id"]
        client.app.state.db.execute(
            "UPDATE document_versions SET validation_status='passed' WHERE id=?", (version_id,)
        )
        confirmed = client.post(
            f"/api/document-versions/{version_id}/confirm",
            json={"actor": "pm", "note": "确认选中方案 B", "human_confirmed": True},
        )
        assert confirmed.status_code == 200, confirmed.text

    readiness = HandoffService(client.app.state.db).readiness(project_id)
    assert readiness["ready"] is True
    data, _manifest = HandoffService(client.app.state.db).build_zip(
        project_id, target_client="codex", actor="pm"
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {
            name: archive.read(name).decode("utf-8")
            for name in ("PROJECT_SNAPSHOT.json", "MVP_SCOPE.md", "CONFIRMED_CONTEXT.md", "PRD_APPROVED.md", "TECHDOC_APPROVED.md")
        }
    assert selected["title"] in files["PROJECT_SNAPSHOT.json"]
    assert selected["title"] in files["MVP_SCOPE.md"]
    assert all(value.strip() for value in files.values())
    for name, content in files.items():
        assert rejected["title"] not in content, name
    assert selected["user_flow"][0] in files["PRD_APPROVED.md"]
    assert selected["user_flow"][0] in files["TECHDOC_APPROVED.md"]
