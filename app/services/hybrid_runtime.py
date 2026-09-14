"""Per-request structured runtime resolution with bounded, safe recovery."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from app.errors import (
    StructuredRuntimeRecoveryError,
    StructuredRuntimeUnavailableError,
)
from app.schemas import (
    AIReferenceDraft,
    CompetitorComparisonDraft,
    EvidenceGuidanceDraft,
    EvidenceRelationSetDraft,
    IdeaBriefDraft,
    QuickStartRequest,
    SolutionSetDraft,
)
from app.services.ai_runtime import StructuredAIRuntime
from app.services.credential_store import CredentialBackendUnavailable
from app.services.evaluation_policy import EvaluationExecutionPolicy, EvaluationTransportGuard
from app.services.model_profiles import ModelProfileService
from app.services.provider_adapters import ModelAdapter, ProviderCallError


AdapterFactory = Callable[..., ModelAdapter]
BeforeProviderCall = Callable[[str], Any]
AfterProviderFailure = Callable[[str, Any], Any]
PROVIDER_USAGE_OPERATIONS = {
    "design_solutions": "solution_generation",
    "analyze_evidence": "evidence_analysis",
    "compare_competitors": "solution_generation",
    "generate_ai_reference": "solution_generation",
    "generate_evidence_guidance": "evidence_analysis",
}
SCHEMA_ERROR_CODES = {
    "invalid_content",
    "malformed_response",
    "structured_output_unsupported",
    "unsupported_feature",
}


def _input_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def _recovery_for_provider_error(
    error: ProviderCallError,
    *,
    preserved_input: Any,
) -> StructuredRuntimeRecoveryError:
    mapping: dict[str, tuple[str, str, list[str]]] = {
        "unauthorized": (
            "MODEL_CREDENTIAL_INVALID",
            "模型服务未能通过身份验证；你的输入已保留。",
            ["在模型设置中重新填写密钥", "测试连接后重试"],
        ),
        "quota_exhausted": (
            "MODEL_QUOTA_EXHAUSTED",
            "所选模型额度或余额不足；你的输入已保留。",
            ["补充额度后重试", "明确选择其他模型配置", "使用本地引导继续梳理"],
        ),
        "model_not_found": (
            "MODEL_NOT_FOUND",
            "所选模型不存在或当前账号无权使用；你的输入已保留。",
            ["检查模型 ID", "明确选择已验证的模型配置"],
        ),
        "rate_limited": (
            "MODEL_RATE_LIMITED",
            "所选模型当前请求过多；系统已停止重试并保留输入。",
            ["稍后重试", "使用本地引导继续梳理"],
        ),
        "timeout": (
            "MODEL_TIMEOUT",
            "所选模型响应超时；系统已停止重试并保留输入。",
            ["检查网络后重试", "使用本地引导继续梳理"],
        ),
        "network_error": (
            "MODEL_NETWORK_ERROR",
            "当前无法连接所选模型；你的输入已保留。",
            ["检查网络和服务地址", "稍后重试", "使用本地引导继续梳理"],
        ),
        "invalid_request": (
            "MODEL_REQUEST_REJECTED",
            "所选模型拒绝了结构化生成请求；你的输入已保留。",
            ["测试模型能力", "检查模型配置"],
        ),
    }
    if error.code in SCHEMA_ERROR_CODES:
        code, message, actions = (
            "MODEL_OUTPUT_SCHEMA_INVALID",
            "模型连续返回不完整或格式无效的结果，系统未保存伪造的完整结果。",
            ["补充 Idea 细节后重试", "检查模型的结构化输出能力", "使用本地引导继续梳理"],
        )
    else:
        code, message, actions = mapping.get(
            error.code,
            (
                "MODEL_PROVIDER_ERROR",
                "所选模型暂时无法完成生成；你的输入已保留。",
                ["稍后重试", "检查所选模型配置", "使用本地引导继续梳理"],
            ),
        )
    return StructuredRuntimeRecoveryError(
        error_code=code,
        message=message,
        recovery_actions=actions,
        preserved_input=_input_payload(preserved_input),
        safe_diagnostic=error.safe_diagnostic,
    )


class _LocalGuidanceRuntime:
    """Keep frozen cases exact and turn unsupported inputs into honest guidance."""

    def __init__(
        self,
        runtime: StructuredAIRuntime,
        *,
        max_model_rounds: int,
        max_tool_rounds: int,
    ) -> None:
        self._runtime = runtime
        self.mode = runtime.mode
        self.provider = runtime.provider
        self.model = runtime.model
        self.prompt_version = runtime.prompt_version
        self.schema_version = runtime.schema_version
        self.max_model_rounds = max_model_rounds
        self.max_tool_rounds = max_tool_rounds
        self.model_rounds_used = 0

    def _consume_round(self, preserved_input: Any) -> None:
        if self.model_rounds_used >= self.max_model_rounds:
            raise StructuredRuntimeRecoveryError(
                error_code="MODEL_ROUND_LIMIT_REACHED",
                message="本地引导已达到安全轮次上限；系统已停止并保留输入。",
                recovery_actions=["补充输入后重试", "转为人工复核"],
                preserved_input=_input_payload(preserved_input),
            )
        self.model_rounds_used += 1

    def _call(self, method: str, value: Any) -> Any:
        self._consume_round(value)
        try:
            return getattr(self._runtime, method)(value)
        except StructuredRuntimeUnavailableError:
            raise StructuredRuntimeRecoveryError(
                error_code="LOCAL_GUIDANCE_REQUIRED",
                message="当前本地引导模式没有可安全套用的完整案例；你的输入已保留。",
                recovery_actions=["补充目标用户与约束", "配置并测试模型后重试"],
                preserved_input=_input_payload(value),
            ) from None

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return self._call("interpret_idea", request)

    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        return self._call("design_solutions", brief)

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None
    ) -> CompetitorComparisonDraft:
        self._consume_round(candidates)
        try:
            return self._runtime.compare_competitors(candidates, project_context=project_context)
        except StructuredRuntimeUnavailableError:
            raise StructuredRuntimeRecoveryError(
                error_code="LOCAL_GUIDANCE_REQUIRED",
                message="当前本地引导模式没有可安全套用的竞品比较案例。",
                recovery_actions=["补充候选产品信息", "配置并测试模型后重试"],
                preserved_input=candidates,
            ) from None

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        preserved_input = {"claim": claim, "chunks": chunks}
        self._consume_round(preserved_input)
        try:
            return self._runtime.analyze_evidence(claim=claim, chunks=chunks)
        except StructuredRuntimeUnavailableError:
            raise StructuredRuntimeRecoveryError(
                error_code="LOCAL_GUIDANCE_REQUIRED",
                message="当前本地引导模式没有可安全套用的证据分析案例。",
                recovery_actions=["配置并测试模型后重试", "改用人工证据复核"],
                preserved_input=preserved_input,
            ) from None

    def generate_ai_reference(self, context: dict[str, Any], *, evaluation_context: Any | None = None) -> AIReferenceDraft:
        return self._call("generate_ai_reference", context)

    def generate_evidence_guidance(self, context: dict[str, Any]) -> EvidenceGuidanceDraft:
        return self._call("generate_evidence_guidance", context)


class _ProfileStructuredRuntime:
    mode = "llm_structured"
    prompt_version = "hybrid-structured-v1"
    schema_version = "v3-p0-1"

    def __init__(
        self,
        *,
        profile: dict[str, Any],
        profile_service: ModelProfileService,
        adapter_factory: AdapterFactory,
        max_model_rounds: int,
        max_tool_rounds: int,
        before_provider_call: BeforeProviderCall | None = None,
        after_provider_failure: AfterProviderFailure | None = None,
        after_provider_success: Callable[[str, Any], Any] | None = None,
        evaluation_policy: EvaluationExecutionPolicy | None = None,
    ) -> None:
        self.provider = profile["provider"]
        self.model = profile["model_id"]
        self.profile_id = profile["id"]
        self.profile_revision = profile["revision"]
        self._profile = profile
        self._profile_service = profile_service
        self._adapter_factory = adapter_factory
        self.evaluation_policy = evaluation_policy
        self.max_model_rounds = 1 if evaluation_policy is not None else max_model_rounds
        self.max_tool_rounds = max_tool_rounds
        self.model_rounds_used = 0
        self._before_provider_call = before_provider_call
        self._after_provider_failure = after_provider_failure
        self._after_provider_success = after_provider_success
        self._pending_reservation: tuple[str, Any] | None = None
        self._transport_guard = (
            EvaluationTransportGuard(evaluation_policy.max_provider_transports)
            if evaluation_policy is not None
            else None
        )

    @property
    def provider_transport_attempts(self) -> int:
        """Return the locally observed provider transport attempts."""

        return self._transport_guard.attempted if self._transport_guard is not None else 0

    def _remember_reservation(self, operation: str | None, reservation: Any) -> None:
        if operation is not None and reservation is not None:
            self._pending_reservation = (operation, reservation)

    def _release_reservation(self, operation: str | None, reservation: Any) -> None:
        if operation is not None and self._after_provider_failure is not None:
            self._after_provider_failure(operation, reservation)
        if self._pending_reservation is not None and self._pending_reservation[1] is reservation:
            self._pending_reservation = None

    def commit_current_reservation(self) -> None:
        pending = self._pending_reservation
        if pending is not None and self._after_provider_success is not None:
            self._after_provider_success(*pending)
        self._pending_reservation = None

    def release_current_reservation(self) -> None:
        pending = self._pending_reservation
        if pending is not None:
            self._release_reservation(*pending)

    def _credential(self, preserved_input: Any) -> str:
        credential_ref = self._profile.get("credential_ref")
        if not credential_ref:
            raise StructuredRuntimeRecoveryError(
                error_code="MODEL_CREDENTIAL_MISSING",
                message="所选模型尚未配置密钥；你的输入已保留。",
                recovery_actions=["在模型设置中填写密钥", "测试连接后重试"],
                preserved_input=_input_payload(preserved_input),
            )
        try:
            return self._profile_service.credential_store.resolve(credential_ref)
        except KeyError:
            raise StructuredRuntimeRecoveryError(
                error_code="MODEL_CREDENTIAL_MISSING",
                message="所选模型的密钥已失效或缺失；你的输入已保留。",
                recovery_actions=["重新填写密钥", "测试连接后重试"],
                preserved_input=_input_payload(preserved_input),
            ) from None
        except CredentialBackendUnavailable:
            raise StructuredRuntimeRecoveryError(
                error_code="CREDENTIAL_BACKEND_UNAVAILABLE",
                message="本机密钥存储暂时不可用；你的输入已保留。",
                recovery_actions=["修复本机凭据存储", "修复后重新测试模型连接"],
                preserved_input=_input_payload(preserved_input),
            ) from None

    def _call(
        self,
        method: str,
        *,
        preserved_input: Any,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        if self._transport_guard is not None and self._transport_guard.attempted >= self._transport_guard.max_provider_transports:
            raise StructuredRuntimeRecoveryError(
                error_code="EVALUATION_TRANSPORT_LIMIT_REACHED",
                message="评估 Provider transport 已达到安全上限；系统已停止。",
                recovery_actions=["转为人工复核"],
                preserved_input=_input_payload(preserved_input),
            )
        api_key = self._credential(preserved_input)
        try:
            adapter = self._adapter_factory(
                provider=self._profile["provider"],
                protocol=self._profile["protocol"],
                base_url=self._profile["base_url"],
                model=self._profile["model_id"],
                api_key=api_key,
            )
        except Exception:
            raise StructuredRuntimeRecoveryError(
                error_code="MODEL_CONFIGURATION_INVALID",
                message="所选模型配置无法初始化；你的输入已保留。",
                recovery_actions=["检查服务商、协议、地址和模型 ID", "重新测试连接"],
                preserved_input=_input_payload(preserved_input),
            ) from None
        try:
            adapter_method = getattr(adapter, method, None)
            if adapter_method is None:
                raise StructuredRuntimeRecoveryError(
                    error_code="MODEL_CAPABILITY_UNAVAILABLE",
                    message="所选模型适配器不支持当前操作；系统未生成替代结论。",
                    recovery_actions=["改用人工复核", "选择支持该能力的模型配置"],
                    preserved_input=_input_payload(preserved_input),
                )
            while self.model_rounds_used < self.max_model_rounds:
                self.model_rounds_used += 1
                operation = PROVIDER_USAGE_OPERATIONS.get(method)
                reservation = None
                if self._transport_guard is not None:
                    try:
                        self._transport_guard.before_attempt()
                    except RuntimeError:
                        raise StructuredRuntimeRecoveryError(
                            error_code="EVALUATION_TRANSPORT_LIMIT_REACHED",
                            message="评估 Provider transport 已达到安全上限；系统已停止。",
                            recovery_actions=["转为人工复核"],
                            preserved_input=_input_payload(preserved_input),
                        ) from None
                if operation is not None and self._before_provider_call is not None:
                    # This is deliberately after all local profile/credential/adapter
                    # validation and immediately before the real provider dispatch.
                    reservation = self._before_provider_call(operation)
                self._remember_reservation(operation, reservation)
                try:
                    result = adapter_method(*args, **(kwargs or {}))
                    if method == "analyze_evidence":
                        try:
                            parsed = (
                                result
                                if isinstance(result, EvidenceRelationSetDraft)
                                else EvidenceRelationSetDraft.model_validate(
                                    {"relations": result}
                                )
                            )
                        except ValidationError:
                            raise ProviderCallError(
                                "invalid_content",
                                "Provider response did not match the required schema.",
                                False,
                            ) from None
                        return [item.model_dump(mode="json") for item in parsed.relations]
                    return result
                except ProviderCallError as error:
                    if operation is not None and self._after_provider_failure is not None:
                        self._release_reservation(operation, reservation)
                    can_retry = (
                        self.evaluation_policy is None
                        and (error.code in SCHEMA_ERROR_CODES or error.retryable)
                    )
                    if can_retry and self.model_rounds_used < self.max_model_rounds:
                        continue
                    raise _recovery_for_provider_error(
                        error, preserved_input=preserved_input
                    ) from None
                except StructuredRuntimeRecoveryError:
                    if operation is not None and self._after_provider_failure is not None:
                        self._release_reservation(operation, reservation)
                    raise
                except Exception:
                    if operation is not None and self._after_provider_failure is not None:
                        self._release_reservation(operation, reservation)
                    raise StructuredRuntimeRecoveryError(
                        error_code="MODEL_PROVIDER_ERROR",
                        message="所选模型暂时无法完成生成；你的输入已保留。",
                        recovery_actions=["稍后重试", "检查所选模型配置"],
                        preserved_input=_input_payload(preserved_input),
                    ) from None
            raise StructuredRuntimeRecoveryError(
                error_code="MODEL_ROUND_LIMIT_REACHED",
                message="模型生成已达到安全轮次上限；系统已停止并保留输入。",
                recovery_actions=["补充输入后重试", "转为人工复核"],
                preserved_input=_input_payload(preserved_input),
            )
        finally:
            try:
                adapter.close()
            except Exception:
                pass

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return self._call(
            "interpret_idea", preserved_input=request, args=(request,)
        )

    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        return self._call(
            "design_solutions", preserved_input=brief, args=(brief,)
        )

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None
    ) -> CompetitorComparisonDraft:
        return self._call(
            "compare_competitors",
            preserved_input={"candidates": candidates, "project_context": project_context},
            args=(candidates,),
            kwargs={"project_context": project_context},
        )

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        value = {"claim": claim, "chunks": chunks}
        return self._call(
            "analyze_evidence",
            preserved_input=value,
            kwargs={"claim": claim, "chunks": chunks},
        )

    def generate_ai_reference(self, context: dict[str, Any], *, evaluation_context: Any | None = None) -> AIReferenceDraft:
        return self._call(
            "generate_ai_reference", preserved_input=context, args=(context,)
        )

    def generate_evidence_guidance(self, context: dict[str, Any]) -> EvidenceGuidanceDraft:
        return self._call(
            "generate_evidence_guidance", preserved_input=context, args=(context,)
        )


class HybridStructuredRuntime:
    """Resolve exactly one configured profile for every project request."""

    provider = "profile_resolver"
    model = "per_request"
    prompt_version = "hybrid-structured-v1"
    schema_version = "v3-p0-1"
    model_rounds_used = 0

    def __init__(
        self,
        profile_service: ModelProfileService,
        *,
        local_runtime: StructuredAIRuntime,
        adapter_factory: AdapterFactory = ModelAdapter,
        max_model_rounds: int = 2,
        max_tool_rounds: int = 4,
        before_provider_call: BeforeProviderCall | None = None,
        after_provider_failure: AfterProviderFailure | None = None,
        after_provider_success: Callable[[str, Any], Any] | None = None,
        managed_runtime: StructuredAIRuntime | None = None,
        managed_runtime_factory: Callable[[Any], StructuredAIRuntime] | None = None,
        fixture_runtime: StructuredAIRuntime | None = None,
    ) -> None:
        if max_model_rounds < 1 or max_model_rounds > 2:
            raise ValueError("max_model_rounds must be in [1, 2]")
        if max_tool_rounds < 1 or max_tool_rounds > 8:
            raise ValueError("max_tool_rounds must be in [1, 8]")
        if local_runtime.mode != "deterministic_demo":
            raise ValueError("local_runtime must be deterministic_demo")
        self.profile_service = profile_service
        self.local_runtime = local_runtime
        self.adapter_factory = adapter_factory
        self.max_model_rounds = max_model_rounds
        self.max_tool_rounds = max_tool_rounds
        self.before_provider_call = before_provider_call
        self.after_provider_failure = after_provider_failure
        self.after_provider_success = after_provider_success
        if managed_runtime is not None and managed_runtime.mode not in {"managed_qwen", "managed_model"}:
            raise ValueError("managed_runtime must use a managed runtime")
        self.managed_runtime = managed_runtime
        self.managed_runtime_factory = managed_runtime_factory
        self.fixture_runtime = fixture_runtime

    @property
    def mode(self) -> str:
        # The resolver has not selected local or remote execution until a request starts.
        return "hybrid"

    def _selected_profile(self, project_id: str | None) -> dict[str, Any] | None:
        if project_id is not None:
            override = self.profile_service.db.fetch_one(
                """
                SELECT mp.*
                FROM project_model_profiles pmp
                LEFT JOIN model_profiles mp ON mp.id = pmp.profile_id
                WHERE pmp.project_id = ? AND pmp.enabled = 1
                """,
                (project_id,),
            )
            if override is not None:
                return override if override.get("id") and override.get("enabled") else None
        return self.profile_service.db.fetch_one(
            """
            SELECT * FROM model_profiles
            WHERE is_default = 1 AND enabled = 1
            ORDER BY updated_at DESC, id
            LIMIT 1
            """
        )

    def for_project(
        self,
        project_id: str | None,
        managed_selection: Any | None = None,
        *,
        evaluation_policy: EvaluationExecutionPolicy | None = None,
    ) -> StructuredAIRuntime:
        if self.fixture_runtime is not None:
            return self.fixture_runtime
        if self.managed_runtime_factory is not None and managed_selection is not None:
            return self.managed_runtime_factory(managed_selection)
        if self.managed_runtime is not None:
            return self.managed_runtime
        profile = self._selected_profile(project_id)
        if profile is None:
            return _LocalGuidanceRuntime(
                self.local_runtime,
                max_model_rounds=self.max_model_rounds,
                max_tool_rounds=self.max_tool_rounds,
            )
        return _ProfileStructuredRuntime(
            profile=profile,
            profile_service=self.profile_service,
            adapter_factory=self.adapter_factory,
            max_model_rounds=self.max_model_rounds,
            max_tool_rounds=self.max_tool_rounds,
            before_provider_call=self.before_provider_call,
            after_provider_failure=self.after_provider_failure,
            after_provider_success=self.after_provider_success,
            evaluation_policy=evaluation_policy,
        )

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        runtime = self.for_project(claim.get("project_id"))
        return runtime.analyze_evidence(claim=claim, chunks=chunks)

    def generate_ai_reference(self, context: dict[str, Any], *, evaluation_context: Any | None = None) -> AIReferenceDraft:
        runtime = self.for_project(context.get("project_id"))
        if evaluation_context is None:
            return runtime.generate_ai_reference(context)
        return runtime.generate_ai_reference(context, evaluation_context=evaluation_context)

    def generate_evidence_guidance(self, context: dict[str, Any]) -> EvidenceGuidanceDraft:
        runtime = self.for_project(context.get("project_id"))
        return runtime.generate_evidence_guidance(context)

    def design_solutions(
        self,
        brief: IdeaBriefDraft,
        *,
        project_id: str | None = None,
        managed_selection: Any | None = None,
    ) -> SolutionSetDraft:
        runtime = self.for_project(project_id, managed_selection=managed_selection)
        return runtime.design_solutions(brief)
