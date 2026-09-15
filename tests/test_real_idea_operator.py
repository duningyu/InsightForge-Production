from __future__ import annotations

import json

from app.db import Database
from app.schemas import ProjectCreateRequest
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


def test_public_project_route_does_not_expose_evaluation_identity():
    schema = ProjectCreateRequest.model_json_schema()
    properties = schema["properties"]
    assert "project_origin" not in properties
    assert "exclude_from_beta_metrics" not in properties
