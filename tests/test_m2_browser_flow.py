from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
APP = (ROOT / "app/static/app.js").read_text(encoding="utf-8")


def test_build_slice_workspace_contract_is_present_in_project_page():
    required_markup = (
        "m2-build-slice-panel",
        "m2-build-slice-save",
        "m2-build-slice-confirm",
        "m2-in-scope",
        "m2-out-of-scope",
        "m2-acceptance-criteria",
        "m2-build-slice-status",
    )
    missing = [marker for marker in required_markup if marker not in INDEX]
    assert not missing, f"Build Slice UI is missing: {missing}"


def test_build_slice_workspace_wires_persistence_and_refresh_reopen():
    required_behavior = (
        "/build-slice",
        "m2-build-slice-save",
        "m2-build-slice-confirm",
        "loadM2Artifacts",
        "renderM2BuildSlice",
        "expected_revision",
    )
    missing = [marker for marker in required_behavior if marker not in APP]
    assert not missing, f"Build Slice browser path is missing: {missing}"


def test_build_slice_workspace_has_no_external_execution_controls():
    forbidden = ("m2-build-slice-execute", "m2-build-slice-deploy", "m2-build-slice-github")
    present = [marker for marker in forbidden if marker in INDEX or marker in APP]
    assert not present, f"M2 Build Slice must not expose external controls: {present}"
