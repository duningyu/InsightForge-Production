"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class ClassList {
  constructor() { this.values = new Set(); }
  add(...items) { items.forEach((item) => this.values.add(item)); }
  remove(...items) { items.forEach((item) => this.values.delete(item)); }
  contains(item) { return this.values.has(item); }
  toggle(item, force) { const on = force === undefined ? !this.values.has(item) : Boolean(force); if (on) this.values.add(item); else this.values.delete(item); return on; }
}
class Element {
  constructor() { this.value = ""; this.innerHTML = ""; this.textContent = ""; this.dataset = {}; this.classList = new ClassList(); this.disabled = false; this.listeners = new Map(); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  setAttribute() {}
  removeAttribute() {}
  querySelectorAll() { return []; }
  focus() {}
}

const elements = new Map();
const getElement = (selector) => { if (!elements.has(selector)) elements.set(selector, new Element()); return elements.get(selector); };
global.document = {querySelector: getElement, querySelectorAll: () => [], addEventListener: () => {}, createElement: () => new Element()};
global.window = {__INSIGHTFORGE_TEST__: true, ModelSettings: undefined};
global.setTimeout = () => 0;
global.clearTimeout = () => {};

const calls = [];
let fetchMode = "error";
global.fetch = async (path, options = {}) => {
  calls.push({path, options});
  if (fetchMode === "error" && path === "/api/projects/demo/documents/prd/versions") {
    return {ok: false, status: 404, statusText: "Not Found", headers: {get: () => "application/json"}, json: async () => ({detail: "document version not found", error_code: "DOCUMENT_VERSION_NOT_FOUND"})};
  }
  if (fetchMode === "success") {
    if (path === "/api/projects/demo/documents/prd/versions") {
      return {ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => ([{id: "prd-v1", doc_type: "prd", version: 1, status: "draft", validation_status: "passed", artifact_health: {health_status: "current"}, content: "# PRD"}])};
    }
    if (path === "/api/projects/demo/documents/techdoc/versions") {
      return {ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => ([{id: "techdoc-v1", doc_type: "techdoc", version: 1, status: "draft", validation_status: "passed", artifact_health: {health_status: "current"}, content: "# TechDoc"}])};
    }
    if (path.endsWith("/draft")) {
      return {ok: false, status: 404, statusText: "Not Found", headers: {get: () => "application/json"}, json: async () => ({detail: "draft not found"})};
    }
  }
  throw new Error(`unexpected fetch ${path}`);
};

vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});
const hooks = window.InsightForgeUi.__test;
assert.ok(hooks, "app.js test hooks are available");
assert.equal(typeof hooks.loadDocumentWorkspace, "function", "document workspace loader is testable");
(async () => {
  hooks.state.currentProjectId = "demo";
  await hooks.loadDocumentWorkspace("prd");
  const error = getElement("#document-workspace-error");
  assert.ok(!error.classList.contains("hidden"), "document loading errors are visible instead of becoming a blank editor");
  assert.match(error.innerHTML, /无法加载|文档|版本/);
  assert.match(error.innerHTML, /DOCUMENT_VERSION_NOT_FOUND/);
  fetchMode = "success";
  await hooks.loadDocumentWorkspace("prd");
  assert.equal(hooks.state.documentWorkspace.docType, "prd");
  assert.equal(getElement("#document-editor").value, "# PRD");
  await hooks.loadDocumentWorkspace("techdoc");
  assert.equal(hooks.state.documentWorkspace.docType, "techdoc");
  assert.equal(getElement("#document-editor").value, "# TechDoc");
  console.log("document evidence UX RED/GREEN harness passed: error visibility + PRD/TechDoc load");
})().catch((error) => { console.error(error); process.exitCode = 1; });
