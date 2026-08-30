from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.beta_runtime import validate_participant_id

LOGGER = logging.getLogger("insightforge.beta.feedback")


class BetaFeedbackService:
    def __init__(self, db, analytics, *, participant_id: str | None, release_id: str, beta_mode: bool):
        self.db = db
        self.analytics = analytics
        self.participant_id = participant_id
        self.release_id = release_id
        self.beta_mode = beta_mode
        self.clock = lambda: datetime.now(timezone.utc)

    def submit(
        self,
        *,
        project_id: str | None,
        project_stage: str,
        rating: int,
        feedback_type: str,
        comment: str,
        session_id: str,
    ) -> dict[str, Any]:
        if not self.beta_mode:
            raise PermissionError("beta mode is not enabled")
        if not self.analytics.has_consent():
            raise PermissionError("beta consent required")
        participant_id = validate_participant_id(self.participant_id or "")
        if project_id and self.db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise KeyError("project not found")

        feedback_id = uuid.uuid4().hex
        created_at = self.clock().isoformat()
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO beta_feedback(
                    id,participant_id,project_id,project_stage,rating,feedback_type,
                    comment,beta_release_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    feedback_id, participant_id, project_id, project_stage, rating,
                    feedback_type, comment, self.release_id, created_at,
                ),
            )

        rating_bucket = "1_2" if rating <= 2 else "3" if rating == 3 else "4_5"
        try:
            self.analytics.record_safe(
                "beta_feedback_submitted",
                {
                    "feedback_type": feedback_type,
                    "rating_bucket": rating_bucket,
                    "project_stage": project_stage,
                },
                session_id=session_id,
                project_id=project_id,
            )
        except Exception:
            LOGGER.warning("feedback_analytics_side_effect_failed feedback_id=%s", feedback_id)

        return {"id": feedback_id, "received": True, "created_at": created_at}
