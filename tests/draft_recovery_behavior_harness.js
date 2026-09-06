"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
}

class FakeElement {
  constructor() { this.value = ""; this.textContent = ""; this.innerHTML = ""; this.hidden = true; this.dataset = {}; this.classList = new FakeClassList(); }
  addEventListener() {}
  setAttribute() {}
  removeAttribute() {}
  focus() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

const elements = new Map();
const element = (selector) => {
  if (!elements.has(selector)) elements.set(selector, new FakeElement());
  return elements.get(selector);
};
global.document = {
  querySelector: element,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => new FakeElement(),
};
global.window = {__INSIGHTFORGE_TEST__: true, ModelSettings: undefined};
const localValues = new Map();
global.localStorage = {
  getItem(key) { return localValues.has(key) ? localValues.get(key) : null; },
  setItem(key, value) { localValues.set(key, String(value)); },
  removeItem(key) { localValues.delete(key); },
};
global.sessionStorage = global.localStorage;

function response(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 409 ? "Conflict" : "OK",
    headers: {get: () => "application/json"},
    json: async () => payload,
  };
}

const calls = [];
let mode = "normal";
let resolveDelayed;
global.fetch = async (path, options = {}) => {
  calls.push({path, options});
  if (options.method === "PUT" && mode === "delayed") {
    return new Promise((resolve) => { resolveDelayed = () => resolve(response({revision: 2, payload: JSON.parse(options.body).payload})); });
  }
  if (options.method === "PUT" && mode === "conflict") return response({code: "DRAFT_CONFLICT", detail: "这个内容已经在其他页面更新。", latest: {revision: 2}}, 409);
  if (!options.method || options.method === "GET") return response({revision: 2, payload: {idea: "服务器最新内容"}}, 200);
  return response({revision: 1, payload: JSON.parse(options.body || "{}").payload || {}}, 200);
};

vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});
const hooks = window.InsightForgeUi.__test;
assert.ok(hooks, "draft recovery hooks must be available in test mode");
element("#draft-recovery-status");

async function tick(ms = 0) { await new Promise((resolve) => setTimeout(resolve, ms)); }

async function main() {
  hooks.setAccountContext("account-a");
  hooks.writeRecoveryCopy("project-1", "idea", "main", {idea: "A的未同步内容"}, 1);
  assert.deepEqual(hooks.readRecoveryCopy("project-1", "idea", "main").payload, {idea: "A的未同步内容"});
  hooks.setAccountContext("account-b");
  assert.equal(hooks.readRecoveryCopy("project-1", "idea", "main"), null, "local recovery is account scoped");

  hooks.setAccountContext("account-a");
  elements.get("#draft-recovery-status").textContent = "";
  const loaded = await hooks.loadUnifiedDraft("project-1", "idea", "main");
  assert.equal(loaded.server.revision, 2);
  assert.equal(loaded.local.baseRevision, 1);
  assert.match(elements.get("#draft-recovery-status").textContent, /其他页面更新/);
  hooks.writeRecoveryCopy("project-1", "idea", "main", {idea: "本地较新的内容"}, 2);
  const localPreferred = await hooks.loadUnifiedDraft("project-1", "idea", "main");
  assert.deepEqual(hooks.preferredRecoveryPayload(localPreferred), {idea: "本地较新的内容"}, "newer local recovery wins without overwriting server state");

  mode = "delayed";
  elements.get("#draft-recovery-status").textContent = "";
  hooks.queueUnifiedDraft("project-1", "idea", "main", {idea: "A的新内容"}, {baseRevision: 1, delay: 0});
  await tick();
  assert.equal(typeof resolveDelayed, "function", "the save request reached the transport");
  hooks.setAccountContext("account-b");
  resolveDelayed();
  await tick();
  assert.equal(elements.get("#draft-recovery-status").textContent, "正在保存…", "late response cannot update another account's UI");

  mode = "conflict";
  hooks.setAccountContext("account-a");
  hooks.queueUnifiedDraft("project-1", "idea", "main", {idea: "旧页面内容"}, {baseRevision: 1, delay: 0});
  await tick();
  await tick();
  assert.match(elements.get("#draft-recovery-status").textContent, /其他页面更新/);

  mode = "normal";
  calls.length = 0;
  hooks.queueUnifiedDraft("project-1", "idea", "main", {idea: "a"}, {delay: 5});
  hooks.queueUnifiedDraft("project-1", "idea", "main", {idea: "ab"}, {delay: 5});
  await tick(20);
  assert.equal(calls.filter((call) => call.options.method === "PUT").length, 1, "autosave is debounced");
  assert.equal(hooks.readRecoveryCopy("project-1", "idea", "main"), null, "successful save clears the local recovery copy");
  console.log("draft-recovery-behavior=PASS");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
