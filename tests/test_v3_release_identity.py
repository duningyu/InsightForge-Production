from pathlib import Path

from app.config import Settings

ROOT = Path(__file__).resolve().parents[1]


def test_release_identity_is_3_0_0_across_runtime_package_and_static_assets():
    assert Settings().app_version == "3.0.0"
    assert 'version = "3.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    assert 'href="/static/styles.css?v=3.0.0&amp;build=user-feedback-complete.1"' in html
    assert 'src="/static/app.js?v=3.0.0&amp;build=user-feedback-complete.3"' in html


def test_verification_report_uses_current_release_identity():
    text = (ROOT / "VERIFICATION_REPORT.md").read_text(encoding="utf-8")
    assert "**Application version:** 3.0.0" in text
    assert "**Application version:** 2.0.0" not in text
    assert "2.0.6 untouched = 99 passed" in text
