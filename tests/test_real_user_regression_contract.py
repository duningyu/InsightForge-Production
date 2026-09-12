from pathlib import Path
import subprocess


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_competitor_context_never_enables_snapshot_without_an_id():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "state.useCompetitorSnapshot = Boolean(context.useCompetitorSnapshot)" in js
    assert '"X-Use-Competitor-Snapshot": String(Boolean(state.useCompetitorSnapshot))' in js
    assert "const useSnapshot = Boolean(state.useCompetitorSnapshot)" in js
    assert "competitor_snapshot_id: useSnapshot && state.competitorSnapshotId ? state.competitorSnapshotId : null" in js
    assert "silently turning it into" in js


def test_primary_ui_maps_runtime_errors_and_keeps_raw_details_collapsed():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "humanizeErrorMessage" in js
    assert "技术详情" in js
    assert "stableErrorCode" in js
    assert "原始错误仅保留在服务端日志中" in js
    assert "escapeHtml(technicalMessage)" not in js
    assert "toast(humanMessage" in js


def test_primary_ui_never_renders_backend_error_or_structured_json():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "JSON.stringify({validation_status" not in js
    assert "JSON.stringify({status: version.status" not in js
    assert "technicalErrorMessage(workspace.error)" not in js
    assert "current confirmed competitor snapshot is required" not in js
    assert "String(object)" not in js


def test_snapshot_uses_structured_presenters_and_vertical_flow():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "presentStructuredValue" in js
    assert "product-flow" in js
    assert "product-flow-step" in css
    assert "输入 / 输出" in js
    assert "humanizeSnapshotAction(next.action)" in js
    assert "action.textContent = next.action" not in js


def test_ai_reference_renders_object_items_without_object_stringification():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "presentStructuredValue(item, \"待确认\")" in js
    assert "JSON.stringify(item)" in js
    assert "ai-reference-item-content" in js
    assert 'id="generation-progress-retry"' in html
    assert "重新生成" in html
    assert "这次没有生成可用建议，请重新尝试。" in js
    assert "setTestAIReference" in js


def test_unknown_user_visible_reasons_do_not_echo_machine_text():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'return /[\\u3400-\\u9fff]/.test(value) ? value : "还有一项交接前条件未完成。";' in js
    assert 'return /[\\u3400-\\u9fff]/.test(value) ? value : "相关资料或判断发生变化，需要重新检查";' in js


def test_handoff_unresolved_items_have_safe_human_fallbacks():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function humanizeUnresolvedItem(item)" in js
    assert "traceback|exception|valueerror|keyerror|sql|stack trace" in js
    assert '还有一项内容需要确认' in js
    assert '补充资料或进行一次实际验证' in js
    assert "unresolved.map(humanizeUnresolvedItem)" in js


def test_account_errors_do_not_echo_backend_exception_text():
    js = (STATIC / "account.js").read_text(encoding="utf-8")
    assert "message.textContent = error.message" not in js
    assert "账号操作未完成，请检查填写内容或稍后重试。" in js


def test_reference_and_handoff_safe_render_behavior():
    result = subprocess.run(
        ["node", "tests/whole_branch_fix_harness.js", "--regression-render"],
        cwd=STATIC.parents[1], capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SUMMARY passed=2 failed=0" in result.stdout
