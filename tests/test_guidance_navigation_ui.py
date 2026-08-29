import subprocess


def test_guidance_navigation_behavior_contract_runs_in_node():
    result = subprocess.run(
        ["node", "tests/guidance_navigation_behavior_harness.js"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "guidance-navigation-behavior=PASS" in result.stdout
