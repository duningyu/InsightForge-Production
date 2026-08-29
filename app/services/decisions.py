from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import utc_now


class DecisionService:
    def propose_solution_selection(
        self,
        *,
        connection: sqlite3.Connection,
        project_id: str,
        option_ids: list[str],
        selected_option_id: str,
        rationale: str,
        decision_payload: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        if selected_option_id not in option_ids:
            raise ValueError("selected_option_id must be one of option_ids")
        decision_id = f"decision_{uuid.uuid4().hex}"
        now = utc_now()
        connection.execute(
            """
            INSERT INTO project_decisions(
                id, project_id, decision_type, options_json, selected_option_id,
                rationale, status, decision_key, decision_version,
                decision_payload_json, supersedes_decision_id, confirmed_by,
                created_at, confirmed_at
            ) VALUES (?, ?, 'solution_selection', ?, ?, ?, 'proposed',
                      'current_solution', NULL, ?, NULL, NULL, ?, NULL)
            """,
            (
                decision_id,
                project_id,
                json.dumps(option_ids, ensure_ascii=False),
                selected_option_id,
                rationale,
                json.dumps({**decision_payload, "proposed_by": actor}, ensure_ascii=False),
                now,
            ),
        )
        row = connection.execute(
            "SELECT * FROM project_decisions WHERE id = ?", (decision_id,)
        ).fetchone()
        return dict(row)
