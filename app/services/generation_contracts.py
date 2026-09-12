"""Domain completeness and explicit public DTOs for generated surfaces.

Schema parsing is not a completeness check. These gates also revalidate model
instances (including model_copy/model_construct) before anything is persisted.
"""
from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.errors import StructuredOutputContractError
from app.schemas import AIReferenceDraft, EvidenceGuidanceDraft, SolutionCandidateDraft


class GenerationContractError(StructuredOutputContractError, ValueError):
    """Safe domain rejection; the reason is a constant, never provider content."""

    def __init__(self, reason: str):
        super().__init__(safe_diagnostic={"domain_reason": reason})
        self.args = (reason,)


T = TypeVar("T", bound=BaseModel)
REFERENCE_FIELDS = (
    "possible_target_users", "possible_scenarios", "possible_user_problems",
    "missing_information", "mvp_thoughts", "questions_to_validate", "research_directions",
)
CARD_TEXT_FIELDS = (
    "title", "question_to_validate", "why_it_matters", "decision_impact",
    "fallback_if_unavailable", "limitations",
)
CARD_LIST_FIELDS = (
    "who_or_where", "action_steps", "suggested_questions", "acceptable_artifacts", "fill_template",
)
SOLUTION_LIST_FIELDS = (
    "user_flow", "mvp_pages", "features", "inputs", "outputs", "decision_logic",
    "data_requirements", "technical_components", "implementation_plan", "acceptance_cases",
    "risks", "unknowns",
)
SOLUTION_TEXT_FIELDS = (
    "title", "mechanism", "summary", "why_fit", "complexity", "provenance",
    "required_data_class", "automation_level", "human_role", "core_decision_logic", "major_dependency",
)
SOLUTION_BOOL_FIELDS = ("requires_llm_runtime", "requires_rag_runtime", "requires_agent_runtime")
DIVERSITY_FIELDS = (
    "mechanism", "required_data_class", "automation_level", "human_role",
    "core_decision_logic", "major_dependency",
)


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {key: _plain(getattr(value, key, None)) for key in type(value).model_fields}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def parse_generation(schema: type[T], value: Any) -> T:
    parsed = None
    try:
        parsed = schema.model_validate(_plain(value))
    except (ValidationError, TypeError):
        pass
    # Raise outside the handler: even __context__ must not retain input dumps.
    if parsed is None:
        raise GenerationContractError("SURFACE_SCHEMA_FAILED")
    return parsed


def call_generation(call: Callable[[], Any]) -> Any:
    failed = False
    try:
        result = call()
    except ValidationError:
        failed = True
    if failed:
        raise GenerationContractError("SURFACE_SCHEMA_FAILED")
    return result


async def await_generation(call: Awaitable[Any]) -> Any:
    failed = False
    try:
        result = await call
    except ValidationError:
        failed = True
    if failed:
        raise GenerationContractError("SURFACE_SCHEMA_FAILED")
    return result


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _items(value: Any, *, required: bool = True) -> bool:
    return isinstance(value, list) and (bool(value) or not required) and all(_text(item) for item in value)


def _project_fields(data: dict[str, Any], *, text: tuple[str, ...] = (), lists: tuple[str, ...] = (), flags: tuple[str, ...] = ()) -> dict[str, Any]:
    result = {key: data[key] for key in text if isinstance(data.get(key), str) or (key in data and data[key] is None)}
    result.update({key: data[key] for key in lists if _items(data.get(key), required=False)})
    result.update({key: data[key] for key in flags if type(data.get(key)) in (bool, int) and data[key] in (0, 1)})
    return result


def validate_reference(value: Any) -> AIReferenceDraft:
    parsed = parse_generation(AIReferenceDraft, value)
    if not any(getattr(parsed, key) for key in REFERENCE_FIELDS) or not all(
        _items(getattr(parsed, key), required=False) for key in REFERENCE_FIELDS
    ):
        raise GenerationContractError("AI_REFERENCE_INCOMPLETE")
    return parsed


def reference_public(value: Any) -> dict[str, Any]:
    data = _plain(value)
    return _project_fields(data, lists=REFERENCE_FIELDS, text=("uncertainty_notice", "fixture_origin", "fixture_disclosure"))


def validate_guidance(value: Any) -> EvidenceGuidanceDraft:
    parsed = parse_generation(EvidenceGuidanceDraft, value)
    if not parsed.cards or any(
        not all(_text(getattr(card, key)) for key in CARD_TEXT_FIELDS)
        or not all(_items(getattr(card, key), required=key != "suggested_questions") for key in CARD_LIST_FIELDS)
        for card in parsed.cards
    ):
        raise GenerationContractError("EVIDENCE_CARD_INCOMPLETE")
    return parsed


def guidance_public(value: Any) -> dict[str, Any]:
    data = _plain(value)
    result = _project_fields(data, text=("disclosure", "fixture_origin", "fixture_disclosure"))
    result["cards"] = [
        _project_fields(card, text=CARD_TEXT_FIELDS, lists=CARD_LIST_FIELDS)
        for card in data.get("cards", []) if isinstance(card, dict)
    ]
    return result


def validate_solutions(candidates: Any, *, llm_core_required: bool) -> list[SolutionCandidateDraft]:
    if not isinstance(candidates, list) or len(candidates) != 3:
        raise GenerationContractError("SOLUTION_SET_CARDINALITY_FAILED")
    parsed = [parse_generation(SolutionCandidateDraft, candidate) for candidate in candidates]
    for candidate in parsed:
        if not all(_text(getattr(candidate, key)) for key in SOLUTION_TEXT_FIELDS) or not all(
            _items(getattr(candidate, key)) for key in SOLUTION_LIST_FIELDS
        ):
            raise GenerationContractError("SOLUTION_INCOMPLETE")
    normalize = lambda value: " ".join(value.split()).casefold()
    if len({normalize(item.title) for item in parsed}) != 3:
        raise GenerationContractError("SOLUTION_DIVERSITY_FAILED")
    for index, left in enumerate(parsed):
        for right in parsed[index + 1:]:
            if sum(normalize(getattr(left, key)) != normalize(getattr(right, key)) for key in DIVERSITY_FIELDS) < 2:
                raise GenerationContractError("SOLUTION_DIVERSITY_FAILED")
    if not llm_core_required and not any(not any(getattr(item, key) for key in SOLUTION_BOOL_FIELDS) for item in parsed):
        raise GenerationContractError("OVERENGINEERED_SOLUTION_SET")
    return parsed


def candidate_public(data: dict[str, Any]) -> dict[str, Any]:
    return _project_fields(data, text=("id", "run_id", "project_id", "created_at", *SOLUTION_TEXT_FIELDS), lists=SOLUTION_LIST_FIELDS, flags=SOLUTION_BOOL_FIELDS)


def solution_public(data: dict[str, Any]) -> dict[str, Any]:
    result = _project_fields(data, text=(
        "fixture_origin", "fixture_disclosure", "requested_model_preference",
        "resolved_model_family", "resolved_model_id",
    ))
    for key in ("run", "latest_run"):
        if isinstance(data.get(key), dict):
            result[key] = _project_fields(data[key], text=(
                "id", "project_id", "idea_brief_id", "status", "created_at",
                "competitor_snapshot_id",
            ), flags=("use_competitor_snapshot",))
    result["candidates"] = [candidate_public(item) for item in data.get("candidates", []) if isinstance(item, dict)]
    return result


def validate_solution_response(data: dict[str, Any]) -> None:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3 or not all(isinstance(row, dict) for row in candidates):
        raise GenerationContractError("SOLUTION_SET_CARDINALITY_FAILED")
    # Public rows carry IDs in addition to the domain fields; never parse raw extras.
    drafts = [{key: row[key] for key in (*SOLUTION_TEXT_FIELDS, *SOLUTION_LIST_FIELDS, *SOLUTION_BOOL_FIELDS) if key in row}
              for row in candidates if isinstance(row, dict)] if isinstance(candidates, list) else []
    validate_solutions(drafts, llm_core_required=True)


def failure_public(data: dict[str, Any]) -> dict[str, Any]:
    # Error producers own fixed messages. No arbitrary diagnostic/nested fields.
    result = {key: data[key] for key in (
        "error_code", "message", "quota_status", "failure_stage", "fixture_origin", "fixture_disclosure",
    ) if isinstance(data.get(key), str)}
    result.setdefault("error_code", "MODEL_OUTPUT_CONTRACT_FAILED")
    result.setdefault("message", StructuredOutputContractError.message)
    if result["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED":
        result["message"] = StructuredOutputContractError.message
    result["recovery_actions"] = data["recovery_actions"] if _items(data.get("recovery_actions")) else ["重新生成"]
    if isinstance(data.get("retryable"), bool):
        result["retryable"] = data["retryable"]
    return result


def validate_document_sections(content: Any, headings: list[str]) -> None:
    if not _text(content):
        raise GenerationContractError("DOCUMENT_INCOMPLETE")
    sections = list(re.finditer(r"^##[ \t]+[^\r\n]+", content, re.MULTILINE))
    for heading in headings:
        matches = [(i, match) for i, match in enumerate(sections) if match.group().strip() == heading]
        if len(matches) != 1:
            raise GenerationContractError("DOCUMENT_INCOMPLETE")
        index, match = matches[0]
        end = sections[index + 1].start() if index + 1 < len(sections) else len(content)
        body = content[match.end():end]
        if not any(line.strip() and not line.lstrip().startswith("#") for line in body.splitlines()):
            raise GenerationContractError("DOCUMENT_INCOMPLETE")
