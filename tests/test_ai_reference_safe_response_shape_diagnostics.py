import json

import httpx
import pytest

from app.db import Database
from app.schemas import AIReferenceDraft
from app.services.generation_contracts import REFERENCE_FIELDS, safe_reference_shape
from app.services.provider_adapters import ModelAdapter, ProviderCallError
from scripts.stage_b_evaluation_inspect import inspect_provider_attempt


def _envelope(content):
    message = {} if content is ... else {"content": content}
    return {"choices": [{"message": message, "finish_reason": "stop"}]}


def test_safe_shape_captures_provider_and_parsed_reference_metadata_without_values():
    payload = {"possible_target_users": ["学生"], "unknown_advice": "secret marker"}
    result = safe_reference_shape(_envelope(json.dumps(payload, ensure_ascii=False)), payload)

    assert result["provider_response_shape"]["message_content_present"] is True
    assert result["provider_response_shape"]["message_content_type"] == "str"
    assert result["provider_response_shape"]["message_content_char_count"] > 0
    parsed = result["parsed_payload_shape"]
    assert parsed["json_parse_attempted"] is True
    assert parsed["json_parse_success"] is True
    assert parsed["top_level_keys"] == ["possible_target_users", "unknown_advice"]
    assert parsed["field_types"] == {"possible_target_users": "list", "unknown_advice": "str"}
    assert parsed["field_lengths"] == {"possible_target_users": 1, "unknown_advice": len("secret marker")}
    assert parsed["recognized_reference_fields_present"] == ["possible_target_users"]
    assert parsed["recognized_reference_fields_nonempty"] == ["possible_target_users"]
    assert parsed["unknown_top_level_keys"] == ["unknown_advice"]
    assert result["schema_stage"]["ai_reference_schema_attempted"] is True
    assert result["schema_stage"]["ai_reference_schema_pass"] is False
    serialized = json.dumps(result, ensure_ascii=False)
    assert "secret marker" not in serialized
    assert set(REFERENCE_FIELDS) == set(result["reference_fields"])


def test_empty_and_missing_content_are_distinguished():
    empty = safe_reference_shape(_envelope(""), None)
    missing = safe_reference_shape(_envelope(...), None)
    assert empty["provider_response_shape"]["message_content_present"] is True
    assert empty["provider_response_shape"]["message_content_char_count"] == 0
    assert missing["provider_response_shape"]["message_content_present"] is False
    assert missing["provider_response_shape"]["message_content_char_count"] is None


def test_malformed_content_has_safe_parse_diagnostics_only():
    result = safe_reference_shape(_envelope("not json"), None)
    parsed = result["parsed_payload_shape"]
    assert parsed["json_parse_attempted"] is True
    assert parsed["json_parse_success"] is False
    assert parsed["top_level_keys"] == []
    assert "not json" not in json.dumps(result)


def test_valid_reference_has_schema_and_completeness_shape():
    payload = {field: [f"item-{index}"] for index, field in enumerate(REFERENCE_FIELDS)}
    model = AIReferenceDraft.model_validate(payload)
    result = safe_reference_shape(_envelope(json.dumps(payload)), payload, model=model)
    assert result["schema_stage"]["ai_reference_schema_pass"] is True
    assert result["completeness_stage"]["completeness_attempted"] is True
    assert result["completeness_stage"]["completeness_pass"] is True
    assert all("item-" not in json.dumps(value) for value in result.values())


def test_shape_metadata_is_durable_and_body_free(tmp_path):
    db = Database(tmp_path / "shape.sqlite3")
    db.init_schema()
    adapter = ModelAdapter(
        provider="openai", model="test-model", api_key="fake-test-key",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"possible_target_users": ["secret"]})}}]},
        ))),
        attempt_observer=db.insert_provider_attempt,
    )
    adapter.generate_ai_reference({"idea": "synthetic"})
    attempt_id = adapter._last_attempt_id
    assert attempt_id
    inspected = inspect_provider_attempt(Database(tmp_path / "shape.sqlite3"), attempt_id)
    shape = inspected["safe_response_shape"]
    assert shape["provider_response_shape"]["message_content_present"] is True
    assert "secret" not in json.dumps(inspected)


def test_provider_adapter_shape_diagnostic_has_no_content_values():
    marker = "STAGE_B_DIAGNOSTIC_SECRET_MARKER_123"
    records = []

    def handler(request):
        payload = {"possible_target_users": [marker]}
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    adapter = ModelAdapter(
        provider="openai", model="test-model", api_key="fake-test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        attempt_observer=records.append,
    )
    adapter.generate_ai_reference({"idea": "synthetic"})
    diagnostic = adapter.last_safe_diagnostic["safe_response_shape"]
    assert diagnostic["provider_response_shape"]["message_content_char_count"] > 0
    assert marker not in json.dumps(diagnostic)
    assert marker not in json.dumps(records)


def test_provider_attempt_inspector_returns_only_safe_shape(tmp_path):
    db = Database(tmp_path / "inspector.sqlite3")
    db.init_schema()
    records = []
    adapter = ModelAdapter(
        provider="openai", model="test-model", api_key="fake-test-key",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps({"unexpected_advice": "secret"})}}]},
        ))),
        attempt_observer=lambda record: (records.append(record), db.insert_provider_attempt(record)),
    )
    with pytest.raises(ProviderCallError):
        adapter.generate_ai_reference({"idea": "synthetic"})
    inspected = inspect_provider_attempt(Database(tmp_path / "inspector.sqlite3"), adapter._last_attempt_id)
    shape = inspected["safe_response_shape"]
    assert shape["parsed_payload_shape"]["unknown_top_level_keys"] == ["unexpected_advice"]
    assert "secret" not in json.dumps(inspected)
