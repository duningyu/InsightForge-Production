from __future__ import annotations

from pathlib import Path

import pytest

from app.db import Database
from app.services.provider_dispatch_ledger import ProviderDispatchLedger
from app.services.stage_b_evaluation import StageBExecutionHarness, StageBProviderError


def _db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "stage-b-linkage.sqlite3")
    database.init_schema()
    return database


def _permit(database: Database, execution_id: str) -> str:
    permit = ProviderDispatchLedger(database).acquire_permit(
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


def _kwargs(evaluation_id: str, permit: str) -> dict:
    return {
        "evaluation_id": evaluation_id,
        "idea_id": "synthetic-job-tracker",
        "execution_mode": "INSIGHTFORGE",
        "operation": "ai_reference",
        "provider": "bailian",
        "model": "qwen3.7-flash",
        "prompt_version": "stage-b-insightforge-v1",
        "context_version": "stage-b-context-v1",
        "dispatch_permit_id": permit,
    }


def test_ai_reference_dispatch_permit_is_durably_linked_to_evaluation(tmp_path: Path) -> None:
    database = _db(tmp_path)
    evaluation_id = "ai-reference-eval-success"
    permit = _permit(database, evaluation_id)

    StageBExecutionHarness(database=database).execute(
        **_kwargs(evaluation_id, permit),
        transport=lambda: {"content": "具体建议", "usage": {"total": 3}},
    )

    row = database.fetch_one(
        "SELECT evaluation_id FROM provider_dispatch_evaluation_links WHERE permit_id=?", (permit,)
    )
    assert row["evaluation_id"] == evaluation_id


def test_provider_503_keeps_dispatch_linkage_and_marks_transport_stage(tmp_path: Path) -> None:
    database = _db(tmp_path)
    evaluation_id = "ai-reference-eval-503"
    permit = _permit(database, evaluation_id)

    with pytest.raises(StageBProviderError):
        StageBExecutionHarness(database=database).execute(
            **_kwargs(evaluation_id, permit),
            transport=lambda: (_ for _ in ()).throw(
                StageBProviderError("HTTP_STATUS_503", classification="PROVIDER_5XX")
            ),
        )

    receipt = StageBExecutionHarness(database=database).inspect(evaluation_id)
    assert receipt["dispatch_permit_id"] == permit
    assert receipt["dispatch_evaluation_id"] == evaluation_id
    assert receipt["dispatch_count"] == 1
    assert receipt["transport_count"] == 1
    assert receipt["failure_classification"] == "PROVIDER_5XX"
    assert receipt["output_contract_attempted"] == 0
    assert receipt["failure_stage"] == "PROVIDER_TRANSPORT"


def test_invalid_provider_shape_is_not_reported_as_transport_failure(tmp_path: Path) -> None:
    database = _db(tmp_path)
    evaluation_id = "ai-reference-eval-invalid-response"
    permit = _permit(database, evaluation_id)

    with pytest.raises(StageBProviderError):
        StageBExecutionHarness(database=database).execute(
            **_kwargs(evaluation_id, permit),
            transport=lambda: (_ for _ in ()).throw(
                StageBProviderError("invalid provider response", classification="INVALID_RESPONSE")
            ),
        )

    receipt = StageBExecutionHarness(database=database).inspect(evaluation_id)
    assert receipt["failure_stage"] == "OUTPUT_NORMALIZATION"
    assert receipt["output_contract_attempted"] == 0


def test_interleaved_evaluations_cannot_cross_link(tmp_path: Path) -> None:
    database = _db(tmp_path)
    first = "ai-reference-eval-a"
    second = "ai-reference-eval-b"
    first_permit = _permit(database, first)
    second_permit = _permit(database, second)

    for evaluation_id, permit in ((second, second_permit), (first, first_permit)):
        StageBExecutionHarness(database=database).execute(
            **_kwargs(evaluation_id, permit),
            transport=lambda: {"content": evaluation_id},
        )

    rows = database.fetch_all(
        "SELECT permit_id, evaluation_id FROM provider_dispatch_evaluation_links ORDER BY permit_id"
    )
    assert {row["evaluation_id"] for row in rows} == {first, second}
    assert database.fetch_one(
        "SELECT evaluation_id FROM provider_dispatch_evaluation_links WHERE permit_id=?", (first_permit,)
    )["evaluation_id"] == first
    assert database.fetch_one(
        "SELECT evaluation_id FROM provider_dispatch_evaluation_links WHERE permit_id=?", (second_permit,)
    )["evaluation_id"] == second
