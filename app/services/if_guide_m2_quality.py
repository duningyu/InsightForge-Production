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

    status = "PASS" if not codes else "FAIL"
    complete = not any(code.startswith("M2_MISSING_") for code in codes)
    return {
        "status": status,
        "codes": codes,
        "metrics": {
            "scope_recall": 1.0 if complete else 0.0,
            "scope_precision": 1.0 if complete else 0.0,
            "acceptance_coverage": 1.0
            if isinstance(payload.get("acceptance_criteria"), list)
            and bool(payload.get("acceptance_criteria"))
            else 0.0,
            "acceptance_testability": 1.0 if complete else 0.0,
            "constraint_preservation": 1.0 if complete else 0.0,
            "dependency_clarity": 1.0
            if isinstance(payload.get("unknowns"), list)
            and bool(payload.get("unknowns"))
            else 0.0,
            "unsupported_claim_rate": 1.0 if "M2_FALSE_EXECUTION_CLAIM" in codes else 0.0,
        },
    }


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

    status = "PASS" if not codes else "FAIL"
    complete = not any(code.startswith("M2_MISSING_") for code in codes)
    return {
        "status": status,
        "codes": codes,
        "metrics": {
            "scope_recall": 1.0 if complete else 0.0,
            "scope_precision": 1.0 if complete else 0.0,
            "acceptance_coverage": 1.0
            if isinstance(payload.get("acceptance_steps"), list)
            and bool(payload.get("acceptance_steps"))
            else 0.0,
            "acceptance_testability": 1.0 if complete else 0.0,
            "constraint_preservation": 1.0 if complete else 0.0,
            "dependency_clarity": 1.0
            if isinstance(payload.get("unknown_dependencies"), list)
            else 0.0,
            "unsupported_claim_rate": 1.0
            if "M2_FALSE_EXECUTION_CLAIM" in codes
            else 0.0,
        },
    }
