from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from app.tools import ToolRegistry
from app.services.handoff import HandoffService


def _prepare_v3(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    project_id = quick.json()["project_id"]
    client.post(f"/api/projects/{project_id}/idea-brief/confirm", json={"human_confirmed": True, "note": "确认"})
    candidates = client.post(f"/api/projects/{project_id}/solutions/generate").json()["candidates"]
    selected = next(item for item in candidates if item["mechanism"] == "rule_based")
    snapshot = client.post(
        f"/api/projects/{project_id}/solutions/select",
        json={"strategy": "single", "candidate_ids": [selected["id"]], "rationale": "先验证规则 MVP", "human_confirmed": True},
    ).json()
    for title, source_type, content in (
        ("公开资料", "public_source", "便利店补货需要查看库存和周转情况。"),
        ("实现证据", "implementation_evidence", "库存 API 与 SQLite 规则查询已经验证可以运行。"),
        ("模拟资料", "simulated_research", "人工构造的便利店访谈用于工作流测试。"),
    ):
        response = client.post(
            f"/api/projects/{project_id}/sources",
            json={"title": title, "source_type": source_type, "authority": 0.8, "content": content, "filename": f"{title}.txt"},
        )
        assert response.status_code == 201
    return project_id, snapshot


def _generate_confirm_pair(client, project_id: str):
    versions = {}
    for doc_type in ("prd", "techdoc"):
        generated = client.post(
            f"/api/projects/{project_id}/documents/generate",
            json={"doc_type": doc_type, "idempotency_key": f"handoff-v3-{doc_type}"},
        )
        assert generated.status_code == 200, generated.text
        version_id = generated.json()["version_id"]
        client.app.state.db.execute("UPDATE document_versions SET validation_status='passed' WHERE id=?", (version_id,))
        confirmed = client.post(
            f"/api/document-versions/{version_id}/confirm",
            json={"actor": "pm", "note": "确认", "human_confirmed": True},
        )
        assert confirmed.status_code == 200, confirmed.text
        versions[doc_type] = confirmed.json()
    return versions


def test_v3_handoff_requires_current_healthy_snapshot_and_both_current_confirmed_documents(client):
    project_id, snapshot = _prepare_v3(client)
    service = HandoffService(client.app.state.db)
    before = service.readiness(project_id)
    assert before["ready"] is False
    assert {item["code"] for item in before["missing"]} >= {"confirmed_prd_missing", "confirmed_techdoc_missing"}

    versions = _generate_confirm_pair(client, project_id)
    ready = service.readiness(project_id)
    assert ready["ready"] is True
    assert ready["snapshot"]["id"] == snapshot["id"]
    assert ready["snapshot"]["health_status"] == "current"
    assert ready["documents"]["prd"]["version_id"] == versions["prd"]["id"]
    assert ready["documents"]["techdoc"]["version_id"] == versions["techdoc"]["id"]


def test_v3_handoff_fails_closed_after_confirmed_document_becomes_stale(client):
    project_id, _snapshot = _prepare_v3(client)
    versions = _generate_confirm_pair(client, project_id)
    service = HandoffService(client.app.state.db)
    assert service.readiness(project_id)["ready"] is True

    db = client.app.state.db
    source_dep = db.fetch_one(
        "SELECT dependency_id FROM artifact_dependencies WHERE artifact_type='document_version' AND artifact_id=? AND dependency_type='source' LIMIT 1",
        (versions["prd"]["id"],),
    )
    assert source_dep is not None
    archived = client.post(f"/api/projects/{project_id}/sources/{source_dep['dependency_id']}/archive")
    assert archived.status_code == 200
    not_ready = service.readiness(project_id)
    assert not_ready["ready"] is False
    assert any("unhealthy" in item["code"] for item in not_ready["missing"])


def test_v3_handoff_package_starts_with_snapshot_mvp_risks_and_confirmed_context(client):
    project_id, _snapshot = _prepare_v3(client)
    _generate_confirm_pair(client, project_id)
    data, manifest = HandoffService(client.app.state.db).build_zip(project_id, target_client="codex", actor="pm")
    assert manifest["snapshot"]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"PROJECT_SNAPSHOT.json", "MVP_SCOPE.md", "UNRESOLVED_RISKS.md", "CONFIRMED_CONTEXT.md"} <= names
        assert "APPROVED_CONTEXT.md" not in names
        assert archive.read("MVP_SCOPE.md").decode("utf-8").startswith("# MVP Scope")


def test_v3_tool_registry_has_required_risk_surface_and_l2_requires_host_confirmation(db):
    registry = ToolRegistry(db)
    schemas = {item["function"]["name"]: item["function"] for item in registry.schemas()}
    expected = {
        "get_current_snapshot": "L0",
        "get_project_claims": "L0",
        "retrieve_project_evidence": "L0",
        "get_solution_candidates": "L0",
        "get_document_version": "L0",
        "create_solution_proposal": "L1",
        "create_evidence_relation_proposal": "L1",
        "create_change_proposal": "L1",
        "create_document_draft": "L1",
        "confirm_solution_decision": "L2",
        "accept_change_proposal": "L2",
        "confirm_document_version": "L2",
    }
    for name, risk in expected.items():
        assert schemas[name]["x-risk-level"] == risk
    assert {"delete_project", "publish_external", "overwrite_approved_version", "export_handoff_zip"}.isdisjoint(schemas)
    for name, arguments in (
        ("confirm_solution_decision", {"project_id": "x", "strategy": "single", "candidate_ids": ["x"], "rationale": "x"}),
        ("accept_change_proposal", {"proposal_id": "x", "note": ""}),
        ("confirm_document_version", {"version_id": "x", "note": ""}),
    ):
        with pytest.raises(PermissionError):
            registry.execute(name, arguments, actor="host", human_confirmed=False)


def test_mcp_server_exposes_only_p0_snapshot_document_mvp_resources_and_two_tools():
    text = (Path(__file__).resolve().parents[1] / "app" / "mcp_server.py").read_text(encoding="utf-8")
    for uri in (
        "insightforge://projects/{project_id}/snapshot/current",
        "insightforge://projects/{project_id}/documents/prd/current",
        "insightforge://projects/{project_id}/documents/techdoc/current",
        "insightforge://projects/{project_id}/mvp-scope",
        "insightforge://projects/{project_id}/unresolved-risks",
    ):
        assert uri in text
    assert text.count("@mcp.tool()") == 2
    assert "def get_current_project_context" in text
    assert "def build_handoff_manifest" in text
    for forbidden in ("retrieve_project_sources", "create_artifact_draft", "remote OAuth", "multi-client"):
        assert forbidden not in text
