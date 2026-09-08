from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import ValidationError

from app.db import Database, utc_now
from app.errors import StructuredRuntimeUnavailableError
from app.schemas import AIReferenceDraft
from app.services.ai_runtime import sha256_payload


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

    def generate(self, project_id: str, *, actor: str, runtime: Any, idempotency_key: str | None = None) -> dict[str, Any]:
        self._project(project_id)
        if idempotency_key:
            existing = self.db.fetch_one(
                "SELECT * FROM ai_reference_results WHERE project_id=? AND idempotency_key=?",
                (project_id, idempotency_key),
            )
            if existing:
                return self._row(existing)
        context = self.build_context(project_id)
        try:
            result = runtime.generate_ai_reference(context)
            parsed = result if isinstance(result, AIReferenceDraft) else AIReferenceDraft.model_validate(result)
        except ValidationError as exc:
            raise StructuredRuntimeUnavailableError(
                "这次没有生成可用建议，请重新尝试。"
            ) from exc
        result_json = parsed.model_dump(mode="json")
        if not any(result_json.get(category) for category in _CATEGORIES):
            raise StructuredRuntimeUnavailableError("这次没有生成可用建议，请重新尝试。")
        result_json["uncertainty_notice"] = "AI生成参考，尚未经外部资料核实。"
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
        return {"id": row["id"], "project_id": row["project_id"], "result": json.loads(row["result_json"]),
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
