"""Task 1 contract tests for the Stage-B Phase 2 local canary operators."""

import sqlite3

import pytest

import scripts.stage_b_evaluation_inspect as operator


@pytest.mark.parametrize(
    "command",
    [
        "confirm-prd-canary",
        "local-techdoc-canary",
        "confirm-techdoc-canary",
        "handoff-canary",
    ],
)
def test_phase2_operator_command_help_is_exposed_without_execution(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert operator.main([command, "--help"]) == 0

    output = capsys.readouterr().out
    assert command in output
    assert "--project-id" in output
    assert "--provider" not in output
    assert "--model" not in output


def test_phase2_help_has_no_evaluation_product_provider_search_or_budget_side_effects(
    tmp_path, monkeypatch, capsys
) -> None:
    database_path = tmp_path / "isolated-stage-b.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE product_tripwire (value TEXT NOT NULL)")
        connection.execute("INSERT INTO product_tripwire VALUES ('unchanged')")
        connection.commit()

    calls: list[str] = []

    class DatabaseTripwire:
        def __init__(self, *_args, **_kwargs):
            calls.append("database")
            raise AssertionError("help must not construct or mutate a database")

    def tripwire(*_args, **_kwargs):
        calls.append("external-or-budget")
        raise AssertionError("help must not evaluate, dispatch, search, or consume budget")

    monkeypatch.setattr(operator, "Database", DatabaseTripwire)
    monkeypatch.setattr(operator, "StageBEvaluationReceiptStore", tripwire)
    monkeypatch.setattr(operator, "evaluate_stage_b_guard", tripwire)
    monkeypatch.setattr(operator, "_database_path", lambda: database_path)

    for command in operator._PHASE2_COMMANDS:
        assert operator.main([command, "--help", "--database", str(database_path)]) == 0

    assert calls == []
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT value FROM product_tripwire").fetchone() == ("unchanged",)
    capsys.readouterr()


def test_phase2_operator_without_project_id_returns_rejection_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert operator.main(["local-techdoc-canary"]) == 2
    assert "--project-id" in capsys.readouterr().err


def test_phase2_normal_invocation_dispatches_to_mapped_runner(monkeypatch, capsys) -> None:
    calls: list[tuple[object, str, str]] = []

    class DatabaseFixture:
        def __init__(self, path):
            self.path = path

    def runner(*, database, project_id, actor):
        calls.append((database, project_id, actor))
        return operator.Phase2SafeReceiptMetadata(
            operation=operator.PHASE2_TECHDOC_GENERATE, status="not_implemented"
        )

    monkeypatch.setattr(operator, "Database", DatabaseFixture)
    monkeypatch.setitem(
        operator._PHASE2_COMMANDS,
        "local-techdoc-canary",
        (operator.PHASE2_TECHDOC_GENERATE, runner),
    )

    assert operator.main([
        "local-techdoc-canary", "--project-id", "isolated-project",
        "--database", "isolated.sqlite3", "--actor", "test-actor",
    ]) == 0
    assert len(calls) == 1
    assert calls[0][1:] == ("isolated-project", "test-actor")
    assert '"operation": "PHASE2_TECHDOC_GENERATE"' in capsys.readouterr().out
