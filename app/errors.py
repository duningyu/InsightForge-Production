from __future__ import annotations

from typing import Any


class ConflictError(RuntimeError):
    """The requested write conflicts with the current immutable/versioned state."""


class StructuredRuntimeUnavailableError(RuntimeError):
    """The requested structured AI runtime cannot safely serve this request."""


class StructuredRuntimeRecoveryError(StructuredRuntimeUnavailableError):
    """A safe, user-actionable generation failure with no provider diagnostics."""

    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        recovery_actions: list[str],
        preserved_input: Any | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.recovery_actions = list(recovery_actions)
        self.preserved_input = preserved_input
        super().__init__(error_code)

    def as_payload(self, *, preserved_input: Any | None = None) -> dict[str, Any]:
        value = self.preserved_input if preserved_input is None else preserved_input
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return {
            "error_code": self.error_code,
            "message": self.message,
            "recovery_actions": list(self.recovery_actions),
            "preserved_input": value,
        }
