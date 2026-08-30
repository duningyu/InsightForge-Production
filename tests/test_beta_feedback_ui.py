from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_feedback_entry_and_dialog_are_present_but_secondary():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="beta-feedback-button"' in html
    assert 'id="beta-feedback-dialog"' in html
    assert 'id="beta-feedback-rating"' in html
    assert 'id="beta-feedback-type"' in html
    assert 'id="beta-feedback-comment"' in html
    assert 'id="beta-feedback-submit"' in html
    assert 'class="beta-feedback-entry"' in html


def test_feedback_ui_posts_only_contract_fields_and_never_renders_comment_html():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'api("/api/beta/feedback"' in script
    assert "project_stage: feedbackProjectStage()" in script
    assert "feedback_type: qs(\"#beta-feedback-type\").value" in script
    assert "comment: qs(\"#beta-feedback-comment\").value" in script
    assert 'toast("已收到，谢谢。")' in script
    assert "feedbackComment.innerHTML" not in script


def test_feedback_entry_is_shown_only_after_beta_consent():
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "updateBetaFeedbackVisibility" in script
    assert "state.betaMode && state.betaConsented" in script
