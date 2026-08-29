"use strict";

(() => {
  const API_ROOT = "/api/settings/model-profiles";
  const providerNames = {qwen: "Qwen", kimi: "Kimi", deepseek: "DeepSeek", glm: "GLM", openai: "OpenAI", custom: "Custom"};
  let profiles = [];

  const ui = () => window.InsightForgeUi;
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[ch]));

  function credentialLabel(profile) {
    return profile.credential_status === "configured" ? "密钥已配置" : "尚未配置密钥";
  }

  function capabilityLabel(profile) {
    if (profile.last_test_status === "expired") return "能力结果已过期，请重新测试";
    const capabilities = profile.capabilities || {};
    const supported = Object.values(capabilities).filter((value) => value === "supported").length;
    return supported ? `已确认 ${supported} 项能力` : "能力尚未确认";
  }

  function liveConnectionStatusLabel(profile) {
    if (profile.last_live_test_status === "passed") {
      return `真实连接已验证${profile.last_live_latency_ms == null ? "" : ` · ${profile.last_live_latency_ms} ms`}`;
    }
    if (profile.last_live_test_status === "failed") {
      return `真实连接失败${profile.last_live_error_code ? ` · ${profile.last_live_error_code}` : ""}`;
    }
    return "尚未真实连接验证";
  }

  function connectionStatusLabel(profile) {
    const labels = {
      passed: "最近连接：通过",
      failed: "最近连接：失败",
      inconclusive: "最近连接：结果不确定",
      expired: "最近连接：结果已过期",
    };
    return labels[profile.last_test_status] || "尚未测试连接";
  }

  function syncCustomFields() {
    const form = qs("#model-profile-form");
    const isCustom = form.elements.provider.value === "custom";
    qs("#custom-provider-fields").classList.toggle("hidden", !isCustom);
    form.elements.protocol.required = isCustom;
    form.elements.base_url.required = isCustom;
  }

  function resetForm() {
    const form = qs("#model-profile-form");
    form.reset();
    delete form.dataset.profileId;
    qs("#model-profile-form-title").textContent = "新增模型配置";
    qs("#model-profile-cancel").classList.add("hidden");
    const apiKeyInput = form.elements.api_key;
    apiKeyInput.value = "";
    syncCustomFields();
  }

  function renderProfiles() {
    const target = qs("#model-profile-list");
    qs("#model-profile-count").textContent = profiles.length ? `${profiles.length} 个配置` : "";
    if (!profiles.length) {
      target.innerHTML = '<div class="empty-state"><p>尚未保存模型配置。新增后可设为默认配置。</p></div>';
      return;
    }
    target.innerHTML = profiles.map((profile) => `
      <article class="model-profile-card" data-profile-id="${escapeHtml(profile.id)}">
        <div class="model-profile-card-head"><div><strong>${escapeHtml(profile.display_name)}</strong><span>${escapeHtml(providerNames[profile.provider] || profile.provider)} · ${escapeHtml(profile.model_id)}</span></div><span class="pill">${profile.enabled ? "已启用" : "已停用"}${profile.is_default ? " · 默认" : ""}</span></div>
        <div class="model-profile-meta"><span>${credentialLabel(profile)}</span><span>协议：${escapeHtml(profile.protocol)}</span><span>${capabilityLabel(profile)}</span><span>${connectionStatusLabel(profile)}</span><span>${liveConnectionStatusLabel(profile)}</span></div>
        <p class="model-test-notice">能力测试会检查基础对话与结构化输出，可能产生用量或费用；真实连接测试只发送 1 次最小真实请求。</p>
        <div class="model-profile-actions">
          <button class="button button-secondary" type="button" data-model-action="edit">编辑</button>
          <button class="button button-secondary" type="button" data-model-action="test">能力测试</button>
          <button class="button button-secondary" type="button" data-model-action="live-test">真实连接测试</button>
          ${profile.is_default ? "" : '<button class="button button-secondary" type="button" data-model-action="default">设为默认</button>'}
          <button class="button button-secondary" type="button" data-model-action="toggle">${profile.enabled ? "停用" : "启用"}</button>
          <button class="button button-quiet danger-button" type="button" data-model-action="delete">删除</button>
        </div>
      </article>`).join("");
    qsa("[data-model-action]", target).forEach((button) => button.addEventListener("click", () => {
      const card = button.closest("[data-profile-id]");
      const profile = profiles.find((item) => item.id === card.dataset.profileId);
      if (profile) runAction(profile, button.dataset.modelAction);
    }));
  }

  async function loadProfiles() {
    profiles = await ui().api(API_ROOT);
    renderProfiles();
  }

  function editProfile(profile) {
    const form = qs("#model-profile-form");
    form.dataset.profileId = profile.id;
    form.elements.display_name.value = profile.display_name;
    form.elements.provider.value = profile.provider;
    form.elements.model_id.value = profile.model_id;
    form.elements.enabled.checked = profile.enabled;
    form.elements.protocol.value = profile.protocol;
    form.elements.base_url.value = profile.base_url;
    const apiKeyInput = form.elements.api_key;
    apiKeyInput.value = "";
    qs("#model-profile-form-title").textContent = `编辑：${profile.display_name}`;
    qs("#model-profile-cancel").classList.remove("hidden");
    syncCustomFields();
    form.elements.display_name.focus();
  }

  function formPayload(form) {
    const payload = {
      display_name: form.elements.display_name.value.trim(),
      provider: form.elements.provider.value,
      model_id: form.elements.model_id.value.trim(),
      enabled: form.elements.enabled.checked,
    };
    if (payload.provider === "custom") {
      payload.protocol = form.elements.protocol.value;
      payload.base_url = form.elements.base_url.value.trim();
    }
    return payload;
  }

  async function saveProfile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const apiKeyInput = form.elements.api_key;
    const apiKey = apiKeyInput.value;
    const payload = formPayload(form);
    if (apiKey) payload.api_key = apiKey;
    const profileId = form.dataset.profileId;
    try {
      await ui().api(profileId ? `${API_ROOT}/${encodeURIComponent(profileId)}` : API_ROOT, {
        method: profileId ? "PATCH" : "POST",
        body: JSON.stringify(payload),
      });
    } catch (error) {
      ui().reportError(error);
      return;
    } finally {
      apiKeyInput.value = "";
    }
    resetForm();
    try {
      await loadProfiles();
      ui().toast(profileId ? "模型配置已更新。" : "模型配置已保存。");
    } catch (_) {
      ui().toast(profileId ? "模型配置已更新，但列表刷新失败；请重新打开设置确认。" : "模型配置已保存，但列表刷新失败；请重新打开设置确认。");
    }
  }

  async function runAction(profile, action) {
    try {
      if (action === "edit") return editProfile(profile);
      if (action === "test") {
        if (!window.confirm("能力测试会向供应商发起请求，并检查基础对话与结构化输出，可能产生多次用量或费用。是否继续？")) return;
        await ui().api(`${API_ROOT}/${encodeURIComponent(profile.id)}/test`, {method: "POST"});
        ui().toast("能力测试完成。");
      } else if (action === "live-test") {
        if (!window.confirm("真实连接测试将向供应商发送 1 次最小真实请求，可能产生少量 API 费用。是否继续？")) return;
        const result = await ui().api(`${API_ROOT}/${encodeURIComponent(profile.id)}/live-test`, {
          method: "POST",
          body: JSON.stringify({confirm_live_call: true}),
        });
        if (result.status === "PASS") {
          ui().toast(`真实连接成功 · ${result.latency_ms} ms${result.model_returned ? ` · ${result.model_returned}` : ""}`);
        } else {
          ui().toast(`真实连接失败 · ${result.error_code || "provider_error"}`);
        }
      } else if (action === "default") {
        await ui().api(`${API_ROOT}/${encodeURIComponent(profile.id)}/set-default`, {method: "POST"});
        ui().toast("已设为默认模型配置。");
      } else if (action === "toggle") {
        await ui().api(`${API_ROOT}/${encodeURIComponent(profile.id)}`, {method: "PATCH", body: JSON.stringify({enabled: !profile.enabled})});
        ui().toast(profile.enabled ? "模型配置已停用。" : "模型配置已启用。");
      } else if (action === "delete") {
        if (!window.confirm(`确定删除“${profile.display_name}”吗？`)) return;
        await ui().api(`${API_ROOT}/${encodeURIComponent(profile.id)}`, {method: "DELETE"});
        ui().toast("模型配置已删除。");
      }
      await loadProfiles();
    } catch (error) {
      if (action === "delete" && error.status === 409) {
        ui().toast("无法删除：请先将默认配置或项目引用改为其他配置后重试。");
      } else {
        ui().reportError(error);
      }
    }
  }

  let initialized = false;
  function initialize() {
    if (initialized) return;
    initialized = true;
    const form = qs("#model-profile-form");
    form.addEventListener("submit", saveProfile);
    form.elements.provider.addEventListener("change", syncCustomFields);
    qs("#model-profile-cancel").addEventListener("click", resetForm);
    syncCustomFields();
  }

  async function open() {
    initialize();
    resetForm();
    try {
      await loadProfiles();
    } catch (error) {
      ui().reportError(error);
    }
  }

  function exit() {
    profiles = [];
    resetForm();
  }

  const testHooks = {
    capabilityLabel,
    connectionStatusLabel,
    editProfile,
    runAction,
    saveProfile,
    syncCustomFields,
  };
  window.ModelSettings = {open, exit, ...(window.__INSIGHTFORGE_TEST__ ? {__test: testHooks} : {})};
})();
