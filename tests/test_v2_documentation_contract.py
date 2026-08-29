from pathlib import Path

from docx import Document


ROOT = Path(__file__).resolve().parents[1]


def _docx_text(path: Path) -> str:
    document = Document(path)
    parts = [paragraph.text for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def test_package_version_and_readme_describe_v2_product_shape():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert 'version = "3.0.0"' in pyproject
    for phrase in (
        "Guided Mode",
        "Advanced Workspace",
        "retrieval trace",
        "claim-evidence ledger",
        "AI coding handoff ZIP",
    ):
        assert phrase in readme


def test_feedback_iteration_record_is_qualitative_not_market_validation():
    record = (ROOT / "docs" / "USER_FEEDBACK_AND_ITERATION.md").read_text(encoding="utf-8")
    for phrase in (
        "一次定性产品经理反馈",
        "不构成市场验证",
        "约束不知道怎么填",
        "RAG 配置用途不清楚",
        "AI Coding 交接只有名义接口",
        "黑箱",
        "v1.1.0",
        "v2.0.0",
    ):
        assert phrase in record


def test_v2_prd_records_feedback_redesign_and_technology_boundaries():
    text = _docx_text(ROOT / "docs" / "PRD_InsightForge.docx")
    for phrase in (
        "InsightForge 2.0",
        "用户反馈与版本迭代",
        "一次定性产品经理反馈",
        "不构成市场验证",
        "对话式引导 + 分步任务流 + 右侧证据追溯面板",
        "新手引导模式为默认",
        "高级工作台",
        "为什么使用当前检索档位",
        "manual_baseline_not_frozen_best",
        "Claim-Evidence Ledger",
        "真实 AI Coding 交接 ZIP",
        "LangChain 不作为本版本强制依赖",
        "不得声称参数最优",
    ):
        assert phrase in text


def test_prd_images_have_accessible_alt_text():
    document = Document(ROOT / "docs" / "PRD_InsightForge.docx")
    assert len(document.inline_shapes) == 5
    for shape in document.inline_shapes:
        doc_pr = shape._inline.docPr
        assert (doc_pr.get("descr") or "").strip()
        assert (doc_pr.get("title") or "").strip()


def test_prd_generator_uses_packaged_assets_instead_of_container_absolute_paths():
    script = (ROOT / "scripts" / "generate_prd_v2.py").read_text(encoding="utf-8")
    assert "/mnt/data/" not in script
    for filename in (
        "user_flow.png",
        "architecture_modes.png",
        "ui_guided.png",
        "ui_advanced.png",
        "provenance_chain.png",
    ):
        assert (ROOT / "docs" / "assets" / filename).is_file()
