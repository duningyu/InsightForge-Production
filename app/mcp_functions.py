from __future__ import annotations

import json
from typing import Any

from app.db import Database
from app.services.loop import DocumentLoop
from app.services.claims import ClaimService
from app.services.handoff import HandoffService
from app.services.projects import ProjectService
from app.services.retrieval_service import ProjectRetrievalService


class InsightForgeMCPFunctions:
    """Pure MCP-facing business functions, independently testable from transport."""

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectService(db)
        self.retrieval = ProjectRetrievalService(db)
        self.claims = ClaimService(db)
        self.handoff = HandoffService(db)
        self.loop = DocumentLoop(db)

    def get_canvas_resource(self, project_id: str) -> dict[str, Any]:
        return self.projects.get_canvas(project_id)

    def get_source_resource(self, project_id: str, source_id: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM sources WHERE id = ? AND project_id = ?",
            (source_id, project_id),
        )
        if row is None:
            raise KeyError("source not found in project scope")
        return row

    def get_document_resource(
        self, project_id: str, version_id: str
    ) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM document_versions WHERE id = ? AND project_id = ? AND lifecycle_status = 'active'",
            (version_id, project_id),
        )
        if row is None:
            raise KeyError("document version not found in project scope")
        row["citations"] = json.loads(row.pop("citations_json"))
        return row

    def get_document_version(self, version_id: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM document_versions WHERE id = ? AND lifecycle_status = 'active'", (version_id,)
        )
        if row is None:
            raise KeyError("document version not found")
        row["citations"] = json.loads(row.pop("citations_json"))
        return row

    def retrieve_project_sources(
        self, project_id: str, query: str, top_k: int = 8
    ) -> dict[str, Any]:
        return {
            "items": self.retrieval.retrieve_project_sources(
                project_id, query, top_k
            )
        }

    def get_claim_ledger(self, project_id: str, version_id: str) -> dict[str, Any]:
        version = self.db.fetch_one(
            "SELECT id FROM document_versions WHERE id = ? AND project_id = ? AND lifecycle_status = 'active'",
            (version_id, project_id),
        )
        if version is None:
            raise KeyError("document version not found in project scope")
        return self.claims.list_for_version(version_id)

    def get_handoff_readiness(self, project_id: str) -> dict[str, Any]:
        return self.handoff.readiness(project_id)

    def prepare_handoff_manifest(
        self, project_id: str, target_client: str = "codex"
    ) -> dict[str, Any]:
        return self.handoff.preview_manifest(project_id, target_client=target_client)

    def create_artifact_draft(
        self,
        project_id: str,
        doc_type: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.loop.run(
            project_id,
            doc_type,
            idempotency_key=idempotency_key,
        )

    def _current_snapshot_payload(self, project_id: str) -> dict[str, Any]:
        project = self.db.fetch_one("SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        snapshot_id = project.get("current_snapshot_id")
        if not snapshot_id:
            raise KeyError("current project snapshot not found")
        row = self.db.fetch_one("SELECT * FROM project_snapshots WHERE id=? AND project_id=?", (snapshot_id, project_id))
        if row is None:
            raise KeyError("current project snapshot not found")
        payload = dict(row)
        for field in ("target_user", "problem", "solution", "mvp", "user_flow", "inputs", "outputs", "technical_plan", "unknowns", "next_action"):
            payload[field] = json.loads(payload.pop(f"{field}_json"))
        health = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='project_snapshot' AND artifact_id=?",
            (snapshot_id,),
        )
        payload["artifact_health"] = health
        return payload

    def get_current_snapshot_resource(self, project_id: str) -> dict[str, Any]:
        return self._current_snapshot_payload(project_id)

    def get_current_document_resource(self, project_id: str, doc_type: str) -> dict[str, Any]:
        snapshot = self._current_snapshot_payload(project_id)
        row = self.db.fetch_one(
            """
            SELECT dv.* FROM document_versions dv
            JOIN artifact_dependencies dep ON dep.artifact_type='document_version' AND dep.artifact_id=dv.id
              AND dep.dependency_type='project_snapshot' AND dep.dependency_id=?
            JOIN artifact_health ah ON ah.artifact_type='document_version' AND ah.artifact_id=dv.id
            WHERE dv.project_id=? AND dv.doc_type=? AND dv.status='approved'
              AND dv.validation_status='passed' AND dv.lifecycle_status='active'
              AND ah.health_status='current'
            ORDER BY dv.version DESC,dv.approved_at DESC,dv.id DESC LIMIT 1
            """,
            (snapshot["id"], project_id, doc_type),
        )
        if row is None:
            raise KeyError(f"current confirmed healthy {doc_type} not found")
        row["citations"] = json.loads(row.pop("citations_json"))
        return row

    def get_mvp_scope_resource(self, project_id: str) -> dict[str, Any]:
        snapshot = self._current_snapshot_payload(project_id)
        return {
            "project_id": project_id,
            "snapshot_id": snapshot["id"],
            "solution": snapshot.get("solution") or {},
            "mvp": snapshot.get("mvp") or {},
        }

    def get_unresolved_risks_resource(self, project_id: str) -> dict[str, Any]:
        snapshot = self._current_snapshot_payload(project_id)
        return {
            "project_id": project_id,
            "snapshot_id": snapshot["id"],
            "unknowns": snapshot.get("unknowns") or [],
            "next_action": snapshot.get("next_action") or {},
        }

    def get_current_project_context(self, project_id: str) -> dict[str, Any]:
        readiness = self.handoff.readiness(project_id)
        return {
            "project_id": project_id,
            "readiness": readiness,
            "snapshot": self._current_snapshot_payload(project_id),
            "prd": self.get_current_document_resource(project_id, "prd") if readiness.get("ready") else None,
            "techdoc": self.get_current_document_resource(project_id, "techdoc") if readiness.get("ready") else None,
        }

    def build_handoff_manifest(self, project_id: str, target_client: str = "codex") -> dict[str, Any]:
        return self.handoff.preview_manifest(project_id, target_client=target_client)

    @staticmethod
    def review_prd_prompt(project_id: str, version_id: str) -> str:
        return (
            f"Review project {project_id} document version {version_id}. "
            "Check citation scope, source_type disclosure, project-canvas consistency, "
            "unsupported real-user claims, P0/P1 boundaries, and acceptance criteria. "
            "Do not approve or publish automatically; return issues for human review."
        )

    @staticmethod
    def prepare_coding_handoff_prompt(project_id: str, version_id: str) -> str:
        return (
            f"Prepare an AI coding handoff from project {project_id}, approved document "
            f"version {version_id}. Extract requirements, constraints, API contracts, "
            "acceptance tests, and claim boundaries. Preserve citations and do not invent "
            "implementation status."
        )
