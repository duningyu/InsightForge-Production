import json

import httpx
import pytest

from app.services.provider_adapters import ModelAdapter, ProviderCallError


def _adapter(handler, records):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ModelAdapter(
        provider="openai",
        model="test-model",
        api_key="secret-value",
        client=client,
        timeout=30.0,
        attempt_observer=records.append,
        generation_intent_id="intent-1",
        generation_run_id="run-1",
    )


@pytest.mark.parametrize(
    ("timeout_type", "expected_stage"),
    [
        (httpx.ConnectTimeout, "connect"),
        (httpx.ReadTimeout, "read"),
        (httpx.WriteTimeout, "write"),
        (httpx.PoolTimeout, "pool"),
    ],
)
def test_timeout_subtype_and_safe_durable_attempt_metadata(timeout_type, expected_stage):
    records = []

    def handler(request):
        raise timeout_type("transport secret", request=request)

    adapter = _adapter(handler, records)
    with pytest.raises(ProviderCallError) as caught:
        adapter._request(
            system="system prompt must not be persisted",
            user="user prompt must not be persisted",
            structured=True,
        )

    error = caught.value
    assert isinstance(error.__cause__, timeout_type)
    assert error.safe_diagnostic["provider_exception_class"] == timeout_type.__name__
    assert error.safe_diagnostic["provider_failure_stage"] == f"provider_transport_{expected_stage}"
    assert len(records) == 1
    record = records[0]
    assert record["generation_intent_id"] == "intent-1"
    assert record["generation_run_id"] == "run-1"
    assert record["provider_attempt_id"]
    assert record["model_id"] == "test-model"
    assert record["request_body_bytes"] > 0
    assert record["message_count"] == 2
    assert record["schema_bytes"] > 0
    assert record["structured_output_mode"] == "json_object"
    assert record["effective_timeout"]["timeout_seconds"] == 30.0
    assert record["effective_timeout"]["connect_timeout_seconds"] == 30.0
    assert record["effective_timeout"]["pool_timeout_seconds"] == 30.0
    assert record["effective_timeout"]["write_timeout_seconds"] == 30.0
    assert record["effective_timeout"]["read_timeout_seconds"] == 30.0
    assert record["effective_timeout"]["overall_timeout_seconds"] == 30.0
    assert record["exception_at"]
    assert record["elapsed_ms"] >= 0
    assert record["response_headers_observed"] is False
    serialized = json.dumps(record, sort_keys=True)
    assert "system prompt must not be persisted" not in serialized
    assert "user prompt must not be persisted" not in serialized
    assert "secret-value" not in repr(error)


def test_timeout_cause_chain_is_safe_and_concrete():
    records = []

    def handler(request):
        raise httpx.ReadTimeout("transport secret", request=request)

    adapter = _adapter(handler, records)
    with pytest.raises(ProviderCallError) as caught:
        adapter._request(system="system", user="user", structured=False)
    assert type(caught.value.__cause__) is httpx.ReadTimeout
    assert caught.value.__cause__.__cause__ is None
    assert "Authorization" not in repr(caught.value)
    assert "secret-value" not in repr(caught.value)


def test_provider_attempt_metadata_is_durable_and_body_free(db):
    records = []

    def handler(request):
        raise httpx.ReadTimeout("sensitive transport detail", request=request)

    adapter = _adapter(handler, records)

    def observe(record):
        records.append(record)
        db.insert_provider_attempt(record)

    adapter._attempt_observer = observe
    with pytest.raises(ProviderCallError):
        adapter._request(
            system="private prompt sentinel",
            user="private user sentinel",
            structured=True,
        )

    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM provider_attempts WHERE provider_attempt_id = ?",
            (records[0]["provider_attempt_id"],),
        ).fetchone()
    assert row is not None
    assert row["generation_intent_id"] == "intent-1"
    assert row["generation_run_id"] == "run-1"
    assert row["response_headers_observed"] == 0
    serialized = repr(dict(row))
    assert "private prompt sentinel" not in serialized
    assert "sensitive transport detail" not in serialized
