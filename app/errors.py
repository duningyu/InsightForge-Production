from __future__ import annotations

from typing import Any


# Public copy is application-owned. Exception and persisted text are not trusted,
# even when stored under an allowlisted key. Tuples keep action templates private.
_OUTPUT_FAILURE = (
    "AI 返回的内容格式不符合要求，本次未生成可用内容；请检查输入和模型配置。",
    ("检查输入和模型配置后重新生成",), False,
)
_PROVIDER_FAILURE = (
    "所选模型暂时无法完成生成；本次未生成可用内容，请稍后重试。",
    ("稍后重试", "检查所选模型配置"), True,
)
_CONFIGURATION_FAILURE = (
    "所选模型的配置或权限无法支持本次生成；本次未生成可用内容。",
    ("检查模型配置和权限", "测试连接后重新生成"), False,
)
_CREDENTIAL_FAILURE = (
    "所选模型的密钥缺失或未通过身份验证；本次未生成可用内容。",
    ("在模型设置中重新填写密钥", "测试连接后重新生成"), False,
)
_GENERATION_FAILURE = (
    "这次生成未能完成，你的项目内容已经保留，请稍后重试。",
    ("重新生成",), True,
)
_PUBLIC_RECOVERY: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "MODEL_OUTPUT_CONTRACT_FAILED": _OUTPUT_FAILURE,
    "PROVIDER_OUTPUT_PARSE_FAILED": _OUTPUT_FAILURE,
    "MODEL_OUTPUT_SCHEMA_INVALID": _OUTPUT_FAILURE,
    "MODEL_PROVIDER_ERROR": _PROVIDER_FAILURE,
    "STRUCTURED_RUNTIME_UNAVAILABLE": _GENERATION_FAILURE,
    "SOLUTION_GENERATION_FAILED": _GENERATION_FAILURE,
    "ASYNC_GENERATION_FAILED": _GENERATION_FAILURE,
    "STAGE_A_FIXTURE_CONTROLLED_FAILURE": (
        "这次方案没有生成成功，你的项目内容已经保留，请重新生成。",
        ("检查项目内容", "点击重新生成"), True,
    ),
    "MODEL_TIMEOUT": (
        "所选模型响应超时；本次未生成可用内容，请稍后重试。", ("稍后重试",), True,
    ),
    "MODEL_RATE_LIMITED": (
        "所选模型当前请求过多；本次未生成可用内容，请稍后重试。", ("稍后重试",), True,
    ),
    "MODEL_NETWORK_ERROR": (
        "当前无法连接所选模型；本次未生成可用内容。", ("检查网络和服务地址", "稍后重试"), True,
    ),
    "MODEL_CREDENTIAL_MISSING": _CREDENTIAL_FAILURE,
    "MODEL_CREDENTIAL_INVALID": _CREDENTIAL_FAILURE,
    "MODEL_UNAUTHORIZED": _CREDENTIAL_FAILURE,
    "MODEL_CONFIGURATION_INVALID": _CONFIGURATION_FAILURE,
    "MODEL_CAPABILITY_UNAVAILABLE": _CONFIGURATION_FAILURE,
    "MODEL_REQUEST_REJECTED": _CONFIGURATION_FAILURE,
    "MODEL_INVALID_REQUEST": _CONFIGURATION_FAILURE,
    "MODEL_UNSUPPORTED_PROTOCOL": _CONFIGURATION_FAILURE,
    "MODEL_DISPATCH_CONTROL_INVALID": _CONFIGURATION_FAILURE,
    "MODEL_STRUCTURED_OUTPUT_UNSUPPORTED": _CONFIGURATION_FAILURE,
    "MODEL_UNSUPPORTED_FEATURE": _CONFIGURATION_FAILURE,
    "MODEL_NOT_FOUND": _CONFIGURATION_FAILURE,
    "MODEL_MODEL_NOT_FOUND": _CONFIGURATION_FAILURE,
    "MODEL_QUOTA_EXHAUSTED": (
        "所选模型额度或余额不足；本次未生成可用内容。", ("补充额度后重新生成", "选择其他模型配置"), False,
    ),
    "CREDENTIAL_BACKEND_UNAVAILABLE": (
        "本机密钥存储暂时不可用；本次未生成可用内容。", ("修复本机凭据存储", "修复后重新测试模型连接"), False,
    ),
    "MODEL_ROUND_LIMIT_REACHED": (
        "模型生成已达到安全轮次上限；系统已停止并保留输入。", ("补充输入后重新生成", "转为人工复核"), False,
    ),
    "LOCAL_GUIDANCE_REQUIRED": (
        "当前本地引导模式没有可安全套用的完整案例；你的输入已保留。", ("补充目标用户与约束", "配置并测试模型后重新生成"), False,
    ),
    "IDEMPOTENCY_MODEL_MISMATCH": (
        "同一生成操作不能切换模型，请点击重新生成。", ("发起新的生成",), False,
    ),
    "SOLUTION_GENERATION_IN_PROGRESS": (
        "正在生成方案，请稍候。", ("等待当前生成完成",), False,
    ),
    "ASYNC_GENERATION_CANCELLED": (
        "任务已停止，项目内容已保留。已发生的模型调用记录仍保留；停止任务不代表远端调用或费用已取消。",
        ("发起新的生成",), False,
    ),
}


def public_recovery_payload(error_code: Any, *, retryable: Any = None) -> dict[str, Any]:
    """Project a closed failure code to trusted copy and conservative retry policy."""
    code = error_code if isinstance(error_code, str) and error_code in _PUBLIC_RECOVERY else "MODEL_OUTPUT_CONTRACT_FAILED"
    message, actions, may_retry = _PUBLIC_RECOVERY[code]
    return {
        "error_code": code,
        "message": message,
        "recovery_actions": list(actions),
        "content_written": False,
        # A stored/producer veto remains binding; legacy True cannot override
        # a typed failure that needs remediation (including schema and cancel).
        "retryable": may_retry and retryable is not False,
    }


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
        self.retryable: bool = public_recovery_payload(error_code)["retryable"]
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

    def as_public_payload(self) -> dict[str, Any]:
        """Return the stable API failure contract without private diagnostics/input."""
        return public_recovery_payload(self.error_code, retryable=self.retryable)


class StructuredOutputContractError(StructuredRuntimeRecoveryError):
    """Structured generation failed before producing a usable domain object."""

    message = "AI 返回的内容格式不符合要求，本次未生成可用内容；请重试。"

    def __init__(
        self, *, preserved_input: Any | None = None,
        safe_diagnostic: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            error_code="MODEL_OUTPUT_CONTRACT_FAILED",
            message=self.message,
            recovery_actions=["重新生成"],
            preserved_input=preserved_input,
            safe_diagnostic=safe_diagnostic,
        )
