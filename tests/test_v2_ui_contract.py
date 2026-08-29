"""Intentional 3.0 replacements for 2.x UI contracts.

Spec §9 supersedes the Guided/Advanced dual-mode IA. These tests keep only
browser-independent contracts that remain meaningful after the 3.0 redesign.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_primary_navigation_is_user_task_oriented_after_v3_supersession():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for label in ("项目成果", "方案", "证据", "文档", "开发交接"):
        assert label in html
    assert 'id="primary-nav"' in html
    assert 'id="project-content"' in html


def test_evidence_copy_explains_current_validation_task_in_plain_language():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "当前最需要验证什么" in html
    assert "优先验证会改变方案的关键判断" in html
    assert "资料库" in html


def test_browser_calls_quick_value_snapshot_source_document_and_handoff_apis():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for path in (
        "/api/projects/quick-start",
        "/idea-brief/confirm",
        "/solutions/generate",
        "/solutions/select",
        "/snapshot",
        "/claims",
        "/sources",
        "/generate",
        "/handoff/readiness",
    ):
        assert path in js


def test_document_controls_keep_prd_and_techdoc_generation_available():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "PRD" in html
    assert "TechDoc" in html
    assert 'data-generate-doc="prd"' in js
    assert 'data-generate-doc="techdoc"' in js


def test_handoff_view_is_real_workspace_view_not_missing_document_duplication():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="handoff-view"' in html
    assert "开发准备" in html
    assert "renderHandoff" in js


def test_css_is_intrinsically_responsive_and_retains_reduced_motion_support():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "@media (max-width: 1199px)" in css
    assert "@media (max-width: 760px)" in css
    assert "minmax(0" in css
    assert "overflow-x: auto" in css
    assert "prefers-reduced-motion" in css


def test_static_assets_are_versioned_to_avoid_cross_product_browser_cache_collisions():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'href="/static/styles.css?v=3.0.0&amp;build=user-feedback-complete.1"' in html
    assert 'src="/static/app.js?v=3.0.0&amp;build=user-feedback-complete.1"' in html
