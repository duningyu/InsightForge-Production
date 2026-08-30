from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_consent_ui_and_client_payload_are_privacy_bounded():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'id="beta-consent-dialog"' in html
    assert "InsightForge Closed Beta" in html
    assert "我了解并继续" in html
    assert 'await ensureBetaConsent();' in javascript
    assert 'JSON.stringify({accepted: true, consent_version: state.betaConsentVersion})' in javascript
    consent_payload = javascript.split('JSON.stringify({accepted: true, consent_version: state.betaConsentVersion})')[0][-300:]
    assert "participant_id" not in consent_payload


def test_next_action_and_walkthrough_events_use_controlled_metadata():
    javascript = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert '"next_action_shown"' in javascript
    assert '"next_action_clicked"' in javascript
    assert "sessionStorage" in javascript
    for event in (
        "walkthrough_started", "walkthrough_step_completed", "walkthrough_skipped",
        "walkthrough_completed", "walkthrough_restarted",
    ):
        assert f'"{event}"' in main
    assert "walkthrough-step-copy" not in javascript.split("trackBetaEvent", 1)[0]
