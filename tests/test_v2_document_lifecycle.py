import pytest

from app.services.document_versions import DocumentVersionService
from app.services.loop import DocumentLoop


def _draft_version(db, doc_type: str = "prd") -> dict:
    return DocumentLoop(db).run(
        "project_insightforge_demo",
        doc_type,
        idempotency_key=f"document-lifecycle-{doc_type}",
    )


def test_document_version_can_be_trashed_restored_and_purged(db):
    version = _draft_version(db)
    service = DocumentVersionService(db)

    trashed = service.move_to_trash(version["version_id"], actor="tester")
    assert trashed["lifecycle_status"] == "trashed"
    assert version["version_id"] not in {
        item["id"] for item in service.list_active("project_insightforge_demo")
    }
    assert version["version_id"] in {
        item["id"] for item in service.list_trashed("project_insightforge_demo")
    }

    restored = service.restore_from_trash(version["version_id"], actor="tester")
    assert restored["lifecycle_status"] == "active"

    service.move_to_trash(version["version_id"], actor="tester")
    purged = service.purge_from_trash(version["version_id"], actor="tester")
    assert purged["status"] == "permanently_deleted"
    assert db.fetch_one("SELECT id FROM document_versions WHERE id = ?", (version["version_id"],)) is None


def test_document_lifecycle_api_exposes_trash_restore_and_purge(client, db):
    version = _draft_version(db, "techdoc")
    version_id = version["version_id"]

    assert client.post(f"/api/documents/{version_id}/trash").json()["lifecycle_status"] == "trashed"
    assert client.get(f"/api/documents/{version_id}").status_code == 404
    assert client.get(f"/api/documents/{version_id}/claims").status_code == 404
    assert version_id in {
        item["id"]
        for item in client.get("/api/projects/project_insightforge_demo/documents/trash").json()
    }
    assert client.post(f"/api/documents/{version_id}/restore").json()["lifecycle_status"] == "active"
    assert client.post(f"/api/documents/{version_id}/trash").status_code == 200
    assert client.delete(f"/api/documents/{version_id}").status_code == 200


def test_handoff_ignores_trashed_approved_document_version(db):
    version = _draft_version(db)
    db.execute(
        "UPDATE document_versions SET status = 'approved', validation_status = 'passed' WHERE id = ?",
        (version["version_id"],),
    )
    DocumentVersionService(db).move_to_trash(version["version_id"], actor="tester")

    from app.services.handoff import HandoffService

    readiness = HandoffService(db).readiness("project_insightforge_demo")
    assert readiness["documents"]["prd"] is None
    assert {item["code"] for item in readiness["missing"]} >= {"approved_prd_missing"}
