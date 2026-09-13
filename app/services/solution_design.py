from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.schemas import SolutionCandidateDraft
from app.services.dispatch_control import DispatchControlContext

from app.services.generation_contracts import (
    GenerationContractError, _material_difference_count, validate_solutions, parse_generation, call_generation,
    candidate_public, solution_public, await_generation,
)


def _commit_runtime_reservation(runtime: Any) -> None:
    callback = getattr(runtime, "commit_current_reservation", None)
    if callable(callback):
        callback()


def _release_runtime_reservation(runtime: Any) -> None:
    callback = getattr(runtime, "release_current_reservation", None)
    if callable(callback):
        callback()


def validate_solution_set(
    candidates: list[SolutionCandidateDraft],
    *,
    llm_core_required: bool,
) -> list[SolutionCandidateDraft]:
    return validate_solutions(candidates, llm_core_required=llm_core_required)


def validate_with_one_regeneration(
    candidates: list[SolutionCandidateDraft],
    *,
    llm_core_required: bool,
    regenerate: Callable[[], list[SolutionCandidateDraft]] | None = None,
) -> list[SolutionCandidateDraft]:
    try:
        return validate_solution_set(candidates, llm_core_required=llm_core_required)
    except GenerationContractError:
        if regenerate is None:
            raise
    return validate_solution_set(regenerate(), llm_core_required=llm_core_required)


# Persistence/service layer is kept here so solution semantics and their validators evolve together.
import json
import time
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import ConflictError, StructuredRuntimeRecoveryError
from app.schemas import IdeaBriefDraft, SolutionSetDraft
from app.services.ai_runtime import StructuredAIRuntime, build_ai_trace_payload, sha256_payload
from app.services.stage_b_evaluation import StageBEvaluationContext, StageBExecutionPolicy


class SolutionDesignService:
    GENERATOR_VERSION = "solution-designer-v1"

    def __init__(self, db: Database, runtime: StructuredAIRuntime, ai_reference: Any | None = None):
        self.db = db
        self.runtime = runtime
        self.ai_reference = ai_reference

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
    def _brief_from_row(
        row: dict[str, Any], competitor_context: dict[str, Any] | None = None
    ) -> IdeaBriefDraft:
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
            competitor_context=competitor_context,
        )

    def _competitor_context(
        self, project_id: str, competitor_snapshot_id: str | None = None,
        *, use_competitor_snapshot: bool = True,
    ) -> dict[str, Any] | None:
        if not use_competitor_snapshot:
            return None
        row = self.db.fetch_one(
            "SELECT current_competitor_snapshot_id FROM projects WHERE id = ?",
            (project_id,),
        )
        snapshot_id = competitor_snapshot_id or (row.get("current_competitor_snapshot_id") if row else None)
        if not snapshot_id:
            return None
        snapshot = self.db.fetch_one(
            "SELECT content_json FROM competitor_decision_snapshots WHERE id=? AND project_id=?",
            (snapshot_id, project_id),
        )
        if not snapshot:
            if competitor_snapshot_id:
                raise ConflictError("COMPETITOR_SNAPSHOT_NOT_FOUND")
            return None
        content = json.loads(snapshot["content_json"])
        grouped = {"adopt": [], "avoid": [], "defer": []}
        for decision in content.get("decisions", []):
            grouped.setdefault(decision["decision"], []).append(
                {"candidate_id": decision["candidate_id"], "rationale": decision.get("rationale", "")}
            )
        return {
            "snapshot_id": snapshot_id,
            "boundary": content.get("boundary", "AI分析参考，建议结合实际产品页面核对。"),
            "adopt": grouped["adopt"],
            "avoid": grouped["avoid"],
            "defer": grouped["defer"],
        }

    def _brief_for_project(
        self, project_id: str, brief_row: dict[str, Any],
        competitor_snapshot_id: str | None = None,
        *, use_competitor_snapshot: bool = True,
    ) -> IdeaBriefDraft:
        """Keep the legacy test seam when no optional snapshot is selected."""
        competitor_context = self._competitor_context(
            project_id, competitor_snapshot_id,
            use_competitor_snapshot=use_competitor_snapshot,
        )
        ai_context = (
            self.ai_reference.get_context(project_id, actor="solution_generation")
            if self.ai_reference is not None else None
        )
        if ai_context and (ai_context.get("adopted") or ai_context.get("ignored")):
            competitor_context = dict(competitor_context or {})
            competitor_context["ai_reference"] = ai_context
        if competitor_context is None:
            return self._brief_from_row(brief_row)
        return self._brief_from_row(brief_row, competitor_context=competitor_context)

    def _confirmed_brief_row(self, project_id: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE project_id = ? ORDER BY version DESC LIMIT 1",
            (project_id,),
        )
        if row is None:
            raise ConflictError("IDEA_BRIEF_REQUIRED: quick-start IdeaBrief does not exist")
        if bool(row.get("clarification_required", 0)):
            raise ConflictError("IDEA_BRIEF_CLARIFICATION_REQUIRED")
        if row["confirmation_status"] != "confirmed":
            raise ConflictError("IDEA_BRIEF_NOT_CONFIRMED")
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
        return candidate_public(payload)

    def generate(self, project_id: str, *, actor: str, managed_selection: Any | None = None,
                 dispatch_control: DispatchControlContext | None = None,
                 evaluation_context: StageBEvaluationContext | None = None,
                 execution_policy: StageBExecutionPolicy | None = None,
                 competitor_snapshot_id: str | None = None,
                 use_competitor_snapshot: bool = True) -> dict[str, Any]:
        brief_row = self._confirmed_brief_row(project_id)
        brief = self._brief_for_project(
            project_id, brief_row, competitor_snapshot_id,
            use_competitor_snapshot=use_competitor_snapshot,
        )
        resolver = getattr(self.runtime, "for_project", None)
        runtime = (
            resolver(project_id, managed_selection=managed_selection)
            if callable(resolver) and managed_selection is not None
            else resolver(project_id) if callable(resolver) else self.runtime
        )
        started = time.perf_counter()
        try:
            if execution_policy is not None:
                execution_policy.validate()
            design_kwargs = {}
            if dispatch_control is not None:
                design_kwargs["dispatch_control"] = dispatch_control
            if evaluation_context is not None:
                design_kwargs["evaluation_context"] = evaluation_context
            raw_output = call_generation(lambda: runtime.design_solutions(brief, **design_kwargs))
            try:
                raw_set = parse_generation(SolutionSetDraft, raw_output)
            except GenerationContractError:
                # Keep an explicitly empty model result on the persisted-run path
                # so it is recorded as failed rather than as a recovery-only call.
                empty_candidates = (
                    raw_output.get("candidates") == []
                    if isinstance(raw_output, dict)
                    else getattr(raw_output, "candidates", None) == []
                )
                if not empty_candidates:
                    raise
                raw_set = (
                    raw_output
                    if isinstance(raw_output, SolutionSetDraft)
                    else SolutionSetDraft.model_construct(
                        candidates=[], llm_core_required=False
                    )
                )
        except StructuredRuntimeRecoveryError as exc:
            _release_runtime_reservation(runtime)
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
                    status, competitor_snapshot_id, use_competitor_snapshot, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'validating', ?, ?, ?)
                """,
                (
                    run_id, project_id, brief_row["id"], runtime.provider, runtime.model,
                    runtime.prompt_version, runtime.schema_version, self.GENERATOR_VERSION,
                    input_sha, initial_output_sha,
                    competitor_snapshot_id if use_competitor_snapshot else None,
                    int(use_competitor_snapshot), now,
                ),
            )

        regenerated: list[SolutionCandidateDraft] | None = None

        def regenerate() -> list[SolutionCandidateDraft]:
            nonlocal regenerated
            regenerate_kwargs = {}
            if dispatch_control is not None:
                regenerate_kwargs["dispatch_control"] = dispatch_control
            if evaluation_context is not None:
                regenerate_kwargs["evaluation_context"] = evaluation_context
            regenerated_set = parse_generation(SolutionSetDraft, call_generation(lambda: runtime.design_solutions(brief, **regenerate_kwargs)))
            regenerated = list(regenerated_set.candidates)
            return regenerated

        def recover_after_persisted_run(exc: StructuredRuntimeRecoveryError) -> dict[str, Any]:
            _release_runtime_reservation(runtime)
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

        try:
            candidates = validate_with_one_regeneration(
                list(raw_set.candidates),
                llm_core_required=raw_set.llm_core_required,
                regenerate=(
                    regenerate
                    if (
                        execution_policy.validation_regeneration_allowed
                        if execution_policy is not None
                        else dispatch_control is None
                    )
                    else None
                ),
            )
        except ValueError as exc:
            if isinstance(exc, GenerationContractError) and raw_set.candidates:
                return recover_after_persisted_run(exc)
            _release_runtime_reservation(runtime)
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
        except StructuredRuntimeRecoveryError as exc:
            return recover_after_persisted_run(exc)

        final_set = SolutionSetDraft(
            candidates=candidates,
            llm_core_required=raw_set.llm_core_required,
            recommendation_candidate_id=raw_set.recommendation_candidate_id,
            recommendation_rationale=raw_set.recommendation_rationale,
        )
        final_output_sha = sha256_payload(final_set)
        status = "completed"
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
            _release_runtime_reservation(runtime)
            raise ConflictError("SOLUTION_GENERATION_NO_VALID_CANDIDATES")
        _commit_runtime_reservation(runtime)
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
        result = {"run": latest, "latest_run": latest, "candidates": candidates}
        if latest.get("provider") == "safe_fixture":
            result["fixture_origin"] = "STAGE_A_SYNTHETIC"
            result["fixture_disclosure"] = "Stage A 演示结果 · 非真实 AI 生成"
        return solution_public(result)

    async def generate_async(
        self,
        project_id: str,
        *,
        actor: str,
        managed_selection: Any | None = None,
        generation_intent_id: str | None = None,
        generation_run_id: str | None = None,
        dispatch_control: DispatchControlContext | None = None,
        evaluation_context: StageBEvaluationContext | None = None,
        execution_policy: StageBExecutionPolicy | None = None,
        competitor_snapshot_id: str | None = None,
        use_competitor_snapshot: bool = True,
    ) -> dict[str, Any]:
        """Generate through the real async provider boundary.

        This deliberately performs one provider attempt.  A new attempt is
        only legal after the caller creates a new durable generation intent.
        """
        brief_row = self._confirmed_brief_row(project_id)
        brief = self._brief_for_project(
            project_id, brief_row, competitor_snapshot_id,
            use_competitor_snapshot=use_competitor_snapshot,
        )
        resolver = getattr(self.runtime, "for_project", None)
        runtime = (
            resolver(project_id, managed_selection=managed_selection)
            if callable(resolver) and managed_selection is not None
            else resolver(project_id) if callable(resolver) else self.runtime
        )
        started = time.perf_counter()
        if execution_policy is not None:
            execution_policy.validate()
        try:
            async_kwargs = {
                "generation_intent_id": generation_intent_id,
                "generation_run_id": generation_run_id,
            }
            if dispatch_control is not None:
                async_kwargs["dispatch_control"] = dispatch_control
            if evaluation_context is not None:
                async_kwargs["evaluation_context"] = evaluation_context
            raw_set = parse_generation(SolutionSetDraft, await await_generation(runtime.async_design_solutions(brief, **async_kwargs)))
        except StructuredRuntimeRecoveryError as exc:
            _release_runtime_reservation(runtime)
            self._audit_failure(
                runtime=runtime, brief=brief, started_at=started, actor=actor,
                entity_type="project", entity_id=project_id,
                action="solution_generation_recovery_required", status="recovery_required",
                error_code=exc.error_code, safe_diagnostic=exc.safe_diagnostic,
            )
            payload = exc.as_payload(preserved_input=brief)
            if isinstance(exc, GenerationContractError):
                payload.update(quota_status="RELEASED", retryable=False)
            fixture_origin = getattr(runtime, "fixture_origin", None)
            if fixture_origin:
                payload["fixture_origin"] = fixture_origin
                payload["fixture_disclosure"] = getattr(
                    runtime, "disclosure", "Stage A 演示结果 · 非真实 AI 生成"
                )
            return payload

        try:
            candidates = validate_solution_set(
                list(raw_set.candidates), llm_core_required=raw_set.llm_core_required
            )
        except GenerationContractError as exc:
            _release_runtime_reservation(runtime)
            self._audit_failure(
                runtime=runtime, brief=brief, started_at=started, actor=actor,
                entity_type="project", entity_id=project_id,
                action="solution_generation_failed", status="failed_validation",
                error_code=str(exc).split(":", 1)[0],
            )
            return {**exc.as_payload(), "quota_status": "RELEASED", "retryable": False}

        run_id = f"solution_run_{uuid.uuid4().hex}"
        final_set = SolutionSetDraft(
            candidates=candidates,
            llm_core_required=raw_set.llm_core_required,
            recommendation_candidate_id=raw_set.recommendation_candidate_id,
            recommendation_rationale=raw_set.recommendation_rationale,
        )
        input_sha = sha256_payload(brief)
        output_sha = sha256_payload(final_set)
        now = utc_now()
        trace = build_ai_trace_payload(
            runtime=runtime, input_payload=brief, output_payload=final_set,
            started_at=started,
            status="completed",
            component_version=self.GENERATOR_VERSION,
        )
        trace["generator_version"] = trace.pop("component_version")
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
                """INSERT INTO solution_runs(
                    id, project_id, idea_brief_id, provider, model, prompt_version,
                    schema_version, generator_version, input_sha256, output_sha256,
                    status, competitor_snapshot_id, use_competitor_snapshot, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?)""",
                (run_id, project_id, brief_row["id"], runtime.provider, runtime.model,
                 runtime.prompt_version, runtime.schema_version, self.GENERATOR_VERSION,
                 input_sha, output_sha,
                 competitor_snapshot_id if use_competitor_snapshot else None,
                 int(use_competitor_snapshot), now),
            )
            for candidate in candidates:
                candidate_id = f"solution_{uuid.uuid4().hex}"
                connection.execute(
                    """INSERT INTO solution_candidates(
                        id, run_id, project_id, title, mechanism, summary, why_fit,
                        user_flow_json, mvp_pages_json, features_json, inputs_json, outputs_json,
                        decision_logic_json, data_requirements_json, technical_components_json,
                        implementation_plan_json, acceptance_cases_json, risks_json, unknowns_json,
                        complexity, provenance, required_data_class, automation_level, human_role,
                        core_decision_logic, major_dependency, requires_llm_runtime,
                        requires_rag_runtime, requires_agent_runtime, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    self._candidate_to_params(
                        candidate_id=candidate_id, run_id=run_id, project_id=project_id,
                        candidate=candidate, now=utc_now(),
                    ),
                )
            self.db.insert_audit_tx(
                connection, actor=actor, action="solution_candidates_generated",
                entity_type="solution_run", entity_id=run_id, payload=trace,
            )
        result = self.list_candidates(project_id)
        result["_solution_run_id"] = run_id
        _commit_runtime_reservation(runtime)
        return result
