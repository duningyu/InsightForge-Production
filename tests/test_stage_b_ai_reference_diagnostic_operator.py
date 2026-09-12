from __future__ import annotations

from pathlib import Path

from app.db import Database


def test_stage_b_ai_reference_shape_operator_has_a_product_path(tmp_path: Path) -> None:
    """The diagnostic must enter the existing AI Reference product chain."""
    from scripts.stage_b_evaluation_inspect import run_ai_reference_shape_canary

    database = Database(tmp_path / "stage-b-operator.sqlite3")
    database.init_schema()

    result = run_ai_reference_shape_canary(
        database=database,
        project_id="synthetic-project",
        actor="stage-b-operator-test",
    )

    assert result["execution_mode"] == "INSIGHTFORGE"
    assert result["surface"] == "AI_REFERENCE"
