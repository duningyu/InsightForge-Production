from __future__ import annotations

from collections.abc import Callable

from app.schemas import SolutionCandidateDraft

DIVERSITY_FIELDS = (
    "mechanism",
    "required_data_class",
    "automation_level",
    "human_role",
    "core_decision_logic",
    "major_dependency",
)


def _material_difference_count(left: SolutionCandidateDraft, right: SolutionCandidateDraft) -> int:
    return sum(getattr(left, field) != getattr(right, field) for field in DIVERSITY_FIELDS)


def _has_non_llm_core(candidate: SolutionCandidateDraft) -> bool:
    return not (
        candidate.requires_llm_runtime
        or candidate.requires_rag_runtime
        or candidate.requires_agent_runtime
    )


def validate_solution_set(
    candidates: list[SolutionCandidateDraft],
    *,
    llm_core_required: bool,
) -> list[SolutionCandidateDraft]:
    if not 2 <= len(candidates) <= 3:
        raise ValueError("SOLUTION_SET_CARDINALITY_FAILED: expected 2-3 candidates")
    if len({item.title.strip().casefold() for item in candidates}) != len(candidates):
        raise ValueError("SOLUTION_DIVERSITY_FAILED: duplicate candidate titles")
    for index, left in enumerate(candidates):
        for right in candidates[index + 1 :]:
            if _material_difference_count(left, right) < 2:
                raise ValueError(
                    "SOLUTION_DIVERSITY_FAILED: every pair must differ on at least two material dimensions"
                )
    if not llm_core_required and not any(_has_non_llm_core(item) for item in candidates):
        raise ValueError(
            "OVERENGINEERED_SOLUTION_SET: at least one non-LLM/non-RAG/non-Agent core solution is required"
        )
    return candidates


def _largest_valid_subset(
    candidates: list[SolutionCandidateDraft], *, llm_core_required: bool
) -> list[SolutionCandidateDraft]:
    # P0 sets have at most three candidates, so explicit combinations keep this deterministic.
    if len(candidates) >= 3:
        triplet = candidates[:3]
        try:
            return validate_solution_set(triplet, llm_core_required=llm_core_required)
        except ValueError:
            pass
    for i, left in enumerate(candidates):
        for right in candidates[i + 1 :]:
            pair = [left, right]
            try:
                return validate_solution_set(pair, llm_core_required=llm_core_required)
            except ValueError:
                continue
    return []


def validate_with_one_regeneration(
    candidates: list[SolutionCandidateDraft],
    *,
    llm_core_required: bool,
    regenerate: Callable[[], list[SolutionCandidateDraft]] | None = None,
) -> list[SolutionCandidateDraft]:
    try:
        return validate_solution_set(candidates, llm_core_required=llm_core_required)
    except ValueError as first_error:
        if regenerate is not None:
            regenerated = regenerate()
            try:
                return validate_solution_set(regenerated, llm_core_required=llm_core_required)
            except ValueError:
                subset = _largest_valid_subset(regenerated, llm_core_required=llm_core_required)
                if subset:
                    return subset
        subset = _largest_valid_subset(candidates, llm_core_required=llm_core_required)
        if subset:
            return subset
        raise first_error


# Persistence/service layer is kept here so solution semantics and their validators evolve together.
import json
import time
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import ConflictError, StructuredRuntimeRecoveryError
from app.schemas import IdeaBriefDraft, SolutionSetDraft
from app.services.ai_runtime import StructuredAIRuntime, build_ai_trace_payload, sha256_payload


class SolutionDesignService:
    GENERATOR_VERSION = "solution-designer-v1"

    def __init__(self, db: Database, runtime: StructuredAIRuntime):
        self.db = db
        self.runtime = runtime

    def _audit_failure(
        self,
        *,
        runtime: StructuredAIRuntime,
        brief: IdeaBriefDraft,
        started_at: float,
        actor: str,
        entity_type: str,
        entity_id: str,
        action: str,
        status: str,
        error_code: str,
        safe_diagnostic: dict[str, Any] | None = None,
    ) -> None:
        trace = build_ai_trace_payload(
            runtime=runtime,
            input_payload=brief,
            output_payload=None,
            started_at=started_at,
            status=status,
            component_version=self.GENERATOR_VERSION,
        )
        trace["generator_version"] = trace.pop("component_version")
        trace["error_code"] = error_code
        if safe_diagnostic:
            trace.update(safe_diagnostic)
        self.db.insert_audit(
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=trace,
        )

    @staticmethod
    def _brief_from_row(row: dict[str, Any]) -> IdeaBriefDraft:
        return IdeaBriefDraft(
            original_idea=row["original_idea"],
            target_user=row["target_user"],
            problem=row["problem"],
            desired_outcome=row["desired_outcome"],
            known_resources=json.loads(row["known_resources_json"]),
            constraints=json.loads(row["constraints_json"]),
            unknowns=json.loads(row["unknowns_json"]),
            provenance=json.loads(row["provenance_json"]),
            clarification_required=bool(row.get("clarification_required", 0)),
            clarification_question=row.get("clarification_question"),
        )

    def _confirmed_brief_row(self, project_id: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE project_id = ? ORDER BY version DESC LIMIT 1",
            (project_id,),
        )
        if row is None:
            raise ConflictError("IDEA_BRIEF_REQUIRED: quick-start IdeaBrief does not exist")
        if row["confirmation_status"] != "confirmed":
            raise ConflictError("IDEA_BRIEF_NOT_CONFIRMED")
        if bool(row.get("clarification_required", 0)):
            raise ConflictError("IDEA_BRIEF_CLARIFICATION_REQUIRED")
        return row

    @staticmethod
    def _candidate_to_params(
        *, candidate_id: str, run_id: str, project_id: str, candidate: SolutionCandidateDraft, now: str
    ) -> tuple[Any, ...]:
        return (
            candidate_id, run_id, project_id, candidate.title, candidate.mechanism,
            candidate.summary, candidate.why_fit,
            json.dumps(candidate.user_flow, ensure_ascii=False),
            json.dumps(candidate.mvp_pages, ensure_ascii=False),
            json.dumps(candidate.features, ensure_ascii=False),
            json.dumps(candidate.inputs, ensure_ascii=False),
            json.dumps(candidate.outputs, ensure_ascii=False),
            json.dumps(candidate.decision_logic, ensure_ascii=False),
            json.dumps(candidate.data_requirements, ensure_ascii=False),
            json.dumps(candidate.technical_components, ensure_ascii=False),
            json.dumps(candidate.implementation_plan, ensure_ascii=False),
            json.dumps(candidate.acceptance_cases, ensure_ascii=False),
            json.dumps(candidate.risks, ensure_ascii=False),
            json.dumps(candidate.unknowns, ensure_ascii=False),
            candidate.complexity, candidate.provenance,
            candidate.required_data_class, candidate.automation_level, candidate.human_role,
            candidate.core_decision_logic, candidate.major_dependency,
            int(candidate.requires_llm_runtime), int(candidate.requires_rag_runtime),
            int(candidate.requires_agent_runtime), now,
        )

    @staticmethod
    def _serialize_candidate(row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        for field in (
            "user_flow", "mvp_pages", "features", "inputs", "outputs", "decision_logic",
            "data_requirements", "technical_components", "implementation_plan",
            "acceptance_cases", "risks", "unknowns",
        ):
            payload[field] = json.loads(payload.pop(f"{field}_json"))
        for field in ("requires_llm_runtime", "requires_rag_runtime", "requires_agent_runtime"):
            payload[field] = bool(payload[field])
        return payload

    def generate(self, project_id: str, *, actor: str) -> dict[str, Any]:
        brief_row = self._confirmed_brief_row(project_id)
        brief = self._brief_from_row(brief_row)
        resolver = getattr(self.runtime, "for_project", None)
        runtime = resolver(project_id) if callable(resolver) else self.runtime
        started = time.perf_counter()
        try:
            raw_set = runtime.design_solutions(brief)
        except StructuredRuntimeRecoveryError as exc:
            self._audit_failure(
                runtime=runtime,
                brief=brief,
                started_at=started,
                actor=actor,
                entity_type="project",
                entity_id=project_id,
                action="solution_generation_recovery_required",
                status="recovery_required",
                error_code=exc.error_code,
                safe_diagnostic=exc.safe_diagnostic,
            )
            return exc.as_payload(preserved_input=brief)
        initial_output_sha = sha256_payload(raw_set)
        run_id = f"solution_run_{uuid.uuid4().hex}"
        now = utc_now()
        input_sha = sha256_payload(brief)
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO solution_runs(
                    id, project_id, idea_brief_id, provider, model, prompt_version,
                    schema_version, generator_version, input_sha256, output_sha256,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'validating', ?)
                """,
                (
                    run_id, project_id, brief_row["id"], runtime.provider, runtime.model,
                    runtime.prompt_version, runtime.schema_version, self.GENERATOR_VERSION,
                    input_sha, initial_output_sha, now,
                ),
            )

        regenerated: list[SolutionCandidateDraft] | None = None

        def regenerate() -> list[SolutionCandidateDraft]:
            nonlocal regenerated
            regenerated_set = runtime.design_solutions(brief)
            regenerated = list(regenerated_set.candidates)
            return regenerated

        try:
            candidates = validate_with_one_regeneration(
                list(raw_set.candidates),
                llm_core_required=raw_set.llm_core_required,
                regenerate=regenerate,
            )
        except StructuredRuntimeRecoveryError as exc:
            self.db.execute(
                "UPDATE solution_runs SET status = 'failed_runtime' WHERE id = ?", (run_id,)
            )
            self._audit_failure(
                runtime=runtime,
                brief=brief,
                started_at=started,
                actor=actor,
                entity_type="solution_run",
                entity_id=run_id,
                action="solution_generation_recovery_required",
                status="failed_runtime",
                error_code=exc.error_code,
                safe_diagnostic=exc.safe_diagnostic,
            )
            return exc.as_payload(preserved_input=brief)
        except ValueError as exc:
            message = str(exc)
            status = (
                "failed_overengineering" if "OVERENGINEERED" in message
                else "failed_diversity" if "DIVERSITY" in message
                else "failed_schema"
            )
            self.db.execute("UPDATE solution_runs SET status = ? WHERE id = ?", (status, run_id))
            self._audit_failure(
                runtime=runtime,
                brief=brief,
                started_at=started,
                actor=actor,
                entity_type="solution_run",
                entity_id=run_id,
                action="solution_generation_failed",
                status=status,
                error_code=message.split(":", 1)[0],
            )
            raise

        final_set = SolutionSetDraft(
            candidates=candidates,
            llm_core_required=raw_set.llm_core_required,
            recommendation_candidate_id=raw_set.recommendation_candidate_id,
            recommendation_rationale=raw_set.recommendation_rationale,
        )
        final_output_sha = sha256_payload(final_set)
        status = "completed_two_candidates" if len(candidates) == 2 else "completed"
        trace = build_ai_trace_payload(
            runtime=runtime,
            input_payload=brief,
            output_payload=final_set,
            started_at=started,
            status=status,
            component_version=self.GENERATOR_VERSION,
        )
        trace["generator_version"] = trace.pop("component_version")
        trace["initial_output_sha256"] = initial_output_sha
        trace.update(getattr(runtime, "last_provider_diagnostic", {}))
        trace.update({
            "normalized_candidate_count": len(candidates),
            "validator_accepted_count": len(candidates),
            "persisted_candidate_count": len(candidates),
            "response_candidate_count": len(candidates),
            "diversity_verdict": "PASS",
        })
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE solution_runs SET output_sha256 = ?, status = ? WHERE id = ?",
                (final_output_sha, status, run_id),
            )
            for candidate in candidates:
                candidate_id = f"solution_{uuid.uuid4().hex}"
                connection.execute(
                    """
                    INSERT INTO solution_candidates(
                        id, run_id, project_id, title, mechanism, summary, why_fit,
                        user_flow_json, mvp_pages_json, features_json, inputs_json, outputs_json,
                        decision_logic_json, data_requirements_json, technical_components_json,
                        implementation_plan_json, acceptance_cases_json, risks_json, unknowns_json,
                        complexity, provenance, required_data_class, automation_level, human_role,
                        core_decision_logic, major_dependency, requires_llm_runtime,
                        requires_rag_runtime, requires_agent_runtime, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._candidate_to_params(
                        candidate_id=candidate_id,
                        run_id=run_id,
                        project_id=project_id,
                        candidate=candidate,
                        now=utc_now(),
                    ),
                )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action="solution_candidates_generated",
                entity_type="solution_run",
                entity_id=run_id,
                payload=trace,
            )
        result = self.list_candidates(project_id)
        if not result.get("candidates"):
            # A completed run without persisted candidates is never a successful
            # generation; keep the run auditable but prevent a false success.
            self.db.execute(
                "UPDATE solution_runs SET status = 'failed_empty_result' WHERE id = ?",
                (run_id,),
            )
            raise ConflictError("SOLUTION_GENERATION_NO_VALID_CANDIDATES")
        return result

    def list_candidates(self, project_id: str) -> dict[str, Any]:
        latest = self.db.fetch_one(
            "SELECT * FROM solution_runs WHERE project_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (project_id,),
        )
        if latest is None:
            raise KeyError("solution run not found")
        rows = self.db.fetch_all(
            "SELECT * FROM solution_candidates WHERE run_id = ? ORDER BY created_at, id",
            (latest["id"],),
        )
        candidates = [self._serialize_candidate(row) for row in rows]
        return {"run": latest, "latest_run": latest, "candidates": candidates}
