from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import Database, utc_now
from app.schemas import EvidenceGuidanceDraft
from app.services.ai_reference import AIReferenceService, reject_unsupported_claims
from app.services.ai_runtime import sha256_payload
from app.services.generation_contracts import call_generation, validate_guidance, guidance_public


_DISCLOSURE = "AI建议你去补这些资料，尚未加入项目资料，也不代表已经核实。"


class EvidenceCoachService:
    """Generate optional, concrete evidence-collection guidance.

    Action cards are persisted as a reference result, never as a source.  The
    service validates the model response before writing anything so an empty or
    malformed response cannot look like successful guidance in the UI.
    """

    def __init__(self, db: Database):
        self.db = db

    def _project(self, project_id: str) -> dict[str, Any]:
        project = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        return project

    def _context(self, project_id: str) -> dict[str, Any]:
        context = AIReferenceService(self.db).build_context(project_id)
        context["guidance_purpose"] = (
            "给初学者提供可以实际执行的资料行动卡。说明要确认什么、找谁或去哪里、"
            "具体怎么做、拿到什么、怎么填写以及会影响哪个产品决定。不要联网，不要生成来源。"
        )
        return context

    @staticmethod
    def _validate_cards(parsed: EvidenceGuidanceDraft) -> None:
        validate_guidance(parsed)

    def generate(
        self,
        project_id: str,
        *,
        actor: str,
        runtime: Any,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        self._project(project_id)
        if idempotency_key:
            existing = self.db.fetch_one(
                "SELECT * FROM evidence_guidance_results WHERE project_id=? AND idempotency_key=?",
                (project_id, idempotency_key),
            )
            if existing:
                return self._row(existing)

        context = self._context(project_id)
        parsed = validate_guidance(call_generation(lambda: runtime.generate_evidence_guidance(context)))
        reject_unsupported_claims(
            getattr(card, key)
            for card in parsed.cards
            for key in (
                "title",
                "question_to_validate",
                "why_it_matters",
                "who_or_where",
                "action_steps",
                "suggested_questions",
                "acceptable_artifacts",
                "fill_template",
                "decision_impact",
                "fallback_if_unavailable",
                "limitations",
            )
            for item in (getattr(card, key) if isinstance(getattr(card, key), list) else [getattr(card, key)])
        )
        result_json = guidance_public(parsed)
        result_json["disclosure"] = _DISCLOSURE
        fixture_origin = getattr(runtime, "fixture_origin", None)
        if fixture_origin:
            result_json["fixture_origin"] = fixture_origin
            result_json["fixture_disclosure"] = getattr(
                runtime, "disclosure", "Stage A 演示结果 · 非真实 AI 生成"
            )
        result_json = guidance_public(result_json)
        now = utc_now()
        result_id = f"evidence_guidance_{uuid.uuid4().hex}"
        content_sha256 = sha256_payload(result_json)
        self.db.execute(
            """INSERT INTO evidence_guidance_results
               (id, project_id, created_by, input_json, result_json, content_sha256, status, idempotency_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
            (
                result_id,
                project_id,
                actor,
                json.dumps(context, ensure_ascii=False),
                json.dumps(result_json, ensure_ascii=False),
                content_sha256,
                idempotency_key,
                now,
            ),
        )
        self.db.insert_audit(
            actor=actor,
            action="evidence_guidance_generated",
            entity_type="evidence_guidance",
            entity_id=result_id,
            payload={"project_id": project_id, "is_evidence": False, "source_created": False},
        )
        return {
            "id": result_id,
            "project_id": project_id,
            "result": result_json,
            "status": "completed",
            "is_evidence": False,
            "source_created": False,
            "created_at": now,
            "content_sha256": content_sha256,
        }

    def _row(self, row: dict[str, Any]) -> dict[str, Any]:
        result = guidance_public(json.loads(row["result_json"]))
        result["disclosure"] = _DISCLOSURE
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "result": result,
            "status": row["status"],
            "is_evidence": False,
            "source_created": False,
            "created_at": row["created_at"],
            "content_sha256": row["content_sha256"],
        }

    def get(self, project_id: str, guidance_id: str, *, actor: str) -> dict[str, Any]:
        self._project(project_id)
        row = self.db.fetch_one(
            "SELECT * FROM evidence_guidance_results WHERE project_id=? AND id=?",
            (project_id, guidance_id),
        )
        if row is None:
            raise KeyError("资料行动建议不存在或不可访问")
        return self._row(row)
