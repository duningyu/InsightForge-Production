"""Validated, durable context for strict acceptance dispatch control."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DispatchControlContext:
    acceptance_execution_id: str
    forward_ledger_epoch_id: str
    beta_instance: str
    expected_provider: str
    expected_model: str
    dispatch_ordinal: int = 1
    strict_at_most_once: bool = True
    acceptance_window_id: str | None = None
    quota_scope: str = "acceptance"

    def validate(self, *, provider: str, model: str, base_url: str | None = None) -> None:
        if not self.strict_at_most_once:
            raise ValueError("STRICT_DISPATCH_CONTROL_REQUIRED")
        if self.dispatch_ordinal != 1:
            raise ValueError("INVALID_DISPATCH_ORDINAL")
        if self.beta_instance != "beta001":
            raise ValueError("INVALID_ACCEPTANCE_INSTANCE")
        if (self.expected_provider, self.expected_model) != ("bailian", "qwen3.7-flash"):
            raise ValueError("INVALID_ACCEPTANCE_TARGET")
        wire_provider_matches_bailian = (
            self.expected_provider == "bailian"
            and provider == "qwen"
            and self.expected_model == "qwen3.7-flash"
            and (base_url is None or base_url.rstrip("/") == "https://dashscope.aliyuncs.com/compatible-mode/v1")
        )
        if (provider, model) != (self.expected_provider, self.expected_model) and not wire_provider_matches_bailian:
            raise ValueError("DISPATCH_TARGET_MISMATCH")

    @property
    def window_id(self) -> str:
        return self.acceptance_window_id or self.forward_ledger_epoch_id

    @property
    def authorization_reference(self) -> str:
        return "sha256:" + hashlib.sha256(self.acceptance_execution_id.encode()).hexdigest()[:32]
