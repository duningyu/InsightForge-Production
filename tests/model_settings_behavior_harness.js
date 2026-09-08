"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(name) { this.values.add(name); }
  remove(name) { this.values.delete(name); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name); else this.values.delete(name);
    return enabled;
  }
}

class FakeElement {
  constructor() {
    this.value = "";
    this.defaultValue = "";
    this.checked = false;
    this.defaultChecked = false;
    this.dataset = {};
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.attributes = new Map();
    this.children = [];
    this.innerHTML = "";
    this.textContent = "";
  }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.children.push(child); return child; }
  replaceChildren(...children) { this.children = children; this.innerHTML = ""; }
  async trigger(name, extra = {}) {
    const callback = this.listeners.get(name);
    if (!callback) throw new Error(`missing ${name} listener`);
    return callback({currentTarget: this, target: this, preventDefault() {}, ...extra});
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) || null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
  close() {}
  closest() { return null; }
}

const element = () => new FakeElement();
const form = element();
form.elements = {
  display_name: element(), provider: element(), model_id: element(), api_key: element(),
  enabled: element(), protocol: element(), base_url: element(),
};
form.elements.provider.value = "qwen";
form.elements.enabled.checked = true;
form.elements.enabled.defaultChecked = true;
form.elements.protocol.value = "openai_chat_completions";
form.reset = () => {
  for (const control of Object.values(form.elements)) {
    control.value = control.defaultValue;
    control.checked = control.defaultChecked;
  }
  form.elements.provider.value = "qwen";
  form.elements.enabled.checked = true;
  form.elements.protocol.value = "openai_chat_completions";
};

const elements = new Map([["#model-profile-form", form]]);
for (const selector of [
  "#custom-provider-fields", "#model-profile-form-title", "#model-profile-cancel",
  "#model-profile-list", "#model-profile-count", "#settings-back", "#quick-start-view",
  "#project-shell", "#model-settings-view", "#project-context", "#mobile-nav-button",
  "#primary-nav", "#settings-button", "#quick-start-form", "#idea-brief-form",
  "#idea-brief-edit", "#new-idea-button", "#show-all-projects", "#project-select",
  "#add-evidence-form", "#analyze-evidence-button", "#snapshot-primary-action", "#toast",
]) elements.set(selector, element());
const mobileProjectNavItem = element();
mobileProjectNavItem.dataset.view = "snapshot";

const documentListeners = new Map();
global.document = {
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, element());
    return elements.get(selector);
  },
  querySelectorAll(selector) { return selector === ".nav-item" ? [mobileProjectNavItem] : []; },
  addEventListener(name, callback) { documentListeners.set(name, callback); },
  createElement() { return element(); },
};
global.window = {
  __INSIGHTFORGE_TEST__: true,
  confirm: () => true,
  ModelSettings: undefined,
  addEventListener() {},
  removeEventListener() {},
};
global.fetch = async (path) => ({
  ok: true,
  status: 200,
  statusText: "OK",
  headers: {get: () => "application/json"},
  json: async () => path === "/api/health" ? {status: "ok"} : [],
});

vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});

const calls = [];
const toasts = [];
const errors = [];
const actionTrace = [];
let saveMode = "success";
window.InsightForgeUi = {
  api: async (path, options = {}) => {
    calls.push({path, options});
    actionTrace.push(`api:${path}`);
    if (options.method === "POST" || options.method === "PATCH") {
      if (saveMode === "mutation-failure") throw new Error("mutation failed");
      return {id: "profile-1"};
    }
    if (saveMode === "refresh-failure" && path === "/api/settings/model-profiles") throw new Error("refresh failed");
    return [];
  },
  toast: (message) => toasts.push(message),
  reportError: (error) => errors.push(error.message),
  escapeHtml: (value) => String(value),
};

vm.runInThisContext(fs.readFileSync("app/static/model-settings.js", "utf8"), {filename: "model-settings.js"});

async function main() {
  await window.ModelSettings.open();
  const hooks = window.ModelSettings.__test;
  assert.ok(hooks, "test-only behavioral hooks must be available to the harness");
  assert.equal(
    hooks.capabilityLabel({last_test_status: "expired", capabilities: {basic_chat: "supported"}}),
    "能力结果已过期，请重新测试",
    "expired capability data is never presented as supported",
  );
  assert.equal(
    hooks.connectionStatusLabel({last_test_status: "expired"}),
    "最近连接：结果已过期",
    "expired connection state uses a Chinese safe label",
  );

  form.elements.api_key.value = "typed-unsaved-key";
  window.ModelSettings.exit();
  assert.equal(form.elements.api_key.value, "", "settings exit clears an unsaved key");

  form.elements.api_key.value = "old-input";
  hooks.editProfile({id: "profile-1", display_name: "Edit", provider: "qwen", model_id: "qwen-plus", enabled: true, protocol: "openai_chat_completions", base_url: "https://example.invalid", api_key: "never-accepted"});
  assert.equal(form.elements.api_key.value, "", "edit never repopulates the key input");

  form.elements.provider.value = "custom";
  hooks.syncCustomFields();
  assert.equal(elements.get("#custom-provider-fields").classList.contains("hidden"), false, "custom fields are shown");
  assert.equal(form.elements.protocol.required, true, "custom protocol is required");
  form.elements.provider.value = "qwen";
  hooks.syncCustomFields();
  assert.equal(elements.get("#custom-provider-fields").classList.contains("hidden"), true, "preset hides custom fields");
  assert.equal(form.elements.base_url.required, false, "preset does not require a custom URL");

  form.reset();
  form.elements.display_name.value = "Saved";
  form.elements.model_id.value = "qwen-plus";
  form.elements.api_key.value = "clear-on-success";
  saveMode = "success";
  await hooks.saveProfile({preventDefault() {}, currentTarget: form});
  assert.equal(form.elements.api_key.value, "", "successful save clears the key");

  form.elements.api_key.value = "clear-on-failure";
  saveMode = "mutation-failure";
  await hooks.saveProfile({preventDefault() {}, currentTarget: form});
  assert.equal(form.elements.api_key.value, "", "failed save clears the key");

  toasts.length = 0;
  errors.length = 0;
  form.elements.api_key.value = "clear-after-refresh-warning";
  saveMode = "refresh-failure";
  await hooks.saveProfile({preventDefault() {}, currentTarget: form});
  assert.equal(form.elements.api_key.value, "", "refresh warning also clears the key");
  assert.ok(toasts.some((message) => message.includes("列表刷新失败")), "refresh failure reports saved-with-refresh-warning");
  assert.equal(errors.length, 0, "refresh failure does not report the already-saved mutation as failed");

  let confirmCalls = 0;
  calls.length = 0;
  actionTrace.length = 0;
  errors.length = 0;
  saveMode = "success";
  window.confirm = () => { confirmCalls += 1; actionTrace.push("confirm"); return true; };
  await hooks.runAction({id: "profile-1", enabled: true, display_name: "Qwen"}, "test");
  assert.equal(confirmCalls, 1, "accepted test action asks for cost confirmation exactly once");
  assert.deepEqual(calls.map(({path, options}) => [path, options.method || "GET"]), [
    ["/api/settings/model-profiles/profile-1/test", "POST"],
    ["/api/settings/model-profiles", "GET"],
  ], "accepted test sends one POST to the exact endpoint then reloads profiles");
  assert.deepEqual(actionTrace, [
    "confirm",
    "api:/api/settings/model-profiles/profile-1/test",
    "api:/api/settings/model-profiles",
  ], "confirmation happens before the test POST and the reload follows it");
  assert.equal(errors.length, 0, "accepted test reload completes without an error");

  calls.length = 0;
  window.confirm = () => { confirmCalls += 1; return false; };
  await hooks.runAction({id: "profile-1", enabled: true, display_name: "Qwen"}, "test");
  assert.equal(calls.length, 0, "declined test action makes zero requests");

  documentListeners.get("DOMContentLoaded")();
  async function assertExitRoute(name, invoke) {
    await window.ModelSettings.open();
    form.elements.api_key.value = `sentinel-${name}`;
    await invoke();
    assert.equal(form.elements.api_key.value, "", `${name} clears the key through the secure exit path`);
  }

  await assertExitRoute("settings-back", () => elements.get("#settings-back").trigger("click"));
  await assertExitRoute("header-home", () => elements.get("#home-button").trigger("click"));
  await assertExitRoute("new-idea", () => elements.get("#new-idea-button").trigger("click"));
  elements.get("#project-select").value = "project-1";
  await assertExitRoute("project-navigation", () => elements.get("#project-select").trigger("change"));
  await assertExitRoute("mobile-menu", () => elements.get("#mobile-nav-button").trigger("click"));
  await assertExitRoute("mobile-project-nav", () => mobileProjectNavItem.trigger("click"));

  console.log("model-settings-behavior=PASS");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
