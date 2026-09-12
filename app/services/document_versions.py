from __future__ import annotations

import json
from typing import Any

from app.db import Database, utc_now
from app.services.generation_contracts import reject_raw_generation_values


class DocumentVersionService:
    """Own the recoverable lifecycle of individual PRD and TechDoc versions."""

    def __init__(self, db: Database):
        self.db = db


    def confirm(
        self,
        version_id: str,
        *,
        actor: str,
        note: str = "",
        human_confirmed: bool = False,
    ) -> dict[str, Any]:
        if not human_confirmed:
            raise PermissionError("document confirmation requires explicit human confirmation")
        version = self._get(version_id)
        if version["lifecycle_status"] != "active":
            raise ValueError("only an active document version can be confirmed")
        if version["validation_status"] != "passed":
            raise ValueError("only a passed document version can be confirmed")
        health = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (version_id,),
        )
        if health is not None and health["health_status"] != "current":
            raise ValueError("only a healthy current document version can be confirmed")
        if version["status"] != "approved":
            confirmed_at = utc_now()
            self.db.execute(
                "UPDATE document_versions SET status='approved', approved_at=? WHERE id=?",
                (confirmed_at, version_id),
            )
            self.db.insert_audit(
                actor=actor, action="document_version_confirmed", entity_type="document_version",
                entity_id=version_id, payload={"note": note, "human_confirmed": True},
            )
        result = self._get(version_id)
        result["citations"] = json.loads(result.pop("citations_json"))
        result["artifact_health"] = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (version_id,),
        )
        return result

    def list_active(self, project_id: str) -> list[dict[str, Any]]:
        return self._list(project_id, lifecycle_status="active")

    def list_trashed(self, project_id: str) -> list[dict[str, Any]]:
        return self._list(project_id, lifecycle_status="trashed")

    def move_to_trash(self, version_id: str, *, actor: str) -> dict[str, Any]:
        version = self._get(version_id)
        if version["lifecycle_status"] == "trashed":
            return version
        self.db.execute(
            "UPDATE document_versions SET lifecycle_status = 'trashed', trashed_at = ? WHERE id = ?",
            (utc_now(), version_id),
        )
        self._audit(actor, "document_version_moved_to_trash", version)
        return self._get(version_id)

    def restore_from_trash(self, version_id: str, *, actor: str) -> dict[str, Any]:
        version = self._get(version_id)
        if version["lifecycle_status"] != "trashed":
            raise ValueError("only trashed document versions can be restored")
        self.db.execute(
            "UPDATE document_versions SET lifecycle_status = 'active', trashed_at = NULL WHERE id = ?",
            (version_id,),
        )
        self._audit(actor, "document_version_restored_from_trash", version)
        return self._get(version_id)

    def purge_from_trash(self, version_id: str, *, actor: str) -> dict[str, Any]:
        version = self._get(version_id)
        if version["lifecycle_status"] != "trashed":
            raise ValueError("document version must be in trash before permanent deletion")
        with self.db.connect() as connection:
            connection.execute(
                "DELETE FROM claim_evidence_links WHERE claim_id IN (SELECT id FROM document_claims WHERE version_id = ?)",
                (version_id,),
            )
            connection.execute("DELETE FROM document_claims WHERE version_id = ?", (version_id,))
            connection.execute("DELETE FROM validation_issues WHERE version_id = ?", (version_id,))
            connection.execute("UPDATE generation_runs SET version_id = NULL WHERE version_id = ?", (version_id,))
            connection.execute("DELETE FROM document_versions WHERE id = ?", (version_id,))
        self._audit(actor, "document_version_permanently_deleted", version)
        return {"id": version_id, "status": "permanently_deleted"}

    def _list(self, project_id: str, *, lifecycle_status: str) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT id, document_id, project_id, doc_type, version, canvas_version,
                   status, lifecycle_status, trashed_at, validation_status, created_at, approved_at
            FROM document_versions
            WHERE project_id = ? AND lifecycle_status = ?
            ORDER BY doc_type, version DESC
            """,
            (project_id, lifecycle_status),
        )

    def _get(self, version_id: str) -> dict[str, Any]:
        version = self.db.fetch_one("SELECT * FROM document_versions WHERE id = ?", (version_id,))
        if version is None:
            raise KeyError("document version not found")
        reject_raw_generation_values([version["content"], json.loads(version["citations_json"] or "[]")])
        return version

    def _audit(self, actor: str, action: str, version: dict[str, Any]) -> None:
        self.db.insert_audit(
            actor=actor,
            action=action,
            entity_type="document_version",
            entity_id=version["id"],
            payload={
                "project_id": version["project_id"],
                "doc_type": version["doc_type"],
                "version": version["version"],
                "document_status": version["status"],
            },
        )
