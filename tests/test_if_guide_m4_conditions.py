from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4_conditions import (
    M4ConditionContractError,
    default_condition_definitions,
    validate_condition_definition,
    validate_observed_accounting,
)


def test_static_and_insightforge_conditions_are_provider_and_search_free():
    definitions = default_condition_definitions(
        source_commit="source-v1", deployment_id="deploy-v1"
    )
    for condition in ("STATIC_TEMPLATE", "INSIGHTFORGE_STATEFUL"):
        validate_condition_definition(condition, definitions[condition])
        with pytest.raises(M4ConditionContractError, match="PROVIDER_FORBIDDEN"):
            validate_observed_accounting(condition, definitions[condition], provider_calls=1)
        with pytest.raises(M4ConditionContractError, match="SEARCH_FORBIDDEN"):
            validate_observed_accounting(
                condition, definitions[condition], accounting={"search_calls": 1}
            )


def test_general_ai_requires_frozen_call_and_cost_contract():
    definition = default_condition_definitions()["GENERAL_AI"]
    validate_condition_definition("GENERAL_AI", definition)
    for field in ("prompt_hash", "schema_hash", "max_calls", "retry_policy", "timeout_seconds", "cost_per_call"):
        incomplete = dict(definition)
        incomplete.pop(field)
        with pytest.raises(M4ConditionContractError, match="GENERAL_AI_CONTRACT_INCOMPLETE"):
            validate_condition_definition("GENERAL_AI", incomplete)
    with pytest.raises(M4ConditionContractError, match="CALL_CAP_EXCEEDED"):
        validate_observed_accounting("GENERAL_AI", definition, provider_calls=2)


def test_insightforge_condition_requires_exact_frozen_bindings():
    definition = default_condition_definitions(
        source_commit="source-v1", deployment_id="deploy-v1"
    )["INSIGHTFORGE_STATEFUL"]
    broken_source = {**definition, "source_commit": "other-source"}
    with pytest.raises(M4ConditionContractError, match="IF_SOURCE_BINDING_MISMATCH"):
        validate_condition_definition("INSIGHTFORGE_STATEFUL", broken_source, expected_source_commit="source-v1")
    broken_rubric = {**definition, "rubric_versions": {"quality": "old"}}
    with pytest.raises(M4ConditionContractError, match="IF_RUBRIC_BINDING_MISMATCH"):
        validate_condition_definition(
            "INSIGHTFORGE_STATEFUL",
            broken_rubric,
            expected_rubric_versions={"quality": "r1.1-v1"},
        )


def test_invalid_observed_accounting_is_rejected():
    definition = default_condition_definitions()["GENERAL_AI"]
    with pytest.raises(M4ConditionContractError, match="ACCOUNTING_VALUE_INVALID"):
        validate_observed_accounting("GENERAL_AI", definition, provider_cost=-1)
