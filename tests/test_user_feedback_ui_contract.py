from pathlib import Path


HTML = Path("app/static/index.html").read_text(encoding="utf-8")
JS = Path("app/static/app.js").read_text(encoding="utf-8")
CSS = Path("app/static/styles.css").read_text(encoding="utf-8")


def test_home_and_project_next_action_cards_are_real_surfaces():
    assert 'id="home-next-action-card"' in HTML
    assert 'id="project-next-action-card"' in HTML
    assert "/api/home/next-action" in JS
    assert "/next-action" in JS
    assert "applyGuidanceAction" in JS


def test_complete_example_walkthrough_has_seven_steps_and_controls():
    assert 'id="example-list"' in HTML
    assert 'id="walkthrough-panel"' in HTML
    for step in ("idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"):
        assert step in JS
    assert "walkthrough/advance" in JS
    assert "walkthrough/skip" in JS
    assert "walkthrough/restart" in JS


def test_document_workspace_exposes_editor_autosave_versions_diff_restore_and_version_export():
    for marker in (
        'id="document-editor"',
        'id="document-autosave-status"',
        'id="document-version-list"',
        'id="document-diff-view"',
    ):
        assert marker in HTML
    for token in (
        "scheduleDocumentAutosave",
        "/documents/prd/draft",
        "/documents/techdoc/draft",
        "/api/documents/diff",
        "restore-as-new",
        "/export?format=",
    ):
        assert token in JS


def test_history_center_has_search_filter_sort_pagination_copy_and_central_trash():
    for marker in (
        'id="history-search"',
        'id="history-status-filter"',
        'id="history-sort"',
        'id="history-project-list"',
        'id="history-prev"',
        'id="history-next"',
        'id="trash-center"',
    ):
        assert marker in HTML
    assert "/api/projects/history" in JS
    assert "/copy" in JS
    assert "/trash" in JS
    assert "/restore" in JS


def test_project_model_override_selector_is_available_inside_project_context():
    assert 'id="project-model-profile"' in HTML
    assert "继承全局模型" in HTML
    assert "/model-profile" in JS
    assert "/api/settings/model-profiles" in JS


def test_feedback_completion_ui_remains_responsive():
    assert "@media (max-width: 760px)" in CSS
    for selector in (".walkthrough-panel", ".history-toolbar", ".document-editor-shell"):
        assert selector in CSS


def test_document_commit_sends_selected_base_version_for_conflict_detection():
    assert "expected_base_version_id" in JS


def test_api_preserves_structured_error_body_for_non_2xx_responses():
    assert "let body = null;" in JS
    assert "body = await response.json()" in JS
    assert "error.code = body?.error_code || null" in JS


def test_expected_quota_and_runtime_errors_do_not_pollute_blocking_console_errors():
    assert "if (error?.status === 429 || isStructuredRuntimeFailure(error)) console.warn(error);" in JS
