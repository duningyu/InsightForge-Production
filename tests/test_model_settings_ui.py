"""Browser-independent contract for the secure model-profile settings surface."""

from pathlib import Path
import subprocess


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"
ROOT = STATIC.parent.parent


def _assets() -> tuple[str, str, str]:
    return (
        (STATIC / "index.html").read_text(encoding="utf-8"),
        (STATIC / "model-settings.js").read_text(encoding="utf-8"),
        (STATIC / "styles.css").read_text(encoding="utf-8"),
    )


def test_settings_is_reachable_from_the_header_and_uses_a_dedicated_view():
    html, js, _ = _assets()
    app_js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'id="settings-button"' in html
    assert 'id="model-settings-view"' in html
    assert 'src="/static/model-settings.js' in html
    assert "ModelSettings?.open" in app_js


def test_profile_form_offers_supported_provider_presets_and_custom_advanced_fields():
    html, js, _ = _assets()

    for provider in ("qwen", "kimi", "deepseek", "glm", "openai", "custom"):
        assert f'value="{provider}"' in html
    assert 'name="protocol"' in html
    assert 'name="base_url"' in html
    assert "syncCustomFields" in js


def test_secret_handling_keeps_edit_key_blank_and_only_shows_sanitized_statuses():
    html, js, _ = _assets()

    assert 'name="api_key"' in html
    assert 'value=""' in html
    assert "密钥已配置" in js
    assert "尚未配置密钥" in js
    assert "apiKeyInput.value = \"\"" in js
    assert "finally" in js
    for forbidden in ("reveal", "copy-key", "last-four", "last_four", "masked"):
        assert forbidden not in html.casefold()
        assert forbidden not in js.casefold()


def test_profile_cards_offer_sanitized_crud_and_connection_actions_with_cost_notice():
    _, js, _ = _assets()

    for endpoint in (
        "/api/settings/model-profiles",
        "/test",
        "/set-default",
    ):
        assert endpoint in js
    for label in ("测试连接", "设为默认", "停用", "启用", "删除"):
        assert label in js
    assert "可能产生用量或费用" in js
    assert "默认配置或项目引用" in js


def test_model_settings_behavioral_security_contracts_run_in_node():
    """Run the real browser scripts against a deterministic dependency-free fake DOM."""
    result = subprocess.run(
        ["node", "tests/model_settings_behavior_harness.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "model-settings-behavior=PASS" in result.stdout


def test_generation_recovery_behavior_contracts_run_in_node():
    result = subprocess.run(
        ["node", "tests/generation_recovery_behavior_harness.js"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "generation-recovery-behavior=PASS" in result.stdout



def test_model_settings_separates_capability_probe_from_single_request_live_verification():
    _, js, _ = _assets()

    assert "能力测试" in js
    assert "真实连接测试" in js
    assert "/live-test" in js
    assert "confirm_live_call" in js
    assert "1 次最小真实请求" in js
