import hashlib
import io
import json
import uuid
import zipfile

import pytest

from app.db import utc_now
from app.mcp_functions import InsightForgeMCPFunctions
from app.services.handoff import HandoffService
from app.tools import ToolRegistry


REQUIRED_FILES = {
    "README_FIRST.md",
    "APPROVED_CONTEXT.md",
    "PRD_APPROVED.md",
    "TECHDOC_APPROVED.md",
    "CLAIM_LEDGER.json",
    "SOURCE_MANIFEST.json",
    "RETRIEVAL_TRACE.json",
    "ACCEPTANCE_TESTS.md",
    "IMPLEMENTATION_TASKS.json",
    "AGENTS.md",
    "HANDOFF_MANIFEST.json",
}


def _approve_pair(db):
    registry = ToolRegistry(db)
    created = {}
    for doc_type in ("prd", "techdoc"):
        draft = registry.execute(
            "create_document_draft",
            {
                "project_id": "project_insightforge_demo",
                "doc_type": doc_type,
                "idempotency_key": f"handoff-{doc_type}-{uuid.uuid4().hex}",
            },
            actor="pm",
            human_confirmed=True,
        )
        approved = registry.execute(
            "approve_document_version",
            {"version_id": draft["version_id"], "note": "人工复核通过"},
            actor="pm",
            human_confirmed=True,
        )
        created[doc_type] = approved
    return created


def test_handoff_readiness_fails_closed_before_approved_documents(db):
    service = HandoffService(db)
    readiness = service.readiness("project_insightforge_demo")
    assert readiness["ready"] is False
    assert {item["code"] for item in readiness["missing"]} == {
        "approved_prd_missing",
        "approved_techdoc_missing",
    }
    with pytest.raises(ValueError, match="handoff is not ready"):
        service.build_zip(
            "project_insightforge_demo", target_client="codex", actor="pm"
        )


def test_handoff_reports_draft_unresolved_claims_separately_from_selected_versions(db):
    registry = ToolRegistry(db)
    draft = registry.execute(
        "create_document_draft",
        {
            "project_id": "project_insightforge_demo",
            "doc_type": "prd",
            "idempotency_key": f"draft-unresolved-{uuid.uuid4().hex}",
        },
        actor="pm",
        human_confirmed=True,
    )
    db.execute(
        """
        INSERT INTO document_claims(
            id, version_id, project_id, section, claim_text, claim_type,
            support_status, explanation, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "claim_draft_unresolved",
            draft["version_id"],
            "project_insightforge_demo",
            "风险",
            "草稿仍缺真实用户证据",
            "unresolved",
            "missing_evidence",
            "尚未验证。",
            "{}",
            utc_now(),
        ),
    )

    readiness = HandoffService(db).readiness("project_insightforge_demo")
    assert readiness["unresolved_claim_count"] == 0
    assert readiness["draft_unresolved_claim_count"] >= 1


def test_handoff_zip_contains_real_artifacts_hash_manifest_and_unresolved_boundary(db):
    approved = _approve_pair(db)
    db.execute(
        """
        INSERT INTO document_claims(
            id, version_id, project_id, section, claim_text, claim_type,
            support_status, explanation, metadata_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "claim_manual_unresolved",
            approved["prd"]["id"],
            "project_insightforge_demo",
            "风险",
            "用户愿意持续付费",
            "unresolved",
            "missing_evidence",
            "当前没有真实付费证据，必须在交接中保留。",
            json.dumps({"category": "business_hypothesis"}, ensure_ascii=False),
            utc_now(),
        ),
    )

    service = HandoffService(db)
    readiness = service.readiness("project_insightforge_demo")
    assert readiness["ready"] is False
    assert readiness["unresolved_claim_count"] == 1
    assert "unresolved_items_acknowledgement_required" in {
        item["code"] for item in readiness["missing"]
    }
    acknowledgement = service.acknowledge_unresolved(
        "project_insightforge_demo",
        actor="pm",
        confirmed=True,
        note="已了解仍需确认的事项",
    )
    assert acknowledgement["status"] == "acknowledged"
    readiness = service.readiness("project_insightforge_demo")
    assert readiness["ready"] is True

    data, manifest = service.build_zip(
        "project_insightforge_demo", target_client="codex", actor="pm"
    )
    assert data.startswith(b"PK")
    assert manifest["target_client"] == "codex"
    assert manifest["unresolved_claim_count"] == 1
    assert manifest["claim_boundary"]["auto_approval"] is False

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert REQUIRED_FILES <= set(archive.namelist())
        embedded = json.loads(archive.read("HANDOFF_MANIFEST.json"))
        assert embedded["handoff_run_id"] == manifest["handoff_run_id"]
        for filename, metadata in embedded["files"].items():
            payload = archive.read(filename)
            assert hashlib.sha256(payload).hexdigest() == metadata["sha256"]
            assert len(payload) == metadata["bytes"]

        claim_ledger = json.loads(archive.read("CLAIM_LEDGER.json"))
        assert any(
            item["claim_text"] == "用户愿意持续付费" and item["claim_type"] == "unresolved"
            for document in claim_ledger["documents"]
            for item in document["items"]
        )
        agents = archive.read("AGENTS.md").decode("utf-8")
        assert "不得静默修改已批准需求" in agents
        assert "Codex" in agents

    stored = db.fetch_one(
        "SELECT * FROM handoff_runs WHERE id = ?", (manifest["handoff_run_id"],)
    )
    assert stored is not None
    assert stored["sha256"] == hashlib.sha256(data).hexdigest()
    audit = db.fetch_one(
        "SELECT action FROM audit_events WHERE entity_id = ? ORDER BY created_at DESC LIMIT 1",
        (manifest["handoff_run_id"],),
    )
    assert audit == {"action": "handoff_package_exported"}


def test_handoff_http_readiness_and_binary_export(client, db):
    _approve_pair(db)
    ready = client.get("/api/projects/project_insightforge_demo/handoff/readiness")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True

    exported = client.post(
        "/api/projects/project_insightforge_demo/handoff/export",
        json={"target_client": "codex"},
    )
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    assert exported.headers["x-handoff-sha256"] == hashlib.sha256(exported.content).hexdigest()
    assert exported.content.startswith(b"PK")


def test_handoff_tools_and_mcp_are_read_or_bounded_not_approval_shortcuts(db):
    registry = ToolRegistry(db)
    schemas = {item["function"]["name"]: item["function"] for item in registry.schemas()}
    assert schemas["get_handoff_readiness"]["x-risk-level"] == "L0"
    assert schemas["prepare_handoff_manifest"]["x-risk-level"] == "L1"
    assert "export_handoff_zip" not in schemas

    readiness = registry.execute(
        "get_handoff_readiness",
        {"project_id": "project_insightforge_demo"},
        actor="reviewer",
    )
    assert readiness["ready"] is False

    mcp = InsightForgeMCPFunctions(db)
    assert mcp.get_handoff_readiness("project_insightforge_demo")["ready"] is False
    claims = mcp.get_claim_ledger(
        "project_insightforge_demo",
        _approve_pair(db)["prd"]["id"],
    )
    assert claims["project_id"] == "project_insightforge_demo"
