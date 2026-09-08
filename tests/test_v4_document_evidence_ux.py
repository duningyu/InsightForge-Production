from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
EVIDENCE_COACH = (ROOT / "app/services/evidence_coach.py").read_text(encoding="utf-8")


def test_document_workspace_has_page_level_error_and_lifecycle_controls():
    for marker in (
        'id="document-workspace-error"',
        'id="document-editor"',
        'id="document-version-list"',
        'id="document-diff-view"',
    ):
        assert marker in INDEX_HTML
    for marker in (
        "/documents/${docType}/versions",
        "/draft/commit",
        "/api/documents/${selected.id}/validate",
        "/api/document-versions/${versionId}/confirm",
        "/handoff/readiness",
    ):
        assert marker in APP_JS
    assert "DOCUMENT_VERSION_LOAD_FAILED" in APP_JS


def test_document_loading_does_not_trigger_generation():
    loader = APP_JS.split("async function loadDocumentWorkspace", 1)[1].split("async function loadDocumentDiff", 1)[0]
    assert "/documents/generate" not in loader
    assert "documentWorkspace" in loader


def test_status_mapping_keeps_raw_codes_and_humanizes_core_states():
    for marker in (
        "const STATUS_PRESENTATION",
        "额度已释放",
        "额度已结算",
        "technical-details",
        "PROVIDER_FAILURE",
        "GENERATION_PENDING",
        "IDEMPOTENT_REPLAY",
    ):
        assert marker in APP_JS or marker in INDEX_HTML


def test_guided_evidence_entry_preserves_verification_and_rag_boundary():
    for marker in (
        'id="evidence-entry-guidance"',
        "联网查找暂未开启",
        "evidence-entry-disabled",
        "我有自己的资料",
        "暂时没有，先继续",
        'id="guided-evidence-form"',
        "/sources/guided",
        "不会伪造搜索结果",
        "不会进入正式项目 RAG",
        "待确认来源",
        "待验证",
    ):
        assert marker in APP_JS or marker in INDEX_HTML
    assert 'origin_kind' in APP_JS


def test_guided_evidence_is_separate_from_legacy_raw_source_type_form():
    assert '兼容模式：按内部类型添加资料' in INDEX_HTML
    assert '资料类型<select id="guided-source-origin"' in APP_JS
    assert 'source_type' in APP_JS


def test_evidence_coach_renders_specific_action_cards_without_creating_sources():
    for marker in (
        'id="evidence-coach-open"',
        "AI帮我想怎么验证",
        "生成资料行动卡",
        "资料行动卡",
        "要确认什么",
        "拿到什么就可以填写",
        "会影响哪个产品决定",
        "AI建议，仍需你结合实际情况判断；这不是已验证资料。",
        "/evidence-guidance",
        "没有创建资料来源",
    ):
        assert marker in APP_JS or marker in INDEX_HTML
    assert "source_created" in EVIDENCE_COACH
    assert '"is_evidence": False' in EVIDENCE_COACH


def test_handoff_document_status_uses_server_confirmed_version_summary():
    assert "function handoffDocumentLabel" in APP_JS
    assert "handoffDocumentLabel(docSummary.prd)" in APP_JS
    assert "handoffDocumentLabel(docSummary.techdoc)" in APP_JS
    assert 'docSummary.prd?.id || "未确认"' not in APP_JS
    assert 'docSummary.techdoc?.id || "未确认"' not in APP_JS
