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

const elements = new Map();
function element(selector) {
  if (!elements.has(selector)) {
    elements.set(selector, {
      innerHTML: "",
      textContent: "",
      value: "",
      dataset: {},
      classList: new FakeClassList(),
      focus() { this.focused = true; },
      setAttribute() {},
      querySelectorAll() { return []; },
      addEventListener() {},
      showModal() { this.open = true; },
      close() { this.open = false; },
    });
  }
  return elements.get(selector);
}

const apiCalls = [];
function jsonResponse(body) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    headers: {get: () => "application/json"},
    json: async () => body,
  };
}

global.document = {
  querySelector: element,
  querySelectorAll: () => [],
  getElementById: (id) => elements.get(`#${id}`) || null,
  addEventListener: () => {},
  createElement: () => ({}),
};
global.window = {__INSIGHTFORGE_TEST__: true, ModelSettings: undefined};
global.setTimeout = () => 0;
global.fetch = async (path, options = {}) => {
  apiCalls.push({path, options});
  if (path === "/api/projects/project-current/snapshot/reconfirm") {
    return jsonResponse({
      id: "snapshot-current",
      version: 1,
      title: "当前 Snapshot",
      one_liner: "恢复后的 Snapshot",
      health: {health_status: "current"},
      ux_state: "executable",
      target_user: {}, solution: {}, mvp: {}, unknowns: [], inputs: [], outputs: [], user_flow: [],
    });
  }
  if (path.endsWith("/evidence/impact")) return jsonResponse({claims: [], change_proposals: []});
  if (path.endsWith("/handoff/readiness")) return jsonResponse({ready: true, documents: {}, missing: []});
  if (path === "/api/projects/project-current") return jsonResponse({document_versions: []});
  return jsonResponse([]);
};

vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});

const hooks = window.InsightForgeUi.__test;
assert.equal(typeof window.InsightForgeUi.applyGuidanceAction, "function", "Task 4 can consume the production navigation seam");
assert.equal(typeof hooks.reconfirmSnapshotHealth, "function", "test mode exposes the real Snapshot health recovery handler");
assert.equal(typeof hooks.renderImpactHistory, "function", "test mode exposes the real proposal renderer");

async function main() {
  const projectTrace = [];
  const duplicateTitleProjects = [
    {id: "project-older", title: "同名项目"},
    {id: "project-newer", title: "同名项目"},
  ];
  const projectNavigator = hooks.createGuidanceNavigator({
    hasProject: (id) => duplicateTitleProjects.some((project) => project.id === id),
    loadProject: async (id) => projectTrace.push(`load:${id}`),
    activateView: (view) => projectTrace.push(`view:${view}`),
    setEvidenceTab: (tab) => projectTrace.push(`tab:${tab}`),
    showHome: () => projectTrace.push("home"),
    focusControl: (id) => projectTrace.push(`focus:${id}`),
    openIdeaBriefReview: () => projectTrace.push("open:idea-brief-review"),
  });
  await projectNavigator({
    code: "continue_project",
    title: "继续当前项目",
    reason: "两个项目标题相同，但必须打开较新的 UUID。",
    view: "project:project-newer",
    control_id: "project-select:project-newer",
  });
  assert.deepEqual(
    projectTrace,
    ["load:project-newer", "view:snapshot", "focus:project-select"],
    "duplicate titles cannot alter the UUID-specific project selection",
  );

  hooks.state.snapshot = {id: "snapshot-current"};
  hooks.state.impacts = {
    claims: [],
    change_proposals: [
      {
        id: "proposal-secondary", status: "open", from_snapshot_id: "snapshot-current",
        summary: "第二优先建议", reason: "需要处理", affected_claims: [], affected_decisions: [],
      },
      {
        id: "proposal-priority", status: "open", from_snapshot_id: "snapshot-current",
        summary: "最高优先建议", reason: "需要先处理", affected_claims: [], affected_decisions: [],
      },
    ],
  };
  hooks.renderImpactHistory();
  const impactHtml = element("#impact-content").innerHTML;
  assert.match(impactHtml, /id="proposal-actions:proposal-priority"[^>]*data-proposal-actions-for="proposal-priority"/, "priority proposal has a unique DOM recovery target");
  assert.match(impactHtml, /id="proposal-actions:proposal-secondary"[^>]*data-proposal-actions-for="proposal-secondary"/, "secondary proposal has its own DOM recovery target");
  assert.match(impactHtml, /data-proposal-actions-for="proposal-priority"[\s\S]*?data-proposal-action="accept"[\s\S]*?data-proposal-action="defer"[\s\S]*?data-proposal-action="reject"/, "the exact proposal target contains the real decision controls");
  assert.doesNotMatch(impactHtml, /current-snapshot-proposal-actions/, "multiple proposals cannot share an ambiguous focus ID");

  const priorityControl = element("#proposal-actions:proposal-priority");
  await window.InsightForgeUi.applyGuidanceAction({
    code: "review_project_snapshot",
    title: "检查并确认项目快照",
    reason: "当前 Snapshot 有多个待处理变更。",
    view: "evidence",
    control_id: "proposal-actions:proposal-priority",
  });
  assert.equal(hooks.state.activeView, "evidence", "production navigation opens the Evidence view");
  assert.equal(hooks.state.evidenceTab, "impact", "production navigation opens the Impact tab");
  assert.equal(priorityControl.focused, true, "production navigation focuses the exact selected proposal");

  projectTrace.length = 0;
  const confirmationNavigator = hooks.createGuidanceNavigator({
    hasProject: () => true,
    loadProject: async () => {},
    activateView: (view) => projectTrace.push(`view:${view}`),
    setEvidenceTab: () => {},
    showHome: () => {},
    focusControl: (id) => projectTrace.push(`focus:${id}`),
    openIdeaBriefReview: () => projectTrace.push("open:idea-brief-review"),
  });
  await confirmationNavigator({
    code: "confirm_idea_brief",
    title: "确认或修改 Idea 理解",
    reason: "先确认系统理解。",
    view: "solutions",
    control_id: "idea-brief-confirm",
  });
  assert.deepEqual(
    projectTrace,
    ["view:solutions", "open:idea-brief-review"],
    "confirm IdeaBrief guidance opens the review UI instead of only focusing a submit control",
  );

  hooks.state.ideaBrief = {
    confirmation_status: "draft",
    target_user: "硕士研究生",
    problem: "确定研究方向后难以选择合适的论文问题",
    desired_outcome: "形成可执行的论文选题方向",
    unknowns: ["当前不知道可获得哪些数据"],
    provenance: {target_user: "model_hypothesis", problem: "model_hypothesis"},
  };
  hooks.renderIdeaBrief(true);
  const briefReviewHtml = element("#idea-brief-dialog-content").innerHTML;
  assert.match(briefReviewHtml, /id="idea-brief-target-user"[^>]*value="硕士研究生"/, "review UI prefills target user for editing");
  assert.match(briefReviewHtml, /id="idea-brief-problem"[^>]*确定研究方向后难以选择合适的论文问题/, "review UI prefills problem for editing");
  assert.match(briefReviewHtml, /id="idea-brief-desired-outcome"[^>]*形成可执行的论文选题方向/, "review UI prefills desired outcome for editing");
  assert.match(briefReviewHtml, /id="idea-brief-unknowns"[^>]*>[\s\S]*当前不知道可获得哪些数据/, "review UI prefills unknowns for editing");

  hooks.state.ideaBrief = {
    confirmation_status: "inferred",
    clarification_required: true,
    clarification_question: "请选择已有论文筛选还是新的选题推荐？",
    target_user: "硕士研究生", problem: "需要明确论文方向", desired_outcome: "形成阅读路径", unknowns: [], provenance: {},
  };
  hooks.renderIdeaBrief(true);
  const clarificationHtml = element("#idea-brief-dialog-content").innerHTML;
  assert.match(clarificationHtml, /还需要补充一项信息/, "clarification state has a visible user-facing prompt");
  assert.match(clarificationHtml, /id="idea-brief-clarification-answer"/, "clarification state has an answer control");
  hooks.state.solutions = null;
  hooks.renderSolutions();
  assert.match(element("#solutions-content").innerHTML, /还需要补充一项信息/, "clarification state does not present Generate Solutions");
  assert.doesNotMatch(element("#solutions-content").innerHTML, /id="generate-solutions-button"/, "clarification state hides the generate CTA");
  window.InsightForgeUi.reportError({code: "IDEA_BRIEF_CLARIFICATION_REQUIRED", clarificationQuestion: "请选择一个方向", message: "internal code"});
  assert.equal(element("#idea-brief-dialog").open, true, "clarification error opens the review UI");

  apiCalls.length = 0;
  hooks.state.currentProjectId = "project-current";
  hooks.state.snapshot = {
    id: "snapshot-current", version: 1, title: "当前 Snapshot", one_liner: "待重新确认",
    health: {health_status: "stale_evidence"}, ux_state: "reconfirm_required",
    target_user: {}, solution: {}, mvp: {}, unknowns: [], inputs: [], outputs: [], user_flow: [],
  };
  hooks.state.impacts = {claims: [], change_proposals: []};
  await hooks.reconfirmSnapshotHealth();
  assert.deepEqual(
    apiCalls.filter((call) => call.path.endsWith("/snapshot/reconfirm")).map((call) => [call.path, call.options.method]),
    [["/api/projects/project-current/snapshot/reconfirm", "POST"]],
    "the real recovery handler sends one explicit reconfirmation request",
  );
  assert.equal(hooks.state.snapshot.health.health_status, "current", "the real recovery handler updates Snapshot state after repair");

  console.log("guidance-navigation-behavior=PASS");
}

main().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
