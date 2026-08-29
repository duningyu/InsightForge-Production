from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from app.errors import StructuredRuntimeUnavailableError
from app.schemas import EvidenceRelationSetDraft, IdeaBriefDraft, QuickStartRequest, SolutionSetDraft

RuntimeMode = Literal["llm_structured", "deterministic_demo"]


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

    def analyze_evidence(
        self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...


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


def build_structured_runtime(
    *,
    mode: RuntimeMode | None = None,
    fixture_path: str | Path | None = None,
    model: str | None = None,
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
    raise StructuredRuntimeUnavailableError(f"UNKNOWN_STRUCTURED_AI_MODE: {selected}")
