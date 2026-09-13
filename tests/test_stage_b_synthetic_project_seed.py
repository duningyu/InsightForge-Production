from __future__ import annotations

import pytest

from app.db import Database
from app.errors import ConflictError
from app.services.stage_b_synthetic_seed import (
    PHASE1A_SYNTHETIC_PROJECT_TITLE,
    STAGE_B_PHASE1A_PARTICIPANT,
    StageBPhase1ASyntheticProjectSeedService,
)


def _database(tmp_path):
    database = Database(tmp_path / "seed.sqlite3")
    database.init_schema()
    return database


def test_seed_creates_confirmed_demo_project_without_runtime(tmp_path):
    database = _database(tmp_path)
    service = StageBPhase1ASyntheticProjectSeedService(database)

    result = service.seed(
        participant=STAGE_B_PHASE1A_PARTICIPANT,
        actor="stage-b-operator",
    )

    project = database.fetch_one("SELECT * FROM projects WHERE id=?", (result["project_id"],))
    brief = database.fetch_one(
        "SELECT * FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1",
        (result["project_id"],),
    )
    assert project["title"] == PHASE1A_SYNTHETIC_PROJECT_TITLE
    assert project["project_origin"] == "demo"
    assert project["exclude_from_beta_metrics"] == 1
    assert brief["confirmation_status"] == "confirmed"
    assert brief["clarification_required"] == 0
    assert result["solutions_context_preflight"] == "PASS"
    assert database.fetch_one("SELECT COUNT(*) AS n FROM solution_runs WHERE project_id=?", (result["project_id"],))["n"] == 0


def test_seed_is_idempotent_and_does_not_create_a_second_project(tmp_path):
    database = _database(tmp_path)
    service = StageBPhase1ASyntheticProjectSeedService(database)

    first = service.seed(participant=STAGE_B_PHASE1A_PARTICIPANT, actor="stage-b-operator")
    second = service.seed(participant=STAGE_B_PHASE1A_PARTICIPANT, actor="stage-b-operator")

    assert second["project_id"] == first["project_id"]
    assert database.fetch_one(
        "SELECT COUNT(*) AS n FROM projects WHERE title=? AND project_origin='demo'",
        (PHASE1A_SYNTHETIC_PROJECT_TITLE,),
    )["n"] == 1


def test_seed_requires_stage_b_participant_before_writing(tmp_path):
    database = _database(tmp_path)
    service = StageBPhase1ASyntheticProjectSeedService(database)

    with pytest.raises(ValueError, match="STAGE_B_PARTICIPANT_REQUIRED"):
        service.seed(participant="stage-a", actor="stage-a-operator")
    assert database.fetch_one("SELECT COUNT(*) AS n FROM projects", ())["n"] == 0


def test_seed_rolls_back_project_and_brief_atomically(tmp_path, monkeypatch):
    database = _database(tmp_path)
    service = StageBPhase1ASyntheticProjectSeedService(database)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic brief failure")

    monkeypatch.setattr(service, "_insert_confirmed_brief_tx", fail)
    with pytest.raises(RuntimeError, match="synthetic brief failure"):
        service.seed(participant=STAGE_B_PHASE1A_PARTICIPANT, actor="stage-b-operator")
    assert database.fetch_one("SELECT COUNT(*) AS n FROM projects", ())["n"] == 0
    assert database.fetch_one("SELECT COUNT(*) AS n FROM idea_briefs", ())["n"] == 0


def test_seed_rejects_ambiguous_existing_identity(tmp_path):
    database = _database(tmp_path)
    for project_id in ("project_a", "project_b"):
        database.execute(
            """INSERT INTO projects(
                id,title,summary,status,project_origin,exclude_from_beta_metrics,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?)""",
            (project_id, PHASE1A_SYNTHETIC_PROJECT_TITLE, "seed", "active", "demo", 1, "1", "1"),
        )
    service = StageBPhase1ASyntheticProjectSeedService(database)
    with pytest.raises(ConflictError, match="AMBIGUOUS"):
        service.seed(participant=STAGE_B_PHASE1A_PARTICIPANT, actor="stage-b-operator")


def test_seed_operator_creates_only_through_internal_cli(tmp_path, capsys):
    from scripts.stage_b_evaluation_inspect import main

    database_path = tmp_path / "cli-seed.sqlite3"
    assert main([
        "seed-phase1a-project",
        "--database", str(database_path),
        "--participant", STAGE_B_PHASE1A_PARTICIPANT,
    ]) == 0
    output = capsys.readouterr().out
    assert '"project_id": "project_seed_phase1a_synthetic"' in output


def test_seed_operator_is_internal_and_help_is_side_effect_free():
    from scripts.stage_b_evaluation_inspect import main

    assert main(["seed-phase1a-project", "--help"]) == 0
