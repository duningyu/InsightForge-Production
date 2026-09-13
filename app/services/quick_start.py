from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import ConflictError, StructuredRuntimeRecoveryError
from app.schemas import IdeaBriefDraft, IdeaBriefRefineRequest, QuickStartRequest
from app.services.ai_runtime import StructuredAIRuntime, build_ai_trace_payload
from app.services.projects import ProjectService


class QuickStartService:
    INTERPRETER_VERSION = "idea-interpreter-v1"

    def __init__(
        self,
        db: Database,
        projects: ProjectService,
        runtime: StructuredAIRuntime,
    ):
        self.db = db
        self.projects = projects
        self.runtime = runtime

    @staticmethod
    def _title_from_idea(idea: str) -> str:
        compact = " ".join(idea.split()).strip()
        return compact[:80] or "新产品 Idea"

    @staticmethod
    def _serialize_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload["known_resources"] = json.loads(payload.pop("known_resources_json"))
        payload["constraints"] = json.loads(payload.pop("constraints_json"))
        payload["unknowns"] = json.loads(payload.pop("unknowns_json"))
        payload["provenance"] = json.loads(payload.pop("provenance_json"))
        payload["clarification_required"] = bool(payload.get("clarification_required", 0))
        return payload

    def _insert_brief_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        version: int,
        draft: IdeaBriefDraft,
        confirmation_status: str,
        supersedes_id: str | None = None,
    ) -> str:
        brief_id = f"brief_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO idea_briefs(
                id, project_id, version, original_idea, target_user, problem, desired_outcome,
                known_resources_json, constraints_json, unknowns_json, provenance_json,
                clarification_required, clarification_question, confirmation_status,
                created_at, confirmed_at, supersedes_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                brief_id,
                project_id,
                version,
                draft.original_idea,
                draft.target_user,
                draft.problem,
                draft.desired_outcome,
                json.dumps(draft.known_resources, ensure_ascii=False),
                json.dumps(draft.constraints, ensure_ascii=False),
                json.dumps(draft.unknowns, ensure_ascii=False),
                json.dumps(draft.provenance, ensure_ascii=False, sort_keys=True),
                int(draft.clarification_required),
                draft.clarification_question,
                confirmation_status,
                utc_now(),
                supersedes_id,
            ),
        )
        return brief_id

    def _confirm_brief_tx(
        self,
        connection: sqlite3.Connection,
        *,
        brief_id: str,
        project_id: str,
        actor: str,
        note: str,
    ) -> None:
        now = utc_now()
        connection.execute(
            "UPDATE idea_briefs SET confirmation_status = 'confirmed', confirmed_at = ? WHERE id = ?",
            (now, brief_id),
        )
        self.db.insert_audit_tx(
            connection,
            actor=actor,
            action="idea_brief_confirmed",
            entity_type="idea_brief",
            entity_id=brief_id,
            payload={"project_id": project_id, "note": note, "market_validation": False},
        )

    def quick_start(self, payload: QuickStartRequest, *, actor: str) -> dict[str, Any]:
        project = self.projects.create_project(
            title=self._title_from_idea(payload.idea),
            summary=payload.idea.strip(),
            actor=actor,
        )
        resolver = getattr(self.runtime, "for_project", None)
        runtime = resolver(project["id"]) if callable(resolver) else self.runtime
        started = time.perf_counter()
        try:
            draft = runtime.interpret_idea(payload)
        except StructuredRuntimeRecoveryError as exc:
            trace = build_ai_trace_payload(
                runtime=runtime,
                input_payload=payload,
                output_payload=None,
                started_at=started,
                status="recovery_required",
                component_version=self.INTERPRETER_VERSION,
            )
            trace["interpreter_version"] = trace.pop("component_version")
            trace["error_code"] = exc.error_code
            self.db.insert_audit(
                actor=actor,
                action="idea_generation_recovery_required",
                entity_type="project",
                entity_id=project["id"],
                payload=trace,
            )
            return exc.as_payload(preserved_input=payload)
        except Exception:
            # The project row intentionally remains as the user's captured Idea; no fake brief is written.
            raise
        trace = build_ai_trace_payload(
            runtime=runtime,
            input_payload=payload,
            output_payload=draft,
            started_at=started,
            status="completed",
            component_version=self.INTERPRETER_VERSION,
        )
        trace["interpreter_version"] = trace.pop("component_version")
        with self.db.connect() as connection:
            brief_id = self._insert_brief_tx(
                connection,
                project_id=project["id"],
                version=1,
                draft=draft,
                confirmation_status="inferred",
            )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action="idea_brief_interpreted",
                entity_type="idea_brief",
                entity_id=brief_id,
                payload=trace,
            )
        brief = self.get_brief(project["id"])
        return {
            "project_id": project["id"],
            "idea_brief": brief,
            "clarification_required": brief["clarification_required"],
            "clarification_question": brief.get("clarification_question"),
            "runtime_mode": runtime.mode,
        }

    def get_brief(self, project_id: str) -> dict[str, Any]:
        self.projects.get_project(project_id)
        row = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE project_id = ? ORDER BY version DESC LIMIT 1",
            (project_id,),
        )
        if row is None:
            raise KeyError("idea brief not found")
        return self._serialize_row(row)

    def confirm_brief(
        self,
        project_id: str,
        *,
        human_confirmed: bool,
        note: str,
        actor: str,
    ) -> dict[str, Any]:
        if not human_confirmed:
            raise PermissionError("explicit human confirmation is required")
        brief = self.get_brief(project_id)
        if brief["confirmation_status"] == "superseded":
            raise ConflictError("cannot confirm a superseded IdeaBrief")
        if brief["confirmation_status"] == "confirmed":
            return brief
        with self.db.connect() as connection:
            self._confirm_brief_tx(
                connection,
                brief_id=brief["id"],
                project_id=project_id,
                actor=actor,
                note=note,
            )
        return self.get_brief(project_id)

    def refine_brief(
        self,
        project_id: str,
        patch: IdeaBriefRefineRequest,
        *,
        actor: str,
    ) -> dict[str, Any]:
        current = self.get_brief(project_id)
        updates = patch.model_dump(exclude_none=True)
        clarification_answer = updates.pop("clarification_answer", None)
        if not updates and not clarification_answer:
            raise ValueError("at least one IdeaBrief field must be refined")

        provenance = dict(current["provenance"])
        mutable = {
            "target_user": current["target_user"],
            "problem": current["problem"],
            "desired_outcome": current["desired_outcome"],
            "known_resources": current["known_resources"],
            "constraints": current["constraints"],
            "unknowns": current["unknowns"],
        }
        for key, value in updates.items():
            mutable[key] = value
            provenance[key] = "user_input"
        clarification_required = bool(current["clarification_required"])
        clarification_question = current.get("clarification_question")
        if clarification_answer:
            clarification_required = False
            clarification_question = None
            # Preserve the answer as an explicit constraint rather than inventing a semantic rewrite.
            mutable["constraints"] = [*mutable["constraints"], f"用户澄清：{clarification_answer}"]
            provenance["constraints"] = "user_input"

        draft = IdeaBriefDraft(
            original_idea=current["original_idea"],
            **mutable,
            provenance=provenance,
            clarification_required=clarification_required,
            clarification_question=clarification_question,
        )
        now = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE idea_briefs SET confirmation_status = 'superseded' WHERE id = ?",
                (current["id"],),
            )
            brief_id = self._insert_brief_tx(
                connection,
                project_id=project_id,
                version=int(current["version"]) + 1,
                draft=draft,
                confirmation_status="inferred",
                supersedes_id=current["id"],
            )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action="idea_brief_refined",
                entity_type="idea_brief",
                entity_id=brief_id,
                payload={
                    "project_id": project_id,
                    "supersedes_id": current["id"],
                    "user_written_fields": sorted(
                        [*updates.keys(), *( ["constraints"] if clarification_answer else [])]
                    ),
                },
            )
            connection.execute(
                "UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id)
            )
        return self.get_brief(project_id)
