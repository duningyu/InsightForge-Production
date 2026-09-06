from __future__ import annotations

import difflib
import json
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import ConflictError, DraftConflictError


class DocumentWorkspaceService:
    """Editable draft layer over immutable PRD/TechDoc versions."""

    DOC_TYPES = {"prd", "techdoc"}

    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _validate_doc_type(doc_type: str) -> None:
        if doc_type not in DocumentWorkspaceService.DOC_TYPES:
            raise ValueError("unsupported document type")

    def _project(self, project_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise KeyError("project not found")
        return row

    def _version(self, version_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM document_versions WHERE id=?", (version_id,))
        if row is None:
            raise KeyError("document version not found")
        row["citations"] = json.loads(row.pop("citations_json") or "[]")
        row["artifact_health"] = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (version_id,),
        )
        return row

    def list_versions(self, project_id: str, doc_type: str) -> list[dict[str, Any]]:
        self._project(project_id)
        self._validate_doc_type(doc_type)
        rows = self.db.fetch_all(
            """
            SELECT id FROM document_versions
            WHERE project_id=? AND doc_type=? AND lifecycle_status='active'
            ORDER BY version DESC, created_at DESC, id DESC
            """,
            (project_id, doc_type),
        )
        return [self._version(row["id"]) for row in rows]

    def get_draft(self, project_id: str, doc_type: str) -> dict[str, Any]:
        self._project(project_id)
        self._validate_doc_type(doc_type)
        row = self.db.fetch_one(
            "SELECT * FROM document_edit_drafts WHERE project_id=? AND doc_type=?",
            (project_id, doc_type),
        )
        if row is None:
            raise KeyError("document edit draft not found")
        return row

    def save_draft(
        self,
        project_id: str,
        doc_type: str,
        *,
        base_version_id: str,
        content: str,
        actor: str,
        base_revision: int | None = None,
    ) -> dict[str, Any]:
        self._project(project_id)
        self._validate_doc_type(doc_type)
        base = self._version(base_version_id)
        if base["project_id"] != project_id or base["doc_type"] != doc_type:
            raise ValueError("base version does not belong to project/document type")
        if base["lifecycle_status"] != "active":
            raise ValueError("base version must be active")
        if not content.strip():
            raise ValueError("document draft content cannot be empty")
        clean_content = content
        now = utc_now()
        current = self.db.fetch_one(
            "SELECT * FROM document_edit_drafts WHERE project_id=? AND doc_type=?",
            (project_id, doc_type),
        )
        if current is not None and base_revision is not None and int(current.get("revision", 1)) != base_revision:
            raise DraftConflictError(self.get_draft(project_id, doc_type))
        next_revision = int(current.get("revision", 1)) + 1 if current else 1
        draft_id = f"document_edit_draft_{uuid.uuid4().hex}"
        self.db.execute(
            """
            INSERT INTO document_edit_drafts(
                id,project_id,doc_type,base_version_id,content,updated_by,updated_at,revision
            ) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(project_id,doc_type) DO UPDATE SET
                base_version_id=excluded.base_version_id,
                content=excluded.content,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at,
                revision=excluded.revision
            """,
            (draft_id, project_id, doc_type, base_version_id, clean_content, actor.strip() or "web_user", now, next_revision),
        )
        return self.get_draft(project_id, doc_type)

    def _copy_dependencies_tx(self, connection, source_version_id: str, new_version_id: str, now: str) -> None:
        rows = connection.execute(
            """
            SELECT dependency_type,dependency_id,dependency_version
            FROM artifact_dependencies
            WHERE artifact_type='document_version' AND artifact_id=?
            """,
            (source_version_id,),
        ).fetchall()
        for row in rows:
            connection.execute(
                """
                INSERT OR IGNORE INTO artifact_dependencies(
                    artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at
                ) VALUES ('document_version',?,?,?,?,?)
                """,
                (new_version_id, row["dependency_type"], row["dependency_id"], row["dependency_version"], now),
            )

    def _create_version_from_source_tx(
        self,
        connection,
        *,
        source: dict[str, Any],
        content: str,
        actor: str,
        note: str,
        restored_from_version_id: str | None,
        audit_action: str,
    ) -> str:
        next_row = connection.execute(
            "SELECT COALESCE(MAX(version),0)+1 AS next_version FROM document_versions WHERE document_id=?",
            (source["document_id"],),
        ).fetchone()
        next_version = int(next_row["next_version"])
        version_id = f"document_version_{uuid.uuid4().hex}"
        now = utc_now()
        citations_json = json.dumps(source.get("citations") or [], ensure_ascii=False)
        connection.execute(
            """
            INSERT INTO document_versions(
                id,document_id,project_id,doc_type,version,canvas_version,status,content,
                citations_json,validation_status,idempotency_key,created_at,approved_at,
                competitor_snapshot_id,lifecycle_status,trashed_at,restored_from_version_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL,?,'active',NULL,?)
            """,
            (
                version_id,
                source["document_id"],
                source["project_id"],
                source["doc_type"],
                next_version,
                source["canvas_version"],
                "draft",
                content,
                citations_json,
                "not_run",
                f"manual-edit:{uuid.uuid4().hex}",
                now,
                source.get("competitor_snapshot_id"),
                restored_from_version_id,
            ),
        )
        self._copy_dependencies_tx(connection, source["id"], version_id, now)
        connection.execute(
            """
            INSERT INTO artifact_health(artifact_type,artifact_id,health_status,reason,trigger_source_id,updated_at)
            VALUES ('document_version',?,'needs_review',?,NULL,?)
            ON CONFLICT(artifact_type,artifact_id) DO UPDATE SET
                health_status='needs_review',reason=excluded.reason,trigger_source_id=NULL,updated_at=excluded.updated_at
            """,
            (version_id, "manual edit requires deterministic validation before confirmation", now),
        )
        self.db.insert_audit_tx(
            connection,
            actor=actor,
            action=audit_action,
            entity_type="document_version",
            entity_id=version_id,
            payload={
                "project_id": source["project_id"],
                "doc_type": source["doc_type"],
                "source_version_id": source["id"],
                "restored_from_version_id": restored_from_version_id,
                "note": note,
            },
        )
        return version_id

    def commit_draft(
        self,
        project_id: str,
        doc_type: str,
        *,
        actor: str,
        note: str = "",
        expected_base_version_id: str | None = None,
    ) -> dict[str, Any]:
        draft = self.get_draft(project_id, doc_type)
        if expected_base_version_id is not None and draft["base_version_id"] != expected_base_version_id:
            raise ConflictError(
                "document draft base does not match the version currently selected by the user"
            )
        source = self._version(draft["base_version_id"])
        with self.db.connect() as connection:
            version_id = self._create_version_from_source_tx(
                connection,
                source=source,
                content=draft["content"],
                actor=actor,
                note=note,
                restored_from_version_id=None,
                audit_action="document_edit_draft_committed",
            )
            connection.execute(
                "DELETE FROM document_edit_drafts WHERE project_id=? AND doc_type=?",
                (project_id, doc_type),
            )
        return self._version(version_id)

    def restore_as_new(self, version_id: str, *, actor: str, note: str = "") -> dict[str, Any]:
        source = self._version(version_id)
        with self.db.connect() as connection:
            new_id = self._create_version_from_source_tx(
                connection,
                source=source,
                content=source["content"],
                actor=actor,
                note=note,
                restored_from_version_id=version_id,
                audit_action="document_version_restored_as_new",
            )
        result = self._version(new_id)
        result["restored_from_version_id"] = version_id
        return result

    def diff(self, from_version_id: str, to_version_id: str) -> dict[str, Any]:
        before = self._version(from_version_id)
        after = self._version(to_version_id)
        if before["project_id"] != after["project_id"] or before["doc_type"] != after["doc_type"]:
            raise ValueError("document diff versions must belong to the same project and document type")
        before_lines = before["content"].splitlines()
        after_lines = after["content"].splitlines()
        unified = "\n".join(
            difflib.unified_diff(
                before_lines,
                after_lines,
                fromfile=f"{before['doc_type']}_v{before['version']}",
                tofile=f"{after['doc_type']}_v{after['version']}",
                lineterm="",
            )
        )
        return {
            "project_id": before["project_id"],
            "doc_type": before["doc_type"],
            "from_version_id": before["id"],
            "to_version_id": after["id"],
            "from_version": before["version"],
            "to_version": after["version"],
            "unified_diff": unified,
            "changed": before["content"] != after["content"],
        }
