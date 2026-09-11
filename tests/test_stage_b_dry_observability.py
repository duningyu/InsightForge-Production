from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import Database
from app.services.stage_b_evaluation import (
    StageBGuardError,
    StageBEvaluationReceiptStore,
)
from scripts.stage_b_evaluation_inspect import main


def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "stage-b.sqlite3")
    database.init_schema()
    return database


def _stage_b_env(monkeypatch: pytest.MonkeyPatch, *, participant: str = "railway_stage_b") -> None:
    monkeypatch.setenv("BETA_PARTICIPANT_ID", participant)
    monkeypatch.setenv("REAL_PROVIDER_STAGE_B", "true")
    monkeypatch.setenv("INSIGHTFORGE_SAFE_FIXTURE_MODE", "false")
    monkeypatch.setenv("INSIGHTFORGE_ACCOUNTS_ENABLED", "false")


@pytest.mark.parametrize("participant", ["railway_stage_a", "beta_003", "unknown"])
def test_dry_create_rejects_wrong_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, participant: str) -> None:
    _stage_b_env(monkeypatch, participant=participant)
    store = StageBEvaluationReceiptStore(database=_database(tmp_path))

    with pytest.raises(StageBGuardError):
        store.create_dry_check(
            evaluation_id="dry-rejected", idea_id="synthetic-dry", participant=participant
        )


def test_dry_create_is_durable_without_dispatch_transport_or_budget_consumption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage_b_env(monkeypatch)
    database = _database(tmp_path)
    store = StageBEvaluationReceiptStore(database=database)

    result = store.create_dry_check(evaluation_id="dry-success", idea_id="synthetic-dry")

    assert result["status"] == "DRY_SUCCEEDED"
    assert result["execution_mode"] == "DRY_OBSERVABILITY"
    assert result["evaluation_type"] == "OBSERVABILITY_CLOUD_DRY_CHECK"
    assert result["dispatch_count"] == 0
    assert result["transport_count"] == 0
    assert result["transport_attempted"] == 0
    assert result["budget_before"] == result["budget_after"] == 12
    assert result["budget_consumed"] == 0
    assert result["artifact_exists"] is True
    assert result["artifact_sha256"]
    assert result["artifact_bytes"] > 0
    assert result["failure_classification"] == "NONE"

    restored = StageBEvaluationReceiptStore(database=database).inspect("dry-success")
    assert restored["artifact_sha256"] == result["artifact_sha256"]
    assert restored["dispatch_count"] == 0
    assert restored["transport_count"] == 0


def test_dry_cli_creates_and_inspects_without_payload_or_secret_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stage_b_env(monkeypatch)
    database_path = tmp_path / "stage-b.sqlite3"
    Database(database_path).init_schema()

    assert main(["dry-create", "--database", str(database_path), "--json"]) == 0
    created = json.loads(capsys.readouterr().out)
    evaluation_id = created["evaluation_id"]
    assert created["dispatch_count"] == 0
    assert created["transport_count"] == 0
    assert created["budget_before"] == created["budget_after"]

    assert main(["inspect", evaluation_id, "--database", str(database_path)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["evaluation_id"] == evaluation_id
    assert inspected["execution_mode"] == "DRY_OBSERVABILITY"
    assert inspected["artifact_exists"] is True
    assert inspected["artifact_bytes"] > 0
    assert "stage-b durable observability verification" not in repr(inspected)
    assert "MANAGED_QWEN_API_KEY" not in repr(inspected)
