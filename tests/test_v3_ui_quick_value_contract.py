from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_v3_has_exactly_five_primary_nav_tasks_and_no_dual_mode_toggle():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for label in ("项目成果", "方案", "证据", "文档", "开发交接"):
        assert label in html
    for forbidden in ("新手引导", "高级工作台", "RAG 检索", "主张账本", "人工审批"):
        assert forbidden not in html
    assert 'id="mode-toggle"' not in html


def test_first_screen_accepts_one_idea_before_project_navigation():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="quick-start-form"' in html
    assert 'id="quick-start-idea"' in html
    assert 'id="project-shell"' in html


def test_first_screen_exposes_recent_projects_and_can_open_one():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="recent-projects"' in html
    assert 'id="recent-project-list"' in html
    assert 'id="show-all-projects"' in html
    assert 'data-open-project' in js
    assert 'loadProject(button.dataset.openProject)' in js


def test_snapshot_is_primary_value_surface_and_exposes_one_next_action():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'id="snapshot-view"' in html
    assert 'id="snapshot-primary-action"' in html
    assert "next_action" in js
    assert "renderSnapshot" in js


def test_solution_cards_have_compact_and_expandable_contract():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for token in (
        "mechanismLabel",
        "data_requirements",
        "implementation_plan",
        "acceptance_cases",
        "unknowns",
    ):
        assert token in js


def test_css_has_narrow_desktop_and_mobile_navigation_breakpoints():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "@media (max-width: 1199px)" in css
    assert "@media (max-width: 760px)" in css
    assert "overflow-x: auto" in css or "overflow-wrap" in css


def test_mobile_menu_button_is_hidden_on_desktop_and_only_revealed_when_active_on_mobile():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    desktop_rule = css.split(".mobile-nav-button {", 1)[1].split("}", 1)[0]

    assert "display: none" in desktop_rule
    assert ".mobile-nav-button:not(.hidden) { display: inline-grid !important;" in css


def test_quick_start_browser_uses_v3_project_id_response_contract():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "result.project_id" in js
    assert "result.project.id" not in js


def test_page_state_no_longer_carries_guided_or_advanced_mode_fields():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    state_block = js.split("const state = {", 1)[1].split("};", 1)[0]
    assert "activeView" in state_block
    assert "runtimeMode" in state_block
    assert "guided" not in state_block.casefold()
    assert "advanced" not in state_block.casefold()
