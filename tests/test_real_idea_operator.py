from __future__ import annotations

import json

from app.db import Database
from app.schemas import ProjectCreateRequest
from app.services.real_idea_budget import EXTENSION_CREDITS, EXTENSION_ID, RealIdeaBudgetService
from app.services.stage_b_evaluation import StageBEvaluationReceiptStore
from scripts.stage_b_evaluation_inspect import main


def test_real_idea_help_has_no_side_effects(tmp_path, capsys):
    database = Database(tmp_path / "isolated.sqlite")
    database.init_schema()
    before = database.table_names()

    assert main(["real-idea-batch", "--help"]) == 0
    output = capsys.readouterr().out

    assert "real-idea-batch" in output
    assert database.table_names() == before
    assert database.fetch_one("SELECT COUNT(*) AS count FROM real_idea_batches")["count"] == 0


def test_real_idea_inspector_is_safe_metadata_only(tmp_path, capsys):
    database = Database(tmp_path / "isolated.sqlite")
    database.init_schema()

    assert main(["real-idea-inspect", "--help"]) == 0
    output = capsys.readouterr().out
    assert "real-idea-inspect" in output
    assert "--batch-id" in output


def test_create_real_idea_batch_help_has_no_side_effects(tmp_path, capsys):
    database = Database(tmp_path / "isolated.sqlite")
    database.init_schema()
    before = database.table_names()

    assert main(["create-real-idea-batch", "--help"]) == 0
    output = capsys.readouterr().out

    assert "create-real-idea-batch" in output
    assert "--source-commit" in output
    assert "--deployment-id" in output
    assert database.table_names() == before
    assert database.fetch_one("SELECT COUNT(*) AS count FROM real_idea_batches")["count"] == 0


def test_create_real_idea_batch_operator_delegates_to_atomic_service(tmp_path, capsys, monkeypatch):
    database_path = tmp_path / "operator.sqlite"
    database = Database(database_path)
    database.init_schema()
    RealIdeaBudgetService(database, durable_budget=6).activate_extension(
        EXTENSION_ID, EXTENSION_CREDITS
    )
    receipt_store = StageBEvaluationReceiptStore(database=database)
    for index in range(6):
        evaluation_id = f"consumed-{index}"
        receipt_store.create(
            evaluation_id=evaluation_id,
            execution_id=evaluation_id,
            idea_id="operator-budget-test",
            execution_mode="REAL_PROVIDER",
            operation="operator-budget-test",
            participant="railway_stage_b",
            provider="bailian",
            model="qwen3.7-flash",
            prompt_version="test",
            context_version="test",
            retry_ordinal=0,
            budget_before=12 - index,
        )
        receipt_store.mark_transport_started(evaluation_id)
    monkeypatch.setenv("REAL_PROVIDER_STAGE_B", "1")
    monkeypatch.setenv("INSIGHTFORGE_SAFE_FIXTURE_MODE", "0")
    monkeypatch.setenv("INSIGHTFORGE_ACCOUNTS_ENABLED", "0")

    assert main([
        "create-real-idea-batch",
        "--database", str(database_path),
        "--source-commit", "candidate-sha",
        "--deployment-id", "deployment-id",
    ]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["batch"]["batch"]["batch_id"] == "REAL_IDEA_BATCH_01"
    assert result["batch"]["batch"]["sample_count"] == 3
    assert result["accounting"] == {
        "authorized_total": 9,
        "general_spendable": 3,
        "restricted_unbound": 0,
        "bound_allocation": 6,
        "safe_ceiling": 8,
    }
    assert result["safe_metadata_only"] is True


def test_public_project_route_does_not_expose_evaluation_identity():
    schema = ProjectCreateRequest.model_json_schema()
    properties = schema["properties"]
    assert "project_origin" not in properties
    assert "exclude_from_beta_metrics" not in properties
