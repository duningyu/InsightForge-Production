"""Deterministic, provider-free quality gates for IF Guide R1.1 M2."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any


REQUIRED_BUILD_SLICE_FIELDS = (
    "in_scope",
    "out_of_scope",
    "minimal_flow",
    "acceptance_criteria",
    "inputs",
    "expected_outputs",
    "error_handling",
    "unknowns",
)

REQUIRED_PROTOTYPE_TASK_FIELDS = (
    "scope",
    "inputs",
    "outputs",
    "existing_behaviors_to_preserve",
    "explicit_non_goals",
    "known_technical_context",
    "unknown_dependencies",
    "implementation_tasks",
    "acceptance_steps",
    "failure_recovery_notes",
    "required_return_evidence",
    "permission_risk_notes",
)

# These expressions identify claims that read as already-executed outcomes.
# A future acceptance step may describe an action (for example, "运行测试"),
# but it must not be presented as evidence that the action already happened.
_FALSE_EXECUTION_CLAIM = re.compile(
    r"(?:已(?:经)?(?:部署|测试|执行|上线|完成)|已经部署|已经测试|"
    r"(?:was|is|has been)\s+(?:deployed|tested|executed|completed)|"
    r"production[- ]ready)",
    re.IGNORECASE,
)

_FORBIDDEN_EXTERNAL_ACTION = re.compile(
    r"(?:自动|直接|无需确认|无须确认)?(?:部署|发布|上线|写入\s*github|推送\s*github|"
    r"执行终端|terminal\s+execution|正式\s*handoff|export\s+handoff|"
    r"发送外部请求|external\s+(?:write|request|action))",
    re.IGNORECASE,
)

_M2_RUBRIC_VERSION = "if-guide-m2-quality-v1"
_FACTUAL_CLAIM_CLASSES = {
    "SUPPORTED_FACT",
    "USER_INPUT",
    "UNVERIFIED_CLAIM",
    "UNSUPPORTED_FACTUAL_ASSERTION",
}


def _flatten(values: Iterable[Any]) -> list[str]:
    flattened: list[str] = []
    for value in values:
        if isinstance(value, str):
            flattened.append(value)
        elif isinstance(value, Mapping):
            flattened.extend(_flatten(value.values()))
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
            flattened.extend(_flatten(value))
    return flattened


def _as_ids(value: Any) -> list[str]:
    """Return stable, non-empty item identifiers without copying item text."""
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _ratio_detail(numerator: int, denominator: int, item_ids: Iterable[str]) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "item_ids": list(item_ids),
    }


def _m2_quality_rubric(
    payload: Mapping[str, Any], *, artifact_kind: str, complete: bool, false_execution_claim: bool,
) -> tuple[dict[str, float], dict[str, dict[str, Any]], list[str], str, list[str]]:
    """Compute M2 P1 metrics from explicit safe rubric identifiers.

    The fallback keeps pre-rubric M2 records compatible while a supplied rubric
    is evaluated by exact numerator/denominator semantics.  Text itself is
    never copied into metric evidence; only stable evidence/item identifiers
    are returned.
    """
    rubric = payload.get("quality_rubric")
    if not isinstance(rubric, Mapping):
        acceptance_field = "acceptance_criteria" if artifact_kind == "BUILD_SLICE" else "acceptance_steps"
        dependency_field = "unknowns" if artifact_kind == "BUILD_SLICE" else "unknown_dependencies"
        metrics = {
            "scope_recall": 1.0 if complete else 0.0,
            "scope_precision": 1.0 if complete else 0.0,
            "acceptance_coverage": 1.0 if isinstance(payload.get(acceptance_field), list) and payload.get(acceptance_field) else 0.0,
            "acceptance_testability": 1.0 if complete else 0.0,
            "constraint_preservation": 1.0 if complete else 0.0,
            "dependency_clarity": 1.0 if isinstance(payload.get(dependency_field), list) and payload.get(dependency_field) else 0.0,
            "unsupported_claim_rate": 1.0 if false_execution_claim else 0.0,
        }
        details = {
            name: _ratio_detail(int(value > 0), 1, ()) for name, value in metrics.items()
        }
        details["unsupported_claim_rate"] = _ratio_detail(
            int(false_execution_claim), 1 if false_execution_claim else 0, ()
        )
        return metrics, details, [], _M2_RUBRIC_VERSION, []

    rubric_version = rubric.get("rubric_version", _M2_RUBRIC_VERSION)
    if not isinstance(rubric_version, str) or not rubric_version.strip():
        rubric_version = _M2_RUBRIC_VERSION
    evidence_ids = _as_ids(rubric.get("evidence_ids"))
    codes: list[str] = []

    scope = rubric.get("scope")
    scope = scope if isinstance(scope, Mapping) else {}
    confirmed_scope = set(_as_ids(scope.get("confirmed_item_ids")))
    represented_scope = set(_as_ids(scope.get("represented_item_ids")))
    task_scope = set(_as_ids(scope.get("task_item_ids")))
    scope_recall_ids = sorted(confirmed_scope & represented_scope)
    scope_precision_ids = sorted(task_scope & confirmed_scope)
    scope_recall_denominator = len(confirmed_scope)
    scope_precision_denominator = len(task_scope)

    critical_items = set(_as_ids(rubric.get("critical_build_item_ids")))
    covered_items = set(_as_ids(rubric.get("covered_acceptance_item_ids")))
    acceptance_ids = sorted(critical_items & covered_items)

    testability_items = rubric.get("acceptance_testability")
    testability_items = testability_items if isinstance(testability_items, list) else []
    testable_ids: list[str] = []
    for item in testability_items:
        if not isinstance(item, Mapping) or not isinstance(item.get("id"), str):
            continue
        if all(isinstance(item.get(key), str) and item[key].strip() for key in (
            "precondition", "action", "expected_result", "failure_interpretation"
        )):
            testable_ids.append(item["id"].strip())

    constraints = rubric.get("constraints")
    constraints = constraints if isinstance(constraints, Mapping) else {}
    required_constraints = set(_as_ids(constraints.get("required_ids")))
    preserved_constraints = set(_as_ids(constraints.get("preserved_ids")))
    contradicted_constraints = set(_as_ids(constraints.get("contradicted_ids")))
    preserved_ids = sorted((preserved_constraints - contradicted_constraints) & required_constraints)

    dependencies = rubric.get("dependencies")
    dependencies = dependencies if isinstance(dependencies, list) else []
    clear_dependency_ids: list[str] = []
    for dependency in dependencies:
        if not isinstance(dependency, Mapping) or not isinstance(dependency.get("id"), str):
            continue
        dependency_id = dependency["id"].strip()
        status = dependency.get("status")
        if status == "UNKNOWN":
            clear_dependency_ids.append(dependency_id)
        elif status == "KNOWN" and dependency.get("verified") is True:
            clear_dependency_ids.append(dependency_id)
        elif status == "KNOWN":
            codes.append("M2_FABRICATED_DEPENDENCY_MARKED_VERIFIED")

    claims = rubric.get("claims")
    claims = claims if isinstance(claims, list) else []
    factual_ids: list[str] = []
    unsupported_ids: list[str] = []
    for claim in claims:
        if not isinstance(claim, Mapping) or claim.get("presented_as_fact") is not True:
            continue
        claim_id = claim.get("id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            continue
        claim_id = claim_id.strip()
        if claim.get("class") in _FACTUAL_CLAIM_CLASSES:
            factual_ids.append(claim_id)
        if claim.get("class") == "UNSUPPORTED_FACTUAL_ASSERTION":
            unsupported_ids.append(claim_id)

    metrics = {
        "scope_recall": len(scope_recall_ids) / scope_recall_denominator if scope_recall_denominator else 0.0,
        "scope_precision": len(scope_precision_ids) / scope_precision_denominator if scope_precision_denominator else 0.0,
        "acceptance_coverage": len(acceptance_ids) / len(critical_items) if critical_items else 0.0,
        "acceptance_testability": len(testable_ids) / len(testability_items) if testability_items else 0.0,
        "constraint_preservation": len(preserved_ids) / len(required_constraints) if required_constraints else 0.0,
        "dependency_clarity": len(clear_dependency_ids) / len(dependencies) if dependencies else 0.0,
        "unsupported_claim_rate": len(unsupported_ids) / len(factual_ids) if factual_ids else 0.0,
    }
    details = {
        "scope_recall": _ratio_detail(len(scope_recall_ids), scope_recall_denominator, sorted(scope_recall_ids)),
        "scope_precision": _ratio_detail(len(scope_precision_ids), scope_precision_denominator, sorted(scope_precision_ids)),
        "acceptance_coverage": _ratio_detail(len(acceptance_ids), len(critical_items), acceptance_ids),
        "acceptance_testability": _ratio_detail(len(testable_ids), len(testability_items), sorted(testable_ids)),
        "constraint_preservation": _ratio_detail(len(preserved_ids), len(required_constraints), preserved_ids),
        "dependency_clarity": _ratio_detail(len(clear_dependency_ids), len(dependencies), sorted(clear_dependency_ids)),
        "unsupported_claim_rate": _ratio_detail(len(unsupported_ids), len(factual_ids), sorted(unsupported_ids)),
    }
    return metrics, details, codes, rubric_version, evidence_ids


def _quality_result(
    *, codes: list[str], metrics: dict[str, float], metric_details: dict[str, dict[str, Any]],
    rubric_version: str, evidence_ids: list[str], artifact_kind: str,
) -> dict[str, Any]:
    return {
        "status": "PASS" if not codes else "FAIL",
        "codes": codes,
        "metrics": metrics,
        "metric_details": metric_details,
        "rubric_version": rubric_version,
        "evidence_ids": evidence_ids,
        "evidence_kind": "M2_SEMANTIC_CONTENT",
        "artifact_kind": artifact_kind,
    }


def evaluate_build_slice(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable P0 codes and the M2 metric shape without side effects."""
    codes: list[str] = []
    for field in REQUIRED_BUILD_SLICE_FIELDS:
        value = payload.get(field)
        if not isinstance(value, list) or not value or not any(
            isinstance(item, str) and item.strip() for item in value
        ):
            codes.append(f"M2_MISSING_{field.upper()}")

    all_text = _flatten(payload.values())
    if any(_FALSE_EXECUTION_CLAIM.search(text) for text in all_text):
        codes.append("M2_FALSE_EXECUTION_CLAIM")

    complete = not any(code.startswith("M2_MISSING_") for code in codes)
    metrics, details, rubric_codes, rubric_version, evidence_ids = _m2_quality_rubric(
        payload,
        artifact_kind="BUILD_SLICE",
        complete=complete,
        false_execution_claim="M2_FALSE_EXECUTION_CLAIM" in codes,
    )
    codes.extend(rubric_codes)
    return _quality_result(
        codes=codes,
        metrics=metrics,
        metric_details=details,
        rubric_version=rubric_version,
        evidence_ids=evidence_ids,
        artifact_kind="BUILD_SLICE",
    )


def evaluate_prototype_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a Prototype Task without treating its instructions as execution evidence."""
    codes: list[str] = []
    for field in REQUIRED_PROTOTYPE_TASK_FIELDS:
        value = payload.get(field)
        if not isinstance(value, list) or not value or not any(
            isinstance(item, str) and item.strip() for item in value
        ):
            codes.append(f"M2_MISSING_{field.upper()}")

    # Only inspect fields that describe required work or observable checks.
    # Explicit non-goals and permission notes are allowed to mention actions
    # that are deliberately forbidden in M2.
    action_text = _flatten(
        payload.get(field, [])
        for field in ("implementation_tasks", "acceptance_steps", "required_return_evidence")
    )
    if any(_FORBIDDEN_EXTERNAL_ACTION.search(text) for text in action_text):
        codes.append("M2_FORBIDDEN_EXTERNAL_ACTION")
    all_text = _flatten(payload.values())
    if any(_FALSE_EXECUTION_CLAIM.search(text) for text in all_text):
        codes.append("M2_FALSE_EXECUTION_CLAIM")

    complete = not any(code.startswith("M2_MISSING_") for code in codes)
    metrics, details, rubric_codes, rubric_version, evidence_ids = _m2_quality_rubric(
        payload,
        artifact_kind="PROTOTYPE_TASK",
        complete=complete,
        false_execution_claim="M2_FALSE_EXECUTION_CLAIM" in codes,
    )
    codes.extend(rubric_codes)
    return _quality_result(
        codes=codes,
        metrics=metrics,
        metric_details=details,
        rubric_version=rubric_version,
        evidence_ids=evidence_ids,
        artifact_kind="PROTOTYPE_TASK",
    )
