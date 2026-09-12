"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
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
    this.dataset = {};
    this.classList = new FakeClassList();
    this.listeners = new Map();
    this.attributes = new Map();
    this.innerHTML = "";
    this.textContent = "";
    this.showModalCalls = 0;
    this.closeCalls = 0;
  }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  removeAttribute(name) { this.attributes.delete(name); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
  focus() {}
  showModal() { this.showModalCalls += 1; this.attributes.set("open", ""); }
  close() { this.closeCalls += 1; this.attributes.delete("open"); }
}

const elements = new Map();
const completeSolutionsFixture = JSON.parse(fs.readFileSync("tests/fixtures/stage_b_generation_ux_cases.json", "utf8")).solutions_complete;
function getElement(selector) {
  if (!elements.has(selector)) elements.set(selector, new FakeElement());
  return elements.get(selector);
}

global.document = {
  querySelector: getElement,
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => new FakeElement(),
};
global.window = {__INSIGHTFORGE_TEST__: true, ModelSettings: undefined};
global.setTimeout = () => 0;

function jsonResponse(payload, status = 201) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "Created",
    headers: {get: () => "application/json"},
    json: async () => payload,
  };
}

const fetchCalls = [];
let recoveryPayload = null;
global.fetch = async (path, options = {}) => {
  fetchCalls.push({path, options});
  if (path === "/api/projects") {
    return jsonResponse([{id: "captured-project", title: "已保存的失败项目", summary: "保留输入", status: "active"}], 200);
  }
  if (path.includes("/quick-start") || path.includes("/solutions/generate")) {
    return jsonResponse(recoveryPayload, 201);
  }
  throw new Error(`unexpected fetch ${path}`);
};

vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});

const hooks = window.InsightForgeUi.__test;
assert.ok(hooks, "app.js must expose behavior hooks only in test mode");
hooks.state.runtimeMode = "hybrid";
hooks.renderRuntimeDisclosure();
assert.equal(
  getElement("#runtime-disclosure").classList.contains("hidden"),
  true,
  "unresolved hybrid health state does not claim deterministic local execution",
);
assert.equal(getElement("#runtime-note").textContent, "", "hybrid state has no local-mode label");
hooks.state.runtimeMode = "deterministic_demo";
hooks.renderRuntimeDisclosure();
assert.ok(
  getElement("#runtime-disclosure").innerHTML.includes("本地演示模式"),
  "a resolved local result may show the local-mode label",
);

const recoveryCases = {
  local: {
    error_code: "LOCAL_GUIDANCE_REQUIRED",
    message: "当前本地引导无法生成完整结果；你的输入已保留。",
    recovery_actions: ["补充目标用户与约束", "配置并测试模型后重试"],
    preserved_input: {idea: "火星设备调度", target_user: null, resources: [], priority: "fast_mvp"},
  },
  credential: {
    error_code: "MODEL_CREDENTIAL_INVALID",
    message: "模型密钥无效；你的输入已保留。",
    recovery_actions: ["重新填写密钥", "测试连接后重试"],
    preserved_input: {idea: "工业预警", target_user: "运维", resources: ["历史数据"], priority: "best_effect"},
  },
  quota: {
    error_code: "MODEL_QUOTA_EXHAUSTED",
    message: "模型额度不足；当前 IdeaBrief 已保留。",
    recovery_actions: ["补充额度后重试", "明确选择其他模型配置"],
    preserved_input: {original_idea: "高误报告警排序"},
  },
  schema: {
    error_code: "MODEL_OUTPUT_SCHEMA_INVALID",
    message: "模型输出结构无效；系统没有保存伪造的候选方案。",
    recovery_actions: ["检查结构化输出能力", "补充 Idea 细节后重试"],
    preserved_input: {original_idea: "伪正常记忆"},
  },
};

function recoveryUiText() {
  const disclosure = getElement("#runtime-disclosure");
  return `${disclosure.textContent}\n${disclosure.innerHTML}`;
}

function assertSafeRecoveryMessage(payload, suffix) {
  const rendered = recoveryUiText();
  assert.ok(rendered.includes("你的输入已保留") || rendered.includes("项目内容已保留") || rendered.includes("这次操作没有完成"), `${suffix} shows an actionable safe recovery message`);
  assert.ok(!rendered.includes("Traceback") && !rendered.includes("ValueError") && !rendered.includes("KeyError"), `${suffix} does not show a backend exception`);
  assert.ok(!rendered.includes("/app/") && !rendered.includes("\\\\"), `${suffix} does not show a server path`);
  for (const action of payload.recovery_actions) {
    const humanized = action === "retry" || action === "retry_generation" ? "重试" : action;
    assert.ok(rendered.includes(humanized) || rendered.includes("按页面提示检查后重试"), `${suffix} shows a safe recovery action`);
  }
}

async function exerciseQuickStart(payload, suffix) {
  recoveryPayload = payload;
  fetchCalls.length = 0;
  const dialog = getElement("#idea-brief-dialog");
  dialog.showModalCalls = 0;
  dialog.closeCalls = 0;
  dialog.setAttribute("open", "");
  getElement("#quick-start-idea").value = `保留-${suffix}-Idea`;
  getElement("#quick-start-target-user").value = `保留-${suffix}-用户`;
  getElement("#quick-start-resources").value = `资源-${suffix}`;
  getElement("#quick-start-priority").value = "best_effect";
  hooks.state.currentProjectId = "existing-project";
  hooks.state.ideaBrief = {id: "stale-brief"};

  await hooks.quickStart({preventDefault() {}});

  assert.equal(getElement("#quick-start-idea").value, `保留-${suffix}-Idea`, `${suffix} keeps Idea input`);
  assert.equal(getElement("#quick-start-target-user").value, `保留-${suffix}-用户`, `${suffix} keeps target input`);
  assert.equal(hooks.state.currentProjectId, "existing-project", `${suffix} never assigns undefined project ID`);
  assert.equal(hooks.state.ideaBrief, null, `${suffix} clears a stale IdeaBrief`);
  assert.equal(dialog.showModalCalls, 0, `${suffix} never opens a stale IdeaBrief dialog`);
  assert.ok(dialog.closeCalls >= 1, `${suffix} closes any stale IdeaBrief dialog`);
  assert.ok(fetchCalls.some((call) => call.path === "/api/projects"), `${suffix} refreshes history after project capture`);
  assertSafeRecoveryMessage(payload, suffix);
}

async function exerciseSolutions(payload, suffix) {
  recoveryPayload = payload;
  fetchCalls.length = 0;
  hooks.state.currentProjectId = "project-with-brief";
  hooks.state.solutions = {candidates: [{id: "stale-candidate", title: "过时候选"}]};

  await hooks.generateSolutions();

  assert.equal(hooks.state.currentProjectId, "project-with-brief", `${suffix} keeps the defined project ID`);
  assert.equal(hooks.state.solutions, null, `${suffix} clears stale candidates`);
  assert.ok(!getElement("#solutions-content").innerHTML.includes("过时候选"), `${suffix} never renders a stale candidate`);
  assert.equal(fetchCalls.length, 1, `${suffix} performs no blind follow-up request`);
  assertSafeRecoveryMessage(payload, suffix);
}

async function exerciseRetryClearsStaleFailure() {
  const originalFetch = global.fetch;
  hooks.state.runtimeMode = "hybrid";
  hooks.showRecoveryPayload({
    error_code: "PROVIDER_FAILURE",
    message: "这次操作没有完成；你的项目内容已保留。",
    recovery_actions: ["retry_generation"],
  }, "solution_generation");
  assert.equal(
    getElement("#runtime-disclosure").classList.contains("hidden"),
    false,
    "initial generation failure is visible",
  );
  global.fetch = async (path, options = {}) => {
    if (options.method === "POST") {
      const payload = JSON.parse(JSON.stringify(completeSolutionsFixture));
      payload.candidates[0].title = "可恢复方案";
      payload.candidates[0].why_fit = "用于验证重试后的成功结果。";
      return jsonResponse(payload, 200);
    }
    if (path.endsWith("/next-action")) return jsonResponse({}, 200);
    throw new Error(`unexpected retry fetch ${path}`);
  };
  try {
    hooks.state.currentProjectId = "retry-project";
    hooks.state.solutions = null;
    await hooks.generateSolutions({newIntent: true});
    assert.equal(hooks.state.solutions.candidates.length, 3, "retry renders the complete solution result");
    assert.equal(
      getElement("#runtime-disclosure").classList.contains("hidden"),
      true,
      "successful retry clears the stale failure banner",
    );
    hooks.renderRuntimeDisclosure();
    assert.equal(
      getElement("#runtime-disclosure").classList.contains("hidden"),
      true,
      "refresh-equivalent disclosure render does not restore the old failure",
    );
    hooks.showRecoveryPayload({
      error_code: "PROVIDER_FAILURE",
      message: "新的独立生成失败；你的项目内容已保留。",
      recovery_actions: ["retry_generation"],
    }, "solution_generation");
    assert.equal(
      getElement("#runtime-disclosure").classList.contains("hidden"),
      false,
      "a new independent solution failure remains visible",
    );
  } finally {
    global.fetch = originalFetch;
  }
}

async function main() {
  await exerciseQuickStart(recoveryCases.local, "local");
  await exerciseQuickStart(recoveryCases.credential, "credential");
  await exerciseSolutions(recoveryCases.quota, "quota");
  await exerciseSolutions(recoveryCases.schema, "schema");
  await exerciseRetryClearsStaleFailure();
  // Exercise the actual async orchestration, including the idle polling gap.
  const originalFetch = global.fetch;
  const originalTimeout = global.setTimeout;
  const asyncCalls = [];
  let resumePoll;
  let polls = 0;
  global.setTimeout = (callback) => { resumePoll = callback; };
  global.fetch = async (path, options = {}) => {
    asyncCalls.push({path, options});
    if (options.method === "POST") return jsonResponse({status: "PENDING", generation_run_id: "synthetic-run"}, 202);
    assert.ok(path.endsWith("/synthetic-run"), "polls the original run only");
    return jsonResponse(++polls === 1 ? {status: "RUNNING", poll_after_ms: 2000} : {...recoveryCases.schema, status: "FAILED"}, 200);
  };
  try {
    const generation = hooks.generateSolutions();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(typeof resumePoll, "function", "actual polling loop reached its wait");
    assert.equal(getElement("#loading-status").hidden, false, "progress remains visible between GET polls");
    assert.match(getElement("#loading-message").textContent, /方案正在处理中/);
    const duplicate = hooks.generateSolutions();
    assert.equal(asyncCalls.filter(call => call.options.method === "POST").length, 1, "busy state never resubmits");
    resumePoll();
    await Promise.all([generation, duplicate]);
    assert.equal(getElement("#loading-status").hidden, true, "terminal failure clears progress");
    assert.equal(asyncCalls.length, 3, "one POST and two GETs, no additional generation");
    assert.match(
      getElement("#generation-progress-state").textContent,
      /模型输出结构无效|重新生成/,
      "terminal failure shows a safe actionable message",
    );
    assert.equal(
      getElement("#generation-progress-retry").hidden,
      false,
      "terminal failure exposes a retry action",
    );
  } finally {
    global.fetch = originalFetch;
    global.setTimeout = originalTimeout;
  }
  console.log("generation-recovery-behavior=PASS");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
