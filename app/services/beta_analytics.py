from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from app.services.beta_runtime import validate_participant_id

LOGGER = logging.getLogger("insightforge.beta.analytics")

EVENT_PROPERTIES = {
    "beta_session_started": set(),
    "idea_submitted": {"idea_length_bucket"},
    "idea_brief_confirmed": set(),
    "solutions_generated": {"solution_count", "mechanisms"},
    "solution_selected": {"mechanism", "selection_strategy"},
    "snapshot_created": {"snapshot_version"},
    "snapshot_viewed": set(),
    "evidence_added": {"source_type", "file_type", "size_bucket"},
    "evidence_impact_viewed": {"impact_count"},
    "change_proposal_opened": set(),
    "change_proposal_accepted": set(),
    "prd_generated": {"doc_type", "generation_status"},
    "prd_editor_opened": {"doc_type", "version_no"},
    "prd_draft_saved": {"doc_type", "chars_before", "chars_after", "chars_added", "chars_removed"},
    "prd_version_confirmed": {"doc_type", "version_no"},
    "techdoc_generated": {"doc_type", "generation_status"},
    "handoff_opened": {"handoff_type"},
    "handoff_exported": {"format", "handoff_type"},
    "next_action_shown": {"location", "action_type"},
    "next_action_clicked": {"location", "action_type"},
    "walkthrough_started": set(),
    "walkthrough_step_completed": {"step_no"},
    "walkthrough_skipped": {"step_no"},
    "walkthrough_completed": set(),
    "walkthrough_restarted": set(),
    "beta_task_completed": set(),
    "beta_feedback_submitted": {"feedback_type", "rating_bucket", "project_stage"},
}
EVENTS = frozenset(EVENT_PROPERTIES)
FORBIDDEN = frozenset(
    "api_key authorization credential credential_ref secret password token bearer prompt completion content raw_response response_body reasoning_content source_text document_text idea prd techdoc evidence filename".split()
)
ACTION_TYPES = frozenset(
    "validate_assumption add_evidence generate_prd continue_project review_change open_handoff confirm_idea_brief generate_solutions select_solution export_handoff ready start_tour start_example_tour create_new_idea review_project_snapshot reconfirm_project_snapshot verify_project_claim generate_or_update_prd generate_or_update_techdoc confirm_document_versions".split()
)
MECHANISMS = frozenset(
    "rule_based workflow_based prediction_based recommendation_based optimization search_retrieval automation human_in_the_loop assistant marketplace other".split()
)


def _scan(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN:
                raise ValueError("ANALYTICS_PRIVACY_VIOLATION")
            _scan(item)
    elif isinstance(value, list):
        for item in value:
            _scan(item)


def _validate_values(event_name: str, properties: dict[str, Any]) -> None:
    if event_name == "beta_feedback_submitted":
        if properties.get("feedback_type") not in {"confusing", "helpful", "missing", "incorrect", "bug", "other"}:
            raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
        if properties.get("rating_bucket") not in {"1_2", "3", "4_5"}:
            raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
        if properties.get("project_stage") not in {"idea", "solutions", "snapshot", "evidence", "documents", "handoff", "history", "walkthrough", "other"}:
            raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    action = properties.get("action_type")
    if action is not None and action not in ACTION_TYPES:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    location = properties.get("location")
    if location is not None and location not in {"home", "project"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    mechanism = properties.get("mechanism")
    if mechanism is not None and mechanism not in MECHANISMS:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    mechanisms = properties.get("mechanisms")
    if mechanisms is not None and (
        not isinstance(mechanisms, list) or any(item not in MECHANISMS for item in mechanisms)
    ):
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if event_name == "solution_selected" and properties.get("selection_strategy") not in {"recommended", "manual", "staged"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "idea_length_bucket" in properties and properties["idea_length_bucket"] not in {"0_20", "21_50", "51_100", "101_200", "200_plus"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "solution_count" in properties and (not isinstance(properties["solution_count"], int) or not 2 <= properties["solution_count"] <= 3):
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "source_type" in properties and properties["source_type"] not in {"real_user_research", "simulated_research", "public_source", "user_input", "model_hypothesis", "implementation_evidence"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "file_type" in properties and (not isinstance(properties["file_type"], str) or re.fullmatch(r"[a-z0-9]{1,12}", properties["file_type"]) is None):
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "size_bucket" in properties and properties["size_bucket"] not in {"0_1kb", "1_10kb", "10_100kb", "100kb_plus"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "doc_type" in properties and properties["doc_type"] not in {"prd", "techdoc"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "generation_status" in properties and properties["generation_status"] not in {"succeeded", "failed"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "handoff_type" in properties and properties["handoff_type"] not in {"codex", "claude_code", "cursor", "generic"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "format" in properties and properties["format"] not in {"zip"}:
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    for key in ("snapshot_version", "version_no", "impact_count", "chars_before", "chars_after", "chars_added", "chars_removed"):
        if key in properties and (not isinstance(properties[key], int) or properties[key] < 0):
            raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")
    if "step_no" in properties and (not isinstance(properties["step_no"], int) or not 1 <= properties["step_no"] <= 7):
        raise ValueError("EVENT_PROPERTY_VALUE_NOT_ALLOWED")


class BetaAnalyticsService:
    def __init__(self, db, *, participant_id: str | None, release_id: str, beta_mode: bool, consent_version: int = 1):
        self.db = db
        self.participant_id = participant_id
        self.release_id = release_id
        self.beta_mode = beta_mode
        self.consent_version = consent_version
        self.clock = lambda: datetime.now(timezone.utc)

    def has_consent(self) -> bool:
        if not self.beta_mode or not self.participant_id:
            return False
        return self.db.fetch_one(
            "SELECT id FROM beta_consents WHERE participant_id=? AND beta_release_id=? AND consent_version=?",
            (self.participant_id, self.release_id, self.consent_version),
        ) is not None

    def consent(self, *, accepted: bool, consent_version: int) -> dict[str, Any]:
        if not self.beta_mode:
            raise PermissionError("beta mode is not enabled")
        if not accepted or consent_version != self.consent_version:
            raise ValueError("CONSENT_VERSION_MISMATCH")
        participant = validate_participant_id(self.participant_id or "")
        now = self.clock().isoformat()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO beta_consents(id,participant_id,beta_release_id,consent_version,consented_at) VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, participant, self.release_id, self.consent_version, now),
            )
        return {"consented": True, "consent_version": self.consent_version}

    def record(self, event_name: str, properties: dict[str, Any] | None = None, *, session_id: str, project_id: str | None = None) -> dict[str, Any]:
        if not self.beta_mode:
            return {"recorded": False, "reason": "not_beta"}
        if not self.has_consent():
            raise PermissionError("beta consent required")
        if event_name not in EVENTS:
            raise ValueError("EVENT_NOT_ALLOWED")
        props = properties or {}
        _scan(props)
        if set(props) - EVENT_PROPERTIES[event_name]:
            raise ValueError("EVENT_PROPERTY_NOT_ALLOWED")
        _validate_values(event_name, props)
        validate_participant_id(self.participant_id or "")
        if not session_id or self.db.fetch_one(
            "SELECT id FROM beta_sessions WHERE id=? AND participant_id=? AND beta_release_id=?",
            (session_id, self.participant_id, self.release_id),
        ) is None:
            raise ValueError("INVALID_BETA_SESSION")
        if project_id and self.db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise KeyError("project not found")
        event_id = uuid.uuid4().hex
        now = self.clock().isoformat()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO product_events VALUES (?,?,?,?,?,?,?,?)",
                (event_id, self.participant_id, session_id, project_id, event_name, json.dumps(props, ensure_ascii=False, sort_keys=True), self.release_id, now),
            )
        return {"recorded": True, "id": event_id, "event_name": event_name, "occurred_at": now}

    def record_safe(self, event_name: str, properties: dict[str, Any] | None = None, *, session_id: str, project_id: str | None = None) -> dict[str, Any]:
        try:
            return self.record(event_name, properties, session_id=session_id, project_id=project_id)
        except Exception as exc:  # analytics is never allowed to roll back product work
            LOGGER.warning(
                "analytics_event_failed event_name=%s violation_code=%s participant_id=%s",
                event_name,
                type(exc).__name__,
                self.participant_id,
            )
            return {"recorded": False, "reason": "analytics_write_failed"}

    def record_session_started_once(self, session_id: str) -> dict[str, Any]:
        existing = self.db.fetch_one(
            "SELECT id FROM product_events WHERE event_name='beta_session_started' AND session_id=?",
            (session_id,),
        )
        if existing:
            return {"recorded": False, "reason": "already_recorded"}
        return self.record_safe("beta_session_started", {}, session_id=session_id)
