"""Managed Pilot model registry and operation router.

This module is deliberately provider-agnostic at the UI boundary.  The
registry is the single source of truth for the models exposed by Managed
Pilot; runtime adapters consume the resolved selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class ManagedModelPreference(str, Enum):
    AUTO = "AUTO"
    QWEN = "QWEN"
    GLM = "GLM"
    DEEPSEEK = "DEEPSEEK"


@dataclass(frozen=True)
class ManagedModelSelection:
    preference: ManagedModelPreference
    family: str
    model_id: str
    route: str
    operation: str


class ManagedModelRegistry:
    """Registry for the small, explicitly approved Managed Pilot surface."""

    def __init__(self, default_model_id: str = "qwen3.7-flash") -> None:
        self.default_model_id = default_model_id
        self._models: Dict[ManagedModelPreference, tuple[str, str]] = {
            ManagedModelPreference.QWEN: ("qwen", "qwen3.7-flash"),
            ManagedModelPreference.GLM: ("glm", "glm-5.2"),
            ManagedModelPreference.DEEPSEEK: ("deepseek", "deepseek-v4-flash-0731"),
        }

    @staticmethod
    def normalize_preference(value: object) -> ManagedModelPreference:
        if value is None or value == "":
            return ManagedModelPreference.AUTO
        if isinstance(value, ManagedModelPreference):
            return value
        try:
            return ManagedModelPreference(str(value).strip().upper())
        except ValueError as exc:
            raise ValueError("UNKNOWN_MANAGED_MODEL") from exc

    def resolve(self, preference: object = ManagedModelPreference.AUTO) -> ManagedModelSelection:
        normalized = self.normalize_preference(preference)
        if normalized is ManagedModelPreference.AUTO:
            model_id = self.default_model_id
            for family, candidate_id in self._models.values():
                if candidate_id == model_id:
                    return ManagedModelSelection(normalized, family, candidate_id, "bailian", "")
            raise ValueError("UNKNOWN_MANAGED_MODEL")
        family, model_id = self._models[normalized]
        return ManagedModelSelection(normalized, family, model_id, "bailian", "")

    def list_models(self) -> List[ManagedModelSelection]:
        return [
            ManagedModelSelection(preference, family, model_id, "bailian", "")
            for preference, (family, model_id) in self._models.items()
        ]

    # Compatibility alias for callers/tests that treat the registry as a
    # collection.  Keep list_models as the descriptive public API.
    def list(self) -> List[ManagedModelSelection]:
        return self.list_models()


class ManagedModelRouter:
    """Resolve registry selections only for operations currently supported."""

    SUPPORTED_OPERATIONS = frozenset({"solutions"})

    def __init__(self, registry: ManagedModelRegistry | None = None) -> None:
        self.registry = registry or ManagedModelRegistry()

    def resolve_for_operation(self, operation: str, preference: object = None) -> ManagedModelSelection:
        normalized_operation = str(operation).strip().lower()
        if normalized_operation not in self.SUPPORTED_OPERATIONS:
            raise ValueError("MANAGED_MODEL_OPERATION_UNSUPPORTED")
        selection = self.registry.resolve(preference)
        return ManagedModelSelection(
            selection.preference,
            selection.family,
            selection.model_id,
            selection.route,
            normalized_operation,
        )
