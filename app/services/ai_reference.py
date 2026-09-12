from __future__ import annotations

import json
import re
import uuid
from typing import Any, Iterable

from app.db import Database, utc_now
from app.services.ai_runtime import sha256_payload
from app.services.generation_contracts import (
    GenerationContractError,
    call_generation,
    reference_public,
    validate_reference,
)
from app.services.stage_b_evaluation import StageBEvaluationContext


_CATEGORIES = (
    "possible_target_users",
    "possible_scenarios",
    "possible_user_problems",
    "missing_information",
    "mvp_thoughts",
    "questions_to_validate",
    "research_directions",
)
_DECISIONS = {"adopt", "modify", "ignore"}
_PROVENANCE_NOTICE = (
    "AI生成参考，尚未经外部资料核实。AI参考/待验证：以下内容只是模型建议，不是研究、市场或用户事实。"
)
_UNSUPPORTED_CLAIM_PATTERNS = (
    re.compile(r"(?:研究|调研|市场研究).*(?:证明|表明|显示|发现|验证)"),
    re.compile(r"(?:所有|全部|每个|任何).*(?:用户|客户|人).*(?:都|会|需要|喜欢|愿意|使用|购买)"),
    re.compile(r"(?:用户|客户).*(?:都|普遍|一定会|必然).*(?:需要|喜欢|愿意|使用|购买)"),
    re.compile(r"(?:市场|用户需求).*(?:已经|已|普遍|旺盛|巨大).*(?:验证|证明|存在|需要|喜欢|愿意)"),
    re.compile(r"(?:research|market research).*(?:proves|shows|validated|discovered)", re.IGNORECASE),
    re.compile(r"(?:all|every|any)\s+(?:users?|customers?).*(?:need|like|will use|will buy)", re.IGNORECASE),
)


def reject_unsupported_claims(values: Iterable[Any]) -> None:
    """Reject assertive research/market/user claims without a source boundary."""
    for value in values:
        text = " ".join(str(value or "").split())
        if any(pattern.search(text) for pattern in _UNSUPPORTED_CLAIM_PATTERNS):
            raise GenerationContractError("UNSUPPORTED_UNVERIFIED_CLAIM")


class AIReferenceService:
    """Project-scoped, explicitly unverified AI guidance."""

    def __init__(self, db: Database):
        self.db = db

    def _project(self, project_id: str) -> dict[str, Any]:
        project = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        return project

    def build_context(self, project_id: str) -> dict[str, Any]:
        project = self._project(project_id)
        canvas = self.db.get_canvas(project_id)
        brief = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1", (project_id,)
        )
        source_count = self.db.fetch_one("SELECT COUNT(*) AS n FROM sources WHERE project_id=?", (project_id,))["n"]
        return {
            "project": {"id": project_id, "title": project["title"], "summary": project["summary"]},
            "canvas": canvas or None,
            "idea_brief": brief or None,
            "source_count": int(source_count),
            "boundary": "AI参考，不是证据；具体判断仍需外部资料或用户确认。",
        }

    def generate(
        self,
        project_id: str,
        *,
        actor: str,
        runtime: Any,
        idempotency_key: str | None = None,
        evaluation_context: StageBEvaluationContext | None = None,
    ) -> dict[str, Any]:
        self._project(project_id)
        if idempotency_key:
            existing = self.db.fetch_one(
                "SELECT * FROM ai_reference_results WHERE project_id=? AND idempotency_key=?",
                (project_id, idempotency_key),
            )
            if existing:
                return self._row(existing)
        context = self.build_context(project_id)
        def generate_reference() -> Any:
            if evaluation_context is None:
                return runtime.generate_ai_reference(context)
            return runtime.generate_ai_reference(context, evaluation_context=evaluation_context)

        parsed = validate_reference(call_generation(generate_reference))
        result_json = reference_public(parsed)
        reject_unsupported_claims(
            item for category in _CATEGORIES for item in getattr(parsed, category)
        )
        result_json["uncertainty_notice"] = _PROVENANCE_NOTICE
        fixture_origin = getattr(runtime, "fixture_origin", None)
        if fixture_origin:
            result_json["fixture_origin"] = fixture_origin
            result_json["fixture_disclosure"] = getattr(
                runtime, "disclosure", "Stage A 演示结果 · 非真实 AI 生成"
            )
        result_json = reference_public(result_json)
        now = utc_now()
        result_id = f"ai_reference_{uuid.uuid4().hex}"
        self.db.execute(
            """INSERT INTO ai_reference_results
               (id, project_id, created_by, input_json, result_json, content_sha256, status, idempotency_key, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'completed', ?, ?)""",
            (result_id, project_id, actor, json.dumps(context, ensure_ascii=False),
             json.dumps(result_json, ensure_ascii=False), sha256_payload(result_json), idempotency_key, now),
        )
        self.db.insert_audit(actor=actor, action="ai_reference_generated", entity_type="ai_reference",
                             entity_id=result_id, payload={"project_id": project_id, "is_evidence": False})
        return {"id": result_id, "project_id": project_id, "result": result_json, "status": "completed",
                "is_evidence": False, "created_at": now, "content_sha256": sha256_payload(result_json)}

    def _row(self, row: dict[str, Any]) -> dict[str, Any]:
        result = reference_public(json.loads(row["result_json"]))
        result["uncertainty_notice"] = _PROVENANCE_NOTICE
        return {"id": row["id"], "project_id": row["project_id"], "result": result,
                "status": row["status"], "is_evidence": False, "created_at": row["created_at"],
                "content_sha256": row["content_sha256"]}

    def get(self, project_id: str, reference_id: str, *, actor: str) -> dict[str, Any]:
        self._project(project_id)
        row = self.db.fetch_one("SELECT * FROM ai_reference_results WHERE project_id=? AND id=?", (project_id, reference_id))
        if row is None:
            raise KeyError("AI参考不存在或不可访问")
        return self._row(row)

    def apply(self, project_id: str, *, reference_id: str, actor: str, decisions: list[dict[str, Any]]) -> dict[str, Any]:
        reference = self.get(project_id, reference_id, actor=actor)
        result = reference["result"]
        normalized: list[dict[str, Any]] = []
        for decision in decisions:
            category = str(decision.get("category") or "")
            item = str(decision.get("item") or "")
            choice = str(decision.get("decision") or "")
            if category not in _CATEGORIES or choice not in _DECISIONS or item not in [str(v) for v in result.get(category, [])]:
                raise ValueError("AI参考决策必须对应当前项目的参考结果")
            normalized.append({"category": category, "item": item, "decision": choice,
                               "rationale": str(decision.get("rationale") or ""), "provenance": "AI_REFERENCE",
                               "verification": "UNRESOLVED"})
        adoption_id = f"ai_reference_adoption_{uuid.uuid4().hex}"
        now = utc_now()
        self.db.execute(
            "INSERT INTO ai_reference_adoptions(id, project_id, reference_id, created_by, decisions_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (adoption_id, project_id, reference_id, actor, json.dumps(normalized, ensure_ascii=False), now),
        )
        self.db.insert_audit(actor=actor, action="ai_reference_applied", entity_type="ai_reference_adoption",
                             entity_id=adoption_id, payload={"project_id": project_id, "reference_id": reference_id})
        return {"id": adoption_id, "project_id": project_id, "reference_id": reference_id,
                "status": "applied", "decisions": normalized, "created_at": now}

    def get_context(self, project_id: str, *, actor: str) -> dict[str, Any]:
        self._project(project_id)
        rows = self.db.fetch_all(
            "SELECT decisions_json FROM ai_reference_adoptions WHERE project_id=? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
        decisions = json.loads(rows[0]["decisions_json"]) if rows else []
        return {"adopted": [item for item in decisions if item["decision"] in {"adopt", "modify"}],
                "ignored": [item for item in decisions if item["decision"] == "ignore"],
                "boundary": "AI参考，尚未经外部资料核实。"}
