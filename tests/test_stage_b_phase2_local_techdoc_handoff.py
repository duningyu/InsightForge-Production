"""Task 1 contract tests for the Stage-B Phase 2 local canary operators.

These tests are intentionally the RED checkpoint: the four command names are
not present in the baseline operator yet.  Help must be available without
creating an evaluation or touching product data.
"""

import pytest

from scripts.stage_b_evaluation_inspect import main


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
    assert main([command, "--help"]) == 0

    output = capsys.readouterr().out
    assert command in output
    assert "--project-id" in output
    assert "--provider" not in output
    assert "--model" not in output

