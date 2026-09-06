"""Manual, unverified product candidates in the authenticated workspace database.

Selection is a user decision, never evidence verification or source ingestion.
No network operation is performed by these methods.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.db import Database, utc_now
from app.services.projects import ProjectService


class CompetitorService:
    def __init__(self, db: Database, projects: ProjectService):
        self.db, self.projects = db, projects

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "selected": bool(row["selected"]), "verification_status": "UNVERIFIED"}

    def get(self, project_id: str, candidate_id: str) -> dict[str, Any]:
        self.projects.get_project(project_id)
        row = self.db.fetch_one(
            "SELECT * FROM competitor_candidates WHERE project_id=? AND id=?",
            (project_id, candidate_id),
        )
        if row is None:
            raise KeyError("候选产品不存在或不可访问")
        return self._public(row)

    def list(self, project_id: str) -> dict[str, Any]:
        self.projects.get_project(project_id)
        return {
            "candidates": [self._public(row) for row in self.db.fetch_all(
                "SELECT * FROM competitor_candidates WHERE project_id=? ORDER BY created_at, id",
                (project_id,),
            )],
            "search_status": "NOT_CONFIGURED",
            "search_disclosure": "联网查找暂未开启，你可以先手动添加已有产品，或者跳过这一步。",
        }

    def create(self, project_id: str, *, name: str, url: str, description: str, actor: str) -> dict[str, Any]:
        self.projects.get_project(project_id)
        candidate_id = "competitor_" + uuid4().hex
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO competitor_candidates(id,project_id,name,url,description,created_at) VALUES (?,?,?,?,?,?)",
                (candidate_id, project_id, name, url, description, utc_now()),
            )
            self.db.insert_audit_tx(connection, actor=actor, action="competitor_candidate_created",
                                      entity_type="competitor_candidate", entity_id=candidate_id,
                                      payload={"project_id": project_id})
        return self.get(project_id, candidate_id)

    def select(self, project_id: str, candidate_id: str, selected: bool, actor: str) -> dict[str, Any]:
        self.get(project_id, candidate_id)
        with self.db.connect() as connection:
            updated = connection.execute(
                "UPDATE competitor_candidates SET selected=? WHERE project_id=? AND id=? AND selected<>?",
                (int(selected), project_id, candidate_id, int(selected)),
            )
            if updated.rowcount:
                self.db.insert_audit_tx(connection, actor=actor, action="competitor_selection_changed",
                    entity_type="competitor_candidate", entity_id=candidate_id,
                    payload={"project_id": project_id, "selected": selected})
        return self.get(project_id, candidate_id)

    def remove(self, project_id: str, candidate_id: str, actor: str) -> dict[str, bool]:
        self.get(project_id, candidate_id)
        with self.db.connect() as connection:
            removed = connection.execute(
                "DELETE FROM competitor_candidates WHERE project_id=? AND id=?",
                (project_id, candidate_id),
            )
            if removed.rowcount:
                self.db.insert_audit_tx(connection, actor=actor, action="competitor_candidate_removed",
                    entity_type="competitor_candidate", entity_id=candidate_id,
                    payload={"project_id": project_id})
        return {"removed": True}
