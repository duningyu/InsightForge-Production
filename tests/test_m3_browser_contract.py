from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_m3_browser_harness_files_exist():
    assert (ROOT / "tests" / "run_m3_browser.py").is_file()
    assert (ROOT / "tests" / "m3_flow_browser.cjs").is_file()


def test_m3_browser_harness_covers_business_flow_and_safety_boundaries():
    runner = (ROOT / "tests" / "run_m3_browser.py").read_text(encoding="utf-8")
    flow = (ROOT / "tests" / "m3_flow_browser.cjs").read_text(encoding="utf-8")
    required = (
        "accounts_enabled=True",
        "socket.socket.connect",
        "m3_flow_browser.cjs",
        "#m3-open-done-form",
        "#m3-open-blocked-form",
        "#m3-review-form",
        "#m3-recovery-create",
        "#m3-decision-confirm",
        "task_revision",
        "404",
        "external",
        "generate",
        "search",
    )
    missing = [marker for marker in required if marker not in runner + flow]
    assert not missing, f"M3 browser contract markers are missing: {missing}"
