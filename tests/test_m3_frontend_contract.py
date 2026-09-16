from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INDEX = PROJECT_ROOT / "app" / "static" / "index.html"
APP_JS = PROJECT_ROOT / "app" / "static" / "app.js"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_m3_project_panel_exposes_submission_review_recovery_and_decision_controls():
    html = _read(INDEX)
    required_ids = {
        "m3-action-panel",
        "m3-current-action",
        "m3-action-revision",
        "m3-action-status",
        "m3-open-done-form",
        "m3-open-blocked-form",
        "m3-done-form",
        "m3-done-description",
        "m3-done-result",
        "m3-done-attachments",
        "m3-done-check-results",
        "m3-done-notes",
        "m3-done-submit",
        "m3-blocked-form",
        "m3-blocked-step",
        "m3-blocked-observed",
        "m3-blocked-attempted",
        "m3-blocked-evidence",
        "m3-blocked-submit",
        "m3-submission-status",
        "m3-review-panel",
        "m3-review-form",
        "m3-review-status",
        "m3-review-evidence-level",
        "m3-review-check-items",
        "m3-review-unknowns",
        "m3-review-recommendation",
        "m3-review-submit",
        "m3-recovery-panel",
        "m3-recovery-action",
        "m3-recovery-status",
        "m3-recovery-create",
        "m3-decision-panel",
        "m3-decision-recommendation",
        "m3-decision-evidence",
        "m3-decision-unknowns",
        "m3-decision-select",
        "m3-decision-rationale",
        "m3-decision-recommend",
        "m3-decision-confirm",
        "m3-history",
        "m3-load-history",
    }
    missing = [element_id for element_id in sorted(required_ids) if f'id="{element_id}"' not in html]
    assert not missing, f"missing M3 controls: {missing}"

    assert "我做完了" in html
    assert "我卡住了" in html
    assert "USER_REPORTED" in html
    assert "ARTIFACT_CHECKED" in html
    assert "AUTHORIZED_RUN" in html


def test_m3_frontend_uses_real_routes_and_reopen_state_without_external_actions():
    javascript = _read(APP_JS)
    required_fragments = (
        "/submissions/",
        "/review",
        "/recovery",
        "/decisions/recommend",
        "/decisions/",
        "/m3/history",
        "loadM3State",
        "renderM3",
        "expected_revision",
        "USER_INPUT",
    )
    missing = [fragment for fragment in required_fragments if fragment not in javascript]
    assert not missing, f"missing M3 frontend contract fragments: {missing}"

    forbidden_controls = (
        "m3-execute",
        "m3-deploy",
        "m3-github",
        "m3-terminal",
        "m3-export",
    )
    assert not any(control in javascript or control in _read(INDEX) for control in forbidden_controls)


def test_m3_project_switches_serialize_full_project_loads():
    javascript = _read(APP_JS)

    # A project load updates shared state from several awaited requests.  The
    # browser flow can switch projects while a prior load is still in flight;
    # the production contract must serialize those stateful loads.
    assert "projectLoadQueue" in javascript
