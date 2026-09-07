from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, runtime_checkable

from app.errors import StructuredRuntimeRecoveryError, StructuredRuntimeUnavailableError
from app.schemas import (
    AIReferenceDraft,
    CompetitorComparisonDraft,
    CompetitorComparisonItem,
    CompetitorProjectLevel,
    EvidenceRelationSetDraft,
    IdeaBriefDraft,
    QuickStartRequest,
    SolutionSetDraft,
)
from app.services.provider_adapters import AsyncModelAdapter, DEFAULT_PROVIDER_TIMEOUT, ModelAdapter, ProviderCallError
from app.services.dispatch_control import DispatchControlContext

RuntimeMode = Literal["llm_structured", "deterministic_demo", "managed_qwen"]


@runtime_checkable
class StructuredAIRuntime(Protocol):
    mode: RuntimeMode
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    max_model_rounds: int
    max_tool_rounds: int
    model_rounds_used: int

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft: ...

    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft: ...

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None
    ) -> CompetitorComparisonDraft: ...

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def generate_ai_reference(self, context: dict[str, Any]) -> AIReferenceDraft: ...


def _canonical_bytes(value: Any) -> bytes:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def build_ai_trace_payload(
    *,
    runtime: StructuredAIRuntime,
    input_payload: Any,
    output_payload: Any | None,
    started_at: float,
    status: str,
    component_version: str,
) -> dict[str, Any]:
    return {
        "provider": runtime.provider,
        "model": runtime.model,
        "prompt_version": runtime.prompt_version,
        "schema_version": runtime.schema_version,
        "component_version": component_version,
        "input_sha256": sha256_payload(input_payload),
        "output_sha256": sha256_payload(output_payload) if output_payload is not None else None,
        "latency_ms": max(0, int(round((time.perf_counter() - started_at) * 1000))),
        "status": status,
        "runtime_mode": runtime.mode,
        "model_rounds_used": getattr(runtime, "model_rounds_used", 1),
        "max_model_rounds": getattr(runtime, "max_model_rounds", 1),
        "max_tool_rounds": getattr(runtime, "max_tool_rounds", 0),
        "profile_id": getattr(runtime, "profile_id", None),
        "profile_revision": getattr(runtime, "profile_revision", None),
    }


class DeterministicDemoRuntime:
    mode: RuntimeMode = "deterministic_demo"
    provider = "fixture"
    model = "frozen_v3_golden_cases"
    prompt_version = "deterministic-demo-v1"
    schema_version = "v3-p0-1"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1

    def __init__(self, *, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)
        if not self.fixture_path.exists():
            raise StructuredRuntimeUnavailableError(
                f"DETERMINISTIC_DEMO_FIXTURE_MISSING: {self.fixture_path}"
            )
        self.cases = json.loads(self.fixture_path.read_text(encoding="utf-8"))

    def _case_for_text(self, text: str) -> tuple[str, dict[str, Any]]:
        normalized = text.casefold()
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for key, case in self.cases.items():
            if not isinstance(case, dict) or "brief" not in case:
                continue
            score = sum(term.casefold() in normalized for term in case.get("match_terms", []))
            if score:
                scored.append((score, key, case))
        if not scored:
            raise StructuredRuntimeUnavailableError(
                "DETERMINISTIC_DEMO_UNSUPPORTED: no frozen semantic case matches this idea"
            )
        scored.sort(key=lambda item: (-item[0], item[1]))
        _, key, case = scored[0]
        return key, case

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        _, case = self._case_for_text(request.idea)
        data = dict(case["brief"])
        data["original_idea"] = request.idea.strip()
        # Explicit user inputs remain user_input; fixture hypotheses never get upgraded implicitly.
        if request.target_user:
            data["target_user"] = request.target_user.strip()
            data.setdefault("provenance", {})["target_user"] = "user_input"
        if request.resources:
            data["known_resources"] = list(request.resources)
            data.setdefault("provenance", {})["known_resources"] = "user_input"
        return IdeaBriefDraft.model_validate(data)

    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        search_text = " ".join([brief.original_idea, brief.target_user, brief.problem])
        _, case = self._case_for_text(search_text)
        if brief.clarification_required:
            raise StructuredRuntimeUnavailableError(
                "CLARIFICATION_REQUIRED: confirm or refine IdeaBrief before solution design"
            )
        solutions = case.get("solutions") or []
        if len(solutions) < 2:
            raise StructuredRuntimeUnavailableError(
                "DETERMINISTIC_DEMO_UNSUPPORTED: frozen case has no complete solution set"
            )
        return SolutionSetDraft(candidates=solutions, llm_core_required=False)

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None
    ) -> CompetitorComparisonDraft:
        return CompetitorComparisonDraft(
            competitors=[
                CompetitorComparisonItem(
                    candidate_id=str(candidate["candidate_id"]),
                    name=str(candidate["name"]),
                    core_problem=str(candidate.get("description") or "暂未确认"),
                    uncertainties=["来源由用户提供，尚未核实"],
                )
                for candidate in candidates
            ],
            project_level=CompetitorProjectLevel(),
            uncertainty_notice="AI分析参考，建议结合实际产品页面核对。",
        )

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []
        frozen_cases = self.cases.get("_evidence_cases", [])
        if not isinstance(frozen_cases, list):
            raise StructuredRuntimeUnavailableError(
                "DETERMINISTIC_DEMO_FIXTURE_INVALID: _evidence_cases must be a list"
            )
        claim_type = str(claim.get("claim_type") or "")
        claim_text = str(claim.get("statement") or "").casefold()
        proposals: list[dict[str, Any]] = []
        for frozen in frozen_cases:
            if not isinstance(frozen, dict) or frozen.get("claim_type") != claim_type:
                continue
            if not all(str(term).casefold() in claim_text for term in frozen.get("claim_terms", [])):
                continue
            for chunk in chunks:
                if chunk.get("source_type") != frozen.get("source_type"):
                    continue
                content = str(chunk.get("content") or "")
                normalized = content.casefold()
                if not all(str(term).casefold() in normalized for term in frozen.get("chunk_terms", [])):
                    continue
                span = str(frozen.get("evidence_span") or "")
                if not span or span not in content:
                    continue
                proposals.append(
                    {
                        "source_id": str(chunk["source_id"]),
                        "chunk_id": str(chunk["chunk_id"]),
                        "relation": frozen["relation"],
                        "directness": frozen["directness"],
                        "scope_fit": frozen["scope_fit"],
                        "recency_state": frozen["recency_state"],
                        "evidence_span": span,
                        "reason": str(frozen.get("reason") or ""),
                    }
                )
        if proposals:
            return proposals
        raise StructuredRuntimeUnavailableError(
            "DETERMINISTIC_DEMO_UNSUPPORTED: no frozen evidence case matches this claim and source"
        )

    def generate_ai_reference(self, context: dict[str, Any]) -> AIReferenceDraft:
        idea = str(context.get("idea") or "你的项目想法")
        return AIReferenceDraft(
            possible_target_users=[f"可能关注“{idea[:40]}”的人群"],
            possible_scenarios=["用户在真实场景中尝试解决当前问题"],
            possible_user_problems=["当前问题可能需要更清晰的流程和反馈"],
            missing_information=["尚未有真实用户反馈或外部资料支持"],
            mvp_thoughts=["先用最小流程验证用户是否愿意完成核心任务"],
            questions_to_validate=["目标用户是否真的频繁遇到这个问题"],
            research_directions=["访谈目标用户并观察他们当前的替代做法"],
        )


class OpenAIStructuredRuntime:
    mode: RuntimeMode = "llm_structured"
    provider = "openai"
    prompt_version = "quick-value-v1"
    schema_version = "v3-p0-1"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 0

    def __init__(self, *, model: str, api_key: str):
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise StructuredRuntimeUnavailableError(
                'Install optional dependencies with: pip install -e ".[llm]"'
            ) from exc
        self.model = model
        self.client = OpenAI(api_key=api_key)

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        self.model_rounds_used = 1
        system = (
            "Interpret a product idea conservatively. Distinguish explicit user input from model hypotheses. "
            "Ask at most one blocking clarification only when multiple materially different product meanings exist. "
            "Do not claim market validation."
        )
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(request.model_dump(), ensure_ascii=False)},
                ],
                text_format=IdeaBriefDraft,
            )
            parsed = response.output_parsed
        except Exception as exc:  # pragma: no cover - live adapter
            raise StructuredRuntimeUnavailableError(f"STRUCTURED_LLM_CALL_FAILED: {exc}") from exc
        if parsed is None:
            raise StructuredRuntimeUnavailableError("STRUCTURED_LLM_EMPTY_OUTPUT")
        if parsed.original_idea != request.idea:
            parsed = parsed.model_copy(update={"original_idea": request.idea})
        return parsed

    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        self.model_rounds_used = 1
        system = (
            "Generate 2-3 materially different solutions to the user's business problem, not variants of this workspace. "
            "Unless the problem inherently requires an LLM, include a non-LLM/non-RAG/non-Agent baseline. "
            "Every market statement remains a model_hypothesis. Return implementation-ready fields."
        )
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": brief.model_dump_json()},
                ],
                text_format=SolutionSetDraft,
            )
            parsed = response.output_parsed
        except Exception as exc:  # pragma: no cover - live adapter
            raise StructuredRuntimeUnavailableError(f"STRUCTURED_LLM_CALL_FAILED: {exc}") from exc
        if parsed is None:
            raise StructuredRuntimeUnavailableError("STRUCTURED_LLM_EMPTY_OUTPUT")
        return parsed

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None
    ) -> CompetitorComparisonDraft:
        self.model_rounds_used = 1
        system = (
            "Compare only the supplied candidate products for the current project. "
            "Treat URLs and descriptions as user-provided, not verified facts. "
            "Return structured analysis and mark unsupported fields as 暂未确认. "
            "Do not invent prices, users, market share, research, or official product facts."
        )
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps({"candidates": candidates, "project_context": project_context}, ensure_ascii=False)},
                ],
                text_format=CompetitorComparisonDraft,
            )
            parsed = response.output_parsed
        except Exception as exc:  # pragma: no cover - live adapter
            raise StructuredRuntimeUnavailableError(f"STRUCTURED_LLM_CALL_FAILED: {exc}") from exc
        if parsed is None:
            raise StructuredRuntimeUnavailableError("STRUCTURED_LLM_EMPTY_OUTPUT")
        return parsed

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        self.model_rounds_used = 1
        system = (
            "Assess only the supplied project-scoped chunks against the supplied product claim. "
            "Return zero or more relation proposals. Every proposal must quote an exact evidence span "
            "from one supplied chunk; do not paraphrase the span. Use contextualizes when the text is "
            "relevant but does not directly support or contradict the claim. Do not infer market truth."
        )
        compact_chunks = [
            {
                "source_id": item["source_id"],
                "chunk_id": item["chunk_id"],
                "source_type": item["source_type"],
                "content": item["content"],
            }
            for item in chunks
        ]
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"claim": claim, "chunks": compact_chunks}, ensure_ascii=False
                        ),
                    },
                ],
                text_format=EvidenceRelationSetDraft,
            )
            parsed = response.output_parsed
        except Exception as exc:  # pragma: no cover - live adapter
            raise StructuredRuntimeUnavailableError(f"STRUCTURED_LLM_CALL_FAILED: {exc}") from exc
        if parsed is None:
            raise StructuredRuntimeUnavailableError("STRUCTURED_LLM_EMPTY_OUTPUT")
        return [item.model_dump(mode="json") for item in parsed.relations]

    def generate_ai_reference(self, context: dict[str, Any]) -> AIReferenceDraft:
        self.model_rounds_used = 1
        system = (
            "Provide conservative brainstorming for a product idea. Return structured reference suggestions only. "
            "Do not claim user research, official data, market facts, or sources. Mark all suggestions as unverified."
        )
        try:
            response = self.client.responses.parse(
                model=self.model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                text_format=AIReferenceDraft,
            )
            parsed = response.output_parsed
        except Exception as exc:  # pragma: no cover - live adapter
            raise StructuredRuntimeUnavailableError(f"STRUCTURED_LLM_CALL_FAILED: {exc}") from exc
        if parsed is None:
            raise StructuredRuntimeUnavailableError("STRUCTURED_LLM_EMPTY_OUTPUT")
        return parsed


class ManagedQwenStructuredRuntime:
    """Use only the deployment-managed Bailian credential, never a demo fallback."""

    mode: RuntimeMode = "managed_qwen"
    provider = "qwen"
    prompt_version = "managed-qwen-v1"
    schema_version = "v3-p0-1"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 0

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider: str = "qwen",
        adapter_factory: Any = ModelAdapter,
        async_adapter_factory: Any = AsyncModelAdapter,
        before_provider_call: Callable[[str], Any] | None = None,
        after_provider_failure: Callable[[str, Any], Any] | None = None,
        after_provider_success: Callable[[str, Any], Any] | None = None,
        attempt_observer: Callable[[dict[str, Any]], Any] | None = None,
        timeout: Any = DEFAULT_PROVIDER_TIMEOUT,
        dispatch_ledger: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise StructuredRuntimeUnavailableError("MANAGED_QWEN_API_KEY is required; no deterministic fallback was used")
        self.model = model
        self.provider = provider
        self._api_key = api_key
        self._base_url = base_url
        self._adapter_factory = adapter_factory
        self._async_adapter_factory = async_adapter_factory
        self._before_provider_call = before_provider_call
        self._after_provider_failure = after_provider_failure
        self._after_provider_success = after_provider_success
        self._pending_reservation: tuple[str, Any] | None = None
        self._attempt_observer = attempt_observer
        self._timeout = timeout
        self._dispatch_ledger = dispatch_ledger

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

    def _dispatch_kwargs(self, control: DispatchControlContext | None) -> dict[str, Any]:
        if control is None:
            return {}
        control.validate(provider=self.provider, model=self.model, base_url=self._base_url)
        if self._dispatch_ledger is None:
            raise StructuredRuntimeUnavailableError("DISPATCH_LEDGER_REQUIRED")
        permit_id = self._dispatch_ledger.acquire_permit(
            acceptance_execution_id=control.acceptance_execution_id,
            acceptance_window_id=control.window_id,
            beta_instance=control.beta_instance, provider=control.expected_provider, model=control.expected_model,
            authorization_reference=control.authorization_reference, quota_scope=control.quota_scope,
        )
        if permit_id is None:
            raise StructuredRuntimeUnavailableError("DISPATCH_PERMIT_UNAVAILABLE")
        return {"dispatch_ledger": self._dispatch_ledger, "dispatch_control": control, "dispatch_permit_id": permit_id}

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.model_rounds_used = 1
        dispatch_control = kwargs.pop("dispatch_control", None)
        operation = {
            "design_solutions": "solution_generation",
            "analyze_evidence": "evidence_analysis",
            "compare_competitors": "solution_generation",
            "generate_ai_reference": "solution_generation",
        }.get(method)
        reservation = None
        if operation is not None and self._before_provider_call is not None:
            # Managed mode bypasses profile resolution; enforce quota at the
            # final boundary before the real provider adapter is constructed.
            reservation = self._before_provider_call(operation)
            self._remember_reservation(operation, reservation)
        try:
            adapter_kwargs = dict(
                provider=self.provider, model=self.model, api_key=self._api_key,
                base_url=self._base_url,
            )
            if self._attempt_observer is not None:
                adapter_kwargs["attempt_observer"] = self._attempt_observer
            adapter_kwargs["timeout"] = self._timeout
            adapter_kwargs.update(self._dispatch_kwargs(dispatch_control))
            adapter = self._adapter_factory(**adapter_kwargs)
        except Exception as exc:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            raise StructuredRuntimeUnavailableError("MANAGED_QWEN_CONFIGURATION_INVALID") from exc
        try:
            result = getattr(adapter, method)(*args, **kwargs)
            self.last_provider_diagnostic = dict(getattr(adapter, "last_safe_diagnostic", {}))
            return result
        except ProviderCallError as exc:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            self.last_provider_diagnostic = dict(exc.safe_diagnostic)
            raise StructuredRuntimeRecoveryError(
                error_code=f"MODEL_{exc.code.upper()}",
                message=(
                    "AI 服务暂时繁忙，你的项目内容已保存，请稍后重试。"
                    if exc.safe_diagnostic.get("provider_error_source") == "UPSTREAM_HTTP_503"
                    else "AI 服务暂时不可用；你的输入已保存，可以稍后重试。"
                ),
                recovery_actions=["检查托管模型服务状态", "稍后重试"],
                preserved_input=kwargs.get("claim") if method == "analyze_evidence" else (args[0] if args else {}),
                safe_diagnostic=exc.safe_diagnostic,
            ) from exc
        except StructuredRuntimeRecoveryError:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            raise
        except Exception as exc:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            raise StructuredRuntimeUnavailableError("MANAGED_QWEN_REQUEST_FAILED") from exc
        finally:
            try:
                adapter.close()
            except Exception:
                pass

    async def _call_async(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.model_rounds_used = 1
        dispatch_control = kwargs.pop("dispatch_control", None)
        operation = {"design_solutions": "solution_generation", "analyze_evidence": "evidence_analysis", "generate_ai_reference": "solution_generation"}.get(method)
        reservation = None
        if operation is not None and self._before_provider_call is not None:
            reservation = self._before_provider_call(operation)
            self._remember_reservation(operation, reservation)
        adapter = None
        try:
            generation_intent_id = kwargs.pop("_generation_intent_id", None)
            generation_run_id = kwargs.pop("_generation_run_id", None)
            adapter_kwargs = dict(provider=self.provider, model=self.model, api_key=self._api_key, base_url=self._base_url, timeout=self._timeout)
            if generation_intent_id is not None:
                adapter_kwargs["generation_intent_id"] = generation_intent_id
            if generation_run_id is not None:
                adapter_kwargs["generation_run_id"] = generation_run_id
            if self._attempt_observer is not None:
                adapter_kwargs["attempt_observer"] = self._attempt_observer
            adapter_kwargs.update(self._dispatch_kwargs(dispatch_control))
            adapter = self._async_adapter_factory(**adapter_kwargs)
            async_method = getattr(adapter, f"{method}_async")
            result = await async_method(*args, **kwargs)
            self.last_provider_diagnostic = dict(getattr(adapter, "last_safe_diagnostic", {}))
            return result
        except asyncio.CancelledError:
            # Cancellation is not proof that the Provider was never dispatched.
            # Settle only the user reservation; leave dispatch evidence intact.
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            raise
        except ProviderCallError as exc:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            self.last_provider_diagnostic = dict(exc.safe_diagnostic)
            raise StructuredRuntimeRecoveryError(
                error_code=f"MODEL_{exc.code.upper()}",
                message=("AI 服务暂时繁忙，你的项目内容已保存，请稍后重试。" if exc.safe_diagnostic.get("provider_error_source") == "UPSTREAM_HTTP_503" else "AI 服务暂时不可用；你的输入已保存，可以稍后重试。"),
                recovery_actions=["检查托管模型服务状态", "稍后重试"],
                preserved_input=kwargs.get("claim") if method == "analyze_evidence" else (args[0] if args else {}),
                safe_diagnostic=exc.safe_diagnostic,
            ) from exc
        except StructuredRuntimeRecoveryError:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            raise
        except Exception as exc:
            if operation is not None and self._after_provider_failure is not None:
                self._release_reservation(operation, reservation)
            raise StructuredRuntimeUnavailableError("MANAGED_QWEN_REQUEST_FAILED") from exc
        finally:
            if adapter is not None:
                try:
                    await adapter.aclose()
                except Exception:
                    pass

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return self._call("interpret_idea", request)

    def design_solutions(self, brief: IdeaBriefDraft, *, dispatch_control: DispatchControlContext | None = None) -> SolutionSetDraft:
        return self._call("design_solutions", brief, dispatch_control=dispatch_control)

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None,
        dispatch_control: DispatchControlContext | None = None,
    ) -> CompetitorComparisonDraft:
        return self._call("compare_competitors", candidates, project_context=project_context, dispatch_control=dispatch_control)

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return self._call("analyze_evidence", claim=claim, chunks=chunks)

    def generate_ai_reference(self, context: dict[str, Any]) -> AIReferenceDraft:
        return self._call("generate_ai_reference", context)

    async def async_design_solutions(self, brief: IdeaBriefDraft, *, generation_intent_id: str | None = None, generation_run_id: str | None = None, dispatch_control: DispatchControlContext | None = None) -> SolutionSetDraft:
        return await self._call_async("design_solutions", brief, dispatch_control=dispatch_control, _generation_intent_id=generation_intent_id, _generation_run_id=generation_run_id)

    async def async_interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return await self._call_async("interpret_idea", request)

    async def async_analyze_evidence(self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return await self._call_async("analyze_evidence", claim=claim, chunks=chunks)


class ManagedModelStructuredRuntime(ManagedQwenStructuredRuntime):
    """Managed Bailian runtime for one already-resolved model selection."""

    mode: RuntimeMode = "managed_model"

    def __init__(self, *, model: str, provider: str, api_key: str,
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
                 adapter_factory: Any = ModelAdapter,
                 async_adapter_factory: Any = AsyncModelAdapter,
                 before_provider_call: Callable[[str], Any] | None = None,
                 after_provider_failure: Callable[[str, Any], Any] | None = None,
                 after_provider_success: Callable[[str, Any], Any] | None = None,
                 attempt_observer: Callable[[dict[str, Any]], Any] | None = None,
                 timeout: Any = DEFAULT_PROVIDER_TIMEOUT,
                 dispatch_ledger: Any | None = None) -> None:
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            provider=provider,
            adapter_factory=adapter_factory,
            async_adapter_factory=async_adapter_factory,
            before_provider_call=before_provider_call,
            after_provider_failure=after_provider_failure,
            after_provider_success=after_provider_success,
            attempt_observer=attempt_observer,
            timeout=timeout,
            dispatch_ledger=dispatch_ledger,
        )


def build_structured_runtime(
    *,
    mode: RuntimeMode | None = None,
    fixture_path: str | Path | None = None,
    model: str | None = None,
    api_key: str | None = None,
    before_provider_call: Callable[[str], Any] | None = None,
    after_provider_failure: Callable[[str, Any], Any] | None = None,
    after_provider_success: Callable[[str, Any], Any] | None = None,
    attempt_observer: Callable[[dict[str, Any]], Any] | None = None,
    base_url: str | None = None,
    dispatch_ledger: Any | None = None,
) -> StructuredAIRuntime:
    selected = mode or os.getenv("INSIGHTFORGE_STRUCTURED_AI_MODE", "deterministic_demo")
    if selected == "llm_structured":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise StructuredRuntimeUnavailableError(
                "OPENAI_API_KEY is required for llm_structured; no deterministic fallback was used"
            )
        return OpenAIStructuredRuntime(
            model=model or os.getenv("OPENAI_MODEL", "gpt-5.6"),
            api_key=api_key,
        )
    if selected == "deterministic_demo":
        path = fixture_path or os.getenv(
            "INSIGHTFORGE_DEMO_FIXTURE_PATH", "tests/fixtures/v3_golden_cases.json"
        )
        return DeterministicDemoRuntime(fixture_path=path)
    if selected == "managed_qwen":
        resolved_key = api_key or os.getenv("MANAGED_QWEN_API_KEY")
        if not resolved_key:
            raise StructuredRuntimeUnavailableError(
                "MANAGED_QWEN_API_KEY is required; no deterministic fallback was used"
            )
        return ManagedQwenStructuredRuntime(
            model=model or os.getenv("MANAGED_QWEN_MODEL", "qwen3.7-flash"),
            api_key=resolved_key,
            before_provider_call=before_provider_call,
            after_provider_failure=after_provider_failure,
            after_provider_success=after_provider_success,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            attempt_observer=attempt_observer,
            dispatch_ledger=dispatch_ledger,
        )
    if selected == "managed_model":
        resolved_key = api_key or os.getenv("MANAGED_BAILIAN_API_KEY") or os.getenv("MANAGED_QWEN_API_KEY")
        if not resolved_key:
            raise StructuredRuntimeUnavailableError(
                "MANAGED_BAILIAN_API_KEY is required; no deterministic fallback was used"
            )
        return ManagedModelStructuredRuntime(
            model=model or os.getenv("MANAGED_MODEL_ID", "qwen3.7-flash"),
            provider=os.getenv("MANAGED_MODEL_PROVIDER", "qwen"),
            api_key=resolved_key,
            before_provider_call=before_provider_call,
            after_provider_failure=after_provider_failure,
            after_provider_success=after_provider_success,
            base_url=base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            attempt_observer=attempt_observer,
            dispatch_ledger=dispatch_ledger,
        )
    raise StructuredRuntimeUnavailableError(f"UNKNOWN_STRUCTURED_AI_MODE: {selected}")
