"""Internal execution bounds for evaluation-only provider operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EvaluationStage = Literal["QUICKSTART", "SOLUTIONS"]


@dataclass(frozen=True, slots=True)
class EvaluationExecutionPolicy:
    """One-shot bounds that are unavailable through public product routes."""

    batch_id: str
    sample_id: str
    stage: EvaluationStage
    max_provider_transports: int = 1
    retry_allowed: bool = False
    regeneration_allowed: bool = False
    fallback_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.batch_id.strip() or not self.sample_id.strip():
            raise ValueError("evaluation identity is required")
        if self.stage not in {"QUICKSTART", "SOLUTIONS"}:
            raise ValueError("unsupported evaluation stage")
        if self.max_provider_transports != 1:
            raise ValueError("evaluation execution is limited to one transport")
        if self.retry_allowed or self.regeneration_allowed or self.fallback_allowed:
            raise ValueError("evaluation execution cannot retry, regenerate, or fallback")


@dataclass(slots=True)
class EvaluationTransportGuard:
    """Mutable per-runtime guard; attempted transports are never returned."""

    max_provider_transports: int
    attempted: int = 0

    def before_attempt(self) -> None:
        if self.attempted >= self.max_provider_transports:
            raise RuntimeError("evaluation provider transport limit reached")
        self.attempted += 1
