#!/usr/bin/env node

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...values) { values.forEach((value) => this.values.add(value)); }
  remove(...values) { values.forEach((value) => this.values.delete(value)); }
  toggle(value, force) {
    const next = force === undefined ? !this.values.has(value) : Boolean(force);
    if (next) this.values.add(value); else this.values.delete(value);
    return next;
  }
  contains(value) { return this.values.has(value); }
}

class FakeElement {
  constructor(selector = "") {
    this.selector = selector;
    this._innerHTML = "";
    this._textContent = "";
    this.value = "";
    this.open = false;
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.dataset = {};
    this.className = "";
    this.classList = new FakeClassList();
    this.listeners = {};
    this.closeCalls = 0;
    this.showModalCalls = 0;
    this.isConnected = true;
  }
  get innerHTML() { return this._innerHTML || (this.children || []).map((child) => child.outerHTML || child.textContent).join(""); }
  set innerHTML(value) { this._innerHTML = String(value ?? ""); this._textContent = ""; this.children = []; }
  get textContent() { return this._innerHTML ? this._innerHTML.replace(/<[^>]*>/g, " ") : (this._textContent || (this.children || []).map((child) => child.textContent).join("")); }
  set textContent(value) { this._innerHTML = ""; this._textContent = String(value ?? ""); this.children = []; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  removeEventListener(type) { delete this.listeners[type]; }
  showModal() { this.open = true; this.showModalCalls += 1; }
  close() { this.open = false; this.closeCalls += 1; }
  focus() {}
  click() { if (this.listeners.click) this.listeners.click({target: this}); }
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { delete this[name]; }
  append(...children) { this._innerHTML = ""; this.children = (this.children || []).concat(children); }
  replaceChildren(...children) { this._innerHTML = ""; this._textContent = ""; this.children = children; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
}

const appPath = require("path").resolve(__dirname, "../app/static/app.js");
const appCode = fs.readFileSync(appPath, "utf8");
const elements = new Map();
const getElement = (selector) => {
  if (!elements.has(selector)) elements.set(selector, new FakeElement(selector));
  return elements.get(selector);
};

global.window = { __INSIGHTFORGE_TEST__: true, ModelSettings: undefined, addEventListener() {} };
global.document = {
  body: getElement("body"),
  addEventListener() {},
  querySelector: getElement,
  querySelectorAll: () => [],
  getElementById: (id) => getElement(`#${id}`),
  createElement: (tag) => new FakeElement(tag),
};
global.CSS = { escape: (value) => String(value) };
global.setTimeout = (callback) => { callback(); return 0; };
global.clearTimeout = () => {};
global.fetch = async () => { throw new Error("unexpected fetch"); };

vm.runInThisContext(appCode, {filename: appPath});
const hooks = window.InsightForgeUi.__test;
assert(hooks, "app test hooks are required");

const fixtures = JSON.parse(fs.readFileSync(
  require("path").resolve(__dirname, "fixtures/stage_b_generation_ux_cases.json"),
  "utf8",
));

function clone(value) { return JSON.parse(JSON.stringify(value)); }

function resetState() {
  hooks.state.currentProjectId = "project-1";
  hooks.state.solutions = null;
  hooks.state.activeGeneration = null;
  hooks.state.handoff = null;
  hooks.state.documentWorkspace = {docType: "prd", loading: false, error: null, document: null, documents: [], versions: [], selectedVersionId: null, compareVersionId: null, draft: null, dirty: false};
  hooks.state.evidenceGuidance = null;
  for (const element of elements.values()) {
    element.innerHTML = "";
    element.textContent = "";
    element.value = "";
    element.open = false;
    element.hidden = false;
    element.disabled = false;
    element.closeCalls = 0;
    element.showModalCalls = 0;
    element.classList = new FakeClassList();
  }
  global.fetch = async () => { throw new Error("unexpected fetch"); };
}

function completeSolutionResult(status = "SUCCEEDED") {
  return {...clone(fixtures.solutions_complete), status};
}

function partialSolution() {
  return {
    id: "partial-1",
    title: "库存预警助手",
    target_user: "一线运维人员",
    problem: "库存缺货无法提前发现",
    scenarios: ["月末补货", "紧急维护"],
    why_fit: "聚合库存与维护窗口后提前提示",
    features: ["库存趋势", "维护窗口"],
    data_requirements: ["库存时间序列"],
    risks: ["库存数据延迟"],
    mvp_pages: ["告警总览"],
    implementation_plan: ["接入库存数据"],
    technical_components: ["规则引擎"],
    decision_logic: ["低库存且无维护窗口时告警"],
    tradeoffs: ["先覆盖高价值物料"],
    unknowns: ["库存延迟上限"],
  };
}

function validHandoff() {
  const documentMetadata = (docType) => ({
    version_id: `${docType}-v1`,
    document_id: `${docType}-document`,
    doc_type: docType,
    version: 1,
    canvas_version: 2,
    validation_status: "passed",
    status: "approved",
    confirmed_at: "2026-09-12T00:00:00Z",
    health_status: "current",
    unresolved_claim_count: 0,
    unresolved_items: [],
    unresolved_acknowledgement: null,
    acknowledgement_required: false,
    draft_unresolved_claim_count: 0,
    expected_files: [],
    claim_boundary: {scope: "project"},
  });
  return {
    project_id: "project-1",
    ready: true,
    missing: [],
    warnings: [],
    canvas_version: 2,
    snapshot: {id: "snapshot-1", version: 3, health_status: "current"},
    documents: {prd: documentMetadata("prd"), techdoc: documentMetadata("techdoc")},
    unresolved_claim_count: 0,
    unresolved_items: [],
    unresolved_acknowledgement: null,
    acknowledgement_required: false,
    draft_unresolved_claim_count: 0,
    expected_files: [],
    claim_boundary: {scope: "project"},
    features: ["库存预警"],
    non_goals: ["不替代人工审批"],
    implementation_tasks: ["接入数据"],
    acceptance_cases: ["提前一天告警"],
    risks: ["数据延迟"],
  };
}

async function testTerminalSuccessIsValidatedBeforeSuccessUi() {
  resetState();
  const dialog = getElement("#generation-progress-dialog");
  dialog.open = true;
  hooks.state.activeGeneration = {runId: "run-1", projectId: "project-1", status: "RUNNING"};
  global.fetch = async () => ({ok: true, headers: {get: () => "application/json"}, json: async () => ({...completeSolutionResult(), candidates: [partialSolution()]})});
  await hooks.pollSolutionGeneration("run-1", "project-1");
  assert.strictEqual(dialog.closeCalls, 0, "malformed terminal success must not close the modal");
  assert.notStrictEqual(getElement("#runtime-disclosure").textContent, "方案已生成");
  assert.strictEqual(hooks.state.solutions, null, "malformed terminal success must not become solutions state");
}

async function testValidTerminalSuccessStillCloses() {
  resetState();
  const dialog = getElement("#generation-progress-dialog");
  dialog.open = true;
  hooks.state.activeGeneration = {runId: "run-2", projectId: "project-1", status: "RUNNING"};
  global.fetch = async () => ({ok: true, headers: {get: () => "application/json"}, json: async () => completeSolutionResult()});
  await hooks.pollSolutionGeneration("run-2", "project-1");
  assert.strictEqual(dialog.closeCalls, 1, "valid terminal success should close the modal");
  assert(hooks.state.solutions, "valid terminal success should be stored");
}

function testDetailAdapterPreservesPartialCandidateAndListStaysStrict() {
  resetState();
  hooks.state.solutions = {candidates: [partialSolution()]};
  hooks.openSolutionDetails("partial-1");
  const dialog = getElement("#solution-detail-dialog");
  const content = getElement("#solution-detail-content");
  assert.strictEqual(dialog.open, true, "partial candidate should remain openable in detail view");
  assert(content.innerHTML.includes("一线运维人员"));
  assert(content.innerHTML.includes("库存缺货无法提前发现"));
  assert(content.innerHTML.includes("月末补货"));
  assert(content.innerHTML.includes("先覆盖高价值物料"));
  resetState();
  hooks.state.solutions = {candidates: [partialSolution()]};
  hooks.renderSolutions();
  assert(!getElement("#solutions-content").innerHTML.includes("solution-card"), "list adapter must remain strict");
}

function testHandoffRejectsMalformedReadyAndUnhealthyDocuments() {
  resetState();
  const malformed = validHandoff();
  delete malformed.documents.prd.validation_status;
  hooks.state.handoff = malformed;
  hooks.renderHandoff();
  assert(getElement("#handoff-content").innerHTML.includes("当前还不能安全交接"));
  assert(!getElement("#handoff-content").innerHTML.includes("PRD：已确认"));

  resetState();
  const unhealthy = validHandoff();
  unhealthy.documents.techdoc.health_status = "stale_evidence";
  hooks.state.handoff = unhealthy;
  hooks.renderHandoff();
  assert(getElement("#handoff-content").innerHTML.includes("当前还不能安全交接"));
  assert(!getElement("#handoff-content").innerHTML.includes("技术文档：已确认"));
}

async function testDocumentRequiresExplicitMatchingTypeAndContractFields() {
  const cases = [
    {name: "missing doc_type", payload: {status: "draft", validation_status: "not_run", artifact_health: {health_status: "current"}}},
    {name: "wrong doc_type", payload: {doc_type: "techdoc", status: "draft", validation_status: "not_run", artifact_health: {health_status: "current"}}},
    {name: "missing status", payload: {doc_type: "prd", validation_status: "not_run", artifact_health: {health_status: "current"}}},
    {name: "missing validation_status", payload: {doc_type: "prd", status: "draft", artifact_health: {health_status: "current"}}},
    {name: "missing artifact health", payload: {doc_type: "prd", status: "draft", validation_status: "not_run"}},
  ];
  for (const testCase of cases) {
    resetState();
    global.fetch = async () => ({ok: true, headers: {get: () => "application/json"}, json: async () => ({
      version_id: "version-1", document_id: "document-1", project_id: "project-1", version: 1,
      content: "# Draft", ...testCase.payload,
    })});
    const originalConsoleError = console.error;
    console.error = () => {};
    try {
      await hooks.generateDocument("prd");
    } finally {
      console.error = originalConsoleError;
    }
    assert(hooks.state.documentWorkspace.error, `${testCase.name} must fail safely`);
  }
}

function testEvidenceIsOptionalButCardsAreComplete() {
  resetState();
  hooks.setTestEvidenceGuidance({cards: [{title: "证据", question_to_validate: "问题", why_it_matters: "原因", decision_impact: "影响", fallback_if_unavailable: "替代", limitations: "限制"}]});
  assert(!getElement("#evidence-guidance-content").innerHTML.includes("evidence-coach-card"));
  assert(getElement("#evidence-guidance-message").textContent.includes("没有生成可用的资料行动建议"));

  resetState();
  hooks.setTestEvidenceGuidance(null);
  hooks.renderEvidenceGuidance();
  assert(!getElement("#evidence-guidance-content").innerHTML.includes("evidence-coach-card"));
}

async function main() {
  await testTerminalSuccessIsValidatedBeforeSuccessUi();
  await testValidTerminalSuccessStillCloses();
  testDetailAdapterPreservesPartialCandidateAndListStaysStrict();
  testHandoffRejectsMalformedReadyAndUnhealthyDocuments();
  await testDocumentRequiresExplicitMatchingTypeAndContractFields();
  testEvidenceIsOptionalButCardsAreComplete();
  console.log("task_2_fix_behavior_harness: PASS");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
