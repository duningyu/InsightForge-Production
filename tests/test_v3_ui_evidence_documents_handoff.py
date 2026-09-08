from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_evidence_has_exact_default_tabs_and_source_library_is_secondary():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for label in ("关键判断", "影响记录", "资料库"):
        assert label in html
    assert html.count('data-evidence-tab=') == 3
    assert "RAG 检索" not in html
    assert "Claim Ledger" not in html


def test_runtime_demo_disclosure_is_explicit_and_no_silent_fallback_copy():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    sentence = "本地演示模式：当前结构化结果用于验证工作流，不代表真实模型已理解任意 Idea。"
    assert sentence in html or sentence in js
    assert "deterministic_demo" in js
    assert "切换到本地演示模式" in js


def test_documents_page_uses_confirmation_and_health_first_copy_not_organizational_approval():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "确认此版本" in js
    assert "人工审批" not in html
    assert "组织审批" not in js
    assert "stale_evidence" in js
    assert "历史确认" in js
    assert "受影响" in js


def test_impact_history_exposes_support_weaken_conflict_unresolved_and_human_proposal_actions():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    for label in ("被支持", "被削弱", "存在冲突", "仍未解决"):
        assert label in js
    for label in ("接受修改", "暂不修改", "标记为冲突继续验证"):
        assert label in js
    assert "/change-proposals/" in js
    assert "human_confirmed: true" in js


def test_handoff_orders_executable_content_before_mcp_controls():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    handoff = js[js.index('qs("#handoff-content")'):]
    tokens = ["MVP 范围", "明确不做", "实施任务", "验收案例", "已确认文档", "未解决风险", "复制/导出", "高级：MCP"]
    positions = [handoff.index(token) for token in tokens]
    assert positions == sorted(positions)


def test_mobile_layout_collapses_navigation_without_fixed_global_content_width():
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "@media (max-width: 760px)" in css
    assert ".primary-nav.open" in css
    assert "body { overflow-x: hidden; }" in css
    assert ".project-content { width: 100%;" in css


def test_health_api_exposes_structured_runtime_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["structured_runtime_mode"] == "hybrid"
