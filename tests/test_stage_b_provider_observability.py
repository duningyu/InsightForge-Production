from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.services.provider_dispatch_ledger import ProviderDispatchLedger
from scripts.stage_b_evaluation_inspect import inspect_receipt
from app.services.stage_b_evaluation import (
    StageBEvaluationReceiptStore,
    StageBExecutionHarness,
    StageBProviderError,
)


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "stage-b.sqlite3")
    database.init_schema()
    return database


def _permit(database: Database, execution_id: str) -> str:
    ledger = ProviderDispatchLedger(database)
    permit = ledger.acquire_permit(
        acceptance_execution_id=execution_id,
        acceptance_window_id="stage-b-window",
        beta_instance="railway_stage_b",
        provider="bailian",
        model="qwen3.7-flash",
        authorization_reference="stage-b-fake-test",
        quota_scope="stage-b-evaluation",
    )
    assert permit
    return permit


def _kwargs(permit: str) -> dict:
    return {
        "evaluation_id": "eval-observe-1",
        "idea_id": "idea_A",
        "execution_mode": "INSIGHTFORGE",
        "operation": "ai_reference",
        "provider": "bailian",
        "model": "qwen3.7-flash",
        "prompt_version": "stage-b-insightforge-v1",
        "context_version": "stage-b-context-v1",
        "prompt": "private synthetic smoke prompt",
        "dispatch_permit_id": permit,
    }


def test_success_receipt_and_private_artifact_survive_new_process(tmp_path: Path) -> None:
    database = _database(tmp_path)
    permit = _permit(database, "eval-observe-1")
    first = StageBExecutionHarness(database=database)

    response = first.execute(
        **_kwargs(permit),
        transport=lambda: {"content": "ok", "usage": {"input": 2, "output": 3, "total": 5}},
    )

    assert response["content"] == "ok"
    second = StageBExecutionHarness(database=database)
    receipt = second.inspect("eval-observe-1")
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["dispatch_count"] == 1
    assert receipt["transport_count"] == 1
    assert receipt["retry_ordinal"] == 0
    assert receipt["total_token_count"] == 5
    assert receipt["budget_before"] == 12
    assert receipt["budget_consumed"] == 1
    assert receipt["budget_after"] == 11
    assert receipt["artifact_exists"] is True
    assert receipt["artifact_sha256"]
    assert receipt["response_bytes"] > 0
    events = database.fetch_all(
        "SELECT event_type FROM provider_dispatch_events "
        "WHERE permit_id=? ORDER BY observed_at",
        (permit,),
    )
    assert [row["event_type"] for row in events][-3:] == [
        "CALL_BOUNDARY_ENTERED", "PROVIDER_RESPONSE_RECEIVED", "COMPLETED"
    ]


def test_failure_receipt_survives_restart_without_retry(tmp_path: Path) -> None:
    database = _database(tmp_path)
    permit = _permit(database, "eval-failure-1")
    first = StageBExecutionHarness(database=database)

    with pytest.raises(StageBProviderError):
        first.execute(
            **{**_kwargs(permit), "evaluation_id": "eval-failure-1", "dispatch_permit_id": permit},
            transport=lambda: (_ for _ in ()).throw(
                StageBProviderError("controlled timeout", classification="TIMEOUT")
            ),
        )

    receipt = StageBExecutionHarness(database=database).inspect("eval-failure-1")
    assert receipt["status"] == "FAILED"
    assert receipt["failure_classification"] == "TIMEOUT"
    assert receipt["dispatch_count"] == 1
    assert receipt["transport_count"] == 1
    assert receipt["budget_consumed"] == 1
    assert receipt["retry_ordinal"] == 0


def test_receipt_created_before_transport_and_budget_not_consumed(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = StageBEvaluationReceiptStore(database=database)
    store.create(
        evaluation_id="eval-pretransport-1",
        idea_id="idea_A",
        execution_mode="INSIGHTFORGE",
        operation="ai_reference",
        provider="bailian",
        model="qwen3.7-flash",
        prompt_version="stage-b-insightforge-v1",
        context_version="stage-b-context-v1",
        retry_ordinal=0,
        budget_before=12,
    )

    restored = StageBEvaluationReceiptStore(database=database).inspect("eval-pretransport-1")
    assert restored["status"] == "CREATED"
    assert restored["dispatch_count"] == 0
    assert restored["transport_count"] == 0
    assert restored["budget_consumed"] == 0
    assert restored["budget_after"] == 12


def test_receipt_and_operator_view_do_not_store_payload_bodies(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = StageBEvaluationReceiptStore(database=database)
    secret_marker = "fake-secret-marker"
    store.create(
        evaluation_id="eval-secret-free-1",
        idea_id="idea_A",
        execution_mode="INSIGHTFORGE",
        operation="ai_reference",
        provider="bailian",
        model="qwen3.7-flash",
        prompt_version="stage-b-insightforge-v1",
        context_version="stage-b-context-v1",
        retry_ordinal=0,
        budget_before=12,
        prompt=secret_marker,
    )
    row = store.inspect("eval-secret-free-1")
    assert secret_marker not in repr(row)
    assert row["prompt_sha256"]
    operator_view = inspect_receipt(database, "eval-secret-free-1")
    assert secret_marker not in repr(operator_view)
    assert "prompt" not in operator_view
    assert "response" not in operator_view


def test_private_artifact_root_is_derived_from_database_path(tmp_path: Path) -> None:
    database = _database(tmp_path)
    store = StageBEvaluationReceiptStore(database=database)
    assert store.artifact_root == tmp_path / "private" / "stage_b_evaluation"
