"""RED contract tests for the Managed Multi-Model V1 boundary.

These tests intentionally describe the additive contract before production
implementation. They use no network and no credentials.
"""

import pytest

from app.services.managed_models import (
    ManagedModelPreference,
    ManagedModelRegistry,
    ManagedModelRouter,
)


def test_registry_contains_only_approved_managed_models():
    registry = ManagedModelRegistry(default_model_id="qwen3.7-flash")

    assert registry.resolve(ManagedModelPreference.AUTO).model_id == "qwen3.7-flash"
    assert registry.resolve(ManagedModelPreference.QWEN).model_id == "qwen3.7-flash"
    assert registry.resolve(ManagedModelPreference.GLM).model_id == "glm-5.2"
    assert registry.resolve(ManagedModelPreference.DEEPSEEK).model_id == "deepseek-v4-flash-0731"
    assert all(item.route == "bailian" for item in registry.list())


def test_registry_rejects_unknown_preference_without_fallback():
    registry = ManagedModelRegistry(default_model_id="qwen3.7-flash")

    with pytest.raises(ValueError, match="UNKNOWN_MANAGED_MODEL"):
        registry.resolve("anthropic")


def test_router_freezes_one_selection_for_solutions():
    router = ManagedModelRouter(ManagedModelRegistry(default_model_id="qwen3.7-flash"))

    selection = router.resolve_for_operation("solutions", "GLM")

    assert selection.preference == ManagedModelPreference.GLM
    assert selection.family == "glm"
    assert selection.model_id == "glm-5.2"
    assert selection.operation == "solutions"


def test_router_does_not_claim_other_operations_are_multi_model():
    router = ManagedModelRouter(ManagedModelRegistry(default_model_id="qwen3.7-flash"))

    with pytest.raises(ValueError, match="MANAGED_MODEL_OPERATION_UNSUPPORTED"):
        router.resolve_for_operation("prd", "GLM")
