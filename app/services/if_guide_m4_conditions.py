"""Frozen M4 condition contracts and safe per-session accounting."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class M4ConditionContractError(ValueError):
    """Raised when an experiment condition is not safely reproducible."""


def default_condition_definitions(
    *, source_commit: str = "m4-source", deployment_id: str = "m4-deploy"
) -> dict[str, dict[str, Any]]:
    """Return a complete fixture contract, useful for isolated test environments."""
    return {
        "STATIC_TEMPLATE": {
            "version": "static-v1",
            "content_hash": "static-template-hash-v1",
            "provider_allowed": False,
            "search_allowed": False,
            "max_calls": 0,
            "retry_policy": "none",
            "timeout_seconds": 0,
            "cost_per_call": 0,
        },
        "GENERAL_AI": {
            "version": "general-v1",
            "prompt_version": "prompt-v1",
            "prompt_hash": "prompt-hash-v1",
            "model": "general-model",
            "provider": "fake-provider",
            "schema_version": "schema-v1",
            "schema_hash": "schema-hash-v1",
            "max_calls": 1,
            "retry_policy": "none",
            "timeout_seconds": 30,
            "cost_per_call": 0.01,
            "search_allowed": False,
        },
        "INSIGHTFORGE_STATEFUL": {
            "version": "if-v1",
            "source_commit": source_commit,
            "deployment_id": deployment_id,
            "feature_flags": {},
            "rubric_versions": {"quality": "r1.1-v1"},
            "migration_identity": "if-guide-m4-v1",
            "provider_allowed": False,
            "search_allowed": False,
            "max_calls": 0,
            "retry_policy": "none",
            "timeout_seconds": 0,
            "cost_per_call": 0,
        },
    }


def _required(definition: Mapping[str, Any], field: str) -> Any:
    value = definition.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise M4ConditionContractError(f"GENERAL_AI_CONTRACT_INCOMPLETE:{field}")
    return value


def _non_negative(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise M4ConditionContractError(f"ACCOUNTING_VALUE_INVALID:{field}")
    return float(value)


def validate_condition_definition(
    condition: str,
    definition: Mapping[str, Any],
    *,
    expected_source_commit: str | None = None,
    expected_deployment_id: str | None = None,
    expected_rubric_versions: Mapping[str, Any] | None = None,
) -> None:
    """Validate the frozen metadata without invoking any runtime or network path."""
    if not isinstance(definition, Mapping):
        raise M4ConditionContractError("CONDITION_DEFINITION_INVALID")
    _required(definition, "version")
    if condition == "STATIC_TEMPLATE":
        if definition.get("provider_allowed") is not False or definition.get("search_allowed") is not False:
            raise M4ConditionContractError("STATIC_PROVIDER_OR_SEARCH_POLICY_INVALID")
        if definition.get("max_calls") != 0 or definition.get("cost_per_call") != 0:
            raise M4ConditionContractError("STATIC_ZERO_COST_POLICY_INVALID")
        return
    if condition == "GENERAL_AI":
        for field in (
            "prompt_version", "prompt_hash", "model", "provider", "schema_version",
            "schema_hash", "max_calls", "retry_policy", "timeout_seconds", "cost_per_call",
        ):
            _required(definition, field)
        max_calls = definition["max_calls"]
        if isinstance(max_calls, bool) or not isinstance(max_calls, int) or max_calls <= 0:
            raise M4ConditionContractError("GENERAL_AI_CALL_CAP_INVALID")
        if definition["timeout_seconds"] <= 0 or definition["cost_per_call"] < 0:
            raise M4ConditionContractError("GENERAL_AI_RUNTIME_POLICY_INVALID")
        if definition.get("search_allowed") is not False:
            raise M4ConditionContractError("GENERAL_AI_SEARCH_POLICY_INVALID")
        return
    if condition == "INSIGHTFORGE_STATEFUL":
        for field in ("source_commit", "deployment_id", "feature_flags", "rubric_versions", "migration_identity"):
            _required(definition, field)
        if expected_source_commit is not None and definition["source_commit"] != expected_source_commit:
            raise M4ConditionContractError("IF_SOURCE_BINDING_MISMATCH")
        if expected_deployment_id is not None and definition["deployment_id"] != expected_deployment_id:
            raise M4ConditionContractError("IF_DEPLOYMENT_BINDING_MISMATCH")
        if expected_rubric_versions is not None and dict(definition["rubric_versions"]) != dict(expected_rubric_versions):
            raise M4ConditionContractError("IF_RUBRIC_BINDING_MISMATCH")
        if definition.get("provider_allowed") is not False or definition.get("search_allowed") is not False:
            raise M4ConditionContractError("IF_PROVIDER_OR_SEARCH_POLICY_INVALID")
        if definition.get("max_calls") != 0 or definition.get("cost_per_call") != 0:
            raise M4ConditionContractError("IF_ZERO_COST_POLICY_INVALID")
        return
    raise M4ConditionContractError("CONDITION_UNKNOWN")


def validate_observed_accounting(
    condition: str,
    definition: Mapping[str, Any],
    accounting: Mapping[str, Any] | None = None,
    *,
    provider_calls: int = 0,
    provider_cost: float = 0,
) -> dict[str, float | int]:
    """Validate observed counters; this function never performs a call."""
    values = dict(accounting or {})
    calls = values.pop("provider_calls", provider_calls)
    cost = values.pop("provider_cost", provider_cost)
    search_calls = values.pop("search_calls", 0)
    if isinstance(calls, bool) or not isinstance(calls, int) or calls < 0:
        raise M4ConditionContractError("ACCOUNTING_VALUE_INVALID:provider_calls")
    _non_negative(cost, "provider_cost")
    if isinstance(search_calls, bool) or not isinstance(search_calls, int) or search_calls < 0:
        raise M4ConditionContractError("ACCOUNTING_VALUE_INVALID:search_calls")
    validate_condition_definition(condition, definition)
    if search_calls:
        raise M4ConditionContractError("SEARCH_FORBIDDEN")
    if condition in {"STATIC_TEMPLATE", "INSIGHTFORGE_STATEFUL"} and (calls or cost):
        raise M4ConditionContractError("PROVIDER_FORBIDDEN")
    if condition == "GENERAL_AI" and calls > int(definition["max_calls"]):
        raise M4ConditionContractError("CALL_CAP_EXCEEDED")
    return {"provider_calls": calls, "provider_cost": float(cost), "search_calls": search_calls}

