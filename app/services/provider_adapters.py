"""Safe protocol translation for configured model providers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.errors import StructuredOutputContractError
from app.schemas import (
    AIReferenceDraft,
    CompetitorComparisonDraft,
    EvidenceGuidanceDraft,
    EvidenceRelationSetDraft,
    IdeaBriefDraft,
    QuickStartRequest,
    SolutionSetDraft,
)
from app.services.capability_probe import CapabilityProbe, CapabilityReport, CapabilityStatus
from app.services.model_providers import ProviderConfigurationError, ProviderRegistry
from app.services.dispatch_control import DispatchControlContext
from app.services.generation_contracts import AI_REFERENCE_GENERATION_INSTRUCTION, safe_reference_shape


class ProviderCallError(RuntimeError):
    """A deliberately body-free error safe to surface to an API client or log."""

    def __init__(
        self, code: str, safe_message: str, retryable: bool, *,
        safe_diagnostic: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
        self.safe_diagnostic = dict(safe_diagnostic or {})
        super().__init__(f"{code}: {safe_message}")


_Model = TypeVar("_Model", bound=BaseModel)


DEFAULT_PROVIDER_TIMEOUT = httpx.Timeout(
    connect=10.0,
    pool=5.0,
    write=15.0,
    read=60.0,
)


def _timeout_metadata(timeout: httpx.Timeout | float) -> dict[str, float | None]:
    if isinstance(timeout, httpx.Timeout):
        return {
            "connect_timeout_seconds": timeout.connect,
            "pool_timeout_seconds": timeout.pool,
            "write_timeout_seconds": timeout.write,
            "read_timeout_seconds": timeout.read,
            "overall_timeout_seconds": 75.0,
        }
    value = float(timeout)
    return {
        "connect_timeout_seconds": value,
        "pool_timeout_seconds": value,
        "write_timeout_seconds": value,
        "read_timeout_seconds": value,
        "overall_timeout_seconds": value,
    }


@dataclass(frozen=True, slots=True)
class LiveConnectionResult:
    provider: str
    status: Literal["PASS", "FAIL"]
    model_requested: str
    model_returned: str | None
    latency_ms: int
    content_received: bool
    usage_available: bool
    error_code: str | None
    safe_message: str
    retryable: bool
    secret_exposed: bool = False
    safe_diagnostic: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "provider": self.provider,
            "status": self.status,
            "model_requested": self.model_requested,
            "model_returned": self.model_returned,
            "latency_ms": self.latency_ms,
            "content_received": self.content_received,
            "usage_available": self.usage_available,
            "error_code": self.error_code,
            "safe_message": self.safe_message,
            "retryable": self.retryable,
            "secret_exposed": self.secret_exposed,
        }
        if self.safe_diagnostic is not None:
            payload["safe_diagnostic"] = self.safe_diagnostic
        return payload


class ModelAdapter:
    """Provider-neutral structured generation backed by explicit HTTP adapters."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
        protocol: str | None = None,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout | float | None = None,
        attempt_observer: Callable[[dict[str, Any]], Any] | None = None,
        generation_intent_id: str | None = None,
        generation_run_id: str | None = None,
        dispatch_ledger: Any | None = None,
        dispatch_control: DispatchControlContext | None = None,
        dispatch_permit_id: str | None = None,
    ) -> None:
        self.preset = ProviderRegistry.resolve(provider, protocol=protocol, base_url=base_url)
        if not str(model).strip():
            raise ProviderConfigurationError("Model ID is required.")
        if not str(api_key).strip():
            raise ProviderConfigurationError("Provider credential is required.")
        self.provider = self.preset.provider
        self.protocol = self.preset.protocol
        self.base_url = self.preset.default_base_url
        self.model = model.strip()
        self._api_key = api_key
        effective_timeout = timeout if timeout is not None else DEFAULT_PROVIDER_TIMEOUT
        if isinstance(effective_timeout, httpx.Timeout):
            self._timeout = effective_timeout
        else:
            self._timeout = httpx.Timeout(float(effective_timeout))
        self._effective_timeout = _timeout_metadata(effective_timeout)
        # Kept for compatibility with existing diagnostics consumers.
        self._timeout_seconds = self._effective_timeout["overall_timeout_seconds"]
        self._attempt_observer = attempt_observer
        self._generation_intent_id = generation_intent_id
        self._generation_run_id = generation_run_id
        self._dispatch_ledger = dispatch_ledger
        self._dispatch_control = dispatch_control
        self._dispatch_permit_id = dispatch_permit_id
        self._use_response_format = True
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=self._timeout)
        self.last_safe_diagnostic: dict[str, Any] = {}
        self._last_attempt_id: str | None = None
        self._last_attempt_record_args: dict[str, Any] | None = None

    def _before_network(self) -> None:
        if self._dispatch_control is None:
            return
        self._dispatch_control.validate(provider=self.provider, model=self.model, base_url=self.base_url)
        if self._dispatch_ledger is None or not self._dispatch_permit_id or not self._dispatch_ledger.permit_matches(self._dispatch_permit_id, self._dispatch_control):
            raise ProviderCallError("dispatch_control_invalid", "Provider dispatch authorization is unavailable.", False)
        self._dispatch_ledger.record_event(self._dispatch_permit_id, "CALL_BOUNDARY_ENTERED")

    def _dispatch_event(self, event_type: str) -> None:
        if self._dispatch_control is not None and self._dispatch_ledger is not None and self._dispatch_permit_id:
            self._dispatch_ledger.record_event(self._dispatch_permit_id, event_type)

    @property
    def effective_timeout(self) -> dict[str, float | None]:
        return dict(self._effective_timeout)

    @property
    def is_closed(self) -> bool:
        return self._client.is_closed

    def close(self) -> None:
        """Release a client created by this adapter without closing injected clients."""
        if self._owns_client and not self._client.is_closed:
            self._client.close()

    def __enter__(self) -> "ModelAdapter":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return self._generate(
            output_model=IdeaBriefDraft,
            system=(
                "Interpret this product idea conservatively. Return only JSON matching the requested schema. "
                "Keep provenance explicit and do not claim market validation."
            ),
            user=json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
        )

    def design_solutions(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        return self._generate(
            output_model=SolutionSetDraft,
            system=(
                "Generate exactly 3 materially different solutions. Return only JSON matching the requested schema. "
                "Do not make unsupported market claims."
            ),
            user=brief.model_dump_json(),
        )

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        compact_chunks = [
            {
                "source_id": item["source_id"],
                "chunk_id": item["chunk_id"],
                "source_type": item["source_type"],
                "content": item["content"],
            }
            for item in chunks
        ]
        parsed = self._generate(
            output_model=EvidenceRelationSetDraft,
            system=(
                "Assess only the supplied claim and project-scoped chunks. Return only JSON matching "
                "the requested schema. Every relation must quote an exact evidence span from one supplied "
                "chunk. Do not infer market truth or invent evidence."
            ),
            user=json.dumps(
                {"claim": claim, "chunks": compact_chunks}, ensure_ascii=False
            ),
        )
        return [item.model_dump(mode="json") for item in parsed.relations]

    def probe(self) -> CapabilityReport:
        """Explicitly send a small structured request; it can consume provider quota."""
        return CapabilityProbe(self).probe()


    def live_check(self) -> LiveConnectionResult:
        """Execute exactly one minimal real chat request and return only safe metadata.

        This deliberately does not probe structured output, function calling, streaming,
        or return provider-generated content. It is a connectivity/account/model check.
        """
        started = perf_counter()
        try:
            body = self._request(
                system="" if self.provider == "qwen" else "You are performing a connectivity check.",
                user="OK" if self.provider == "qwen" else "Reply with exactly OK.",
                structured=False,
                max_tokens=8,
                live=True,
            )
            content = self._content_from_response(body).strip()
            if not content:
                shape = self.extract_safe_chat_response_shape(body)
                return LiveConnectionResult(
                    provider=self.provider,
                    status="FAIL",
                    model_requested=self.model,
                    model_returned=shape.get("model_returned"),
                    latency_ms=max(0, int((perf_counter() - started) * 1000)),
                    content_received=False,
                    usage_available=bool(shape.get("usage_present")),
                    error_code="empty_response",
                    safe_message=(
                        "Provider returned reasoning output but no final chat content."
                        if shape.get("reasoning_content_present")
                        else "Provider returned an empty chat response."
                    ),
                    retryable=False,
                    safe_diagnostic=shape,
                )
            returned_model = body.get("model")
            if not isinstance(returned_model, str) or not returned_model.strip():
                returned_model = None
            else:
                returned_model = returned_model.strip()[:240]
            return LiveConnectionResult(
                provider=self.provider,
                status="PASS",
                model_requested=self.model,
                model_returned=returned_model,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                content_received=True,
                usage_available=isinstance(body.get("usage"), dict),
                error_code=None,
                safe_message="Provider returned a valid minimal chat response.",
                retryable=False,
            )
        except ProviderCallError as exc:
            return LiveConnectionResult(
                provider=self.provider,
                status="FAIL",
                model_requested=self.model,
                model_returned=None,
                latency_ms=max(0, int((perf_counter() - started) * 1000)),
                content_received=False,
                usage_available=False,
                error_code=exc.code,
                safe_message=exc.safe_message,
                retryable=exc.retryable,
            )

    def _probe_basic_chat(self) -> CapabilityStatus:
        try:
            body = self._request(system="Reply with the word ok.", user="probe", structured=False)
            self._content_from_response(body)
        except ProviderCallError:
            # Authentication, quota, network, and model configuration failures do
            # not establish that a feature itself is unsupported.
            return "unknown"
        return "supported"

    def _probe_structured_json(self) -> CapabilityStatus:
        try:
            body = self._request(
                system='Reply with a JSON object only: {"ok":true}.',
                user="probe",
                structured=True,
            )
            content = self._content_from_response(body)
            if not isinstance(json.loads(content), dict):
                return "unsupported"
        except ProviderCallError as exc:
            if exc.code in {
                "invalid_request",
                "structured_output_unsupported",
                "unsupported_feature",
            }:
                return "unsupported"
            return "unknown"
        except (TypeError, json.JSONDecodeError):
            return "unsupported"
        return "supported"

    def _generate(self, *, output_model: type[_Model], system: str, user: str) -> _Model:
        body = self._request(
            system=system,
            user=user,
            structured=True,
            output_model=output_model,
        )
        return self._validate_structured_response(body, output_model)

    def _request(
        self, *, system: str, user: str, structured: bool, max_tokens: int | None = None,
        live: bool = False, output_model: type[_Model] | None = None,
    ) -> dict[str, Any]:
        used_response_format = False
        self.last_safe_diagnostic = {}
        attempt_id = str(uuid.uuid4())
        self._last_attempt_id = attempt_id
        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()
        if self.protocol == "openai_chat_completions":
            endpoint = "/chat/completions"
            headers = {"Authorization": f"Bearer {self._api_key}"}
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": ([{"role": "user", "content": user}] if not system.strip() else [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]),
            }
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if live:
                payload["stream"] = False
                if self.provider == "qwen":
                    payload["enable_thinking"] = False
                if self.provider in {"kimi", "glm"}:
                    payload["thinking"] = {"type": "disabled"}
                if self.provider in {"deepseek", "glm"}:
                    payload.pop("thinking", None)
                    payload["enable_thinking"] = False
                    payload["max_tokens"] = 32
                if self.provider == "glm":
                    payload["max_tokens"] = 32
                if self.provider == "kimi":
                    payload.pop("max_tokens", None)
                    payload["max_completion_tokens"] = 16
            if structured and self.provider == "qwen":
                payload["enable_thinking"] = False
            if structured and self._use_response_format:
                if self.provider == "qwen" and output_model is not None:
                    payload["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": output_model.__name__,
                            "strict": True,
                            "schema": output_model.model_json_schema(),
                        },
                    }
                else:
                    payload["response_format"] = {"type": "json_object"}
                used_response_format = True
        elif self.protocol == "anthropic_messages":
            endpoint = "/messages"
            headers = {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"}
            payload = {"model": self.model, "max_tokens": max_tokens or 1024, "system": system, "messages": [{"role": "user", "content": user}]}
        else:  # ProviderRegistry prevents this, retained as a wire-protocol boundary.
            raise ProviderCallError("unsupported_protocol", "Configured provider protocol is unsupported.", False)
        request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        response_format = payload.get("response_format")
        schema_bytes = len(json.dumps(response_format, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) if response_format else 0
        structured_output_mode = (
            "json_schema" if isinstance(response_format, dict) and response_format.get("type") == "json_schema"
            else "json_object" if response_format else "none"
        )

        transport_failure: tuple[str, str, bool, str, BaseException] | None = None
        try:
            self._before_network()
            response = self._client.post(f"{self.base_url}{endpoint}", headers=headers, json=payload)
        except httpx.TimeoutException as exc:
            subtype = type(exc).__name__
            stage = {
                "ConnectTimeout": "connect",
                "ReadTimeout": "read",
                "WriteTimeout": "write",
                "PoolTimeout": "pool",
            }.get(subtype, "unknown")
            # Rebuild a body-free concrete timeout so the cause chain preserves
            # the transport class without retaining httpx.Request headers.
            safe_cause = type(exc)("Provider transport timeout.")
            transport_failure = ("timeout", "Provider request timed out.", True, f"UPSTREAM_TIMEOUT_{stage.upper()}", safe_cause)
        except httpx.RequestError:
            transport_failure = (
                "network_error",
                "Provider request could not be completed.",
                True,
                "UPSTREAM_CONNECTION_FAILURE",
                RuntimeError("Provider transport request failed."),
            )
        if transport_failure is not None:
            code, message, retryable, source, safe_cause = transport_failure
            diagnostic = {
                "provider_request_started": True,
                "provider_request_completed": False,
                "upstream_response_received": False,
                "provider_error_source": source,
                "provider_error_code": "NO_UPSTREAM_ERROR_CODE",
                "provider_http_status": None,
                "provider_exception_class": type(safe_cause).__name__ if code == "timeout" else "RequestError",
                "provider_failure_stage": "provider_transport" if code != "timeout" else f"provider_transport_{source.removeprefix('UPSTREAM_TIMEOUT_').lower()}",
                "provider_retryable": retryable,
                "provider_retry_after_seconds_if_present": None,
            }
            self.last_safe_diagnostic = diagnostic
            self._emit_attempt(
                attempt_id=attempt_id, started_at=started_at, started_clock=started_clock,
                request_bytes=request_bytes, message_count=len(payload.get("messages", [])),
                schema_bytes=schema_bytes, structured_output_mode=structured_output_mode,
                exception_at=datetime.now(timezone.utc), response_headers_observed=False,
                exception_class=type(safe_cause).__name__ if code == "timeout" else "RequestError",
                failure_stage=diagnostic["provider_failure_stage"],
            )
            self._dispatch_event("TIMEOUT_AFTER_BOUNDARY" if code == "timeout" else "TRANSPORT_ERROR_AFTER_BOUNDARY")
            raise ProviderCallError(
                code, message, retryable,
                safe_diagnostic=diagnostic,
            ) from safe_cause
        # Record the transport boundary before parsing or domain validation. The
        # record contains only bounded request/response metadata and no bodies.
        self._emit_attempt(
            attempt_id=attempt_id, started_at=started_at, started_clock=started_clock,
            request_bytes=request_bytes, message_count=len(payload.get("messages", [])),
            schema_bytes=schema_bytes, structured_output_mode=structured_output_mode,
            exception_at=None, response_headers_observed=True,
            exception_class=None, failure_stage=("provider_http_response" if response.status_code >= 400 else None),
        )
        self._dispatch_event("PROVIDER_HTTP_ERROR_RECEIVED" if response.status_code >= 400 else "PROVIDER_RESPONSE_RECEIVED")
        if used_response_format and response.status_code in {400, 422}:
            # The caller owns retry accounting.  Mark this adapter instance so
            # its next globally-budgeted attempt uses plain completion.
            self._use_response_format = False
            raise ProviderCallError(
                "structured_output_unsupported",
                "Provider rejected native structured output.",
                True,
                safe_diagnostic=self._response_diagnostic(
                    response, source="UPSTREAM_HTTP_ERROR", provider_error_code="NO_UPSTREAM_ERROR_CODE"
                ),
            )
        if response.status_code >= 400:
            raise self._error_for_status(response)
        self.last_safe_diagnostic = {
            "provider_request_started": True,
            "provider_request_completed": True,
            "upstream_response_received": True,
            "upstream_http_status": response.status_code,
            "upstream_request_id": next(
                (response.headers[name][:120] for name in ("x-request-id", "request-id") if response.headers.get(name)),
                None,
            ),
            "upstream_error_code": "NO_UPSTREAM_ERROR_CODE",
            "provider_exception_class": None,
            "provider_failure_stage": None,
            "retry_after_present": "retry-after" in response.headers,
            "response_content_type": response.headers.get("content-type", "").split(";", 1)[0].strip() or None,
            "response_body_length": len(response.content),
        }
        body = self._decode_response_body(response, structured=structured)
        # Internal transport metadata used only for safe diagnostics; never persisted verbatim.
        body["_http_status"] = response.status_code
        if isinstance(body.get("choices"), list) and body["choices"]:
            first = body["choices"][0]
            message = first.get("message") if isinstance(first, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            self.last_safe_diagnostic.update({
                "finish_reason": first.get("finish_reason") if isinstance(first, dict) else None,
                "choices_count": len(body["choices"]),
                "content_present": isinstance(content, str) and bool(content),
                "content_length": len(content) if isinstance(content, str) else 0,
            })
        if structured:
            self.last_safe_diagnostic["safe_response_shape"] = safe_reference_shape(body)
            self._refresh_attempt_shape()
        return body

    def _refresh_attempt_shape(self) -> None:
        """Update the durable attempt row without exposing response content."""
        if self._last_attempt_record_args is not None:
            self._emit_attempt(**self._last_attempt_record_args)

    def _emit_attempt(
        self, *, attempt_id: str, started_at: datetime, started_clock: float,
        request_bytes: int, message_count: int, schema_bytes: int,
        structured_output_mode: str, exception_at: datetime | None,
        response_headers_observed: bool, exception_class: str | None,
        failure_stage: str | None,
    ) -> None:
        self._last_attempt_record_args = {
            "attempt_id": attempt_id,
            "started_at": started_at,
            "started_clock": started_clock,
            "request_bytes": request_bytes,
            "message_count": message_count,
            "schema_bytes": schema_bytes,
            "structured_output_mode": structured_output_mode,
            "exception_at": exception_at,
            "response_headers_observed": response_headers_observed,
            "exception_class": exception_class,
            "failure_stage": failure_stage,
        }
        record = {
            "generation_intent_id": self._generation_intent_id,
            "generation_run_id": self._generation_run_id,
            "provider_attempt_id": attempt_id,
            "model_id": self.model,
            "request_body_bytes": request_bytes,
            "message_count": message_count,
            "schema_bytes": schema_bytes,
            "structured_output_mode": structured_output_mode,
            "effective_timeout": {
                "timeout_seconds": self._timeout_seconds,
                **self._effective_timeout,
            },
            "started_at": started_at.isoformat(),
            "exception_at": exception_at.isoformat() if exception_at else None,
            "elapsed_ms": max(0, int(round((perf_counter() - started_clock) * 1000))),
            "response_headers_observed": response_headers_observed,
            "exception_class": exception_class,
            "failure_stage": failure_stage,
            "safe_response_shape": self.last_safe_diagnostic.get("safe_response_shape", {}),
        }
        if self._attempt_observer is not None:
            try:
                self._attempt_observer(record)
            except Exception:
                # Observability must never turn a provider failure into a secret-
                # bearing exception or alter the established user-facing error.
                pass

    @staticmethod
    def _error_for_status(response: httpx.Response) -> ProviderCallError:
        status_code = response.status_code
        mapping = {
            400: ("invalid_request", "Provider rejected the request format.", False),
            401: ("unauthorized", "Provider authentication was rejected.", False),
            402: ("quota_exhausted", "Provider quota or billing limit was reached.", False),
            404: ("model_not_found", "Configured provider model was not found.", False),
            429: ("rate_limited", "Provider rate limit was reached; retry later.", True),
        }
        code, message, retryable = mapping.get(status_code, ("provider_error", "Provider request failed.", status_code >= 500))
        return ProviderCallError(
            code, message, retryable,
            safe_diagnostic=ModelAdapter._response_diagnostic(
                response,
                source=f"UPSTREAM_HTTP_{status_code}" if status_code == 503 else "UPSTREAM_HTTP_ERROR",
                provider_error_code=ModelAdapter._safe_error_code(response),
            ),
        )

    @staticmethod
    def _safe_error_code(response: httpx.Response) -> str:
        """Extract a bounded scalar code without retaining provider body content."""
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return "NO_UPSTREAM_ERROR_CODE"
        values: list[Any] = []
        if isinstance(payload, dict):
            values.extend([payload.get("code"), payload.get("error_code")])
            error = payload.get("error")
            if isinstance(error, dict):
                values.extend([error.get("code"), error.get("type")])
        for value in values:
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", value):
                return value
        return "NO_UPSTREAM_ERROR_CODE"

    @staticmethod
    def _response_diagnostic(
        response: httpx.Response, *, source: str, provider_error_code: str
    ) -> dict[str, Any]:
        retry_after: int | float | None = None
        raw_retry_after = response.headers.get("retry-after")
        if raw_retry_after:
            try:
                value = float(raw_retry_after.strip())
                if 0 <= value <= 86400:
                    retry_after = int(value) if value.is_integer() else value
            except ValueError:
                pass
        return {
            "provider_error_source": source,
            "provider_error_code": provider_error_code,
            "provider_http_status": response.status_code,
            "provider_exception_class": None,
            "provider_failure_stage": "provider_http_response",
            "provider_retryable": response.status_code >= 500 or response.status_code == 429,
            "provider_retry_after_seconds_if_present": retry_after,
            "response_content_type": response.headers.get("content-type", "").split(";", 1)[0].strip() or None,
            "response_body_length": len(response.content),
        }

    def compare_competitors(
        self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None
    ) -> CompetitorComparisonDraft:
        return self._generate(
            output_model=CompetitorComparisonDraft,
            system=(
                "Compare only supplied user-provided candidate products. Return structured analysis. "
                "Do not invent URLs, prices, users, market share, research, or official facts; use 暂未确认."
            ),
            user=json.dumps({"candidates": candidates, "project_context": project_context}, ensure_ascii=False),
        )

    def generate_ai_reference(self, context: dict[str, Any]) -> AIReferenceDraft:
        return self._generate(
            output_model=AIReferenceDraft,
            system=(
                "Provide conservative brainstorming suggestions for a product idea. "
                "Return only structured JSON. Do not invent research, official facts, "
                "statistics, sources, URLs, or user interviews; keep every suggestion "
                "as an unverified hypothesis. "
                + AI_REFERENCE_GENERATION_INSTRUCTION
            ),
            user=json.dumps(context, ensure_ascii=False),
        )

    def generate_evidence_guidance(self, context: dict[str, Any]) -> EvidenceGuidanceDraft:
        return self._generate(
            output_model=EvidenceGuidanceDraft,
            system=(
                "Generate concrete evidence action cards for the supplied product context. "
                "Return only structured JSON. Do not browse, invent URLs or sources, claim user research, "
                "or present AI suggestions as verified facts. Every card must say what to validate, who or "
                "where to find, concrete action steps, acceptable artifacts, a fill template, decision impact, "
                "fallback if unavailable, and limitations."
            ),
            user=json.dumps(context, ensure_ascii=False),
        )

    def _output_contract_failure(
        self, raw: bytes, *, classification: str, code: str = "malformed_response",
    ) -> ProviderCallError:
        diagnostic = {
            "output_sha256": hashlib.sha256(raw).hexdigest(),
            "output_byte_count": len(raw),
            "output_classification": classification,
        }
        self.last_safe_diagnostic.update(diagnostic)
        return ProviderCallError(
            code, StructuredOutputContractError.message, False,
            safe_diagnostic=diagnostic,
        )

    def _decode_response_body(self, response: httpx.Response, *, structured: bool) -> dict[str, Any]:
        body: Any = None
        try:
            body = response.json()
        except ValueError:
            pass
        # Raise outside the handler: even `from None` retains the raw context.
        if not isinstance(body, dict):
            if structured:
                raise self._output_contract_failure(response.content, classification="invalid_envelope")
            raise ProviderCallError("malformed_response", "Provider returned an invalid response shape.", False)
        if structured:
            # Validate the envelope while its original bytes are available, before
            # transport metadata is added or JSON spelling/whitespace is lost.
            content: str | None = None
            if "error" not in body:
                try:
                    content = self._content_from_response(body)
                except ProviderCallError:
                    pass
            if content is None:
                raise self._output_contract_failure(
                    response.content,
                    classification="provider_error" if "error" in body else "invalid_envelope",
                )
        return body

    def _normalize_structured_output(self, content: str) -> dict[str, Any]:
        """Accept exactly one object, optionally inside a JSON or unlabelled fence."""
        raw = content.encode("utf-8")
        normalized = content.strip().lstrip("\ufeff").strip()
        self.last_safe_diagnostic.update({
            "structured_payload_found": False,
            "json_parse_success": False,
            "schema_validation_success": False,
        })
        if not normalized:
            raise self._output_contract_failure(raw, classification="empty_output")
        fence = re.fullmatch(r"```(?:json)?[ \t]*\r?\n(.*?)\r?\n```", normalized, re.DOTALL)
        if fence is not None:
            normalized = fence.group(1).strip()
        parsed: Any = None
        malformed = False
        try:
            parsed = json.loads(normalized)
        except ValueError:
            malformed = True
        self.last_safe_diagnostic["json_parse_success"] = not malformed
        if malformed:
            raise self._output_contract_failure(raw, classification="invalid_json")
        if not isinstance(parsed, dict):
            raise self._output_contract_failure(raw, classification="non_object")
        if "error" in parsed:
            raise self._output_contract_failure(raw, classification="provider_error")
        self.last_safe_diagnostic["structured_payload_found"] = True
        return parsed

    def _validate_structured_response(self, body: dict[str, Any], output_model: type[_Model]) -> _Model:
        content = self._content_from_response(body)
        parsed = self._normalize_structured_output(content)
        validated: _Model | None = None
        try:
            validated = output_model.model_validate(parsed)
        except ValidationError:
            pass
        self.last_safe_diagnostic["safe_response_shape"] = safe_reference_shape(
            body, parsed, model=validated
        )
        self._refresh_attempt_shape()
        if validated is None:
            raise self._output_contract_failure(
                content.encode("utf-8"), classification="schema_mismatch", code="invalid_content",
            )
        self.last_safe_diagnostic["schema_validation_success"] = True
        if isinstance(parsed.get("candidates"), list):
            self.last_safe_diagnostic["raw_candidate_count"] = len(parsed["candidates"])
        return validated

    def _content_from_response(self, body: dict[str, Any]) -> str:
        malformed = False
        content: Any = None
        try:
            if self.protocol == "openai_chat_completions":
                content = body["choices"][0]["message"]["content"]
            else:
                blocks = body["content"]
                if not isinstance(blocks, list):
                    raise TypeError
                content = None
                for block in blocks:
                    if not isinstance(block, dict):
                        raise TypeError
                    if block.get("type") == "text":
                        content = block.get("text")
                        break
        except (KeyError, IndexError, StopIteration, TypeError):
            malformed = True
        if malformed:
            raise ProviderCallError(
                "malformed_response",
                "Provider returned an invalid response shape.",
                False,
            )
        if not isinstance(content, str):
            raise ProviderCallError("malformed_response", "Provider returned an invalid response shape.", False)
        return content

    @staticmethod
    def extract_safe_chat_response_shape(body: dict[str, Any]) -> dict[str, Any]:
        choices = body.get("choices")
        choices_count = len(choices) if isinstance(choices, list) else 0
        first = choices[0] if choices_count else None
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
        model = body.get("model")
        return {
            "http_status": body.get("_http_status") if isinstance(body.get("_http_status"), int) else None,
            "choices_count": choices_count,
            "finish_reason": finish_reason if isinstance(finish_reason, str) else None,
            "message_present": isinstance(message, dict),
            "content_present": bool(content) if isinstance(content, str) else content is not None,
            "content_type": type(content).__name__ if content is not None else "null",
            "reasoning_content_present": bool(reasoning) if isinstance(reasoning, str) else reasoning is not None,
            "tool_calls_present": bool(tool_calls) if isinstance(tool_calls, list) else tool_calls is not None,
            "usage_present": isinstance(body.get("usage"), dict),
            "model_returned": model.strip()[:240] if isinstance(model, str) and model.strip() else None,
        }


class AsyncModelAdapter(ModelAdapter):
    """Cancellable async counterpart of :class:`ModelAdapter`.

    The provider transport is genuinely async; the overall deadline is owned by
    the coroutine so cancellation reaches httpx rather than blocking a worker
    thread around a synchronous request.
    """

    def __init__(self, *, client: httpx.AsyncClient | None = None,
                 overall_timeout: float | None = None, **kwargs: Any) -> None:
        # Do not construct a synchronous client as a side effect of the async
        # adapter.  The assignments mirror ModelAdapter's validated state.
        provider = kwargs["provider"]
        model = kwargs["model"]
        api_key = kwargs["api_key"]
        protocol = kwargs.get("protocol")
        base_url = kwargs.get("base_url")
        self.preset = ProviderRegistry.resolve(provider, protocol=protocol, base_url=base_url)
        if not str(model).strip():
            raise ProviderConfigurationError("Model ID is required.")
        if not str(api_key).strip():
            raise ProviderConfigurationError("Provider credential is required.")
        self.provider = self.preset.provider
        self.protocol = self.preset.protocol
        self.base_url = self.preset.default_base_url
        self.model = model.strip()
        self._api_key = api_key
        effective_timeout = kwargs.get("timeout") or DEFAULT_PROVIDER_TIMEOUT
        self._timeout = effective_timeout if isinstance(effective_timeout, httpx.Timeout) else httpx.Timeout(float(effective_timeout))
        self._effective_timeout = _timeout_metadata(effective_timeout)
        self._timeout_seconds = self._effective_timeout["overall_timeout_seconds"]
        self._overall_timeout = float(overall_timeout if overall_timeout is not None else self._effective_timeout["overall_timeout_seconds"])
        self._attempt_observer = kwargs.get("attempt_observer")
        self._generation_intent_id = kwargs.get("generation_intent_id")
        self._generation_run_id = kwargs.get("generation_run_id")
        self._dispatch_ledger = kwargs.get("dispatch_ledger")
        self._dispatch_control = kwargs.get("dispatch_control")
        self._dispatch_permit_id = kwargs.get("dispatch_permit_id")
        self._use_response_format = True
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=self._timeout)
        self.last_safe_diagnostic: dict[str, Any] = {}

    async def aclose(self) -> None:
        if not self._client.is_closed:
            await self._client.aclose()

    async def __aenter__(self) -> "AsyncModelAdapter":
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        await self.aclose()

    async def interpret_idea_async(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return await self._generate_async(
            output_model=IdeaBriefDraft,
            system="Interpret this product idea conservatively. Return only JSON matching the requested schema. Keep provenance explicit and do not claim market validation.",
            user=json.dumps(request.model_dump(mode="json"), ensure_ascii=False),
        )

    async def design_solutions_async(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        return await self._generate_async(
            output_model=SolutionSetDraft,
            system="Generate exactly 3 materially different solutions. Return only JSON matching the requested schema. Do not make unsupported market claims.",
            user=brief.model_dump_json(),
        )

    async def compare_competitors_async(
        self, candidates: list[dict[str, Any]]
    ) -> CompetitorComparisonDraft:
        return await self._generate_async(
            output_model=CompetitorComparisonDraft,
            system=(
                "Compare only supplied user-provided candidate products. Return only JSON matching "
                "the requested schema. Keep source-backed facts, user input, AI analysis, and uncertainty "
                "separate; do not invent URLs, prices, usage figures, market claims, or research findings."
            ),
            user=json.dumps({"candidates": candidates}, ensure_ascii=False),
        )

    async def generate_ai_reference_async(self, context: dict[str, Any]) -> AIReferenceDraft:
        return await self._generate_async(
            output_model=AIReferenceDraft,
            system=(
                "Provide conservative brainstorming suggestions for a product idea. "
                "Return only structured JSON. Do not invent research, official facts, "
                "statistics, sources, URLs, or user interviews; keep every suggestion "
                "as an unverified hypothesis. "
                + AI_REFERENCE_GENERATION_INSTRUCTION
            ),
            user=json.dumps(context, ensure_ascii=False),
        )

    async def generate_evidence_guidance_async(self, context: dict[str, Any]) -> EvidenceGuidanceDraft:
        return await self._generate_async(
            output_model=EvidenceGuidanceDraft,
            system=(
                "Generate concrete evidence action cards for the supplied product context. "
                "Return only structured JSON. Do not browse, invent URLs or sources, claim user research, "
                "or present AI suggestions as verified facts. Every card must include concrete steps, "
                "acceptable artifacts, a fill template, decision impact, fallback, and limitations."
            ),
            user=json.dumps(context, ensure_ascii=False),
        )

    async def _generate_async(self, *, output_model: type[_Model], system: str, user: str) -> _Model:
        body = await self._request_async(system=system, user=user, structured=True, output_model=output_model)
        return self._validate_structured_response(body, output_model)

    async def _request_async(self, *, system: str, user: str, structured: bool,
                             max_tokens: int | None = None, live: bool = False,
                             output_model: type[_Model] | None = None) -> dict[str, Any]:
        if self.protocol != "openai_chat_completions":
            raise ProviderCallError("unsupported_protocol", "Configured provider protocol is unsupported.", False)
        self.last_safe_diagnostic = {}
        endpoint = "/chat/completions"
        headers = {"Authorization": f"Bearer {self._api_key}"}
        payload: dict[str, Any] = {"model": self.model, "messages": ([{"role": "user", "content": user}] if not system.strip() else [{"role": "system", "content": system}, {"role": "user", "content": user}])}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if live:
            payload["stream"] = False
        if structured and self.provider == "qwen":
            payload["enable_thinking"] = False
        if structured and self._use_response_format:
            if self.provider == "qwen" and output_model is not None:
                payload["response_format"] = {"type": "json_schema", "json_schema": {"name": output_model.__name__, "strict": True, "schema": output_model.model_json_schema()}}
            else:
                payload["response_format"] = {"type": "json_object"}
        attempt_id = str(uuid.uuid4())
        self._last_attempt_id = attempt_id
        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()
        request_bytes = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        response_format = payload.get("response_format")
        schema_bytes = len(json.dumps(response_format, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) if response_format else 0
        structured_output_mode = "json_schema" if isinstance(response_format, dict) and response_format.get("type") == "json_schema" else "json_object" if response_format else "none"
        try:
            self._before_network()
            async with asyncio.timeout(self._overall_timeout):
                response = await self._client.post(f"{self.base_url}{endpoint}", headers=headers, json=payload)
        except asyncio.TimeoutError as exc:
            self._dispatch_event("TIMEOUT_AFTER_BOUNDARY")
            diagnostic = {"provider_request_started": True, "provider_request_completed": False, "upstream_response_received": False, "provider_error_source": "APPLICATION_OVERALL_DEADLINE", "provider_error_code": "NO_UPSTREAM_ERROR_CODE", "provider_http_status": None, "provider_exception_class": "TimeoutError", "provider_failure_stage": "application_overall_deadline", "provider_retryable": True, "provider_retry_after_seconds_if_present": None}
            self.last_safe_diagnostic = diagnostic
            self._emit_attempt(attempt_id=attempt_id, started_at=started_at, started_clock=started_clock, request_bytes=request_bytes, message_count=len(payload["messages"]), schema_bytes=schema_bytes, structured_output_mode=structured_output_mode, exception_at=datetime.now(timezone.utc), response_headers_observed=False, exception_class="TimeoutError", failure_stage="application_overall_deadline")
            raise ProviderCallError("timeout", "Provider request timed out.", True, safe_diagnostic=diagnostic) from exc
        except httpx.TimeoutException as exc:
            self._dispatch_event("TIMEOUT_AFTER_BOUNDARY")
            subtype = type(exc).__name__
            stage = {"ConnectTimeout": "connect", "ReadTimeout": "read", "WriteTimeout": "write", "PoolTimeout": "pool"}.get(subtype, "unknown")
            safe_cause = type(exc)("Provider transport timeout.")
            diagnostic = {"provider_request_started": True, "provider_request_completed": False, "upstream_response_received": False, "provider_error_source": f"UPSTREAM_TIMEOUT_{stage.upper()}", "provider_error_code": "NO_UPSTREAM_ERROR_CODE", "provider_http_status": None, "provider_exception_class": subtype, "provider_failure_stage": f"provider_transport_{stage}", "provider_retryable": True, "provider_retry_after_seconds_if_present": None}
            self.last_safe_diagnostic = diagnostic
            self._emit_attempt(attempt_id=attempt_id, started_at=started_at, started_clock=started_clock, request_bytes=request_bytes, message_count=len(payload["messages"]), schema_bytes=schema_bytes, structured_output_mode=structured_output_mode, exception_at=datetime.now(timezone.utc), response_headers_observed=False, exception_class=subtype, failure_stage=f"provider_transport_{stage}")
            raise ProviderCallError("timeout", "Provider request timed out.", True, safe_diagnostic=diagnostic) from safe_cause
        except httpx.RequestError as exc:
            self._dispatch_event("TRANSPORT_ERROR_AFTER_BOUNDARY")
            diagnostic = {"provider_request_started": True, "provider_request_completed": False, "upstream_response_received": False, "provider_error_source": "UPSTREAM_CONNECTION_FAILURE", "provider_error_code": "NO_UPSTREAM_ERROR_CODE", "provider_http_status": None, "provider_exception_class": type(exc).__name__, "provider_failure_stage": "provider_transport", "provider_retryable": True}
            self.last_safe_diagnostic = diagnostic
            self._emit_attempt(attempt_id=attempt_id, started_at=started_at, started_clock=started_clock, request_bytes=request_bytes, message_count=len(payload["messages"]), schema_bytes=schema_bytes, structured_output_mode=structured_output_mode, exception_at=datetime.now(timezone.utc), response_headers_observed=False, exception_class=type(exc).__name__, failure_stage="provider_transport")
            raise ProviderCallError("network_error", "Provider request could not be completed.", True, safe_diagnostic=diagnostic) from exc
        self._emit_attempt(attempt_id=attempt_id, started_at=started_at, started_clock=started_clock, request_bytes=request_bytes, message_count=len(payload["messages"]), schema_bytes=schema_bytes, structured_output_mode=structured_output_mode, exception_at=None, response_headers_observed=True, exception_class=None, failure_stage="provider_http_response" if response.status_code >= 400 else None)
        self._dispatch_event("PROVIDER_HTTP_ERROR_RECEIVED" if response.status_code >= 400 else "PROVIDER_RESPONSE_RECEIVED")
        if response.status_code >= 400:
            raise self._error_for_status(response)
        self.last_safe_diagnostic = {"provider_request_started": True, "provider_request_completed": True, "upstream_response_received": True, "upstream_http_status": response.status_code, "upstream_request_id": next((response.headers[name][:120] for name in ("x-request-id", "request-id") if response.headers.get(name)), "NO_UPSTREAM_REQUEST_ID"), "upstream_error_code": "NO_UPSTREAM_ERROR_CODE", "provider_exception_class": None, "provider_failure_stage": None, "retry_after_present": "retry-after" in response.headers, "response_body_length": len(response.content)}
        body = self._decode_response_body(response, structured=structured)
        body["_http_status"] = response.status_code
        if isinstance(body.get("choices"), list) and body["choices"]:
            first = body["choices"][0]
            message = first.get("message") if isinstance(first, dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            self.last_safe_diagnostic.update({"finish_reason": first.get("finish_reason") if isinstance(first, dict) else None, "choices_count": len(body["choices"]), "content_present": isinstance(content, str) and bool(content), "content_length": len(content) if isinstance(content, str) else 0})
        if structured:
            self.last_safe_diagnostic["safe_response_shape"] = safe_reference_shape(body)
            self._refresh_attempt_shape()
        return body
