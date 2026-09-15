from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from app.db import Database, utc_now


class GoldSetNotFinalError(ValueError):
    """The requirement Gold Set has not received idea-provider confirmation."""


class QualityBindingError(ValueError):
    """Quality evidence does not match the evaluation or artifact contract."""


class QualityRevisionError(ValueError):
    """An immutable quality evaluation cannot be revised in place."""


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    batch_id: str
    sample_id: str
    project_id: str
    artifact_type: str
    artifact_version_id: str
    selected_solution_id: str | None
    snapshot_id: str | None
    upstream_version_ids: tuple[str, ...]
    quality_layer: str
    evaluator_role: str
    metric_payload: Mapping[str, Any]
    input_manifest: Mapping[str, Any]
    evidence_manifest: Mapping[str, Any]
    policy_version: str


@dataclass(frozen=True, slots=True)
class ArtifactQualityEvaluation:
    quality_evaluation_id: str
    batch_id: str
    sample_id: str
    project_id: str
    artifact_type: str
    artifact_version_id: str
    selected_solution_id: str | None
    snapshot_id: str | None
    upstream_version_ids: tuple[str, ...]
    quality_layer: str
    quality_revision: int
    status: str
    metric_payload: Mapping[str, Any]
    input_manifest_sha256: str
    evidence_manifest_sha256: str
    policy_version: str
    evaluator_role: str
    created_at: str
    supersedes_quality_evaluation_id: str | None


_QUALITY_METRICS = {
    "SOLUTIONS": {
        "brief_critical_requirement_recall", "brief_overall_requirement_recall",
        "solution_set_recall", "solution_set_critical_recall", "selected_solution_recall",
        "selected_solution_critical_recall", "requirement_alignment_precision", "factual_precision",
        "unsupported_claim_rate", "decision_dimension_coverage", "pairwise_solution_differentiation",
    },
    "PRD": {
        "requirement_coverage_recall", "critical_requirement_coverage", "selected_solution_inheritance",
        "scope_consistency", "mandatory_section_coverage", "acceptance_criteria_testability",
        "completeness", "actionability", "unsupported_claim_rate", "critical_contradiction_rate",
    },
    "TECHDOC": {
        "prd_traceability_recall", "critical_technical_coverage", "nfr_coverage",
        "implementation_actionability", "feasibility_accuracy", "selected_solution_snapshot_inheritance",
        "unsupported_technical_claim_rate", "critical_contradiction_rate", "completeness",
    },
    "HANDOFF": {
        "exact_version_binding_accuracy", "artifact_completeness", "unresolved_item_coverage",
        "evidence_limitation_visibility", "decision_binding_accuracy", "package_integrity",
    },
}


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _assert_safe_evidence(value: Any, path: str = "evidence") -> None:
    forbidden = {"body", "content", "raw_idea", "provider_payload", "full_text", "acknowledgement_text"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() in forbidden:
                raise QualityBindingError(f"unsafe quality evidence field: {path}.{key}")
            _assert_safe_evidence(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_safe_evidence(child, f"{path}[{index}]")


class QualityEvaluationService:
    """Persist immutable, safely projected P0/P1/P2 artifact evaluations."""

    def __init__(self, database: Database):
        self.database = database

    def _validate_binding(self, binding: ArtifactBinding) -> None:
        if binding.artifact_type not in _QUALITY_METRICS:
            raise QualityBindingError("unknown artifact type")
        if binding.quality_layer not in {"P0", "P1", "P2"}:
            raise QualityBindingError("unknown quality layer")
        if binding.evaluator_role not in {"system", "idea_provider", "independent_reviewer", "llm_assist"}:
            raise QualityBindingError("unknown evaluator role")
        _assert_safe_evidence(binding.metric_payload)
        _assert_safe_evidence(binding.input_manifest)
        _assert_safe_evidence(binding.evidence_manifest)
        sample = self.database.fetch_one(
            "SELECT batch_id, project_id FROM real_idea_samples WHERE sample_id = ?", (binding.sample_id,)
        )
        if not sample or sample["batch_id"] != binding.batch_id or sample["project_id"] != binding.project_id:
            raise QualityBindingError("quality evidence is not bound to the sample project")
        missing = _QUALITY_METRICS[binding.artifact_type] - set(binding.metric_payload)
        if missing:
            raise QualityBindingError(f"required metric payload missing: {sorted(missing)[0]}")

    def _insert(self, binding: ArtifactBinding, *, status: str, revision: int = 1,
                supersedes: str | None = None) -> ArtifactQualityEvaluation:
        quality_id = f"quality_{uuid.uuid4().hex}"
        created_at = utc_now()
        input_hash = _canonical_hash(binding.input_manifest)
        evidence_hash = _canonical_hash(binding.evidence_manifest | {"metrics": dict(binding.metric_payload)})
        self.database.execute(
            """INSERT INTO real_idea_quality_evaluations(
                quality_evaluation_id, batch_id, sample_id, project_id, artifact_type,
                artifact_version_id, selected_solution_id, snapshot_id, upstream_version_ids,
                quality_layer, quality_revision, status, metric_payload, input_manifest_sha256,
                evidence_manifest_sha256, policy_version, quality_schema_version, evaluator_role,
                created_at, supersedes_quality_evaluation_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'v1', ?, ?, ?)""",
            (quality_id, binding.batch_id, binding.sample_id, binding.project_id, binding.artifact_type,
             binding.artifact_version_id, binding.selected_solution_id, binding.snapshot_id,
             json.dumps(list(binding.upstream_version_ids)), binding.quality_layer, revision, status,
             json.dumps(dict(binding.metric_payload), ensure_ascii=False, sort_keys=True), input_hash,
             evidence_hash, binding.policy_version, binding.evaluator_role, created_at, supersedes),
        )
        return self.get(quality_id)

    def get(self, quality_evaluation_id: str) -> ArtifactQualityEvaluation:
        row = self.database.fetch_one(
            "SELECT * FROM real_idea_quality_evaluations WHERE quality_evaluation_id = ?",
            (quality_evaluation_id,),
        )
        if not row:
            raise KeyError(quality_evaluation_id)
        return ArtifactQualityEvaluation(
            quality_evaluation_id=row["quality_evaluation_id"], batch_id=row["batch_id"],
            sample_id=row["sample_id"], project_id=row["project_id"], artifact_type=row["artifact_type"],
            artifact_version_id=row["artifact_version_id"], selected_solution_id=row["selected_solution_id"],
            snapshot_id=row["snapshot_id"], upstream_version_ids=tuple(json.loads(row["upstream_version_ids"])),
            quality_layer=row["quality_layer"], quality_revision=row["quality_revision"], status=row["status"],
            metric_payload=json.loads(row["metric_payload"]), input_manifest_sha256=row["input_manifest_sha256"],
            evidence_manifest_sha256=row["evidence_manifest_sha256"], policy_version=row["policy_version"],
            evaluator_role=row["evaluator_role"], created_at=row["created_at"],
            supersedes_quality_evaluation_id=row["supersedes_quality_evaluation_id"],
        )

    def evaluate_p0(self, binding: ArtifactBinding) -> ArtifactQualityEvaluation:
        self._validate_binding(binding)
        violations = binding.metric_payload.get("p0_violations", ())
        status = "FAIL" if violations else "PASS"
        return self._insert(binding, status=status)

    def enqueue_p1(self, quality_evaluation_id: str) -> str:
        """Create the append-only structured evaluation after a passing P0 gate."""
        source = self.get(quality_evaluation_id)
        if source.quality_layer != "P0" or source.status == "FAIL":
            raise QualityBindingError("P1 requires a passing P0 evaluation")
        payload = dict(source.metric_payload)
        gaps = tuple(payload.get("p1_gaps", ()))
        binding = ArtifactBinding(
            source.batch_id, source.sample_id, source.project_id, source.artifact_type,
            source.artifact_version_id, source.selected_solution_id, source.snapshot_id,
            source.upstream_version_ids, "P1", "system", payload,
            {"source_quality_evaluation_id": source.quality_evaluation_id},
            {"source_quality_evaluation_id": source.quality_evaluation_id}, source.policy_version,
        )
        result = self._insert(binding, status="PARTIAL" if gaps else "PASS", revision=2,
                              supersedes=source.quality_evaluation_id)
        return result.quality_evaluation_id

    def record_p2_review(self, quality_evaluation_id: str, review: Mapping[str, Any]) -> ArtifactQualityEvaluation:
        """Persist a human review; an LLM assist cannot be the authoritative P2 reviewer."""
        source = self.get(quality_evaluation_id)
        if source.quality_layer not in {"P0", "P1"} or source.status == "FAIL":
            raise QualityBindingError("P2 requires a passing operational evaluation")
        role = review.get("evaluator_role")
        if role not in {"idea_provider", "independent_reviewer"}:
            raise QualityBindingError("P2 requires an authoritative human reviewer")
        payload = dict(source.metric_payload)
        payload["p2_review"] = {key: value for key, value in review.items() if key != "evaluator_role"}
        binding = ArtifactBinding(
            source.batch_id, source.sample_id, source.project_id, source.artifact_type,
            source.artifact_version_id, source.selected_solution_id, source.snapshot_id,
            source.upstream_version_ids, "P2", role, payload,
            {"source_quality_evaluation_id": source.quality_evaluation_id},
            {"review_id": review.get("review_id", "redacted")}, source.policy_version,
        )
        return self._insert(binding, status=str(review.get("status", "PARTIAL")),
                            revision=source.quality_revision + 1,
                            supersedes=source.quality_evaluation_id)

    def build_batch_report(self, batch_id: str) -> dict[str, Any]:
        rows = self.database.fetch_all(
            "SELECT sample_id, COUNT(*) AS quality_evaluation_count "
            "FROM real_idea_quality_evaluations WHERE batch_id=? GROUP BY sample_id ORDER BY sample_id",
            (batch_id,),
        )
        return {
            "batch_id": batch_id,
            "sample_count": len(rows),
            "samples": [{"sample_id": row["sample_id"],
                         "quality_evaluation_count": row["quality_evaluation_count"]} for row in rows],
            "n3_statistical_superiority_claim_allowed": False,
        }

    def monitoring_summary(self, batch_id: str) -> dict[str, Any]:
        rows = self.database.fetch_all(
            "SELECT status, COUNT(*) AS count FROM real_idea_quality_evaluations "
            "WHERE batch_id=? GROUP BY status ORDER BY status", (batch_id,)
        )
        latest = self.database.fetch_one(
            "SELECT quality_evaluation_id FROM real_idea_quality_evaluations "
            "WHERE batch_id=? ORDER BY created_at DESC, quality_evaluation_id DESC LIMIT 1", (batch_id,)
        )
        return {
            "batch_id": batch_id,
            "quality_evaluation_count": sum(row["count"] for row in rows),
            "statuses": {row["status"]: row["count"] for row in rows},
            "latest_quality_evaluation_id": latest["quality_evaluation_id"] if latest else None,
        }

    def revise(self, quality_evaluation_id: str, *, metric_payload: Mapping[str, Any], status: str,
               correction_reason: str, evaluator_role: str) -> ArtifactQualityEvaluation:
        if not correction_reason.strip():
            raise QualityRevisionError("correction reason is required")
        original = self.get(quality_evaluation_id)
        next_revision = original.quality_revision + 1
        existing = self.database.fetch_one(
            "SELECT 1 FROM real_idea_quality_evaluations WHERE batch_id=? AND sample_id=? AND artifact_type=? AND artifact_version_id=? AND quality_revision=?",
            (original.batch_id, original.sample_id, original.artifact_type, original.artifact_version_id, next_revision),
        )
        if existing:
            raise QualityRevisionError("quality revision already exists")
        binding = ArtifactBinding(
            original.batch_id, original.sample_id, original.project_id, original.artifact_type,
            original.artifact_version_id, original.selected_solution_id, original.snapshot_id,
            original.upstream_version_ids, original.quality_layer, evaluator_role, metric_payload,
            {"source_quality_evaluation_id": original.quality_evaluation_id, "correction": correction_reason},
            {"correction_reason": correction_reason}, original.policy_version,
        )
        self._validate_binding(binding)
        if status not in {"PASS", "PARTIAL", "FAIL"}:
            raise QualityRevisionError("invalid quality status")
        if original.status == "FAIL" and status != "FAIL":
            raise QualityBindingError("a P0 failure cannot be upgraded")
        return self._insert(binding, status=status, revision=next_revision, supersedes=quality_evaluation_id)


@dataclass(frozen=True, slots=True)
class RequirementGoldItem:
    requirement_id: str
    sample_id: str
    canonical_text: str
    importance: str
    source: str
    confirmed_by: str


@dataclass(frozen=True, slots=True)
class RequirementGoldSet:
    sample_id: str
    items: tuple[RequirementGoldItem, ...]
    finalized_by: str
    source: str


@dataclass(frozen=True, slots=True)
class RequirementMapping:
    requirement_id: str
    target_id: str
    correctly_covered: bool
    evaluator_role: str


@dataclass(frozen=True, slots=True)
class ClaimAnnotation:
    claim_id: str
    claim_class: str
    supported: bool
    evaluator_role: str


@dataclass(frozen=True, slots=True)
class DecisionAnnotation:
    dimension: str
    meaningfully_differentiated: bool
    evaluator_role: str


@dataclass(frozen=True, slots=True)
class InheritanceAnnotation:
    relation: str
    accuracy: float
    evaluator_role: str


@dataclass(frozen=True, slots=True)
class QualityMetrics:
    brief_critical_requirement_recall: float
    brief_overall_requirement_recall: float
    solution_set_recall: float
    solution_set_critical_recall: float
    selected_solution_recall: float
    selected_solution_critical_recall: float
    requirement_alignment_precision: float
    factual_precision: float
    unsupported_claim_rate: float
    decision_dimension_coverage: float
    pairwise_solution_differentiation: float
    solution_to_prd_inheritance: float
    prd_to_techdoc_inheritance: float
    handoff_decision_binding_accuracy: float
    critical_contradiction_rate: float
    llm_judge_is_not_ground_truth: bool
    requirement_recall_is_not_retrieval_recall: bool


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


class RealIdeaMetricsService:
    """Provider-free, review-backed quality metrics for one evaluation sample.

    This service intentionally accepts already-reviewed artifact projections rather than
    calling an LLM.  Callers can persist the frozen payload through the evaluation ledger.
    """

    def __init__(
        self,
        *,
        sample_id: str,
        raw_idea: str,
        reviewed_brief: Mapping[str, str],
        provider_decision: str,
        solutions: list[Mapping[str, Any]],
        selected_solution_id: str | None,
        annotations: Mapping[str, Any] | None = None,
    ) -> None:
        if not sample_id or not raw_idea.strip():
            raise ValueError("sample_id and raw_idea are required")
        if provider_decision not in {"ACCEPT_AS_IS", "EDIT_AND_ACCEPT"}:
            raise ValueError("gold set requires an accepted reviewed brief")
        self.sample_id = sample_id
        self.raw_idea = raw_idea
        self.reviewed_brief = dict(reviewed_brief)
        self.provider_decision = provider_decision
        self.solutions = [dict(item) for item in solutions]
        self.selected_solution_id = selected_solution_id
        self.annotations = dict(annotations or {})
        self._gold_set: RequirementGoldSet | None = None

    def finalize_gold_set(self, *, source: str) -> RequirementGoldSet:
        if source != "idea_provider":
            raise GoldSetNotFinalError("only idea-provider review can finalize ground truth")
        fields = (
            ("idea", "CRITICAL", "USER_CONFIRMED_BRIEF"),
            ("target_user", "CRITICAL", "USER_CONFIRMED_BRIEF"),
            ("problem", "CRITICAL", "USER_CONFIRMED_BRIEF"),
            ("desired_outcome", "SECONDARY", "USER_CONFIRMED_BRIEF"),
        )
        items: list[RequirementGoldItem] = []
        for index, (field, importance, item_source) in enumerate(fields, start=1):
            text = str(self.reviewed_brief.get(field, "")).strip()
            if not text:
                continue
            items.append(
                RequirementGoldItem(
                    requirement_id=f"{self.sample_id}:r{index}",
                    sample_id=self.sample_id,
                    canonical_text=text,
                    importance=importance,
                    source=item_source,
                    confirmed_by="idea_provider",
                )
            )
        if not items:
            raise GoldSetNotFinalError("reviewed brief contains no requirements")
        self._gold_set = RequirementGoldSet(self.sample_id, tuple(items), "idea_provider", source)
        return self._gold_set

    @property
    def gold_set(self) -> RequirementGoldSet:
        if self._gold_set is None:
            raise GoldSetNotFinalError("Gold Set must be finalized after provider review")
        return self._gold_set

    def evaluate(self) -> QualityMetrics:
        gold = self.gold_set
        brief_map = self.annotations.get("brief", {})
        covered = {item.requirement_id for item in gold.items if brief_map.get(item.requirement_id, True)}
        critical = {item.requirement_id for item in gold.items if item.importance == "CRITICAL"}

        def solution_requirements(solution: Mapping[str, Any]) -> set[str]:
            values = solution.get("requirements", ())
            return {str(value) for value in values}

        solution_union = set().union(*(solution_requirements(item) for item in self.solutions)) if self.solutions else set()
        all_ids = {item.requirement_id for item in gold.items}
        selected = next(
            (item for item in self.solutions if item.get("id") == self.selected_solution_id),
            {},
        )
        selected_ids = solution_requirements(selected)
        claims = tuple(self.annotations.get("claims", ()))
        supported_claims = sum(1 for claim in claims if claim.get("supported", False))
        factual_claims = sum(1 for claim in claims if claim.get("claim_class") in {"SUPPORTED_FACT", "UNSUPPORTED_FACTUAL_ASSERTION"})
        unsupported = sum(1 for claim in claims if claim.get("claim_class") == "UNSUPPORTED_FACTUAL_ASSERTION")
        decisions = tuple(self.annotations.get("decisions", ()))
        differentiated = sum(1 for decision in decisions if decision.get("meaningfully_differentiated", False))
        inheritance = self.annotations.get("inheritance", {})
        return QualityMetrics(
            brief_critical_requirement_recall=_ratio(len(covered & critical), len(critical)),
            brief_overall_requirement_recall=_ratio(len(covered), len(all_ids)),
            solution_set_recall=_ratio(len(solution_union & all_ids), len(all_ids)),
            solution_set_critical_recall=_ratio(len(solution_union & critical), len(critical)),
            selected_solution_recall=_ratio(len(selected_ids & all_ids), len(all_ids)),
            selected_solution_critical_recall=_ratio(len(selected_ids & critical), len(critical)),
            requirement_alignment_precision=_ratio(len(solution_union & all_ids), len(solution_union)),
            factual_precision=_ratio(supported_claims, factual_claims),
            # With no factual assertions there is no unsupported assertion; the
            # zero-source contract therefore reports a zero rate, not a vacuous 1.
            unsupported_claim_rate=(unsupported / factual_claims if factual_claims else 0.0),
            decision_dimension_coverage=_ratio(differentiated, len(decisions)),
            pairwise_solution_differentiation=_ratio(
                len({tuple(sorted(solution_requirements(item))) for item in self.solutions}), len(self.solutions)
            ),
            solution_to_prd_inheritance=float(inheritance.get("solution_to_prd", 0.0)),
            prd_to_techdoc_inheritance=float(inheritance.get("prd_to_techdoc", 0.0)),
            handoff_decision_binding_accuracy=float(inheritance.get("prd_techdoc_to_handoff", 0.0)),
            critical_contradiction_rate=float(inheritance.get("critical_contradiction_rate", 0.0)),
            llm_judge_is_not_ground_truth=True,
            requirement_recall_is_not_retrieval_recall=True,
        )

    def evidence_fingerprint(self) -> str:
        return hashlib.sha256(f"{self.sample_id}:{self.raw_idea}:{self.provider_decision}".encode()).hexdigest()
