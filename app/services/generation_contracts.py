"""Domain completeness and explicit public DTOs for generated surfaces.

Schema parsing is not a completeness check. These gates also revalidate model
instances (including model_copy/model_construct) before anything is persisted.
"""
from __future__ import annotations

import json
import re
from typing import Any, Awaitable, Callable, TypeVar

from pydantic import BaseModel, ValidationError

from app.errors import StructuredOutputContractError, public_recovery_payload
from app.schemas import AIReferenceDraft, EvidenceGuidanceDraft, SolutionCandidateDraft
from app.services.safe_fixture import SAFE_FIXTURE_DISCLOSURE


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


def _safe_shape_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _safe_shape_fields(value: dict[str, Any]) -> tuple[list[str], dict[str, str], dict[str, int]]:
    keys = sorted(str(key) for key in value)
    types = {key: _safe_shape_type(value[key]) for key in keys}
    lengths = {
        key: len(value[key])
        for key in keys
        if isinstance(value[key], (str, list, dict))
    }
    return keys, types, lengths


def safe_reference_shape(
    provider_response: Any,
    parsed_payload: Any = None,
    *,
    model: AIReferenceDraft | None = None,
) -> dict[str, Any]:
    """Return structure-only AI Reference diagnostics; never retain field values."""
    choices = provider_response.get("choices") if isinstance(provider_response, dict) else None
    choices_count = len(choices) if isinstance(choices, list) else 0
    message = None
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        message = choices[0].get("message")
    message_present = isinstance(message, dict)
    content_present = message_present and "content" in message
    content = message.get("content") if content_present else None
    content_type = _safe_shape_type(content) if content_present else None
    content_length = len(content) if isinstance(content, str) else None

    parsed = parsed_payload
    parse_attempted = False
    parse_success = False
    if parsed is None and isinstance(content, str) and content.strip():
        parse_attempted = True
        try:
            candidate = json.loads(content.lstrip("\ufeff").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            candidate = None
        if isinstance(candidate, dict):
            parsed = candidate
            parse_success = True
    elif isinstance(parsed, dict):
        parse_attempted = True
        parse_success = True
    parsed_shape: dict[str, Any] = {
        "json_parse_attempted": parse_attempted,
        "json_parse_success": parse_success,
        "parsed_top_level_type": _safe_shape_type(parsed) if parsed is not None else None,
        "top_level_keys": [],
        "field_types": {},
        "field_lengths": {},
        "recognized_reference_fields_present": [],
        "recognized_reference_fields_nonempty": [],
        "unknown_top_level_keys": [],
    }
    if isinstance(parsed, dict):
        keys, types, lengths = _safe_shape_fields(parsed)
        recognized = [key for key in keys if key in REFERENCE_FIELDS]
        nonempty = [key for key in recognized if bool(parsed.get(key))]
        parsed_shape.update(
            top_level_keys=keys,
            field_types=types,
            field_lengths=lengths,
            recognized_reference_fields_present=recognized,
            recognized_reference_fields_nonempty=nonempty,
            unknown_top_level_keys=[key for key in keys if key not in REFERENCE_FIELDS],
        )

    schema_attempted = parsed is not None
    schema_pass = False
    completeness_pass = False
    normalized_shape: dict[str, Any] = {
        "top_level_keys": [], "field_types": {}, "field_lengths": {},
    }
    if model is None and isinstance(parsed, dict):
        try:
            model = AIReferenceDraft.model_validate(parsed)
        except (ValidationError, TypeError):
            model = None
    if isinstance(model, AIReferenceDraft):
        schema_pass = True
        normalized = {field: getattr(model, field, None) for field in AIReferenceDraft.model_fields}
        keys, types, lengths = _safe_shape_fields(normalized)
        normalized_shape = {"top_level_keys": keys, "field_types": types, "field_lengths": lengths}
        completeness_pass = bool(any(getattr(model, key) for key in REFERENCE_FIELDS)) and all(
            _items(getattr(model, key), required=False) for key in REFERENCE_FIELDS
        )
    return {
        "provider_response_shape": {
            "choices_count": choices_count,
            "message_present": message_present,
            "message_content_present": content_present,
            "message_content_type": content_type,
            "message_content_char_count": content_length,
        },
        "parsed_payload_shape": parsed_shape,
        "normalized_ai_reference_shape": normalized_shape,
        "schema_stage": {
            "ai_reference_schema_attempted": schema_attempted,
            "ai_reference_schema_pass": schema_pass,
        },
        "completeness_stage": {
            "completeness_attempted": schema_pass,
            "completeness_pass": completeness_pass,
        },
        "reference_fields": list(REFERENCE_FIELDS),
    }
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
MATERIAL_DIFFERENCE_FIELDS = (
    "mechanism", "summary", "why_fit", "user_flow", "mvp_pages", "features",
    "inputs", "outputs", "decision_logic", "data_requirements",
    "technical_components", "implementation_plan", "acceptance_cases", "risks",
    "unknowns",
)


def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {key: _plain(getattr(value, key, None)) for key in type(value).model_fields}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


_RAW_GENERATION_MARKERS = re.compile(
    r"\b(?:choices|messages)\b[\"']?\s*:\s*[\[{]"
    r"|\b(?:provider[_ -]?(?:payload|response|raw)|raw[_ -]?(?:response|output|payload)|"
    r"debug[_ -]?(?:prompt|payload|trace)|system[_ -]?prompt|api[_ -]?key)\b[\"']?\s*[:=]"
    r"|\bAuthorization[\"']?\s*:\s*[\"']?Bearer\s+\S+"
    r"|\{(?=[^{}]*[\"']type[\"']\s*:\s*[\"']message[\"'])"
    r"(?=[^{}]*[\"']role[\"']\s*:\s*[\"']assistant[\"'])"
    r"|Traceback\s*\(most recent call last\)"
    r"|\bValidationError\s*:",
    re.IGNORECASE,
)


def reject_raw_generation_values(value: Any) -> None:
    """Reject recognizable transport/debug dumps, not ordinary JSON or prose.

    This is a value gate in addition to schema/field projection, not a general
    secret detector. Never include the rejected value in an exception.
    """
    if isinstance(value, str):
        if _RAW_GENERATION_MARKERS.search(value):
            raise GenerationContractError("RAW_GENERATION_VALUE")
    elif isinstance(value, (list, tuple)):
        for item in value:
            reject_raw_generation_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            reject_raw_generation_values(item)


def parse_generation(schema: type[T], value: Any) -> T:
    value = _plain(value)
    reject_raw_generation_values(value)
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


def _material_difference_value(value: Any) -> str:
    normalized = _plain(value)
    if isinstance(normalized, (list, dict)):
        return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return " ".join(str(normalized or "").split()).casefold()


def _material_difference_count(left: Any, right: Any) -> int:
    """Count differences in user-visible solution substance, not implementation knobs."""
    return sum(
        _material_difference_value(getattr(left, field, None))
        != _material_difference_value(getattr(right, field, None))
        for field in MATERIAL_DIFFERENCE_FIELDS
    )


def _project_fields(data: dict[str, Any], *, text: tuple[str, ...] = (), lists: tuple[str, ...] = (), flags: tuple[str, ...] = ()) -> dict[str, Any]:
    reject_raw_generation_values([data.get(key) for key in (*text, *lists)])
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
    validate_reference({key: data[key] for key in (*REFERENCE_FIELDS, "uncertainty_notice") if key in data})
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
    cards = data.get("cards")
    validate_guidance({
        "cards": [{key: card[key] for key in (*CARD_TEXT_FIELDS, *CARD_LIST_FIELDS) if key in card}
                  if isinstance(card, dict) else card for card in cards] if isinstance(cards, list) else cards,
        **({"disclosure": data["disclosure"]} if "disclosure" in data else {}),
    })
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
            if _material_difference_count(left, right) < 2:
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


def validate_solution_response(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise GenerationContractError("SURFACE_SCHEMA_FAILED")
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 3 or not all(isinstance(row, dict) for row in candidates):
        raise GenerationContractError("SOLUTION_SET_CARDINALITY_FAILED")
    # Public rows carry IDs in addition to the domain fields; never parse raw extras.
    drafts = [{key: row[key] for key in (*SOLUTION_TEXT_FIELDS, *SOLUTION_LIST_FIELDS, *SOLUTION_BOOL_FIELDS) if key in row}
              for row in candidates if isinstance(row, dict)] if isinstance(candidates, list) else []
    normalized = validate_solutions(drafts, llm_core_required=True)
    result = solution_public(data)
    result["candidates"] = [
        candidate_public({**row, **_plain(candidate)})
        for row, candidate in zip(candidates, normalized)
    ]
    return result


def validate_document_draft(data: Any) -> dict[str, Any]:
    """Check the envelope before regex/claim consumers; evidence stays optional."""
    reject_raw_generation_values(data)
    if not isinstance(data, dict) or not _text(data.get("content")) or not _items(data.get("citations"), required=False):
        raise GenerationContractError("DOCUMENT_SCHEMA_FAILED")
    claims = data.get("claims", [])
    if not isinstance(claims, list) or not all(isinstance(claim, dict) for claim in claims):
        raise GenerationContractError("DOCUMENT_SCHEMA_FAILED")
    for claim in claims:
        evidence = claim.get("evidence", [])
        metadata = claim.get("metadata", {})
        if not isinstance(evidence, list) or not all(isinstance(link, dict) for link in evidence) or not isinstance(metadata, dict):
            raise GenerationContractError("DOCUMENT_SCHEMA_FAILED")
        if not _items(metadata.get("expected_source_types", []), required=False):
            raise GenerationContractError("DOCUMENT_SCHEMA_FAILED")
    return {"content": data["content"], "citations": data["citations"], "claims": claims}


def failure_public(data: dict[str, Any]) -> dict[str, Any]:
    # Persisted text is untrusted too: use the same typed copy as live errors.
    result = {}
    for key, allowed in (
        ("quota_status", ("RESERVED", "RELEASED", "CHARGED")),
        ("failure_stage", ("provider_transport", "provider_transport_connect", "provider_transport_read",
                           "provider_transport_write", "provider_transport_pool", "provider_http_response",
                           "application_overall_deadline")),
    ):
        if data.get(key) in allowed:
            result[key] = data[key]
    if data.get("fixture_origin") == "STAGE_A_SYNTHETIC":
        result.update(fixture_origin="STAGE_A_SYNTHETIC", fixture_disclosure=SAFE_FIXTURE_DISCLOSURE)
    result.update(public_recovery_payload(data.get("error_code"), retryable=data.get("retryable")))
    return result


def validate_document_sections(content: Any, headings: list[str]) -> None:
    reject_raw_generation_values(content)
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
