from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping


class GoldSetNotFinalError(ValueError):
    """The requirement Gold Set has not received idea-provider confirmation."""


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
