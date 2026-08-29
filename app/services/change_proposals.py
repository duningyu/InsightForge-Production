from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import ConflictError
from app.services.snapshots import SnapshotService


class ChangeProposalService:
    JSON_FIELDS = ("affected_claims", "affected_decisions", "suggested_changes")

    def __init__(self, db: Database, snapshots: SnapshotService):
        self.db = db
        self.snapshots = snapshots

    @classmethod
    def _serialize(cls, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        value = dict(row)
        for field in cls.JSON_FIELDS:
            value[field] = json.loads(value.pop(f"{field}_json"))
        return value

    def create_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        from_snapshot_id: str,
        proposal_type: str,
        summary: str,
        reason: str,
        affected_claim_ids: list[str],
        affected_decision_ids: list[str],
        suggested_changes: dict[str, Any],
        trigger_source_id: str | None,
    ) -> dict[str, Any]:
        snapshot = connection.execute(
            "SELECT id FROM project_snapshots WHERE id=? AND project_id=?",
            (from_snapshot_id, project_id),
        ).fetchone()
        if snapshot is None:
            raise ValueError("CHANGE_PROPOSAL_SNAPSHOT_SCOPE_MISMATCH")
        proposal_id = f"proposal_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO change_proposals(
                id,project_id,trigger_source_id,from_snapshot_id,proposal_type,
                summary,reason,affected_claims_json,affected_decisions_json,
                suggested_changes_json,status,created_at,decided_at,decided_by
            ) VALUES (?,?,?,?,?,?,?,?,?,?,'open',?,NULL,NULL)
            """,
            (
                proposal_id,
                project_id,
                trigger_source_id,
                from_snapshot_id,
                proposal_type,
                summary,
                reason,
                json.dumps(affected_claim_ids, ensure_ascii=False),
                json.dumps(affected_decision_ids, ensure_ascii=False),
                json.dumps(suggested_changes, ensure_ascii=False, sort_keys=True),
                utc_now(),
            ),
        )
        row = connection.execute("SELECT * FROM change_proposals WHERE id=?", (proposal_id,)).fetchone()
        return self._serialize(row)

    def create(self, **kwargs: Any) -> dict[str, Any]:
        with self.db.connect() as connection:
            return self.create_tx(connection, **kwargs)

    def get(self, proposal_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM change_proposals WHERE id=?", (proposal_id,))
        if row is None:
            raise KeyError("change proposal not found")
        return self._serialize(row)

    def list_for_project(self, project_id: str) -> list[dict[str, Any]]:
        if self.db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise KeyError("project not found")
        rows = self.db.fetch_all(
            "SELECT * FROM change_proposals WHERE project_id=? ORDER BY created_at DESC,id DESC",
            (project_id,),
        )
        return [self._serialize(row) for row in rows]

    def _decision_only(
        self,
        proposal_id: str,
        *,
        status: str,
        human_confirmed: bool,
        note: str,
        actor: str,
    ) -> dict[str, Any]:
        if not human_confirmed:
            raise PermissionError("explicit human confirmation is required")
        if status not in {"rejected", "deferred"}:
            raise ValueError("invalid proposal decision")
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM change_proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise KeyError("change proposal not found")
            if row["status"] != "open":
                raise ConflictError("CHANGE_PROPOSAL_NOT_OPEN")
            now = utc_now()
            connection.execute(
                "UPDATE change_proposals SET status=?, decided_at=?, decided_by=? WHERE id=?",
                (status, now, actor, proposal_id),
            )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action=f"change_proposal_{status}",
                entity_type="change_proposal",
                entity_id=proposal_id,
                payload={"note": note, "human_confirmed": True},
            )
        return self.get(proposal_id)

    def reject(self, proposal_id: str, *, human_confirmed: bool, note: str, actor: str) -> dict[str, Any]:
        return self._decision_only(
            proposal_id, status="rejected", human_confirmed=human_confirmed, note=note, actor=actor
        )

    def defer(self, proposal_id: str, *, human_confirmed: bool, note: str, actor: str) -> dict[str, Any]:
        return self._decision_only(
            proposal_id, status="deferred", human_confirmed=human_confirmed, note=note, actor=actor
        )

    def accept(
        self,
        proposal_id: str,
        *,
        human_confirmed: bool,
        note: str,
        actor: str,
    ) -> dict[str, Any]:
        if not human_confirmed:
            raise PermissionError("explicit human confirmation is required")
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM change_proposals WHERE id=?", (proposal_id,)).fetchone()
            if row is None:
                raise KeyError("change proposal not found")
            proposal = self._serialize(row)
            if proposal["status"] != "open":
                raise ConflictError("CHANGE_PROPOSAL_NOT_OPEN")
            project = connection.execute(
                "SELECT current_snapshot_id FROM projects WHERE id=?", (proposal["project_id"],)
            ).fetchone()
            if project is None:
                raise KeyError("project not found")
            if project["current_snapshot_id"] != proposal["from_snapshot_id"]:
                raise ConflictError("STALE_CHANGE_PROPOSAL: from_snapshot is no longer current")
            snapshot = self.snapshots.create_from_change_proposal_tx(
                connection,
                proposal=proposal,
                actor=actor,
            )
            now = utc_now()
            connection.execute(
                "UPDATE change_proposals SET status='accepted', decided_at=?, decided_by=? WHERE id=?",
                (now, actor, proposal_id),
            )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action="change_proposal_accepted",
                entity_type="change_proposal",
                entity_id=proposal_id,
                payload={
                    "project_id": proposal["project_id"],
                    "from_snapshot_id": proposal["from_snapshot_id"],
                    "new_snapshot_id": snapshot["id"],
                    "note": note,
                    "human_confirmed": True,
                },
            )
        return {"proposal": self.get(proposal_id), "snapshot": self.snapshots.get(snapshot["id"])}
