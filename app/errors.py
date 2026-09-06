from __future__ import annotations

from typing import Any


class BetaDailyLimitReached(RuntimeError):
    """A participant exhausted one daily closed-beta AI operation budget."""

    message = "该类 Beta AI 操作的今日额度已达到测试上限；其他操作额度不受影响。"

    def __init__(
        self,
        *,
        operation: str,
        limit: int,
        used: int,
        reset_at: str,
    ) -> None:
        self.operation = operation
        self.limit = limit
        self.used = used
        self.reset_at = reset_at
        super().__init__("BETA_DAILY_LIMIT_REACHED")

    def as_payload(self) -> dict[str, Any]:
        return {
            "error_code": "BETA_DAILY_LIMIT_REACHED",
            "operation": self.operation,
            "limit": self.limit,
            "used": self.used,
            "remaining": max(self.limit - self.used, 0),
            "operation_type": self.operation,
            "blocked_operation": self.operation,
            "reset_at": self.reset_at,
            "message": self.message,
        }


class ConflictError(RuntimeError):
    """The requested write conflicts with the current immutable/versioned state."""


class DraftConflictError(ConflictError):
    """A draft write was based on an older server revision."""

    def __init__(self, latest: dict[str, Any]):
        self.latest = latest
        super().__init__("DRAFT_CONFLICT")


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
        safe_diagnostic: dict[str, Any] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.recovery_actions = list(recovery_actions)
        self.preserved_input = preserved_input
        self.safe_diagnostic = dict(safe_diagnostic or {})
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
