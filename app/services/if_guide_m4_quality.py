from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.errors import ConflictError
from app.services.real_idea_metrics import ArtifactBinding, QualityEvaluationService


PRIMARY_METRICS = (
    "first_valid_action",
    "first_usable_flow_completion",
    "independent_acceptance",
    "evidence_backed_decision",
    "recovery",
)

SECONDARY_METRICS = (
    "critical_requirement_recall",
    "overall_requirement_recall",
    "requirement_alignment_precision",
    "checkability_coverage",
    "acceptance_coverage",
    "acceptance_testability",
    "unsupported_claim_rate",
    "actionability",
    "result_decision_traceability",
)


class M4QualityService:
    """Evaluate one isolated M4 session through the existing quality ledger."""

    def __init__(self, database: Any):
        self.database = database
        self.quality = QualityEvaluationService(database)

    def _session(
        self,
        *,
        session_id: str,
        account_id: str,
        project_id: str,
        expected_session_revision: int,
    ) -> Any:
        row = self.database.fetch_one(
            "SELECT * FROM m4_sessions WHERE session_id = ?", (session_id,)
        )
        if not row:
            raise KeyError("M4_SESSION_NOT_FOUND")
        if row["account_id"] != account_id:
            raise PermissionError("M4_ACCOUNT_ACCESS_DENIED")
        if row["project_id"] != project_id:
            raise ConflictError("M4_PROJECT_BINDING_MISMATCH")
        if row["revision"] != expected_session_revision:
            raise ConflictError("M4_SESSION_REVISION_CONFLICT")
        return row

    @staticmethod
    def _ratio(item: Any, name: str, violations: list[str]) -> dict[str, Any]:
        if not isinstance(item, Mapping):
            violations.append(f"missing_metric:{name}")
            return {"numerator": None, "denominator": None, "value": None, "status": "INVALID"}
        numerator = item.get("numerator")
        denominator = item.get("denominator")
        if (
            isinstance(numerator, bool)
            or isinstance(denominator, bool)
            or not isinstance(numerator, int)
            or not isinstance(denominator, int)
            or numerator < 0
            or denominator < 0
            or numerator > denominator
        ):
            violations.append("invalid_metric_ratio")
            return {"numerator": numerator, "denominator": denominator, "value": None, "status": "INVALID"}
        if denominator == 0:
            return {"numerator": 0, "denominator": 0, "value": None, "status": "NOT_APPLICABLE"}
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator,
            "status": "MEASURED",
        }

    @staticmethod
    def _unique(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    def evaluate_session(
        self,
        *,
        session_id: str,
        account_id: str,
        project_id: str,
        expected_session_revision: int,
        metrics: Mapping[str, Any],
    ) -> dict[str, Any]:
        session = self._session(
            session_id=session_id,
            account_id=account_id,
            project_id=project_id,
            expected_session_revision=expected_session_revision,
        )
        payload = dict(metrics)
        violations = list(payload.get("p0_violations", ()))
        primary = {
            name: self._ratio(payload.get(name), name, violations)
            for name in PRIMARY_METRICS
        }
        secondary_payload = payload.get("secondary")
        if not isinstance(secondary_payload, Mapping):
            secondary_payload = {}
            violations.append("missing_secondary_metrics")
        secondary = {
            name: self._ratio(secondary_payload.get(name), name, violations)
            for name in SECONDARY_METRICS
        }
        evidence = payload.get("evidence")
        if not isinstance(evidence, Mapping) or not evidence:
            violations.append("evidence_missing")
        gold_set = payload.get("gold_set")
        if (
            not isinstance(gold_set, Mapping)
            or gold_set.get("participant_confirmed") is not True
            or gold_set.get("confirmed_by") != "idea_provider"
        ):
            violations.append("gold_set_not_human_confirmed")
        if payload.get("provider_calls", 0) != 0 or payload.get("search_calls", 0) != 0:
            violations.append("provider_or_search_violation")
        violations = self._unique(violations)
        payload["primary_metrics"] = primary
        payload["secondary_metrics"] = secondary
        # The shared quality ledger binds metric names at the top level. Keep
        # the grouped representation for M4 reports while exposing the same
        # normalized metrics at the binding boundary.
        payload.update(primary)
        payload.update(secondary)
        payload["p0_violations"] = violations
        # Preserve observed accounting in the immutable quality payload.  The
        # P0 gate must see a non-zero observation as a violation rather than
        # having the evaluator normalize it away.
        payload["provider_calls"] = payload.get("provider_calls", 0)
        payload["search_calls"] = payload.get("search_calls", 0)

        binding = ArtifactBinding(
            None,
            None,
            project_id,
            "M4_SESSION",
            f"{session_id}:r{expected_session_revision}",
            None,
            None,
            (),
            "P0",
            "system",
            payload,
            {"session_id": session_id, "session_revision": expected_session_revision},
            {"session_id": session_id, "evidence": evidence},
            "if-guide-m4-quality-v1",
            owner_actor=account_id,
            artifact_id=session_id,
            artifact_revision=expected_session_revision,
            evaluation_scope="IF_GUIDE_M4",
        )
        p0 = self.quality.evaluate_p0(binding)
        p1_status = "NOT_RUN"
        quality_evaluation_id = p0.quality_evaluation_id
        p1_quality_evaluation_id = None
        if p0.status == "PASS":
            p1_id = self.quality.enqueue_p1(p0.quality_evaluation_id)
            p1 = self.quality.get(p1_id)
            p1_quality_evaluation_id = p1.quality_evaluation_id
            p1_status = p1.status
        return {
            "quality_evaluation_id": quality_evaluation_id,
            "p1_quality_evaluation_id": p1_quality_evaluation_id,
            "p0_status": p0.status,
            "p0_violations": violations,
            "p1_status": p1_status,
            "p2_status": "NOT_REVIEWED",
            "primary_metrics": primary,
            "secondary_metrics": secondary,
            "provider_calls": payload["provider_calls"],
            "search_calls": payload["search_calls"],
        }
