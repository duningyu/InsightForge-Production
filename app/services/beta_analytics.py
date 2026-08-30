from __future__ import annotations
import json, re, uuid
from datetime import datetime, timezone
from typing import Any
from app.services.beta_runtime import validate_participant_id

EVENTS = frozenset('beta_session_started idea_submitted idea_brief_confirmed solutions_generated solution_selected snapshot_created snapshot_viewed evidence_added evidence_impact_viewed change_proposal_opened change_proposal_accepted prd_generated prd_editor_opened prd_draft_saved prd_version_confirmed techdoc_generated handoff_opened handoff_exported next_action_shown next_action_clicked walkthrough_started walkthrough_step_completed walkthrough_skipped walkthrough_completed walkthrough_restarted beta_task_completed beta_feedback_submitted'.split())
FORBIDDEN = frozenset('api_key authorization credential secret prompt completion content raw_response reasoning_content source_text document_text'.split())
EVENT_PROPERTIES = {'idea_submitted': {'idea_length_bucket'}, 'prd_draft_saved': {'doc_type','chars_before','chars_after','chars_added','chars_removed'}, 'next_action_shown': {'location','action_type'}, 'next_action_clicked': {'location','action_type'}}

def _scan(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN: raise ValueError('ANALYTICS_PRIVACY_VIOLATION')
            _scan(item)
    elif isinstance(value, list):
        for item in value: _scan(item)

class BetaAnalyticsService:
    def __init__(self, db, *, participant_id: str | None, release_id: str, beta_mode: bool, consent_version: int = 1):
        self.db, self.participant_id, self.release_id, self.beta_mode, self.consent_version = db, participant_id, release_id, beta_mode, consent_version
    def has_consent(self) -> bool:
        if not self.beta_mode or not self.participant_id: return False
        return self.db.fetch_one('SELECT id FROM beta_consents WHERE participant_id=? AND beta_release_id=? AND consent_version=?', (self.participant_id,self.release_id,self.consent_version)) is not None
    def consent(self) -> dict[str, Any]:
        participant = validate_participant_id(self.participant_id or '')
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connect() as c:
            c.execute('INSERT OR IGNORE INTO beta_consents(id,participant_id,beta_release_id,consent_version,consented_at) VALUES (?,?,?,?,?)',(uuid.uuid4().hex,participant,self.release_id,self.consent_version,now))
        return {'participant_id':participant,'beta_release_id':self.release_id,'consent_version':self.consent_version,'consented_at':now}
    def record(self, event_name: str, properties: dict[str, Any] | None = None, *, session_id: str, project_id: str | None = None) -> dict[str, Any]:
        if not self.beta_mode or not self.has_consent(): raise PermissionError('beta consent required')
        if event_name not in EVENTS: raise ValueError('EVENT_NOT_ALLOWED')
        props = properties or {}; _scan(props)
        allowed = EVENT_PROPERTIES.get(event_name)
        if allowed is not None and not set(props).issubset(allowed): raise ValueError('EVENT_PROPERTY_NOT_ALLOWED')
        validate_participant_id(self.participant_id or '')
        event_id = uuid.uuid4().hex; now = datetime.now(timezone.utc).isoformat()
        with self.db.connect() as c: c.execute('INSERT INTO product_events VALUES (?,?,?,?,?,?,?,?)',(event_id,self.participant_id,session_id,project_id,event_name,json.dumps(props,ensure_ascii=False),self.release_id,now))
        return {'id':event_id,'event_name':event_name,'occurred_at':now}
