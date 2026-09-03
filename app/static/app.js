"use strict";

const DEMO_DISCLOSURE = "本地演示模式：当前结构化结果用于验证工作流，不代表真实模型已理解任意 Idea。";

const state = {
  projects: [],
  currentProjectId: null,
  activeView: "snapshot",
  evidenceTab: "claims",
  ideaBrief: null,
  solutions: null,
  snapshot: null,
  sources: [],
  claims: [],
  impacts: {claims: [], change_proposals: []},
  documents: [],
  handoff: null,
  runtimeMode: null,
  managedModelMode: false,
  managedModelPreference: "AUTO",
  showAllProjects: false,
  examples: [],
  homeNextAction: null,
  projectNextAction: null,
  walkthrough: null,
  modelProfiles: [],
  projectModelProfileId: null,
  generationInFlight: null,
  generationIntentId: null,
  generationTerminalFailure: false,
  betaMode: false,
  betaConsented: false,
  betaConsentVersion: 1,
  history: {q: "", status: "all", sort: "updated_at", order: "desc", page: 1, pageSize: 10, pages: 1, total: 0, items: []},
  documentWorkspace: {docType: "prd", versions: [], selectedVersionId: null, compareVersionId: null, draft: null, autosaveTimer: null, dirty: false},
};

const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    let body = null;
    try { body = await response.json(); detail = body.detail || body.message || detail; } catch (_) {}
    const error = new Error(detail);
    error.status = response.status;
    error.code = body?.error_code || null;
    error.code = body?.code || error.code;
    error.clarificationQuestion = body?.clarification_question || null;
    throw error;
  }
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) return response;
  return response.json();
}

const BETA_ACTION_TYPES = new Set(["validate_assumption", "add_evidence", "generate_prd", "continue_project", "review_change", "open_handoff", "confirm_idea_brief", "generate_solutions", "select_solution", "export_handoff", "ready", "start_tour", "start_example_tour", "create_new_idea", "review_project_snapshot", "reconfirm_project_snapshot", "verify_project_claim", "generate_or_update_prd", "generate_or_update_techdoc", "confirm_document_versions"]);

async function trackBetaEvent(eventName, properties = {}, projectId = null) {
  if (!state.betaMode || !state.betaConsented) return {recorded: false};
  try {
    return await api("/api/beta/events", {method: "POST", body: JSON.stringify({event_name: eventName, project_id: projectId, properties})});
  } catch (error) {
    console.warn("Beta analytics event skipped", eventName, error?.status || "client_error");
    return {recorded: false};
  }
}

function trackBetaEventOnce(key, eventName, properties = {}, projectId = null) {
  const storageKey = `insightforge-beta-event:${key}`;
  const storage = globalThis.sessionStorage;
  if (storage?.getItem(storageKey)) return;
  storage?.setItem(storageKey, "1");
  void trackBetaEvent(eventName, properties, projectId);
}

async function ensureBetaConsent() {
  const status = await api("/api/beta/consent");
  state.betaMode = Boolean(status.beta_mode);
  state.betaConsented = Boolean(status.consented);
  state.betaConsentVersion = Number(status.consent_version || 1);
  updateBetaFeedbackVisibility();
  if (!state.betaMode || state.betaConsented) return;
  const dialog = qs("#beta-consent-dialog");
  dialog.showModal();
  await new Promise((resolve, reject) => {
    qs("#beta-consent-accept").addEventListener("click", async () => {
      try {
        await api("/api/beta/consent", {method: "POST", body: JSON.stringify({accepted: true, consent_version: state.betaConsentVersion})});
        state.betaConsented = true;
        updateBetaFeedbackVisibility();
        dialog.close();
        resolve();
      } catch (error) { reject(error); }
    }, {once: true});
  });
}

function updateBetaFeedbackVisibility() {
  const button = qs("#beta-feedback-button");
  if (button) button.hidden = !(state.betaMode && state.betaConsented);
}

function feedbackProjectStage() {
  const allowed = new Set(["idea", "solutions", "snapshot", "evidence", "documents", "handoff", "history", "walkthrough"]);
  return allowed.has(state.activeView) ? state.activeView : "other";
}

async function submitBetaFeedback(event) {
  event.preventDefault();
  const feedbackComment = qs("#beta-feedback-comment");
  try {
    await api("/api/beta/feedback", {
      method: "POST",
      body: JSON.stringify({
        project_id: state.currentProjectId || null,
        project_stage: feedbackProjectStage(),
        rating: Number(qs("#beta-feedback-rating").value),
        feedback_type: qs("#beta-feedback-type").value,
        comment: qs("#beta-feedback-comment").value,
      }),
    });
    feedbackComment.value = "";
    qs("#beta-feedback-dialog").close();
    toast("已收到，谢谢。");
  } catch (error) { reportError(error); }
}

function toast(message) {
  const node = qs("#toast");
  node.textContent = message;
  node.classList.add("visible");
  setTimeout(() => node.classList.remove("visible"), 3200);
}

function isStructuredRuntimeFailure(error) {
  const message = String(error?.message || "");
  return /STRUCTURED_|OPENAI_API_KEY|DETERMINISTIC_DEMO_UNSUPPORTED|CLARIFICATION_REQUIRED/.test(message);
}

function renderRuntimeDisclosure({failure = null} = {}) {
  const node = qs("#runtime-disclosure");
  if (!node) return;
  if (failure && state.runtimeMode === "llm_structured") {
    node.classList.remove("hidden");
    node.classList.add("runtime-failure");
    node.innerHTML = `<div><strong>结构化模型调用失败</strong><span>${escapeHtml(failure)}</span></div><button id="show-demo-switch-help" class="button button-secondary" type="button">切换到本地演示模式</button>`;
    qs("#show-demo-switch-help")?.addEventListener("click", () => {
      toast("切换到本地演示模式需要设置 INSIGHTFORGE_STRUCTURED_AI_MODE=deterministic_demo 并重启服务；系统不会静默切换。");
    });
    return;
  }
  node.classList.remove("runtime-failure");
  if (state.runtimeMode === "deterministic_demo") {
    node.classList.remove("hidden");
    node.innerHTML = `<div><strong>本地演示模式</strong><span>${DEMO_DISCLOSURE}</span></div>`;
  } else {
    node.classList.add("hidden");
  }
  const note = qs("#runtime-note");
  if (note) note.textContent = state.runtimeMode === "deterministic_demo" ? "本地演示模式 · 仅验证工作流" : "";
}

function reportError(error) {
  if (error?.status === 429 || isStructuredRuntimeFailure(error)) console.warn(error);
  else console.error(error);
  if (isStructuredRuntimeFailure(error)) renderRuntimeDisclosure({failure: error.message});
  if (error?.code === "IDEA_BRIEF_REQUIRED" || error?.code === "IDEA_BRIEF_NOT_CONFIRMED") {
    toast(error.message || "请先完善并确认项目定义，再生成方案。");
    const dialog = qs("#idea-brief-dialog");
    if (dialog && state.ideaBrief) {
      renderIdeaBrief(true);
      if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", "");
    } else {
      activateView("idea");
    }
    return;
  }
  if (error?.code === "IDEA_BRIEF_CLARIFICATION_REQUIRED") {
    if (state.ideaBrief) {
      state.ideaBrief = {...state.ideaBrief, clarification_required: true, clarification_question: error.clarificationQuestion || state.ideaBrief.clarification_question};
      renderIdeaBrief(true);
      const dialog = qs("#idea-brief-dialog");
      if (dialog && dialog.showModal) dialog.showModal(); else dialog?.setAttribute("open", "");
      toast("还需要补充一项信息，请回答后再确认项目理解。");
    } else {
      toast("还需要补充一项信息，请先打开项目定义。");
    }
    return;
  }
  if (error?.code === "SOLUTION_GENERATION_IN_PROGRESS") {
    toast("正在生成方案，请稍候。");
    return;
  }
  if (error?.status === 503 && error?.code === "MODEL_TIMEOUT") {
    toast("AI 服务本次响应超时，你的输入已保留，请稍后重试。");
    return;
  }
  toast(error?.message || "操作失败");
}

function isRecoveryPayload(value) {
  return Boolean(value && typeof value.error_code === "string");
}

function showRecoveryPayload(payload) {
  const message = String(payload?.message || "生成未完成；你的输入已保留。");
  const actions = Array.isArray(payload?.recovery_actions)
    ? payload.recovery_actions.map((action) => String(action)).filter(Boolean)
    : [];
  const node = qs("#runtime-disclosure");
  if (node) {
    node.classList.remove("hidden");
    node.classList.add("runtime-failure");
    node.innerHTML = `<div><strong>生成未完成 · ${escapeHtml(payload.error_code)}</strong><span>${escapeHtml(message)}</span>${actions.length ? `<ul>${actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ul>` : ""}</div>`;
  }
  toast(actions.length ? `${message} 可执行：${actions.join("；")}` : message);
}

function closeStaleIdeaBriefDialog() {
  const dialog = qs("#idea-brief-dialog");
  if (!dialog) return;
  try { dialog.close(); } catch (_) {}
  dialog.removeAttribute?.("open");
}

function mechanismLabel(value) {
  return ({
    rule_based: "规则判断",
    workflow_based: "流程设计",
    prediction_based: "预测驱动",
    recommendation_based: "推荐决策",
    optimization: "优化求解",
    search_retrieval: "检索辅助",
    automation: "自动化",
    human_in_the_loop: "人机协同",
    assistant: "智能助手",
    marketplace: "供需匹配",
    other: "其他机制",
  })[value] || value;
}

function complexityLabel(value) {
  return ({low: "低", medium: "中", high: "高"})[value] || value;
}

function evidenceStatus(value) {
  return ({
    supported: {label: "被支持", className: "status-supported", action: "继续检查证据是否覆盖真实目标用户范围"},
    limited_support: {label: "被支持 · 范围有限", className: "status-limited", action: "补充独立来源，确认是否能扩大当前结论范围"},
    contradicted: {label: "被削弱", className: "status-contradicted", action: "补充反向案例，确认是否需要调整方案"},
    conflict: {label: "存在冲突", className: "status-conflict", action: "继续验证冲突来源，不让系统自动投票决定"},
    stale: {label: "仍未解决 · 原证据已失效", className: "status-stale", action: "补充当前仍有效的证据"},
    unverified: {label: "仍未解决", className: "status-unverified", action: "添加一条能够直接回答这个判断的证据"},
  })[value] || {label: value || "仍未解决", className: "status-unverified", action: "继续验证这个判断"};
}

function claimWhyItMatters(claim) {
  return ({
    target_user: "如果目标用户不成立，后续问题定义和方案范围都需要重做。",
    user_problem: "这是方案选择的直接前提；被削弱时应重新比较解决机制。",
    behavior: "当前行为决定 MVP 应该替代、辅助还是保留哪些人工步骤。",
    value: "需要确认用户是否真的从当前方案得到价值，而不是只证明功能能运行。",
    feasibility: "这是数据或技术 Gate；失败时当前 MVP 可能无法实施。",
  })[claim.claim_type] || "该判断会影响当前产品范围或后续文档。";
}

function sourceTypeLabel(value) {
  return ({
    real_user_research: "真实用户研究",
    simulated_research: "模拟研究",
    public_source: "公开资料",
    user_input: "项目所有者输入",
    model_hypothesis: "模型假设",
    implementation_evidence: "实现证据",
  })[value] || value;
}

function showQuickStart() {
  secureSettingsExit();
  qs("#quick-start-view").classList.remove("hidden");
  qs("#model-settings-view").classList.add("hidden");
  qs("#project-shell").classList.add("hidden");
  qs("#project-context").classList.add("hidden");
  qs("#mobile-nav-button").classList.add("hidden");
}

function showProjectShell() {
  secureSettingsExit();
  qs("#quick-start-view").classList.add("hidden");
  qs("#model-settings-view").classList.add("hidden");
  qs("#project-shell").classList.remove("hidden");
  qs("#project-context").classList.remove("hidden");
  qs("#mobile-nav-button").classList.remove("hidden");
  activateView(state.activeView);
}

function secureSettingsExit() {
  window.ModelSettings?.exit();
}

function showModelSettings() {
  secureSettingsExit();
  qs("#quick-start-view").classList.add("hidden");
  qs("#project-shell").classList.add("hidden");
  qs("#model-settings-view").classList.remove("hidden");
  qs("#project-context").classList.add("hidden");
  qs("#mobile-nav-button").classList.add("hidden");
  qs("#primary-nav").classList.remove("open");
  qs("#mobile-nav-button").setAttribute("aria-expanded", "false");
  window.ModelSettings?.open();
}

function activateView(view) {
  secureSettingsExit();
  state.activeView = view;
  qsa(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  qsa(".workspace-view").forEach((node) => node.classList.toggle("hidden", node.dataset.workspaceView !== view));
  qs("#primary-nav").classList.remove("open");
  qs("#mobile-nav-button").setAttribute("aria-expanded", "false");
  if (view === "snapshot" && state.currentProjectId) trackBetaEventOnce(`snapshot:${state.currentProjectId}`, "snapshot_viewed", {}, state.currentProjectId);
}

const GUIDANCE_ACTION_FIELDS = ["code", "title", "reason", "view", "control_id"];
const WORKSPACE_VIEWS = new Set(["snapshot", "solutions", "evidence", "documents", "handoff"]);

function parseGuidanceAction(action) {
  if (!action || typeof action !== "object" || Object.keys(action).length !== GUIDANCE_ACTION_FIELDS.length || !GUIDANCE_ACTION_FIELDS.every((field) => typeof action[field] === "string")) {
    throw new Error("guidance action must contain exactly five fields");
  }
  if (action.view.startsWith("project:")) {
    const projectId = action.view.slice("project:".length);
    if (!projectId || action.control_id !== `project-select:${projectId}`) {
      throw new Error("guidance project target is invalid");
    }
    return {projectId, workspaceView: "snapshot", evidenceTab: null, controlId: "project-select"};
  }
  if (action.view === "home") {
    return {projectId: null, workspaceView: null, evidenceTab: null, controlId: action.control_id};
  }
  if (!WORKSPACE_VIEWS.has(action.view)) throw new Error("guidance workspace view is invalid");
  const proposalAction = action.control_id.startsWith("proposal-actions:");
  if (proposalAction && !action.control_id.slice("proposal-actions:".length)) {
    throw new Error("guidance proposal target is invalid");
  }
  return {
    projectId: null,
    workspaceView: action.view,
    evidenceTab: action.view === "evidence"
      ? (proposalAction ? "impact" : "claims")
      : null,
    controlId: action.control_id,
  };
}

function openIdeaBriefReview() {
  if (!state.ideaBrief) {
    activateView("idea");
    return false;
  }
  renderIdeaBrief(true);
  const dialog = qs("#idea-brief-dialog");
  if (dialog?.showModal) dialog.showModal(); else dialog?.setAttribute("open", "");
  return true;
}

function createGuidanceNavigator({hasProject, loadProject, activateView, setEvidenceTab, showHome, focusControl, openIdeaBriefReview: openReview}) {
  return async (action) => {
    const target = parseGuidanceAction(action);
    if (target.projectId) {
      if (!hasProject(target.projectId)) throw new Error("guidance project target no longer exists");
      await loadProject(target.projectId);
    }
    if (target.workspaceView) activateView(target.workspaceView);
    else if (!target.projectId) showHome();
    if (target.evidenceTab) setEvidenceTab(target.evidenceTab);
    if (action.code === "confirm_idea_brief" && openReview) openReview();
    else focusControl(target.controlId);
  };
}

function focusGuidanceControl(controlId) {
  const node = document.getElementById?.(controlId) || qs(`#${controlId}`);
  node?.focus?.();
  return Boolean(node);
}

async function applyGuidanceAction(action) {
  const navigate = createGuidanceNavigator({
    hasProject: (projectId) => state.projects.some((project) => project.id === projectId),
    loadProject,
    activateView,
    setEvidenceTab,
    showHome: showQuickStart,
    focusControl: focusGuidanceControl,
    openIdeaBriefReview,
  });
  return navigate(action);
}

function setEvidenceTab(tab) {
  state.evidenceTab = tab;
  qsa("[data-evidence-tab]").forEach((button) => {
    const active = button.dataset.evidenceTab === tab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  for (const name of ["claims", "impact", "sources"]) {
    qs(`#evidence-${name}-panel`)?.classList.toggle("hidden", name !== tab);
  }
  if (tab === "impact" && state.currentProjectId) {
    const impactCount = (state.impacts?.claims || []).length + (state.impacts?.change_proposals || []).length;
    trackBetaEventOnce(`impact:${state.currentProjectId}`, "evidence_impact_viewed", {impact_count: impactCount}, state.currentProjectId);
  }
}

function renderProjectPicker() {
  const select = qs("#project-select");
  select.innerHTML = state.projects.map((project) => `<option value="${escapeHtml(project.id)}">${escapeHtml(project.title)}</option>`).join("");
  if (state.currentProjectId) select.value = state.currentProjectId;
  const current = state.projects.find((item) => item.id === state.currentProjectId);
  qs("#nav-project-title").textContent = current?.title || "当前项目";
}

function formatProjectDate(value) {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", {year: "numeric", month: "short", day: "numeric"}).format(date);
}

function renderRecentProjects() {
  const target = qs("#recent-project-list");
  const toggle = qs("#show-all-projects");
  if (!target || !toggle) return;
  const projects = state.projects || [];
  if (!projects.length) {
    target.innerHTML = `<div class="empty-state"><p>还没有历史项目。生成第一个项目方案后，会自动显示在这里。</p></div>`;
    toggle.classList.add("hidden");
    return;
  }
  const visible = state.showAllProjects ? projects : projects.slice(0, 6);
  target.innerHTML = visible.map((project) => `
    <button class="recent-project-card" type="button" data-open-project="${escapeHtml(project.id)}">
      <span class="recent-project-meta"><b>${project.status === "example" ? "完整示例" : "历史项目"}</b><time>${escapeHtml(formatProjectDate(project.updated_at))}</time></span>
      <strong>${escapeHtml(project.title)}</strong>
      <span class="recent-project-summary">${escapeHtml(project.summary || "暂无项目摘要")}</span>
      <span class="recent-project-action">打开项目 <b aria-hidden="true">→</b></span>
    </button>`).join("");
  qsa("[data-open-project]", target).forEach((button) => button.addEventListener("click", () => loadProject(button.dataset.openProject)));
  toggle.classList.toggle("hidden", projects.length <= 6);
  toggle.textContent = state.showAllProjects ? "收起" : `查看全部历史（${projects.length}）`;
  toggle.setAttribute("aria-expanded", state.showAllProjects ? "true" : "false");
}

function renderGuidanceCard(node, action, scopeLabel) {
  if (!node) return;
  if (!action) {
    node.classList.add("hidden");
    node.innerHTML = "";
    return;
  }
  node.classList.remove("hidden");
  const location = node.id === "home-next-action-card" ? "home" : "project";
  if (BETA_ACTION_TYPES.has(action.code)) trackBetaEventOnce(`next:${location}:${action.code}:${state.currentProjectId || "home"}`, "next_action_shown", {location, action_type: action.code}, location === "project" ? state.currentProjectId : null);
  node.innerHTML = `
    <div class="next-action-copy">
      <span>${escapeHtml(scopeLabel)}</span>
      <strong>${escapeHtml(action.title)}</strong>
      <p>${escapeHtml(action.reason)}</p>
    </div>
    <button class="button button-primary" type="button">${escapeHtml(action.title)}</button>`;
  qs("button", node)?.addEventListener("click", async () => {
    try {
      if (BETA_ACTION_TYPES.has(action.code)) await trackBetaEvent("next_action_clicked", {location, action_type: action.code}, location === "project" ? state.currentProjectId : null);
      await applyGuidanceAction(action);
    } catch (error) { reportError(error); }
  });
}

async function loadHomeNextAction() {
  try { state.homeNextAction = await api("/api/home/next-action"); }
  catch (_) { state.homeNextAction = null; }
  renderGuidanceCard(qs("#home-next-action-card"), state.homeNextAction, "下一步建议");
}

async function loadProjectNextAction() {
  if (!state.currentProjectId) {
    state.projectNextAction = null;
  } else {
    try { state.projectNextAction = await api(`/api/projects/${state.currentProjectId}/next-action`); }
    catch (_) { state.projectNextAction = null; }
  }
  renderGuidanceCard(qs("#project-next-action-card"), state.projectNextAction, "当前项目 · 下一步");
}

function renderExamples() {
  const target = qs("#example-list");
  if (!target) return;
  const examples = state.examples || [];
  if (!examples.length) {
    target.innerHTML = `<div class="empty-state"><p>当前没有可复制的完整示例。</p></div>`;
    return;
  }
  target.innerHTML = examples.map((example) => `
    <article class="example-card">
      <span class="pill">完整示例</span>
      <strong>${escapeHtml(example.title)}</strong>
      <p>${escapeHtml(example.summary)}</p>
      <button class="button button-primary" type="button" data-start-example="${escapeHtml(example.id)}">复制并开始七步讲解</button>
    </article>`).join("");
  qsa("[data-start-example]", target).forEach((button) => button.addEventListener("click", () => startExampleWalkthrough(button.dataset.startExample)));
}

async function loadExamples() {
  try { state.examples = await api("/api/examples"); }
  catch (_) { state.examples = []; }
  renderExamples();
}

const WALKTHROUGH_STEPS = ["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"];
const WALKTHROUGH_COPY = {
  idea: ["1. Idea 理解", "先看系统如何把一句模糊 Idea 结构化为目标用户、核心问题、期望结果和未知项。这里的 AI 推断仍然是待验证假设。"],
  solutions: ["2. 方案比较", "比较三个不同解决机制。重点看它们的数据依赖、自动化程度、人工角色、实施成本和最大风险，而不是比较三个不同名字。"],
  mvp: ["3. MVP 与 Project Snapshot", "查看当前正式方案、MVP 页面、输入输出、实施计划、关键未知项和下一步验证任务。"],
  claims: ["4. 关键判断", "把目标用户、问题、行为、价值和可行性拆成可验证 Claim。用户确认系统理解，不等于这些 Claim 已经被市场验证。"],
  evidence: ["5. 证据影响", "资料上传后查看它支持、削弱还是与哪个 Claim 冲突，以及这是否会影响当前 Decision 和 Snapshot。"],
  documents: ["6. PRD / TechDoc", "在当前 Snapshot 和有效证据基础上生成正式文档。你可以在线编辑、自动保存草稿、比较版本，并把旧版本恢复为一个新的不可变版本。"],
  handoff: ["7. 开发交接", "只有当前 Snapshot 与确认且健康的 PRD / TechDoc 才进入交接。这里可以生成 Codex 等开发工具需要的正式上下文。"],
};

function walkthroughStepIndex(currentStep) {
  const index = WALKTHROUGH_STEPS.indexOf(currentStep);
  return index >= 0 ? index : 0;
}

function activateWalkthroughStep(step) {
  if (step === "idea" || step === "solutions") activateView("solutions");
  else if (step === "mvp") activateView("snapshot");
  else if (step === "claims") { activateView("evidence"); setEvidenceTab("claims"); }
  else if (step === "evidence") { activateView("evidence"); setEvidenceTab("impact"); }
  else if (step === "documents") activateView("documents");
  else if (step === "handoff") activateView("handoff");
}

function renderWalkthrough() {
  const panel = qs("#walkthrough-panel");
  if (!panel) return;
  const tour = state.walkthrough;
  if (!tour || tour.current_step === "skipped") {
    panel.classList.add("hidden");
    return;
  }
  panel.classList.remove("hidden");
  if (tour.current_step === "complete") {
    qs("#walkthrough-progress-text").textContent = "7 / 7 · 已完成";
    qs("#walkthrough-progress").value = 7;
    qs("#walkthrough-step-title").textContent = "完整示例讲解已完成";
    qs("#walkthrough-step-copy").textContent = "你可以继续在这个独立副本中修改内容，或重新开始七步讲解。";
    qs("#walkthrough-next").classList.add("hidden");
    return;
  }
  qs("#walkthrough-next").classList.remove("hidden");
  const step = tour.current_step || "idea";
  const index = walkthroughStepIndex(step);
  const copy = WALKTHROUGH_COPY[step] || WALKTHROUGH_COPY.idea;
  qs("#walkthrough-progress-text").textContent = `步骤 ${index + 1} / ${WALKTHROUGH_STEPS.length}`;
  qs("#walkthrough-progress").value = index + 1;
  qs("#walkthrough-step-title").textContent = copy[0];
  qs("#walkthrough-step-copy").textContent = copy[1];
  qs("#walkthrough-next").textContent = index === WALKTHROUGH_STEPS.length - 1 ? "完成讲解" : "下一步";
  activateWalkthroughStep(step);
}

async function startExampleWalkthrough(exampleId) {
  try {
    const copied = await api(`/api/examples/${encodeURIComponent(exampleId)}/copies`, {method: "POST"});
    await loadProjects();
    await loadProject(copied.id);
    state.walkthrough = await api(`/api/projects/${copied.id}/walkthrough/start`, {method: "POST"});
    renderWalkthrough();
    await Promise.all([loadHomeNextAction(), loadProjectNextAction(), loadHistory()]);
    toast("已复制完整示例。讲解进度会保存在这个独立项目中。");
  } catch (error) { reportError(error); }
}

async function loadWalkthrough({silent = true} = {}) {
  if (!state.currentProjectId) { state.walkthrough = null; renderWalkthrough(); return; }
  try {
    state.walkthrough = await api(`/api/projects/${state.currentProjectId}/walkthrough`);
  } catch (error) {
    state.walkthrough = null;
    if (!silent && error?.status !== 404) reportError(error);
  }
  renderWalkthrough();
}

async function advanceWalkthrough() {
  if (!state.currentProjectId || !state.walkthrough || !WALKTHROUGH_STEPS.includes(state.walkthrough.current_step)) return;
  try {
    state.walkthrough = await api(`/api/projects/${state.currentProjectId}/walkthrough/advance`, {method: "POST", body: JSON.stringify({step: state.walkthrough.current_step})});
    renderWalkthrough();
    await Promise.all([loadHomeNextAction(), loadProjectNextAction()]);
  } catch (error) { reportError(error); }
}

async function skipWalkthrough() {
  if (!state.currentProjectId) return;
  try {
    state.walkthrough = await api(`/api/projects/${state.currentProjectId}/walkthrough/skip`, {method: "POST"});
    renderWalkthrough();
    await loadHomeNextAction();
    toast("已跳过讲解。项目内容不会删除，可随时重新开始。");
  } catch (error) { reportError(error); }
}

async function restartWalkthrough() {
  if (!state.currentProjectId) return;
  try {
    state.walkthrough = await api(`/api/projects/${state.currentProjectId}/walkthrough/restart`, {method: "POST"});
    renderWalkthrough();
    toast("七步讲解已从第一步重新开始。");
  } catch (error) { reportError(error); }
}

function historyQuery() {
  const h = state.history;
  const params = new URLSearchParams({q: h.q, status: h.status, sort: h.sort, order: h.order, page: String(h.page), page_size: String(h.pageSize)});
  return params.toString();
}

function renderHistory() {
  const target = qs("#history-project-list");
  if (!target) return;
  const h = state.history;
  if (!h.items.length) {
    target.innerHTML = `<div class="empty-state"><p>${h.status === "trashed" ? "回收箱为空。" : "没有符合当前条件的项目。"}</p></div>`;
  } else {
    target.innerHTML = h.items.map((project) => {
      const trashed = project.status === "trashed";
      const isExample = project.status === "example";
      const lineage = project.parent_project_id ? `<small>复制自 ${escapeHtml(project.parent_project_id)}</small>` : "";
      return `<article class="history-project-card">
        <div class="history-project-main"><span class="pill">${escapeHtml(trashed ? "回收箱" : isExample ? "完整示例" : "项目")}</span><strong>${escapeHtml(project.title)}</strong><p>${escapeHtml(project.summary || "暂无摘要")}</p>${lineage}<time>${escapeHtml(formatProjectDate(project.updated_at))}</time></div>
        <div class="history-project-actions">
          ${trashed ? `<button class="button button-secondary" data-history-restore="${escapeHtml(project.id)}" type="button">恢复</button><button class="button button-quiet" data-history-purge="${escapeHtml(project.id)}" type="button">永久删除</button>` : `<button class="button button-secondary" data-history-open="${escapeHtml(project.id)}" type="button">打开</button><button class="button button-secondary" data-history-copy="${escapeHtml(project.id)}" data-history-example="${isExample ? "1" : "0"}" type="button">复制</button>${isExample ? "" : `<button class="button button-quiet" data-history-trash="${escapeHtml(project.id)}" type="button">移入回收箱</button>`}`}
        </div>
      </article>`;
    }).join("");
  }
  qs("#history-page-status").textContent = `第 ${h.page} / ${h.pages} 页 · 共 ${h.total} 个`;
  qs("#history-prev").disabled = h.page <= 1;
  qs("#history-next").disabled = h.page >= h.pages;
  qsa("[data-history-open]", target).forEach((button) => button.addEventListener("click", () => loadProject(button.dataset.historyOpen)));
  qsa("[data-history-copy]", target).forEach((button) => button.addEventListener("click", () => copyHistoryProject(button.dataset.historyCopy, button.dataset.historyExample === "1")));
  qsa("[data-history-trash]", target).forEach((button) => button.addEventListener("click", () => trashHistoryProject(button.dataset.historyTrash)));
  qsa("[data-history-restore]", target).forEach((button) => button.addEventListener("click", () => restoreHistoryProject(button.dataset.historyRestore)));
  qsa("[data-history-purge]", target).forEach((button) => button.addEventListener("click", () => purgeHistoryProject(button.dataset.historyPurge)));
}

async function loadHistory() {
  try {
    const payload = await api(`/api/projects/history?${historyQuery()}`);
    state.history = {...state.history, ...payload, items: payload.items || []};
  } catch (_) {
    state.history = {...state.history, items: [], total: 0, pages: 1};
  }
  renderHistory();
}

async function copyHistoryProject(projectId, isExample = false) {
  try {
    const path = isExample ? `/api/examples/${encodeURIComponent(projectId)}/copies` : `/api/projects/${encodeURIComponent(projectId)}/copy`;
    const copied = await api(path, {method: "POST"});
    await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
    toast("已创建独立副本；后续编辑不会修改源项目。");
    await loadProject(copied.id);
  } catch (error) { reportError(error); }
}

async function trashHistoryProject(projectId) {
  try {
    await api(`/api/projects/${encodeURIComponent(projectId)}/trash`, {method: "POST"});
    if (state.currentProjectId === projectId) { state.currentProjectId = null; showQuickStart(); }
    await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
    toast("项目已移入集中回收箱。");
  } catch (error) { reportError(error); }
}

async function restoreHistoryProject(projectId) {
  try {
    await api(`/api/projects/${encodeURIComponent(projectId)}/restore`, {method: "POST"});
    await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
    toast("项目已恢复。");
  } catch (error) { reportError(error); }
}

async function purgeHistoryProject(projectId) {
  if (!window.confirm("永久删除后无法通过回收箱恢复。确认删除这个项目？")) return;
  try {
    await api(`/api/projects/${encodeURIComponent(projectId)}`, {method: "DELETE"});
    await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
    toast("项目已永久删除。");
  } catch (error) { reportError(error); }
}

let historySearchTimer = null;
function scheduleHistorySearch() {
  clearTimeout(historySearchTimer);
  historySearchTimer = setTimeout(async () => {
    state.history.q = qs("#history-search").value.trim();
    state.history.page = 1;
    await loadHistory();
  }, 320);
}

async function loadProjectModelProfile() {
  const select = qs("#project-model-profile");
  if (!select || !state.currentProjectId) return;
  try {
    const [profiles, override] = await Promise.all([
      api("/api/settings/model-profiles"),
      api(`/api/projects/${state.currentProjectId}/model-profile`),
    ]);
    state.modelProfiles = profiles || [];
    state.projectModelProfileId = override?.profile_id || null;
    const managed = state.managedModelMode || state.modelProfiles.some((profile) => String(profile.id || "").startsWith("managed_"));
    select.closest(".project-model-field")?.classList.toggle("hidden", managed);
    if (managed) return;
    select.innerHTML = `<option value="">继承全局模型</option>${state.modelProfiles.filter((profile) => profile.enabled).map((profile) => `<option value="${escapeHtml(profile.id)}">${escapeHtml(profile.display_name)} · ${escapeHtml(profile.provider)}</option>`).join("")}`;
    select.value = state.projectModelProfileId || "";
  } catch (error) {
    console.error(error);
    select.innerHTML = `<option value="">继承全局模型</option>`;
  }
}

async function saveProjectModelProfile() {
  if (!state.currentProjectId) return;
  const profileId = qs("#project-model-profile").value || null;
  try {
    const result = await api(`/api/projects/${state.currentProjectId}/model-profile`, {method: "PUT", body: JSON.stringify({profile_id: profileId})});
    state.projectModelProfileId = result.profile_id || null;
    toast(profileId ? "已为当前项目启用模型覆盖。" : "当前项目已恢复为继承全局模型。");
  } catch (error) { reportError(error); await loadProjectModelProfile(); }
}


function renderIdeaBrief(dialog = false) {
  if (!state.ideaBrief) return;
  const brief = state.ideaBrief;
  const target = dialog ? qs("#idea-brief-dialog-content") : qs("#idea-brief-content");
  if (!target) return;
  if (dialog) {
    const unknowns = (brief.unknowns || []).join("\n");
    const clarification = brief.clarification_required
      ? `<div class="clarification-panel"><strong>还需要补充一项信息</strong><p>${escapeHtml(brief.clarification_question || "请补充当前项目的关键范围。")} </p><label>你的回答<textarea id="idea-brief-clarification-answer" rows="3" required placeholder="请直接回答上面的澄清问题"></textarea></label><small class="muted">回答后仍需点击“确认项目理解”，系统不会自动生成方案。</small></div>`
      : "";
    target.innerHTML = `
      <p class="muted">请检查并补充以下理解；确认前不会生成方案。</p>
      ${clarification}
      <label>目标用户<input id="idea-brief-target-user" value="${escapeHtml(brief.target_user)}" /></label>
      <small class="muted">${escapeHtml(brief.provenance?.target_user === "user_input" ? "用户明确输入" : "AI 推断 · 待验证")}</small>
      <label>核心问题<input id="idea-brief-problem" value="${escapeHtml(brief.problem)}" /></label>
      <small class="muted">${escapeHtml(brief.provenance?.problem === "user_input" ? "用户明确输入" : "AI 推断 · 待验证")}</small>
      <label>希望结果<input id="idea-brief-desired-outcome" value="${escapeHtml(brief.desired_outcome)}" /></label>
      <label>目前不知道<textarea id="idea-brief-unknowns" rows="3">${escapeHtml(unknowns)}</textarea></label>`;
    return;
  }
  target.innerHTML = `
    <div class="brief-grid">
      <article><span>目标用户</span><strong>${escapeHtml(brief.target_user)}</strong><small>${escapeHtml(brief.provenance?.target_user === "user_input" ? "用户明确输入" : "AI 推断 · 待验证")}</small></article>
      <article><span>核心问题</span><strong>${escapeHtml(brief.problem)}</strong><small>${escapeHtml(brief.provenance?.problem === "user_input" ? "用户明确输入" : "AI 推断 · 待验证")}</small></article>
      <article><span>希望结果</span><strong>${escapeHtml(brief.desired_outcome)}</strong></article>
      <article><span>目前不知道</span><ul>${(brief.unknowns || []).map((x) => `<li>${escapeHtml(x)}</li>`).join("") || "<li>暂无</li>"}</ul></article>
    </div>`;
}

function detailList(title, items = []) {
  return `<div class="detail-block"><strong>${escapeHtml(title)}</strong><ul>${items.map((x) => `<li>${escapeHtml(x)}</li>`).join("") || "<li>暂无</li>"}</ul></div>`;
}

function renderSolutions() {
  const target = qs("#solutions-content");
  if (!target) return;
  if (!state.solutions?.candidates?.length) {
    const confirmed = state.ideaBrief?.confirmation_status === "confirmed";
    const clarificationRequired = Boolean(state.ideaBrief?.clarification_required);
    const action = clarificationRequired
      ? `<button id="open-idea-brief-button" class="button button-primary" type="button">补充信息</button>`
      : confirmed
      ? `<label class="managed-model-choice" for="managed-model-preference">模型<select id="managed-model-preference"><option value="AUTO">自动（默认 Qwen3.7-Flash）</option><option value="QWEN">Qwen3.7-Flash</option><option value="GLM">GLM-5.2</option><option value="DEEPSEEK">DeepSeek V4 Flash</option></select></label><button id="generate-solutions-button" class="button button-primary" type="button" aria-disabled="false">${state.generationTerminalFailure ? "重新生成" : "生成方案"}</button>`
      : `<button id="open-idea-brief-button" class="button button-primary" type="button">查看并确认项目定义</button>`;
    const message = clarificationRequired
      ? "还需要补充一项信息，完成澄清后才能确认项目理解并生成方案。"
      : confirmed
      ? "确认 Idea 理解后生成 2–3 个真正不同的解决路径。"
      : state.ideaBrief
        ? "项目定义已根据现有信息整理完成，确认后即可生成方案。"
        : "生成方案前还需要完善并确认项目定义。";
    target.innerHTML = `<div class="empty-state"><h3>还没有方案</h3><p>${message}</p>${action}</div>`;
    qs("#generate-solutions-button")?.addEventListener("click", () => generateSolutions({newIntent: state.generationTerminalFailure}));
    const modelChoice = qs("#managed-model-preference");
    if (modelChoice) {
      modelChoice.value = state.managedModelPreference;
      modelChoice.addEventListener("change", (event) => { state.managedModelPreference = event.target.value; });
    }
    qs("#open-idea-brief-button")?.addEventListener("click", openIdeaBriefReview);
    return;
  }
  target.innerHTML = `<div class="solution-grid">${state.solutions.candidates.map((solution, index) => `
    <article class="solution-card" data-candidate-id="${escapeHtml(solution.id)}">
      <div class="solution-card-head"><span>方案 ${String.fromCharCode(65 + index)}</span><span class="pill">${escapeHtml(mechanismLabel(solution.mechanism))}</span></div>
      <h3>${escapeHtml(solution.title)}</h3>
      <p>${escapeHtml(solution.why_fit)}</p>
      <dl class="compact-spec"><div><dt>MVP 难度</dt><dd>${escapeHtml(complexityLabel(solution.complexity))}</dd></div><div><dt>数据要求</dt><dd>${escapeHtml((solution.data_requirements || [])[0] || "待确认")}</dd></div><div><dt>最大风险</dt><dd>${escapeHtml((solution.risks || [])[0] || "待验证")}</dd></div></dl>
      <details><summary>查看完整实施方案</summary>
        ${detailList("用户流程", solution.user_flow)}
        ${detailList("MVP 页面", solution.mvp_pages)}
        ${detailList("核心功能", solution.features)}
        ${detailList("输入", solution.inputs)}
        ${detailList("输出", solution.outputs)}
        ${detailList("核心判断逻辑", solution.decision_logic)}
        ${detailList("数据来源", solution.data_requirements)}
        ${detailList("技术组成", solution.technical_components)}
        ${detailList("两周实施", solution.implementation_plan)}
        ${detailList("验收案例", solution.acceptance_cases)}
        ${detailList("当前未知项", solution.unknowns)}
      </details>
      <button class="button button-secondary select-solution-button" type="button" data-candidate-id="${escapeHtml(solution.id)}">采用这个方案</button>
    </article>`).join("")}</div>`;
  qsa(".select-solution-button", target).forEach((button) => button.addEventListener("click", () => selectSolution(button.dataset.candidateId)));
}

function renderSnapshot() {
  const target = qs("#snapshot-content");
  const action = qs("#snapshot-primary-action");
  const reconfirm = qs("#snapshot-health-reconfirm");
  if (!state.snapshot) {
    target.innerHTML = `<div class="empty-state"><h2>还没有项目成果</h2><p>确认一个方案后，这里会生成第一份 Project Snapshot。</p></div>`;
    action.classList.add("hidden");
    reconfirm.classList.add("hidden");
    return;
  }
  const snap = state.snapshot;
  const unknown = (snap.unknowns || [])[0] || "暂无关键未知项";
  const solutionTitle = snap.solution?.title || snap.title;
  target.innerHTML = `
    <div class="snapshot-hero"><p class="eyebrow">PROJECT SNAPSHOT · V${escapeHtml(snap.version)}</p><h1>${escapeHtml(snap.title)}</h1><p>${escapeHtml(snap.one_liner)}</p></div>
    <div class="snapshot-grid">
      <article class="result-card"><span>目标用户</span><strong>${escapeHtml(snap.target_user?.primary || "待确认")}</strong><small>${escapeHtml(snap.target_user?.verification_status || "待验证")}</small></article>
      <article class="result-card emphasis"><span>当前方案</span><strong>${escapeHtml(solutionTitle)}</strong><small>${escapeHtml(snap.solution?.rationale || "当前信息下的首选验证路径")}</small></article>
      <article class="result-card"><span>MVP</span><strong>${escapeHtml((snap.mvp?.pages || []).length)} 个页面 · ${escapeHtml((snap.mvp?.features || []).length)} 个核心能力</strong><small>${escapeHtml((snap.mvp?.implementation_plan || [])[0] || "按最小范围实施")}</small></article>
      <article class="result-card risk"><span>当前最大未知项</span><strong>${escapeHtml(unknown)}</strong><small>优先验证会改变方案的判断</small></article>
    </div>
    <section class="snapshot-section"><h2>产品流程</h2><div class="flow-row">${(snap.user_flow || []).map((step) => `<span>${escapeHtml(step)}</span>`).join("<b>→</b>")}</div></section>
    <section class="snapshot-section"><h2>输入 / 输出</h2><div class="two-column"><div>${detailList("输入", snap.inputs || [])}</div><div>${detailList("输出", snap.outputs || [])}</div></div></section>`;
  const next = snap.next_action || {};
  action.textContent = next.action || "继续验证关键判断";
  action.dataset.claimId = next.claim_id || "";
  action.classList.remove("hidden");
  reconfirm.classList.toggle("hidden", snap.ux_state !== "reconfirm_required" || Boolean(snap.has_open_proposal));
}

function renderEvidenceClaims() {
  const target = qs("#evidence-content");
  const claims = state.claims || [];
  target.innerHTML = claims.length ? claims.map((claim, index) => {
    const status = evidenceStatus(claim.verification_status);
    return `<article class="evidence-priority-card">
      <div class="evidence-card-top"><span>优先级 ${index + 1}</span><span class="evidence-status ${status.className}">${escapeHtml(status.label)}</span></div>
      <h3>${escapeHtml(claim.statement)}</h3>
      <p>${escapeHtml(claimWhyItMatters(claim))}</p>
      <small>${escapeHtml(claim.scope_note || "当前仍需验证")}</small>
      <div class="evidence-action"><span>${escapeHtml(status.action)}</span><button class="button button-secondary" data-validate-claim="${escapeHtml(claim.id)}" type="button">验证这个判断</button></div>
    </article>`;
  }).join("") : `<div class="empty-state"><p>确认方案后，这里会列出最需要验证的关键判断。</p></div>`;
  qsa("[data-validate-claim]", target).forEach((button) => button.addEventListener("click", () => {
    setEvidenceTab("sources");
    const claim = state.claims.find((item) => item.id === button.dataset.validateClaim);
    if (claim) qs("#evidence-title").value = `验证：${claim.statement}`.slice(0, 200);
    qs("#evidence-text")?.focus();
  }));
}

function impactLabelForClaim(claim) {
  const status = evidenceStatus(claim.verification_status);
  return status.label;
}

function renderImpactHistory() {
  const target = qs("#impact-content");
  const claims = state.impacts?.claims || [];
  const proposals = state.impacts?.change_proposals || [];
  const claimRows = claims.map((claim) => `<article class="impact-row"><span class="impact-label">${escapeHtml(impactLabelForClaim(claim))}</span><div><strong>${escapeHtml(claim.statement)}</strong><p>${escapeHtml(claim.scope_note || "当前证据范围未扩大到市场事实。")}</p></div></article>`).join("");
  const proposalRows = proposals.map((proposal) => {
    const open = proposal.status === "open";
    const proposalActionsId = `proposal-actions:${proposal.id}`;
    return `<article class="proposal-card">
      <div class="proposal-head"><span>CHANGE PROPOSAL</span><strong>${escapeHtml(proposal.status)}</strong></div>
      <h3>${escapeHtml(proposal.summary)}</h3>
      <p>${escapeHtml(proposal.reason)}</p>
      <div class="proposal-meta"><span>受影响 Claim：${escapeHtml((proposal.affected_claims || []).length)}</span><span>受影响 Decision：${escapeHtml((proposal.affected_decisions || []).length)}</span></div>
      ${open ? `<div id="${escapeHtml(proposalActionsId)}" class="proposal-actions" data-proposal-actions-for="${escapeHtml(proposal.id)}" tabindex="-1"><button class="button button-primary" data-proposal-action="accept" data-proposal-id="${escapeHtml(proposal.id)}" type="button">接受修改</button><button class="button button-secondary" data-proposal-action="defer" data-proposal-id="${escapeHtml(proposal.id)}" type="button">暂不修改</button><button class="button button-quiet" data-proposal-action="reject" data-proposal-id="${escapeHtml(proposal.id)}" type="button">标记为冲突继续验证</button></div>` : `<small>该建议已由用户处理，正式版本不会被自动回写。</small>`}
    </article>`;
  }).join("");
  target.innerHTML = `${claimRows || `<div class="empty-state"><p>当前还没有可展示的证据影响。</p></div>`}${proposalRows ? `<section class="proposal-list"><h3>需要你确认的调整</h3>${proposalRows}</section>` : ""}`;
  qsa("[data-proposal-action]", target).forEach((button) => button.addEventListener("click", () => decideChangeProposal(button.dataset.proposalId, button.dataset.proposalAction)));
}

function renderSourceLibrary() {
  qs("#source-list").innerHTML = (state.sources || []).map((source) => `<article class="source-row"><div><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(sourceTypeLabel(source.source_type))}</small></div><span>${escapeHtml(source.status)}</span></article>`).join("") || "<p class=\"muted\">暂无资料。添加资料后，还需要运行影响分析才能形成 Evidence → Claim 关系。</p>";
}

function renderEvidence() {
  renderEvidenceClaims();
  renderImpactHistory();
  renderSourceLibrary();
  setEvidenceTab(state.evidenceTab);
}

function latestDocumentFor(docType) {
  return (state.documents || []).find((item) => item.doc_type === docType) || null;
}

function documentGenerateAttribute(docType) {
  if (docType === "prd") return 'data-generate-doc="prd"';
  if (docType === "techdoc") return 'data-generate-doc="techdoc"';
  throw new Error(`unsupported document type: ${docType}`);
}

function renderDocumentCard(docType, title, description) {
  const generateAttribute = documentGenerateAttribute(docType);
  const doc = latestDocumentFor(docType);
  if (!doc) {
    return `<article><h3>${title}</h3><p>${description}</p><p class="document-state">尚未生成。</p><button class="button button-secondary" ${generateAttribute} type="button">生成 ${title}</button></article>`;
  }
  const health = doc.artifact_health?.health_status || "unknown";
  const confirmed = doc.status === "approved";
  const stale = health === "stale_evidence" || health === "needs_review";
  const dependencyLabels = (doc.dependencies || []).map((dep) => `${dep.dependency_type}:${dep.dependency_id}`).slice(0, 8);
  let statusCopy = "当前草稿";
  if (confirmed && stale) statusCopy = "历史确认 · 当前证据已变化";
  else if (confirmed && health === "current") statusCopy = "已确认 · 当前有效";
  else if (doc.validation_status === "passed" && health === "current") statusCopy = "系统检查通过 · 等待用户确认";
  else if (stale) statusCopy = "当前版本需要重新检查";
  const warning = stale ? `<div class="document-warning"><strong>受影响：</strong>${escapeHtml(doc.artifact_health?.reason || "当前 Snapshot / Claim / Source 依赖发生变化")}${dependencyLabels.length ? `<small>受影响依赖：${escapeHtml(dependencyLabels.join("、"))}</small>` : ""}<small>历史内容保持不变；请基于当前证据重新生成或检查，而不是覆盖旧版本。</small></div>` : "";
  const canConfirm = !confirmed && doc.validation_status === "passed" && health === "current";
  return `<article class="document-card ${stale ? "document-stale" : ""}">
    <div class="document-card-head"><h3>${title}</h3><span>v${escapeHtml(doc.version)}</span></div>
    <p>${description}</p><p class="document-state">${escapeHtml(statusCopy)}</p>${warning}
    <div class="document-actions">
      ${canConfirm ? `<button class="button button-primary" data-confirm-doc="${escapeHtml(doc.id)}" type="button">确认此版本</button>` : ""}
      <button class="button button-secondary" ${generateAttribute} type="button">${stale ? "基于当前证据重新生成" : "生成新版本"}</button>
      <a class="button button-quiet" href="/api/documents/${encodeURIComponent(doc.id)}/export?format=md">导出 MD</a>
    </div>
    <details class="technical-details"><summary>查看技术详情</summary><pre>${escapeHtml(JSON.stringify({validation_status: doc.validation_status, lifecycle_status: doc.lifecycle_status, artifact_health: doc.artifact_health, dependencies: doc.dependencies || []}, null, 2))}</pre></details>
  </article>`;
}

function renderDocuments() {
  qs("#documents-content").innerHTML = `<div class="document-grid">${renderDocumentCard("prd", "PRD", "从当前 Project Snapshot、项目级 Claim 和有效证据生成。")}${renderDocumentCard("techdoc", "TechDoc", "把当前 MVP 范围、技术约束与验收边界转成开发上下文。")}</div>`;
  qsa("[data-generate-doc]").forEach((button) => button.addEventListener("click", () => generateDocument(button.dataset.generateDoc)));
  qsa("[data-confirm-doc]").forEach((button) => button.addEventListener("click", () => confirmDocument(button.dataset.confirmDoc)));
  renderDocumentWorkspace();
}

const DOCUMENT_DRAFT_PATHS = {
  prd: "/documents/prd/draft",
  techdoc: "/documents/techdoc/draft",
};

function selectedDocumentVersion() {
  return state.documentWorkspace.versions.find((version) => version.id === state.documentWorkspace.selectedVersionId) || null;
}

function compareDocumentVersion() {
  return state.documentWorkspace.versions.find((version) => version.id === state.documentWorkspace.compareVersionId) || null;
}

function renderDocumentWorkspace() {
  const editor = qs("#document-editor");
  const list = qs("#document-version-list");
  if (!editor || !list) return;
  const workspace = state.documentWorkspace;
  const selected = selectedDocumentVersion();
  const draftMatches = workspace.draft && selected && workspace.draft.base_version_id === selected.id;
  const expectedContent = draftMatches ? workspace.draft.content : selected?.content || "";
  if (!workspace.dirty || editor.dataset.loadedVersionId !== (selected?.id || "")) {
    editor.value = expectedContent;
    editor.dataset.loadedVersionId = selected?.id || "";
    workspace.dirty = false;
  }
  editor.disabled = !selected;
  qs("#document-save-version").disabled = !selected;
  qs("#document-validate-selected").disabled = !selected;
  qs("#document-restore-selected").disabled = !selected;
  qs("#document-export-selected").disabled = !selected;
  qs("#document-autosave-status").textContent = selected
    ? (draftMatches ? `草稿已保存 · 基于 v${selected.version}` : `正在编辑 v${selected.version} · 修改会自动保存为草稿`)
    : "先生成一个文档版本后开始编辑";

  list.innerHTML = workspace.versions.length ? workspace.versions.map((version) => {
    const selectedClass = version.id === workspace.selectedVersionId ? " selected" : "";
    const compareClass = version.id === workspace.compareVersionId ? " compare" : "";
    const health = version.artifact_health?.health_status || "unknown";
    return `<article class="document-version-row${selectedClass}${compareClass}">
      <div><strong>v${escapeHtml(version.version)}</strong><span>${escapeHtml(version.status || "draft")} · ${escapeHtml(version.validation_status || "not_run")} · ${escapeHtml(health)}</span><small>${escapeHtml(formatProjectDate(version.created_at))}</small></div>
      <div class="document-version-actions"><button class="button button-secondary" type="button" data-doc-select="${escapeHtml(version.id)}">编辑/查看</button><button class="button button-quiet" type="button" data-doc-compare="${escapeHtml(version.id)}">${version.id === workspace.compareVersionId ? "取消对比" : "设为对比"}</button></div>
    </article>`;
  }).join("") : `<div class="empty-state"><p>当前 ${escapeHtml(workspace.docType.toUpperCase())} 还没有正式版本。</p></div>`;

  qsa("[data-doc-select]", list).forEach((button) => button.addEventListener("click", () => selectDocumentVersion(button.dataset.docSelect)));
  qsa("[data-doc-compare]", list).forEach((button) => button.addEventListener("click", () => toggleDocumentCompare(button.dataset.docCompare)));
  renderDocumentDiff();
}

function renderDocumentDiff() {
  const node = qs("#document-diff-view");
  if (!node) return;
  const selected = selectedDocumentVersion();
  const compare = compareDocumentVersion();
  if (!selected || !compare || selected.id === compare.id) {
    node.textContent = "选择当前版本，并再选择一个不同版本作为对比，即可查看差异。";
    return;
  }
  if (!node.dataset.loadedPair) node.textContent = "点击版本后正在准备差异…";
}

async function loadDocumentWorkspace(docType = state.documentWorkspace.docType) {
  if (!state.currentProjectId) return;
  const workspace = state.documentWorkspace;
  workspace.docType = docType;
  qs("#document-editor-type").value = docType;
  try {
    workspace.versions = await api(`/api/projects/${state.currentProjectId}/documents/${docType}/versions`);
  } catch (_) { workspace.versions = []; }
  if (!workspace.versions.some((version) => version.id === workspace.selectedVersionId)) {
    workspace.selectedVersionId = workspace.versions[0]?.id || null;
    workspace.compareVersionId = workspace.versions[1]?.id || null;
  }
  try {
    const draftPath = DOCUMENT_DRAFT_PATHS[docType];
    workspace.draft = await api(`/api/projects/${state.currentProjectId}${draftPath}`);
  } catch (_) { workspace.draft = null; }
  workspace.dirty = false;
  const editor = qs("#document-editor");
  if (editor) editor.dataset.loadedVersionId = "";
  renderDocumentWorkspace();
  if (docType === "prd" && workspace.versions.length) {
    trackBetaEventOnce(`prd-editor:${state.currentProjectId}:${workspace.versions[0].id}`, "prd_editor_opened", {doc_type: "prd", version_no: workspace.versions[0].version || 1}, state.currentProjectId);
  }
  if (workspace.selectedVersionId && workspace.compareVersionId) await loadDocumentDiff();
}

async function selectDocumentVersion(versionId) {
  clearTimeout(state.documentWorkspace.autosaveTimer);
  state.documentWorkspace.selectedVersionId = versionId;
  state.documentWorkspace.dirty = false;
  const editor = qs("#document-editor");
  if (editor) editor.dataset.loadedVersionId = "";
  renderDocumentWorkspace();
  await loadDocumentDiff();
}

async function toggleDocumentCompare(versionId) {
  state.documentWorkspace.compareVersionId = state.documentWorkspace.compareVersionId === versionId ? null : versionId;
  renderDocumentWorkspace();
  await loadDocumentDiff();
}

async function loadDocumentDiff() {
  const selected = selectedDocumentVersion();
  const compare = compareDocumentVersion();
  const node = qs("#document-diff-view");
  if (!node || !selected || !compare || selected.id === compare.id) return;
  const pair = `${compare.id}:${selected.id}`;
  node.dataset.loadedPair = pair;
  node.textContent = "正在计算版本差异…";
  try {
    const result = await api(`/api/documents/diff?from_version_id=${encodeURIComponent(compare.id)}&to_version_id=${encodeURIComponent(selected.id)}`);
    if (node.dataset.loadedPair !== pair) return;
    node.textContent = result.changed ? (result.unified_diff || "版本内容不同，但没有可显示的行级差异。") : "两个版本内容一致。";
  } catch (error) {
    if (node.dataset.loadedPair === pair) node.textContent = `无法获取差异：${error.message}`;
  }
}

function scheduleDocumentAutosave() {
  const workspace = state.documentWorkspace;
  const selected = selectedDocumentVersion();
  if (!state.currentProjectId || !selected) return;
  workspace.dirty = true;
  qs("#document-autosave-status").textContent = "草稿有修改 · 正在等待自动保存…";
  clearTimeout(workspace.autosaveTimer);
  workspace.autosaveTimer = setTimeout(async () => {
    const content = qs("#document-editor").value;
    if (!content.trim()) {
      qs("#document-autosave-status").textContent = "草稿为空，不会覆盖已保存内容";
      return;
    }
    try {
      const draftPath = DOCUMENT_DRAFT_PATHS[workspace.docType];
      workspace.draft = await api(`/api/projects/${state.currentProjectId}${draftPath}`, {method: "PUT", body: JSON.stringify({base_version_id: selected.id, content})});
      workspace.dirty = false;
      qs("#document-autosave-status").textContent = `草稿已自动保存 · 基于 v${selected.version}`;
    } catch (error) {
      qs("#document-autosave-status").textContent = "自动保存失败，正式版本未被修改";
      reportError(error);
    }
  }, 700);
}

async function commitDocumentDraft() {
  const workspace = state.documentWorkspace;
  const selected = selectedDocumentVersion();
  if (!selected) return;
  clearTimeout(workspace.autosaveTimer);
  if (workspace.dirty) {
    scheduleDocumentAutosave();
    clearTimeout(workspace.autosaveTimer);
    try {
      const draftPath = DOCUMENT_DRAFT_PATHS[workspace.docType];
      workspace.draft = await api(`/api/projects/${state.currentProjectId}${draftPath}`, {method: "PUT", body: JSON.stringify({base_version_id: selected.id, content: qs("#document-editor").value})});
      workspace.dirty = false;
    } catch (error) { reportError(error); return; }
  }
  try {
    const created = await api(`/api/projects/${state.currentProjectId}/documents/${workspace.docType}/draft/commit`, {method: "POST", body: JSON.stringify({actor: "web_user", note: "在线编辑保存为新版本", expected_base_version_id: selected.id})});
    workspace.selectedVersionId = created.id;
    workspace.compareVersionId = selectedDocumentVersion()?.id || workspace.compareVersionId;
    await Promise.all([loadDocuments(), loadProjectNextAction()]);
    toast(`已保存为 ${workspace.docType.toUpperCase()} v${created.version}；旧版本保持不变。`);
  } catch (error) { reportError(error); }
}

async function restoreSelectedDocument() {
  const selected = selectedDocumentVersion();
  if (!selected) return;
  if (!window.confirm(`将 v${selected.version} 的内容恢复为一个新的正式历史版本？原版本不会被覆盖。`)) return;
  try {
    const restored = await api(`/api/documents/${selected.id}/restore-as-new`, {method: "POST", body: JSON.stringify({actor: "web_user", note: `恢复自 v${selected.version}`})});
    state.documentWorkspace.selectedVersionId = restored.id;
    state.documentWorkspace.compareVersionId = selected.id;
    await Promise.all([loadDocuments(), loadProjectNextAction()]);
    toast(`已从 v${selected.version} 创建新版本 v${restored.version}。`);
  } catch (error) { reportError(error); }
}

async function validateSelectedDocument() {
  const selected = selectedDocumentVersion();
  if (!selected) return;
  try {
    await api(`/api/documents/${selected.id}/validate`, {method: "POST"});
    await Promise.all([loadDocuments(), loadProjectNextAction()]);
    toast("文档检查完成。检查通过后仍需用户确认才能进入正式交接。");
  } catch (error) { reportError(error); }
}

function exportSelectedDocument() {
  const selected = selectedDocumentVersion();
  if (!selected) return;
  const format = qs("#document-export-format").value;
  const url = `/api/documents/${encodeURIComponent(selected.id)}/export?format=${encodeURIComponent(format)}`;
  const link = document.createElement("a");
  link.href = url;
  link.download = `${state.documentWorkspace.docType}_v${selected.version}.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
}


function renderHandoff() {
  const h = state.handoff;
  const snap = state.snapshot || {};
  const mvp = snap.mvp || {};
  const nonGoals = snap.solution?.explicit_non_goals || [];
  const implementationTasks = mvp.implementation_plan || [];
  const acceptanceCases = mvp.acceptance_criteria || [];
  const docSummary = h?.documents || {};
  const risks = snap.unknowns || [];
  const missing = h?.missing || [];
  qs("#handoff-content").innerHTML = `
    <div class="handoff-status ${h?.ready ? "handoff-ready" : "handoff-blocked"}"><strong>${escapeHtml(h?.ready ? "开发交接已具备正式上下文" : "当前还不能安全交接")}</strong><span>${escapeHtml(h?.ready ? "当前 Snapshot、PRD 和 TechDoc 均满足交接 Gate。" : (missing[0]?.message || "需要先完成当前 Snapshot 和正式文档。"))}</span></div>
    <section class="handoff-section"><h3>MVP 范围</h3>${detailList("In scope", mvp.features || [])}</section>
    <section class="handoff-section"><h3>明确不做</h3>${detailList("Explicit non-scope", nonGoals.length ? nonGoals : ["当前 Snapshot 暂未声明额外非目标；交接前不要擅自扩展范围。"])}</section>
    <section class="handoff-section"><h3>Implementation Tasks</h3>${detailList("实施顺序", implementationTasks)}</section>
    <section class="handoff-section"><h3>Acceptance Cases</h3>${detailList("验收案例", acceptanceCases)}</section>
    <section class="handoff-section"><h3>已确认文档</h3><div class="handoff-docs"><span>PRD：${escapeHtml(docSummary.prd?.id || "未确认")}</span><span>TechDoc：${escapeHtml(docSummary.techdoc?.id || "未确认")}</span></div></section>
    <section class="handoff-section"><h3>未解决风险</h3>${detailList("Unknowns / Risks", risks.length ? risks : ["当前 Snapshot 未记录关键未知项。"])}${missing.length ? detailList("阻塞项", missing.map((item) => item.message)) : ""}</section>
    <section class="handoff-section"><h3>复制/导出</h3><div class="handoff-actions"><button id="copy-handoff-button" class="button button-secondary" type="button">复制当前开发上下文</button><button id="export-handoff-button" class="button button-primary" type="button" ${h?.ready ? "" : "disabled"}>导出 Codex 交接包</button><button id="load-handoff-button" class="button button-quiet" type="button">重新检查准备度</button></div></section>
    <details class="handoff-section advanced-panel"><summary>高级：MCP</summary><p>MCP 只作为已有确认上下文的高级读取/交接接口；当前 P0 不把远程 MCP 或企业权限作为主卖点。</p></details>`;
  qs("#load-handoff-button")?.addEventListener("click", loadHandoff);
  qs("#copy-handoff-button")?.addEventListener("click", copyHandoffContext);
  qs("#export-handoff-button")?.addEventListener("click", exportHandoff);
}

async function quickStart(event) {
  event.preventDefault();
  const resources = qs("#quick-start-resources").value.split(/\n+/).map((x) => x.trim()).filter(Boolean);
  const payload = {
    idea: qs("#quick-start-idea").value.trim(),
    target_user: qs("#quick-start-target-user").value.trim() || null,
    resources,
    priority: qs("#quick-start-priority").value,
  };
  try {
    const result = await api("/api/projects/quick-start", {method: "POST", body: JSON.stringify(payload)});
    if (isRecoveryPayload(result)) {
      state.ideaBrief = null;
      state.solutions = null;
      closeStaleIdeaBriefDialog();
      showRecoveryPayload(result);
      try {
        await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
      } catch (refreshError) {
        console.error(refreshError);
        toast(`${result.message} 项目已保留，但历史列表刷新失败；请稍后重新打开首页。`);
      }
      return result;
    }
    state.currentProjectId = result.project_id;
    state.ideaBrief = result.idea_brief;
    state.runtimeMode = result.runtime_mode || result.ai_trace?.runtime_mode || state.runtimeMode;
    renderRuntimeDisclosure();
    await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
    openIdeaBriefReview();
  } catch (error) { reportError(error); }
}

async function confirmIdeaBrief(event) {
  event.preventDefault();
  if (!state.currentProjectId || !state.ideaBrief) {
    closeStaleIdeaBriefDialog();
    toast("当前没有可确认的 IdeaBrief；请先完成一次有效生成。");
    return;
  }
  try {
    const clarificationAnswer = qs("#idea-brief-clarification-answer")?.value.trim() || "";
    if (state.ideaBrief.clarification_required) {
      if (!clarificationAnswer) {
        toast("请先回答澄清问题。");
        return;
      }
      state.ideaBrief = await api(`/api/projects/${state.currentProjectId}/idea-brief/refine`, {method: "POST", body: JSON.stringify({clarification_answer: clarificationAnswer})});
      renderIdeaBrief(true);
      toast("澄清信息已保存，请检查并确认项目理解。" );
      return;
    }
    const values = {
      target_user: qs("#idea-brief-target-user")?.value.trim() || "",
      problem: qs("#idea-brief-problem")?.value.trim() || "",
      desired_outcome: qs("#idea-brief-desired-outcome")?.value.trim() || "",
      unknowns: (qs("#idea-brief-unknowns")?.value || "").split(/\n+/).map((item) => item.trim()).filter(Boolean),
    };
    const changed = ["target_user", "problem", "desired_outcome"].some((key) => values[key] !== String(state.ideaBrief[key] || ""))
      || JSON.stringify(values.unknowns) !== JSON.stringify(state.ideaBrief.unknowns || []);
    if (changed) {
      state.ideaBrief = await api(`/api/projects/${state.currentProjectId}/idea-brief/refine`, {method: "POST", body: JSON.stringify(values)});
    }
    state.ideaBrief = await api(`/api/projects/${state.currentProjectId}/idea-brief/confirm`, {method: "POST", body: JSON.stringify({human_confirmed: true, note: "UI confirmation"})});
    qs("#idea-brief-dialog").close();
    showProjectShell();
    renderIdeaBrief();
    activateView("solutions");
    renderSolutions();
    await loadProjectNextAction();
    toast("项目理解已确认，现在可以生成项目方案。");
  } catch (error) {
    console.error(error);
    toast("项目理解暂时无法保存，请重试。");
  }
}

async function generateSolutions({newIntent = false} = {}) {
  if (state.generationInFlight) return state.generationInFlight;
  if (newIntent || !state.generationIntentId) {
    state.generationIntentId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
  state.generationTerminalFailure = false;
  const button = qs("#generate-solutions-button");
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
    button.textContent = "正在生成方案…";
  }
  const attemptId = state.generationIntentId;
  let request;
  request = (async () => {
    try {
      const result = await api(`/api/projects/${state.currentProjectId}/solutions/generate`, {
        method: "POST",
        headers: {"X-Idempotency-Key": attemptId, "X-Generation-Mode": "async", "X-Managed-Model-Preference": state.managedModelPreference || "AUTO"},
      });
      if (["PENDING", "RUNNING"].includes(result.status) && result.generation_run_id) {
        return await pollSolutionGeneration(result.generation_run_id);
      }
      if (isRecoveryPayload(result)) {
        state.solutions = null;
        state.generationTerminalFailure = true;
        renderSolutions();
        showRecoveryPayload(result);
        return result;
      }
      state.solutions = result;
      state.generationIntentId = null;
      state.generationTerminalFailure = false;
      renderSolutions();
      await loadProjectNextAction();
      return result;
    } catch (error) {
      state.generationTerminalFailure = true;
      reportError(error);
      return null;
    } finally {
      if (state.generationInFlight === request) state.generationInFlight = null;
      if (button?.isConnected && !state.solutions?.candidates?.length) {
        button.disabled = false;
        button.setAttribute("aria-disabled", "false");
        button.textContent = state.generationTerminalFailure ? "重新生成" : "生成方案";
      }
    }
  })();
  state.generationInFlight = request;
  return request;
}

async function pollSolutionGeneration(runId) {
  while (true) {
    const result = await api(`/api/projects/${state.currentProjectId}/solutions/generate/${encodeURIComponent(runId)}`);
    if (["PENDING", "RUNNING"].includes(result.status)) {
      await new Promise((resolve) => setTimeout(resolve, Number(result.poll_after_ms || 2000)));
      continue;
    }
    if (isRecoveryPayload(result) || result.status === "FAILED") {
      state.solutions = null;
      state.generationTerminalFailure = true;
      renderSolutions();
      showRecoveryPayload(result);
      return result;
    }
    state.solutions = result;
    state.generationIntentId = null;
    state.generationTerminalFailure = false;
    renderSolutions();
    await loadProjectNextAction();
    return result;
  }
}

async function selectSolution(candidateId) {
  try {
    state.snapshot = await api(`/api/projects/${state.currentProjectId}/solutions/select`, {method: "POST", body: JSON.stringify({strategy: "single", candidate_ids: [candidateId], rationale: "选择当前最值得先验证的 MVP 路径。", human_confirmed: true})});
    renderSnapshot();
    await Promise.all([loadEvidenceData(), loadDocuments(), loadHandoff(), loadProjectNextAction(), loadHomeNextAction(), loadHistory()]);
    activateView("snapshot");
  } catch (error) { reportError(error); }
}

async function loadProjects() {
  state.projects = await api("/api/projects");
  renderProjectPicker();
  renderRecentProjects();
}

async function loadProject(projectId) {
  if (state.currentProjectId !== projectId) {
    state.generationIntentId = null;
    state.generationTerminalFailure = false;
  }
  state.currentProjectId = projectId;
  state.documentWorkspace = {...state.documentWorkspace, versions: [], selectedVersionId: null, compareVersionId: null, draft: null, dirty: false};
  renderProjectPicker();
  showProjectShell();
  try { state.ideaBrief = await api(`/api/projects/${projectId}/idea-brief`); } catch (_) { state.ideaBrief = null; }
  try { state.solutions = await api(`/api/projects/${projectId}/solutions`); } catch (_) { state.solutions = null; }
  try { state.snapshot = await api(`/api/projects/${projectId}/snapshot`); } catch (_) { state.snapshot = null; }
  renderIdeaBrief();
  renderSolutions();
  renderSnapshot();
  await Promise.all([loadEvidenceData(), loadDocuments(), loadHandoff(), loadProjectNextAction(), loadProjectModelProfile(), loadWalkthrough()]);
}

async function loadEvidenceData() {
  if (!state.currentProjectId) return;
  try { state.claims = await api(`/api/projects/${state.currentProjectId}/claims`); } catch (_) { state.claims = []; }
  try { state.sources = await api(`/api/projects/${state.currentProjectId}/sources`); } catch (_) { state.sources = []; }
  try { state.impacts = await api(`/api/projects/${state.currentProjectId}/evidence/impact`); } catch (_) { state.impacts = {claims: [], change_proposals: []}; }
  renderEvidence();
}

async function loadClaimsAndSources() {
  return loadEvidenceData();
}

async function addEvidence(event) {
  event.preventDefault();
  if (!state.currentProjectId) return;
  const payload = {
    title: qs("#evidence-title").value.trim(),
    source_type: qs("#evidence-source-type").value,
    authority: 0.5,
    content: qs("#evidence-text").value.trim(),
    filename: "manual_evidence.txt",
  };
  try {
    await api(`/api/projects/${state.currentProjectId}/sources`, {method: "POST", body: JSON.stringify(payload)});
    qs("#add-evidence-form").reset();
    await Promise.all([loadEvidenceData(), loadProjectNextAction()]);
    toast("资料已加入。上传本身不等于支持判断；请运行影响分析。");
  } catch (error) { reportError(error); }
}

async function analyzeEvidence() {
  if (!state.currentProjectId || !(state.claims || []).length) return;
  try {
    await api(`/api/projects/${state.currentProjectId}/evidence/analyze`, {method: "POST", body: JSON.stringify({claim_ids: state.claims.map((claim) => claim.id)})});
    await Promise.all([loadEvidenceData(), loadDocuments(), loadHandoff(), loadProjectNextAction(), loadHomeNextAction()]);
    setEvidenceTab("impact");
    toast("资料影响分析完成；正式项目判断不会自动修改。");
  } catch (error) { reportError(error); }
}

async function decideChangeProposal(proposalId, action) {
  const note = action === "accept" ? "用户在 Evidence Impact 中接受修改" : action === "defer" ? "用户暂不修改，继续保留当前正式版本" : "用户不接受该调整，继续验证冲突";
  try {
    const result = await api(`/api/change-proposals/${proposalId}/${action}`, {method: "POST", body: JSON.stringify({human_confirmed: true, note})});
    if (action === "accept" && result.snapshot) state.snapshot = result.snapshot;
    try { state.snapshot = await api(`/api/projects/${state.currentProjectId}/snapshot`); } catch (_) {}
    renderSnapshot();
    await Promise.all([loadEvidenceData(), loadDocuments(), loadHandoff(), loadProjectNextAction(), loadHomeNextAction()]);
    toast(action === "accept" ? "已创建新的 Project Snapshot；历史版本保持不变。" : "已记录你的决定；系统没有自动改写正式版本。");
  } catch (error) { reportError(error); }
}

async function reconfirmSnapshotHealth() {
  if (!state.currentProjectId) return;
  try {
    state.snapshot = await api(
      `/api/projects/${state.currentProjectId}/snapshot/reconfirm`,
      {method: "POST", body: JSON.stringify({human_confirmed: true, note: "UI reconfirmed current Snapshot health"})},
    );
    renderSnapshot();
    await Promise.all([loadEvidenceData(), loadDocuments(), loadHandoff(), loadProjectNextAction(), loadHomeNextAction()]);
    toast("已重新确认当前 Snapshot；正式内容未被自动改写。");
  } catch (error) { reportError(error); }
}

async function loadDocuments() {
  if (!state.currentProjectId) { state.documents = []; renderDocuments(); return; }
  try {
    const detail = await api(`/api/projects/${state.currentProjectId}`);
    const latest = new Map();
    for (const row of detail.document_versions || []) {
      if (!latest.has(row.doc_type)) latest.set(row.doc_type, row);
    }
    state.documents = await Promise.all([...latest.values()].map(async (row) => {
      try { return await api(`/api/documents/${row.id}`); } catch (_) { return row; }
    }));
  } catch (_) { state.documents = []; }
  renderDocuments();
  await loadDocumentWorkspace(state.documentWorkspace.docType);
}

async function generateDocument(docType) {
  try {
    const result = await api(`/api/projects/${state.currentProjectId}/documents/generate`, {method: "POST", body: JSON.stringify({doc_type: docType})});
    toast(`${docType.toUpperCase()} 已生成：${result.version_id || result.id || "新版本"}`);
    state.documentWorkspace.docType = docType;
    await Promise.all([loadDocuments(), loadHandoff(), loadProjectNextAction()]);
  } catch (error) { reportError(error); }
}

async function confirmDocument(versionId) {
  try {
    await api(`/api/document-versions/${versionId}/confirm`, {method: "POST", body: JSON.stringify({actor: "web_user", note: "用户确认当前文档版本", human_confirmed: true})});
    await Promise.all([loadDocuments(), loadHandoff(), loadProjectNextAction()]);
    toast("已确认此版本。后续证据发生变化时，历史确认内容不会被覆盖。");
  } catch (error) { reportError(error); }
}

async function loadHandoff() {
  if (!state.currentProjectId) { state.handoff = null; renderHandoff(); return; }
  try { state.handoff = await api(`/api/projects/${state.currentProjectId}/handoff/readiness`); } catch (_) { state.handoff = null; }
  renderHandoff();
}

function handoffContextText() {
  const snap = state.snapshot || {};
  return [
    `Project Snapshot v${snap.version || "-"}: ${snap.title || ""}`,
    `方案：${snap.solution?.title || ""}`,
    `MVP：${(snap.mvp?.features || []).join("；")}`,
    `明确不做：${(snap.solution?.explicit_non_goals || []).join("；") || "当前未声明额外非目标"}`,
    `实施：${(snap.mvp?.implementation_plan || []).join("；")}`,
    `验收：${(snap.mvp?.acceptance_criteria || []).join("；")}`,
    `未解决：${(snap.unknowns || []).join("；")}`,
  ].join("\n");
}

async function copyHandoffContext() {
  try {
    await navigator.clipboard.writeText(handoffContextText());
    toast("已复制当前开发上下文。");
  } catch (error) { reportError(error); }
}

async function exportHandoff() {
  try {
    const response = await api(`/api/projects/${state.currentProjectId}/handoff/export`, {method: "POST", body: JSON.stringify({target_client: "codex"})});
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `InsightForge_Handoff_${state.currentProjectId}_codex.zip`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) { reportError(error); }
}

function wireEvents() {
  qs("#beta-feedback-button")?.addEventListener("click", () => qs("#beta-feedback-dialog")?.showModal());
  qs("#beta-feedback-cancel")?.addEventListener("click", () => qs("#beta-feedback-dialog")?.close());
  qs("#beta-feedback-form")?.addEventListener("submit", submitBetaFeedback);
  qs("#home-button").addEventListener("click", (event) => { event.preventDefault(); showQuickStart(); });
  qs("#quick-start-form").addEventListener("submit", quickStart);
  qs("#idea-brief-form").addEventListener("submit", confirmIdeaBrief);
  qs("#idea-brief-edit").addEventListener("click", (event) => { event.preventDefault(); qs("#idea-brief-target-user")?.focus(); toast("可以直接修改以上项目理解，确认后才会保存。"); });
  qs("#new-idea-button").addEventListener("click", showQuickStart);
  qs("#settings-button").addEventListener("click", showModelSettings);
  qs("#settings-back").addEventListener("click", showQuickStart);
  qs("#show-all-projects").addEventListener("click", () => {
    state.showAllProjects = !state.showAllProjects;
    renderRecentProjects();
  });
  qs("#project-select").addEventListener("change", (event) => loadProject(event.target.value));
  qs("#project-model-profile")?.addEventListener("change", saveProjectModelProfile);
  qs("#history-search")?.addEventListener("input", scheduleHistorySearch);
  qs("#history-status-filter")?.addEventListener("change", async (event) => { state.history.status = event.target.value; state.history.page = 1; await loadHistory(); });
  qs("#history-sort")?.addEventListener("change", async (event) => { const [sort, order] = event.target.value.split(":"); state.history.sort = sort; state.history.order = order; state.history.page = 1; await loadHistory(); });
  qs("#history-prev")?.addEventListener("click", async () => { if (state.history.page > 1) { state.history.page -= 1; await loadHistory(); } });
  qs("#history-next")?.addEventListener("click", async () => { if (state.history.page < state.history.pages) { state.history.page += 1; await loadHistory(); } });
  qs("#walkthrough-next")?.addEventListener("click", advanceWalkthrough);
  qs("#walkthrough-skip")?.addEventListener("click", skipWalkthrough);
  qs("#walkthrough-restart")?.addEventListener("click", restartWalkthrough);
  qs("#walkthrough-close")?.addEventListener("click", () => qs("#walkthrough-panel")?.classList.add("hidden"));
  qs("#document-editor")?.addEventListener("input", scheduleDocumentAutosave);
  qs("#document-editor-type")?.addEventListener("change", async (event) => { clearTimeout(state.documentWorkspace.autosaveTimer); state.documentWorkspace.selectedVersionId = null; state.documentWorkspace.compareVersionId = null; await loadDocumentWorkspace(event.target.value); });
  qs("#document-save-version")?.addEventListener("click", commitDocumentDraft);
  qs("#document-validate-selected")?.addEventListener("click", validateSelectedDocument);
  qs("#document-restore-selected")?.addEventListener("click", restoreSelectedDocument);
  qs("#document-export-selected")?.addEventListener("click", exportSelectedDocument);
  qsa(".nav-item").forEach((button) => button.addEventListener("click", () => activateView(button.dataset.view)));
  qsa("[data-evidence-tab]").forEach((button) => button.addEventListener("click", () => setEvidenceTab(button.dataset.evidenceTab)));
  qs("#add-evidence-form")?.addEventListener("submit", addEvidence);
  qs("#analyze-evidence-button")?.addEventListener("click", analyzeEvidence);
  qs("#mobile-nav-button").addEventListener("click", () => {
    secureSettingsExit();
    const nav = qs("#primary-nav");
    nav.classList.toggle("open");
    qs("#mobile-nav-button").setAttribute("aria-expanded", nav.classList.contains("open") ? "true" : "false");
  });
  qs("#snapshot-primary-action").addEventListener("click", () => {
    activateView("evidence");
    setEvidenceTab("claims");
  });
  qs("#snapshot-health-reconfirm").addEventListener("click", reconfirmSnapshotHealth);
}

const recoveryTestHooks = window.__INSIGHTFORGE_TEST__ ? {
  __test: {
    state,
    quickStart,
    confirmIdeaBrief,
    openIdeaBriefReview,
    renderIdeaBrief,
    renderSolutions,
    generateSolutions,
    isRecoveryPayload,
    renderRuntimeDisclosure,
    createGuidanceNavigator,
    parseGuidanceAction,
    renderImpactHistory,
    reconfirmSnapshotHealth,
  },
} : {};
window.InsightForgeUi = {api, escapeHtml, reportError, toast, secureSettingsExit, applyGuidanceAction, ...recoveryTestHooks};

async function bootstrap() {
  wireEvents();
  try {
    await ensureBetaConsent();
    const health = await api("/api/health");
    state.runtimeMode = health.structured_runtime_mode || health.runtime_mode || health.llm_mode || null;
    const mode = await api("/api/settings/mode");
    state.managedModelMode = Boolean(mode.managed_beta_mode);
    renderRuntimeDisclosure();
    await Promise.all([loadProjects(), loadExamples(), loadHistory(), loadHomeNextAction()]);
    showQuickStart();
    renderEvidence();
    renderDocuments();
    renderHandoff();
  } catch (error) { reportError(error); }
}

document.addEventListener("DOMContentLoaded", bootstrap);
