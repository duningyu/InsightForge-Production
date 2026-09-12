"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const vm = require("node:vm");

const fixtures = JSON.parse(fs.readFileSync("tests/fixtures/stage_b_generation_ux_cases.json", "utf8"));
let domReadyHandler;

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
  addEventListener(name, callback) {
    const callbacks = this.listeners.get(name) || [];
    callbacks.push(callback);
    this.listeners.set(name, callbacks);
  }
  dispatchEvent(event = {}) {
    const type = typeof event === "string" ? event : event.type;
    const payload = typeof event === "string" ? {type, target: this} : {...event, target: event.target || this};
    for (const callback of this.listeners.get(type) || []) callback(payload);
    return true;
  }
  click() { return this.dispatchEvent({type: "click"}); }
  setAttribute(name, value) { this[name] = String(value); }
  removeAttribute(name) { delete this[name]; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() {}
  showModal() { this.open = true; }
  close() { this.open = false; for (const callback of this.listeners.get("close") || []) callback({type: "close", target: this}); }
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
  getElementById: (id) => getElement(`#${id}`),
  addEventListener(name, callback) { if (name === "DOMContentLoaded") domReadyHandler = callback; },
  createElement: (tagName) => new Element(tagName),
};
global.window = {__INSIGHTFORGE_TEST__: true, ModelSettings: undefined, addEventListener() {}};
global.CSS = {escape: (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&")};
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
  const completeVersion = {
    ...version,
    status: version.status || "draft",
    validation_status: version.validation_status || "not_run",
    artifact_health: version.artifact_health || {health_status: "current"},
  };
  hooks.state.documentWorkspace = {
    docType: completeVersion.doc_type,
    versions: [completeVersion],
    selectedVersionId: completeVersion.id,
    compareVersionId: null,
    draft: null,
    dirty: false,
    error: null,
  };
  hooks.renderDocumentWorkspace();
}

function completeHandoffFixture(projectId = "surface-project") {
  const handoff = JSON.parse(JSON.stringify(fixtures.handoff_ready));
  handoff.project_id = projectId;
  handoff.missing = [];
  handoff.warnings = [];
  handoff.canvas_version = 2;
  handoff.snapshot = {id: "snapshot-surface", version: 2, health_status: "current"};
  handoff.unresolved_claim_count = 0;
  handoff.acknowledgement_required = false;
  handoff.unresolved_acknowledgement = null;
  handoff.draft_unresolved_claim_count = 0;
  handoff.expected_files = ["README_FIRST.md"];
  handoff.claim_boundary = {scope: "project"};
  for (const [docType, doc] of Object.entries(handoff.documents)) {
    handoff.documents[docType] = {
      ...doc,
      document_id: `${docType}-document`,
      doc_type: docType,
      canvas_version: 2,
      validation_status: "passed",
      status: "approved",
      confirmed_at: "2026-09-12T00:00:00Z",
      health_status: "current",
    };
  }
  return handoff;
}

function jsonResponse(payload, status = 200) {
  return {ok: status >= 200 && status < 300, status, statusText: status >= 200 && status < 300 ? "OK" : "Not Found", headers: {get: () => "application/json"}, json: async () => payload};
}

function deferredResponse(payload, status = 200) {
  let settle;
  const pending = new Promise((resolve) => { settle = resolve; });
  return {
    requested: false,
    promise: pending,
    resolve() { settle(jsonResponse(payload, status)); },
  };
}

function installSurfaceFetch(routes = {}) {
  global.fetch = async (path, options = {}) => {
    const route = routes[`${options.method || "GET"} ${path}`] || routes[path];
    if (route) {
      if (route.promise) { route.requested = true; return route.promise; }
      return route;
    }
    if (path.includes("/search") || path.includes("/provider")) throw new Error(`forbidden external route ${path}`);
    if (path.endsWith("/next-action")) return jsonResponse({}, 200);
    if (path.includes("/drafts/") || path.endsWith("/draft")) return jsonResponse(null, 404);
    return jsonResponse({}, 200);
  };
}

async function flushSurfacePromises() {
  await Promise.resolve();
  await Promise.resolve();
  await new Promise((resolve) => setImmediate(resolve));
}

let surfaceBootstrapPromise;
async function driveRealSurfaceBootstrap() {
  if (surfaceBootstrapPromise) return surfaceBootstrapPromise;
  installSurfaceFetch({
    "/api/beta/consent": jsonResponse({beta_mode: false, consented: true, consent_version: 1}),
    "/api/health": jsonResponse({runtime_mode: "deterministic_demo"}),
    "/api/settings/mode": jsonResponse({managed_beta_mode: false}),
    "/api/usage/policy": jsonResponse({daily_user_limits_enabled: false}),
    "/api/projects": jsonResponse([], 200),
    "/api/examples": jsonResponse([], 200),
    "/api/history": jsonResponse({items: [], pages: 1, total: 0}, 200),
    "/api/home/next-action": jsonResponse({}, 200),
    "/api/auth/me": jsonResponse({id: "surface-test-account"}, 200),
  });
  surfaceBootstrapPromise = domReadyHandler();
  await flushSurfacePromises();
  return surfaceBootstrapPromise;
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

function inspectSolutionFixtureContract(solutionSet) {
  const script = [
    "import json, sys",
    "from pydantic import ValidationError",
    "from app.schemas import SolutionCandidateDraft",
    "from app.services.generation_contracts import GenerationContractError, validate_solution_response",
    "payload = json.loads(__import__('base64').b64decode(sys.stdin.read()).decode('utf-8'))",
    "schema_valid = True",
    "for candidate in payload.get('candidates', []):",
    "    draft = {key: value for key, value in candidate.items() if key != 'id'}",
    "    try:",
    "        SolutionCandidateDraft.model_validate(draft)",
    "    except (ValidationError, TypeError):",
    "        schema_valid = False",
    "        break",
    "result = {'schema_valid': schema_valid}",
    "if schema_valid:",
    "    try:",
    "        validate_solution_response(payload)",
    "    except GenerationContractError as exc:",
    "        result.update(response_valid=False, response_error=str(exc))",
    "    else:",
    "        result.update(response_valid=True, response_error=None)",
    "print(json.dumps(result))",
  ].join("\n");
  const childResult = childProcess.spawnSync(
    "py",
    ["-3.12", "-c", script],
    {cwd: process.cwd(), input: Buffer.from(JSON.stringify(solutionSet), "utf8").toString("base64"), encoding: "utf8"},
  );
  assert.equal(childResult.status, 0, `actual solution contract probe failed: ${childResult.stderr.trim()}`);
  return JSON.parse(childResult.stdout);
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
    hooks.state.currentProjectId = "surface-project";
    hooks.state.snapshot = {...fixtures.snapshot_selected_b, id: "snapshot-surface", health: {health_status: "current"}};
    hooks.state.handoff = completeHandoffFixture();
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
    const contract = inspectSolutionFixtureContract(fixtures.duplicate_solutions);
    assert.equal(candidates.length, 3, "duplicate fixture must contain exactly three candidates");
    assert.equal(contract.schema_valid, true, "duplicate fixture candidates must pass the solution candidate schema before quality validation");
    assert.equal(contract.response_valid, false, "duplicate fixture must fail quality validation");
    assert.equal(contract.response_error, "SOLUTION_DIVERSITY_FAILED", "duplicate fixture must fail for differentiation, not schema validity");
    const diversityFields = ["mechanism", "required_data_class", "automation_level", "human_role", "core_decision_logic", "major_dependency"];
    const normalize = (value) => String(value).replace(/\s+/g, " ").trim().toLocaleLowerCase();
    const differenceCount = (left, right) => diversityFields.filter((field) => normalize(left[field]) !== normalize(right[field])).length;
    assert.equal(differenceCount(candidates[0], candidates[1]), 1, "near-identical pair must differ in only one quality dimension");
    assert.ok(differenceCount(candidates[0], candidates[2]) >= 2, "third candidate must differ materially from the first");
    assert.ok(differenceCount(candidates[1], candidates[2]) >= 2, "third candidate must differ materially from the near-identical pair");
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
    hooks.state.snapshot = {...fixtures.snapshot_selected_b, id: "snapshot-surface", health: {health_status: "current"}};
    assertDocumentSafetyContract(fixtures.documents.wrong_solution_prd, {
      validMarker: "方案：路径 B：人工复核队列",
      forbiddenMarker: /路径 A：规则检查台|自动补货/,
      label: "wrong-solution PRD",
    });
  });

  await runCase("TechDoc scope drift is rejected instead of being shown as current", () => {
    hooks.state.snapshot = {...fixtures.snapshot_selected_b, id: "snapshot-surface", health: {health_status: "current"}};
    assertDocumentSafetyContract(fixtures.documents.techdoc_scope_drift, {
      validMarker: "定义队列字段",
      forbiddenMarker: /自动全量部署|自动补货/,
      label: "TechDoc scope drift",
    });
  });

  await runCase("real AI reference generation renders the mocked API result", async () => {
    assert.equal(typeof domReadyHandler, "function", "the harness must retain the real DOMContentLoaded surface wiring");
    await driveRealSurfaceBootstrap();
    hooks.state.currentProjectId = "surface-project";
    const response = deferredResponse({id: "reference-1", result: fixtures.ai_reference_complete});
    installSurfaceFetch({
      "POST /api/projects/surface-project/ai-reference": response,
    });
    await vm.runInThisContext("loadAIReference()", {filename: "app.js"});
    getElement("#ai-reference-generate").click();
    assert.equal(response.requested, true, "the real AI reference click handler must issue the mocked POST");
    response.resolve();
    await flushSurfacePromises();
    const body = visibleBody("#ai-reference-content");
    assert.match(body, /门店运营人员/);
    assert.match(body, /AI生成参考/);
  });

  await runCase("real Evidence Action Card generation renders every required field", async () => {
    assert.equal(typeof domReadyHandler, "function", "the real DOMContentLoaded surface wiring is required");
    hooks.state.currentProjectId = "surface-project";
    installSurfaceFetch({
      "/api/projects/surface-project/evidence-guidance": jsonResponse({id: "guidance-1", result: fixtures.action_card_complete}, 201),
    });
    hooks.selectEvidenceEntry("action_guidance");
    getElement("#evidence-guidance-generate").click();
    await flushSurfacePromises();
    const body = visibleBody("#evidence-guidance-content");
    for (const label of ["要确认什么", "找谁 / 去哪里", "具体怎么做", "拿到什么就可以填写", "填写模板", "会影响哪个产品决定", "暂时拿不到怎么办", "这条材料的局限"]) assert.match(body, new RegExp(label.replace(/[.*+?^${}()|[\\]\\]/g, "\\\\$&")));
    assert.match(body, /最近一次缺货处理经历/);
  });

  await runCase("real solution generation renders exactly three visible cards", async () => {
    hooks.state.currentProjectId = "surface-project";
    hooks.state.ideaBrief = {confirmation_status: "confirmed"};
    hooks.state.solutions = null;
    installSurfaceFetch({
      "/api/projects/surface-project/solutions/generate": jsonResponse(fixtures.solutions_complete, 200),
    });
    hooks.renderSolutions();
    getElement("#generate-solutions-button").click();
    await flushSurfacePromises();
    const body = visibleBody("#solutions-content");
    assert.equal((getElement("#solutions-content").innerHTML.match(/class=\"solution-card\"/g) || []).length, 3);
    for (const title of fixtures.solutions_complete.candidates.map((candidate) => candidate.title)) assert.match(body, new RegExp(title));
  });

  await runCase("real document and handoff loaders preserve selected references", async () => {
    hooks.state.currentProjectId = "surface-project";
    installSurfaceFetch({
      "/api/projects/surface-project/documents/prd/versions": jsonResponse([{...fixtures.documents.prd, status: "draft", validation_status: "not_run", artifact_health: {health_status: "current"}}], 200),
      "/api/projects/surface-project/documents/prd/draft": jsonResponse(null, 404),
      "/api/projects/surface-project/handoff/readiness": jsonResponse(completeHandoffFixture(), 200),
    });
    await hooks.loadDocumentWorkspace("prd");
    assert.match(getElement("#document-editor").value, /方案：路径 B：人工复核队列/);
    await vm.runInThisContext("loadHandoff()", {filename: "app.js"});
    const body = visibleBody("#handoff-content");
    assert.match(body, /PRD：已确认 v1/);
    assert.match(body, /TechDoc：已确认 v1/);
  });

  await runCase("real retry click clears stale content before the mocked response resolves", async () => {
    hooks.state.currentProjectId = "surface-project";
    hooks.state.generationInFlight = null;
    hooks.state.generationIntentId = null;
    hooks.state.generationTerminalFailure = true;
    hooks.state.generationFailureCode = "PROVIDER_FAILURE";
    hooks.state.solutions = {candidates: [{id: "stale", title: "过时方案"}]};
    hooks.renderSolutions();
    hooks.state.activeGeneration = {status: "FAILED", projectId: "surface-project", runId: "failed-run"};
    hooks.renderGenerationProgress();
    const response = deferredResponse(fixtures.solutions_complete);
    installSurfaceFetch({
      "/api/projects/surface-project/solutions/generate": response,
    });
    getElement("#generation-progress-retry").click();
    await flushSurfacePromises();
    assert.equal(response.requested, true, "the real retry click must issue a new generation POST");
    assert.doesNotMatch(getElement("#solutions-content").innerText, /过时方案/);
    response.resolve();
    await flushSurfacePromises();
  });

  const passed = results.filter((result) => result.status === "PASS").length;
  const failed = results.length - passed;
  console.log(`SUMMARY total=${results.length} passed=${passed} failed=${failed}`);
  if (failed) process.exitCode = 1;
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
