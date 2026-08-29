from __future__ import annotations

import json
from typing import Any

from app.db import Database, utc_now


TOUR_ID = "complete-example-v1"
TOUR_STEPS = ("idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff")


class WalkthroughService:
    """Persist the seven-step complete-example tour without altering project artifacts."""

    def __init__(self, db: Database):
        self.db = db

    def _ensure_project(self, project_id: str) -> None:
        if self.db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise KeyError("project not found")

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        try:
            completed = json.loads(row.get("completed_steps_json") or "[]")
        except (TypeError, json.JSONDecodeError):
            completed = []
        completed = [step for step in TOUR_STEPS if step in set(completed)]
        return {
            "project_id": row["project_id"],
            "tour_id": row["tour_id"],
            "current_step": row["current_step"],
            "completed_steps": completed,
            "dismissed_at": row.get("dismissed_at"),
            "updated_at": row["updated_at"],
            "steps": list(TOUR_STEPS),
        }

    def get(self, project_id: str) -> dict[str, Any]:
        self._ensure_project(project_id)
        row = self.db.fetch_one(
            "SELECT * FROM project_tour_progress WHERE project_id=? AND tour_id=?",
            (project_id, TOUR_ID),
        )
        if row is None:
            raise KeyError("walkthrough not started")
        return self._public(row)

    def start(self, project_id: str) -> dict[str, Any]:
        self._ensure_project(project_id)
        now = utc_now()
        self.db.execute(
            """
            INSERT INTO project_tour_progress(
                project_id,tour_id,current_step,completed_steps_json,dismissed_at,updated_at
            ) VALUES (?,?,?,'[]',NULL,?)
            ON CONFLICT(project_id,tour_id) DO UPDATE SET
                dismissed_at=NULL,
                updated_at=excluded.updated_at
            """,
            (project_id, TOUR_ID, TOUR_STEPS[0], now),
        )
        return self.get(project_id)

    def advance(self, project_id: str, step: str) -> dict[str, Any]:
        if step not in TOUR_STEPS:
            raise ValueError("invalid walkthrough step")
        try:
            current = self.get(project_id)
        except KeyError:
            current = self.start(project_id)
        completed = list(current["completed_steps"])
        # A user may revisit an already completed step, but cannot jump over the next unfinished one.
        if step not in completed:
            expected = TOUR_STEPS[len(completed)] if len(completed) < len(TOUR_STEPS) else None
            if step != expected:
                raise ValueError(f"walkthrough must advance in order; expected {expected}")
            completed.append(step)
        if len(completed) == len(TOUR_STEPS):
            next_step = "complete"
        else:
            next_step = TOUR_STEPS[len(completed)]
        self.db.execute(
            """
            UPDATE project_tour_progress
            SET current_step=?, completed_steps_json=?, dismissed_at=NULL, updated_at=?
            WHERE project_id=? AND tour_id=?
            """,
            (next_step, json.dumps(completed, ensure_ascii=False), utc_now(), project_id, TOUR_ID),
        )
        return self.get(project_id)

    def skip(self, project_id: str) -> dict[str, Any]:
        try:
            self.get(project_id)
        except KeyError:
            self.start(project_id)
        now = utc_now()
        self.db.execute(
            """
            UPDATE project_tour_progress
            SET current_step='skipped', dismissed_at=?, updated_at=?
            WHERE project_id=? AND tour_id=?
            """,
            (now, now, project_id, TOUR_ID),
        )
        return self.get(project_id)

    def restart(self, project_id: str) -> dict[str, Any]:
        self._ensure_project(project_id)
        now = utc_now()
        self.db.execute(
            """
            INSERT INTO project_tour_progress(
                project_id,tour_id,current_step,completed_steps_json,dismissed_at,updated_at
            ) VALUES (?,?,?,'[]',NULL,?)
            ON CONFLICT(project_id,tour_id) DO UPDATE SET
                current_step=excluded.current_step,
                completed_steps_json='[]',
                dismissed_at=NULL,
                updated_at=excluded.updated_at
            """,
            (project_id, TOUR_ID, TOUR_STEPS[0], now),
        )
        return self.get(project_id)
