"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const fixtures = JSON.parse(fs.readFileSync("tests/fixtures/stage_b_generation_ux_cases.json", "utf8"));

class ClassList {
  constructor() { this.values = new Set(); }
  add(...items) { items.forEach((item) => this.values.add(item)); }
  remove(...items) { items.forEach((item) => this.values.delete(item)); }
  contains(item) { return this.values.has(item); }
  toggle(item, force) { const on = force === undefined ? !this.values.has(item) : Boolean(force); if (on) this.values.add(item); else this.values.delete(item); return on; }
}

function stripTags(html) {
  return String(html || "").replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'");
}

class Element {
  constructor(tagName = "div") {
    this.tagName = tagName.toUpperCase();
    this._innerHTML = "";
    this._textContent = "";
    this.children = [];
    this.classList = new ClassList();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.value = "";
    this.open = false;
    this.isConnected = true;
  }
  get innerHTML() { return this._innerHTML || this.children.map((child) => child.outerHTML || child.textContent).join(""); }
  set innerHTML(value) { this._innerHTML = String(value ?? ""); this._textContent = ""; this.children = []; }
  get textContent() { return this._innerHTML ? stripTags(this._innerHTML) : (this._textContent || this.children.map((child) => child.textContent).join("")); }
  set textContent(value) { this._innerHTML = ""; this._textContent = String(value ?? ""); this.children = []; }
  get innerText() { return this.textContent; }
  append(...nodes) { this._innerHTML = ""; nodes.forEach((node) => { if (node && typeof node === "object") this.children.push(node); }); }
  replaceChildren(...nodes) { this._innerHTML = ""; this._textContent = ""; this.children = []; this.append(...nodes); }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { delete this[name]; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.listeners.get("close")?.(); }
  get outerHTML() { return `<${this.tagName.toLowerCase()}>${this.innerHTML}</${this.tagName.toLowerCase()}>`; }
}

const elements = new Map();
function getElement(selector) {
  if (!elements.has(selector)) elements.set(selector, new Element());
  return elements.get(selector);
}
global.document = {
  body: new Element("body"),
  querySelector: getElement,
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: (tagName) => new Element(tagName),
};
global.window = {__INSIGHTFORGE_TEST__: true, ModelSettings: undefined};
global.setTimeout = () => 0;
global.clearTimeout = () => {};
global.fetch = async () => ({ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => ({})});

vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});
const hooks = window.InsightForgeUi.__test;
assert.ok(hooks, "app.js test hooks are available");

function visibleBody(selector) {
  const body = getElement(selector).innerText.trim();
  assert.ok(body, `${selector} must contain visible body text`);
  assert.doesNotMatch(body, /\"(?:choices|messages|provider|schema)\"\s*:/, `${selector} must not show a raw provider/API object`);
  return body;
}

const results = [];
async function runCase(name, fn) {
  try {
    await fn();
    results.push({name, status: "PASS"});
    console.log(`PASS ${name}`);
  } catch (error) {
    results.push({name, status: "FAIL", message: error.message});
    console.error(`FAIL ${name}: ${error.message}`);
  }
}

function setDocument(version) {
  hooks.state.documentWorkspace = {
    docType: version.doc_type,
    versions: [version],
    selectedVersionId: version.id,
    compareVersionId: null,
    draft: null,
    dirty: false,
    error: null,
  };
  hooks.renderDocumentWorkspace();
}

function assertDocumentSafetyContract(version, {validMarker, forbiddenMarker, label}) {
  setDocument(version);
  const editor = getElement("#document-editor");
  const errorNode = getElement("#document-workspace-error");
  const editorBody = editor.value;
  const errorBody = errorNode.innerText.trim();
  const validContinuation = editorBody.includes(validMarker) && !forbiddenMarker.test(editorBody);
  const typedFailClosed = Boolean(
    hooks.state.documentWorkspace.error
      && typeof hooks.state.documentWorkspace.error.code === "string"
      && hooks.state.documentWorkspace.error.code.trim()
      && editor.disabled
      && !errorNode.classList.contains("hidden")
      && errorBody,
  );

  assert.doesNotMatch(editorBody, forbiddenMarker, `${label} does not show unsafe document content`);
  assert.doesNotMatch(errorBody, forbiddenMarker, `${label} error does not echo unsafe document content`);
  assert.ok(validContinuation || typedFailClosed, `${label} either preserves a valid continuation or returns a typed fail-closed result`);
}

async function main() {
  await runCase("AI reference success has indicator and visible body", () => {
    hooks.setTestAIReference(fixtures.ai_reference_complete);
    const body = visibleBody("#ai-reference-content");
    assert.match(body, /AI生成参考/);
    assert.match(body, /门店运营人员/);
    assert.match(body, /待核实|尚未经外部资料核实/);
  });

  await runCase("Action Card success exposes an actual complete card", () => {
    hooks.setTestEvidenceGuidance(fixtures.action_card_complete);
    const body = visibleBody("#evidence-guidance-content");
    for (const label of ["要确认什么", "找谁 / 去哪里", "具体怎么做", "拿到什么就可以填写", "填写模板", "会影响哪个产品决定", "暂时拿不到怎么办", "这条材料的局限"]) assert.match(body, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
    assert.match(body, /最近一次缺货处理经历/);
    assert.match(body, /AI建议，仍需你结合实际情况判断；这不是已验证资料/);
  });

  await runCase("solution success renders exactly three complete cards", () => {
    hooks.state.solutions = fixtures.solutions_complete;
    hooks.renderSolutions();
    const body = visibleBody("#solutions-content");
    assert.equal((getElement("#solutions-content").innerHTML.match(/class=\"solution-card\"/g) || []).length, 3);
    for (const title of fixtures.solutions_complete.candidates.map((candidate) => candidate.title)) assert.match(body, new RegExp(title));
    assert.match(body, /优先级队列/);
    assert.match(body, /仅用于 UX 合同测试/);
  });

  await runCase("document success shows a non-empty PRD body", () => {
    setDocument(fixtures.documents.prd);
    assert.match(getElement("#document-editor").value, /方案：路径 B：人工复核队列/);
    assert.match(getElement("#document-editor").value, /优先级队列/);
  });

  await runCase("handoff success references selected PRD and TechDoc", () => {
    hooks.state.snapshot = fixtures.snapshot_selected_b;
    hooks.state.handoff = fixtures.handoff_ready;
    hooks.renderHandoff();
    const body = visibleBody("#handoff-content");
    assert.match(body, /PRD：已确认 v1/);
    assert.match(body, /TechDoc：已确认 v1/);
    assert.match(body, /优先级队列/);
  });

  await runCase("empty and malformed AI outputs remain non-success surfaces", () => {
    for (const fixture of [fixtures.empty, fixtures.malformed, fixtures.wrong_schema]) {
      hooks.setTestAIReference(fixture);
      const body = visibleBody("#ai-reference-content");
      assert.match(body, /没有生成可用建议/);
      assert.doesNotMatch(body, /hidden-provider-wrapper/);
    }
  });

  await runCase("provider failure exposes safe recovery copy", () => {
    hooks.showRecoveryPayload(fixtures.provider_failure, "solution_generation");
    const body = visibleBody("#runtime-disclosure");
    assert.match(body, /没有完成|保留|重试/);
  });

  await runCase("duplicate solutions are rejected before three cards are shown", () => {
    const candidates = fixtures.duplicate_solutions.candidates;
    assert.equal(candidates.length, 3, "duplicate fixture must contain exactly three candidates");
    assert.notEqual(candidates[0].id, candidates[1].id, "near-identical candidates must have distinct identities");
    assert.notEqual(candidates[0].title, candidates[1].title, "near-identical candidates must have distinct titles");
    assert.deepEqual(candidates[0].user_flow, candidates[1].user_flow, "duplicate pair shares the same user flow");
    assert.deepEqual(candidates[0].features, candidates[1].features, "duplicate pair shares the same feature set");
    assert.notDeepEqual(candidates[0].user_flow, candidates[2].user_flow, "third candidate is materially distinct");
    hooks.state.solutions = fixtures.duplicate_solutions;
    hooks.renderSolutions();
    const body = visibleBody("#solutions-content");
    assert.equal((getElement("#solutions-content").innerHTML.match(/class=\"solution-card\"/g) || []).length, 0, "duplicate solution set must not render cards");
    assert.doesNotMatch(body, /路径 A：规则检查台|路径 B：规则检查台增强版|班次提醒摘要/, "rejected duplicate candidates must not be visible");
    assert.match(body, /没有方案|重新生成|没有生成可用|进一步收敛/, "duplicate rejection must leave an actionable safe state");
  });

  await runCase("wrong-solution PRD is rejected instead of becoming the selected handoff", () => {
    hooks.state.snapshot = fixtures.snapshot_selected_b;
    assertDocumentSafetyContract(fixtures.documents.wrong_solution_prd, {
      validMarker: "方案：路径 B：人工复核队列",
      forbiddenMarker: /路径 A：规则检查台|自动补货/,
      label: "wrong-solution PRD",
    });
  });

  await runCase("TechDoc scope drift is rejected instead of being shown as current", () => {
    hooks.state.snapshot = fixtures.snapshot_selected_b;
    assertDocumentSafetyContract(fixtures.documents.techdoc_scope_drift, {
      validMarker: "定义队列字段",
      forbiddenMarker: /自动全量部署|自动补货/,
      label: "TechDoc scope drift",
    });
  });

  await runCase("retry clears stale solution content before the request resolves", async () => {
    const originalFetch = global.fetch;
    let release;
    global.fetch = async (path, options = {}) => {
      if (options.method === "POST" && path.endsWith("/solutions/generate")) {
        return new Promise((resolve) => { release = () => resolve({ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => fixtures.solutions_complete}); });
      }
      return {ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => ({})};
    };
    try {
      hooks.state.currentProjectId = "stale-project";
      hooks.state.generationInFlight = null;
      hooks.state.generationIntentId = null;
      hooks.state.generationTerminalFailure = true;
      hooks.state.generationFailureCode = "PROVIDER_FAILURE";
      hooks.state.solutions = {candidates: [{id: "stale", title: "过时方案"}]};
      hooks.renderSolutions();
      const generation = hooks.retryFailedGeneration();
      await Promise.resolve();
      assert.equal(typeof release, "function", "fake POST must be pending so the pre-response state is observable");
      assert.doesNotMatch(getElement("#solutions-content").innerText, /过时方案/, "retry must not keep showing stale solution cards while loading");
      release();
      await generation;
    } finally {
      global.fetch = originalFetch;
    }
  });

  const passed = results.filter((result) => result.status === "PASS").length;
  const failed = results.length - passed;
  console.log(`SUMMARY total=${results.length} passed=${passed} failed=${failed}`);
  if (failed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
