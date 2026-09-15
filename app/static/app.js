"use strict";

const DEMO_DISCLOSURE = "本地演示模式：当前结构化结果用于验证工作流，不代表真实模型已理解任意 Idea。";

const state = {
  accountId: null,
  projects: [],
  currentProjectId: null,
  activeView: "snapshot",
  evidenceTab: "claims",
  ideaBrief: null,
  solutions: null,
  snapshot: null,
  competitorSnapshotId: null,
  useCompetitorSnapshot: true,
  sources: [],
  claims: [],
  impacts: {claims: [], change_proposals: []},
  documents: [],
  handoff: null,
  runtimeMode: null,
  managedModelMode: false,
  usagePolicy: null,
  managedModelPreference: "AUTO",
  showAllProjects: false,
  examples: [],
  homeNextAction: null,
  projectNextAction: null,
  projectIntent: null,
  buildSlice: null,
  buildSliceQuality: null,
  prototypeTask: null,
  prototypeTaskQuality: null,
  walkthrough: null,
  modelProfiles: [],
  projectModelProfileId: null,
  generationInFlight: null,
  activeGeneration: null,
  generationReferenceKey: null,
  generationIntentId: null,
  generationTerminalFailure: false,
  generationFailureCode: null,
  runtimeDisclosureContext: null,
  betaMode: false,
  betaConsented: false,
  betaConsentVersion: 1,
  history: {q: "", status: "all", sort: "updated_at", order: "desc", page: 1, pageSize: 10, pages: 1, total: 0, items: []},
  documentWorkspace: {docType: "prd", versions: [], selectedVersionId: null, compareVersionId: null, draft: null, autosaveTimer: null, dirty: false, error: null},
  evidenceEntry: {mode: null, submitting: false, pending: false},
};

const qs = (selector, root = document) => root.querySelector(selector);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch]));

// Tokens represent actual pending work, not elapsed-time estimates.
const pendingLoading = new Map();
function renderLoading() {
  const shell = qs("#loading-status");
  if (!shell) return;
  shell.hidden = pendingLoading.size === 0;
  const message = qs("#loading-message");
  if (message) message.textContent = pendingLoading.values().next().value || "";
}
function beginLoading(message = "正在加载，请稍候…") {
  const token = Symbol("pending-work");
  pendingLoading.set(token, message);
  renderLoading();
  return {
    update(nextMessage) {
      if (pendingLoading.has(token)) pendingLoading.set(token, nextMessage);
      renderLoading();
    },
    finish() { pendingLoading.delete(token); renderLoading(); },
  };
}

async function api(path, options = {}) {
  const loading = beginLoading(options.method && options.method !== "GET"
    ? "正在处理请求，请勿重复提交…" : "正在加载，请稍候…");
  try {
    return await requestApi(path, options);
  } finally {
    loading.finish();
  }
}

async function requestApi(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {"Content-Type": "application/json", "X-InsightForge-Request": "1", ...(options.headers || {})},
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    let body = null;
    try { body = await response.json(); detail = body.detail || body.message || detail; } catch (_) {}
    const error = new Error(detail);
    error.status = response.status;
    error.code = body?.error_code || null;
    error.code = body?.code || error.code;
    error.payload = body;
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
  return error?.code === "STRUCTURED_RUNTIME_UNAVAILABLE" || /STRUCTURED_|OPENAI_API_KEY|DETERMINISTIC_DEMO_UNSUPPORTED|CLARIFICATION_REQUIRED/.test(message);
}

function technicalErrorMessage(error) {
  return String(error?.payload?.detail || error?.payload?.message || error?.message || error?.detail || error?.error_code || "").trim();
}

function stableErrorCode(error) {
  const code = String(error?.code || error?.payload?.error_code || error?.error_code || "").trim();
  const raw = technicalErrorMessage(error).toLowerCase();
  if (code) {
    return /^[A-Z][A-Z0-9_]{2,}$/.test(code) ? code : "RUNTIME_OPERATION_FAILED";
  }
  if (/structured_|openai_api_key|deterministic_demo_unsupported|managed_qwen/.test(raw)) return "STRUCTURED_RUNTIME_UNAVAILABLE";
  if (/competitor snapshot is required|confirmed competitor snapshot/.test(raw)) return "COMPETITOR_SNAPSHOT_REQUIRED";
  if (/snapshot is not part of this project|competitor snapshot is not part/.test(raw)) return "COMPETITOR_SNAPSHOT_NOT_FOUND";
  if (/timeout|timed out|超时/.test(raw)) return "MODEL_TIMEOUT";
  if (/traceback|exception|keyerror|valueerror|sql|\\app\\|\/app\//.test(raw)) return "RUNTIME_OPERATION_FAILED";
  return "RUNTIME_OPERATION_FAILED";
}

function humanizeErrorMessage(error, fallback = "这次操作没有完成，请稍后重试。") {
  const code = String(error?.code || error?.payload?.error_code || error?.error_code || "");
  const raw = technicalErrorMessage(error);
  if (code === "STRUCTURED_RUNTIME_UNAVAILABLE" || /STRUCTURED_|OPENAI_API_KEY|DETERMINISTIC_DEMO_UNSUPPORTED|MANAGED_QWEN/.test(raw)) {
    return "AI参考这次没有生成可用内容，请稍后重试。你的项目内容未被改成资料。";
  }
  if (code === "COMPETITOR_SNAPSHOT_REQUIRED" || /confirmed competitor snapshot|competitor snapshot is required|competitor snapshot is not part of this project|snapshot is not part of this project|竞品决策信息/.test(raw)) {
    return "当前方案缺少竞品决策信息。请返回方案页重新确认；如果本次不需要竞品比较，可以选择暂时跳过。";
  }
  if (/current confirmed snapshot|current confirmed Snapshot|confirmed Snapshot is required/i.test(raw)) {
    return "当前项目还没有可用的方案快照，请先完成方案选择后再生成文档。";
  }
  if (code === "MODEL_TIMEOUT" || /timeout|timed out|超时/i.test(raw)) return "AI服务本次响应超时，你的输入已保留，请稍后重试。";
  if (code === "PROVIDER_FAILURE") return "AI服务暂时无法完成请求，你的输入已保留，请稍后重试。";
  if (code === "APPLICATION_POSTPROCESS_FAILURE") return "AI返回的方案未通过应用校验，你的项目内容已保留，请重新生成。";
  if (code === "MODEL_OUTPUT_SCHEMA_INVALID") return "AI返回的方案结构不完整，你的项目内容已保留，请重新生成。";
  if (code === "DOCUMENT_CONTENT_INVALID") return "当前文档内容与已选项目成果不一致，未展示该版本，请重新生成。";
  if (code === "DOCUMENT_VERSION_SCHEMA_INVALID") return "当前文档版本信息不完整，未展示该版本，请稍后重试。";
  if (code === "GENERATION_PENDING") return "本次生成仍在处理中，请稍候查看结果。";
  if (code === "SOLUTION_GENERATION_IN_PROGRESS") return "正在生成方案，请稍候。";
  if (code === "IDEA_BRIEF_REQUIRED" || code === "IDEA_BRIEF_NOT_CONFIRMED") return "请先完善并确认项目定义，再生成方案。";
  if (code === "BETA_DAILY_LIMIT_REACHED") return "今日可用次数已用尽，其他项目资料不会受到影响。";
  return fallback;
}

function humanizeRecoveryAction(action) {
  const value = String(action || "").trim();
  if (!value) return "";
  const known = {
    retry: "稍后重试",
    retry_generation: "稍后重新生成",
    review_project: "返回项目页检查当前输入",
    check_model: "检查模型配置后重试",
    add_evidence: "补充相关资料后再试",
  };
  if (known[value]) return known[value];
  if (/^[A-Z][A-Z0-9_]{2,}$/.test(value) || /[a-z]+_[a-z_]+/.test(value)) return "按页面提示检查后重试";
  return /[\u3400-\u9fff]/.test(value) ? value : "按页面提示检查后重试";
}

function humanizeSnapshotAction(action) {
  const value = String(action || "").trim();
  if (!value) return "继续验证关键判断";
  const known = {
    add_evidence: "补充一条能改变当前判断的资料",
    review_evidence: "查看仍需确认的关键判断",
    generate_documents: "继续整理正式文档",
    confirm_snapshot: "确认当前项目成果",
  };
  if (known[value]) return known[value];
  if (/^[A-Z][A-Z0-9_]{2,}$/.test(value) || /[a-z]+_[a-z_]+/.test(value)) return "继续验证关键判断";
  return /[\u3400-\u9fff]/.test(value) ? value : "继续验证关键判断";
}

function renderRuntimeDisclosure({failure = null} = {}) {
  const node = qs("#runtime-disclosure");
  if (!node) return;
  if (failure && state.runtimeMode === "llm_structured") {
    const error = {message: String(failure || "")};
    const humanMessage = humanizeErrorMessage(error, "AI参考这次没有生成可用内容，请稍后重试。你的项目内容未被改成资料。");
    const code = stableErrorCode(error);
    node.classList.remove("hidden");
    node.classList.add("runtime-failure");
    node.innerHTML = `<div><strong>${escapeHtml(humanMessage)}</strong><details class="technical-details"><summary>技术详情</summary><code>错误代码：${escapeHtml(code)}</code><span>建议稍后重试；原始错误仅保留在服务端日志中。</span></details></div><button id="show-demo-switch-help" class="button button-secondary" type="button">切换到本地演示模式</button>`;
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
  const humanMessage = humanizeErrorMessage(error);
  if (error?.code === "IDEA_BRIEF_REQUIRED" || error?.code === "IDEA_BRIEF_NOT_CONFIRMED") {
    toast(humanMessage);
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
  if (error?.code === "APPLICATION_POSTPROCESS_FAILURE") {
    const settlement = error?.payload?.quota_status === "RELEASED" ? "本次操作额度已释放。" : "";
    toast(`AI 返回的内容未通过应用校验。${settlement}未自动重试；再次生成将发起新的模型请求。`);
    return;
  }
  if (error?.code === "PROVIDER_FAILURE") { toast(humanMessage, 4500); return; }
  if (error?.code === "GENERATION_PENDING") { toast(humanMessage, 4000); return; }
  if (error?.code === "IDEMPOTENT_REPLAY") { toast("已找到这次操作的已有结果，不会重复发起生成。", 4000); return; }
  if (error?.code === "BETA_DAILY_LIMIT_REACHED" || error?.payload?.blocked_operation) {
    const operation = error?.payload?.operation_type || error?.payload?.blocked_operation;
    toast(humanMessage || `${operation} 今日额度已用尽；其他操作额度不受影响。`);
    return;
  }
  if (error?.status === 503 && error?.code === "MODEL_TIMEOUT") {
    toast("AI 服务本次响应超时，你的输入已保留，请稍后重试。");
    return;
  }
  toast(humanMessage);
}

function isRecoveryPayload(value) {
  return Boolean(value && typeof value.error_code === "string");
}

function showRecoveryPayload(payload, context = "general") {
  state.runtimeDisclosureContext = context;
  const message = String(payload?.message || "生成未完成；你的输入已保留。");
  const code = String(payload?.error_code || "");
  const humanMessage = humanizeErrorMessage({message, code, payload}, ({
    APPLICATION_POSTPROCESS_FAILURE: "生成结果需要重新整理",
    PROVIDER_FAILURE: "AI 服务暂时无法完成请求",
    MODEL_TIMEOUT: "AI 服务响应超时",
    OVERENGINEERED_SOLUTION_SET: "方案范围需要进一步收敛",
  })[code] || "这次操作没有完成");
  const safeCode = stableErrorCode({message, code, payload});
  const actions = Array.isArray(payload?.recovery_actions)
    ? payload.recovery_actions.map((action) => humanizeRecoveryAction(action)).filter(Boolean)
    : [];
  const node = qs("#runtime-disclosure");
  if (node) {
    node.classList.remove("hidden");
    node.classList.add("runtime-failure");
    node.innerHTML = `<div><strong>${escapeHtml(humanMessage)}</strong>${actions.length ? `<ul>${actions.map((action) => `<li>${escapeHtml(action)}</li>`).join("")}</ul>` : ""}<details class="technical-details"><summary>技术详情</summary><code>错误代码：${escapeHtml(safeCode)}</code><span>原始错误仅保留在服务端日志中。</span></details></div>`;
  }
  toast(actions.length ? `${humanMessage} 可执行：${actions.join("；")}` : humanMessage);
}

function clearSolutionGenerationFailureNotice() {
  if (state.runtimeDisclosureContext !== "solution_generation") return;
  state.runtimeDisclosureContext = null;
  renderRuntimeDisclosure();
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

const AI_REFERENCE_FIELDS = [
  "possible_target_users", "possible_scenarios", "possible_user_problems",
  "missing_information", "mvp_thoughts", "questions_to_validate", "research_directions",
];
const AI_REFERENCE_PROVENANCE_NOTICE = "AI生成参考，尚未经外部资料核实。AI参考/待验证：以下内容只是模型建议，不是研究、市场或用户事实。";
const EVIDENCE_CARD_TEXT_FIELDS = [
  "title", "question_to_validate", "why_it_matters", "decision_impact",
  "fallback_if_unavailable", "limitations",
];
const EVIDENCE_CARD_LIST_FIELDS = [
  "who_or_where", "action_steps", "suggested_questions", "acceptable_artifacts", "fill_template",
];
const SOLUTION_LIST_FIELDS = [
  "user_flow", "mvp_pages", "features", "inputs", "outputs", "decision_logic",
  "data_requirements", "technical_components", "implementation_plan", "acceptance_cases",
  "risks", "unknowns",
];
const SOLUTION_OBJECT_LIST_FIELDS = {
  user_flow: ["step", "action", "ui_hint"],
  inputs: ["input_type", "field", "required", "description"],
  outputs: ["input_type", "field", "required", "description"],
  data_requirements: ["data_field", "purpose", "source"],
  risks: ["risk", "mitigation"],
};
const SOLUTION_TEXT_FIELDS = ["id", "title", "summary", "why_fit", "mechanism", "complexity"];
const SOLUTION_DETAIL_TEXT_FIELDS = ["title", "target_user", "problem", "why_fit", "mechanism", "complexity"];
const SOLUTION_DETAIL_LIST_FIELDS = ["scenarios", ...SOLUTION_LIST_FIELDS, "tradeoffs"];
const SOLUTION_DIVERSITY_FIELDS = [
  "mechanism", "required_data_class", "automation_level", "human_role", "core_decision_logic", "major_dependency",
];

function isPlainRecord(value) {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

// Keep marker semantics aligned with generation_contracts; ordinary JSON/prose
// remains valid. Projection alone cannot stop a dump inside an allowed string.
const RAW_GENERATION_MARKERS = /\b(?:choices|messages)\b["']?\s*:\s*[\[{]|\b(?:provider[_ -]?(?:payload|response|raw)|raw[_ -]?(?:response|output|payload)|debug[_ -]?(?:prompt|payload|trace)|system[_ -]?prompt|api[_ -]?key)\b["']?\s*[:=]|\bAuthorization["']?\s*:\s*["']?Bearer\s+\S+|\{(?=[^{}]*["']type["']\s*:\s*["']message["'])(?=[^{}]*["']role["']\s*:\s*["']assistant["'])|Traceback\s*\(most recent call last\)|\bValidationError\s*:/i;

function hasRawGenerationValue(value) {
  if (typeof value === "string") return RAW_GENERATION_MARKERS.test(value);
  if (Array.isArray(value)) return value.some(hasRawGenerationValue);
  if (isPlainRecord(value)) return Object.values(value).some(hasRawGenerationValue);
  return false;
}

function hasRawViewFields(value, fields) {
  return fields.some((key) => hasRawGenerationValue(value[key]));
}

function viewString(value, {required = true, maxLength = 4000} = {}) {
  if (typeof value !== "string") return required ? null : "";
  if (hasRawGenerationValue(value)) return null;
  const normalized = value.trim();
  if (required && !normalized) return null;
  return normalized.slice(0, maxLength);
}

function viewStringList(value, {required = true, maxItems = 20, maxLength = 4000} = {}) {
  if (value === undefined && !required) return [];
  if (!Array.isArray(value)) return null;
  if (required && value.length === 0) return null;
  if (value.length > maxItems) return null;
  const result = value.map((item) => viewString(item, {maxLength}));
  return result.some((item) => item === null) ? null : result;
}

function viewDisclosure(value) {
  const explicit = viewString(value, {required: false, maxLength: 500});
  return explicit || "";
}

function viewSolutionList(value, field) {
  if (!Array.isArray(value) || value.length > 20) return null;
  const keys = SOLUTION_OBJECT_LIST_FIELDS[field] || [];
  const result = value.map((item) => {
    if (typeof item === "string") return viewString(item);
    if (!isPlainRecord(item) || !keys.length) return null;
    if (hasRawViewFields(item, keys)) return null;
    const parts = keys.map((key) => {
      const raw = item[key];
      if (typeof raw === "string") return viewString(raw, {required: false, maxLength: 1000});
      if (typeof raw === "number" || typeof raw === "boolean") return String(raw);
      return "";
    }).filter(Boolean);
    return parts.length ? parts.join("；") : null;
  });
  return result.some((item) => !item) ? null : result;
}

function toAIReferenceViewModel(value) {
  if (!isPlainRecord(value)) return null;
  if (hasRawViewFields(value, ["uncertainty_notice", "fixture_origin", "fixture_disclosure"])) return null;
  const model = {};
  for (const key of AI_REFERENCE_FIELDS) {
    const items = viewStringList(value[key], {required: false, maxItems: 20});
    if (!items) return null;
    model[key] = items;
  }
  if (!AI_REFERENCE_FIELDS.some((key) => model[key].length)) return null;
  model.uncertainty_notice = AI_REFERENCE_PROVENANCE_NOTICE;
  model.fixture_disclosure = viewDisclosure(value.fixture_disclosure)
    || (value.fixture_origin === "STAGE_A_SYNTHETIC" ? "Stage A 演示结果 · 非真实 AI 生成" : "");
  return model;
}

function toEvidenceGuidanceViewModel(value) {
  if (!isPlainRecord(value) || !Array.isArray(value.cards) || !value.cards.length || value.cards.length > 5) return null;
  if (hasRawViewFields(value, ["disclosure", "fixture_origin", "fixture_disclosure"])) return null;
  const cards = value.cards.map((card) => {
    if (!isPlainRecord(card)) return null;
    const model = {};
    for (const key of EVIDENCE_CARD_TEXT_FIELDS) {
      model[key] = viewString(card[key]);
      if (!model[key]) return null;
    }
    for (const key of EVIDENCE_CARD_LIST_FIELDS) {
      model[key] = viewStringList(card[key], {required: key !== "suggested_questions", maxItems: 20});
      if (!model[key]) return null;
    }
    return model;
  });
  if (cards.some((card) => !card)) return null;
  return {
    cards,
    fixture_disclosure: viewDisclosure(value.fixture_disclosure)
      || (value.fixture_origin === "STAGE_A_SYNTHETIC" ? "Stage A 演示结果 · 非真实 AI 生成" : ""),
  };
}

function normalizeDiversityValue(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).replace(/\s+/g, " ").trim().toLocaleLowerCase()).join("|");
  return String(value || "").replace(/\s+/g, " ").trim().toLocaleLowerCase();
}

function toSolutionCandidateViewModel(value) {
  if (!isPlainRecord(value)) return null;
  const model = {};
  for (const key of SOLUTION_TEXT_FIELDS) {
    model[key] = viewString(value[key]);
    if (!model[key]) return null;
  }
  if (! ["low", "medium", "high"].includes(model.complexity)) return null;
  for (const key of SOLUTION_LIST_FIELDS) {
    model[key] = viewSolutionList(value[key], key);
    if (!model[key] || !model[key].length) return null;
  }
  model.tradeoffs = model.risks.slice();
  return model;
}

function toSolutionDetailViewModel(value) {
  if (!isPlainRecord(value)) return null;
  if (hasRawViewFields(value, SOLUTION_DETAIL_TEXT_FIELDS)) return null;
  const id = viewString(value.id, {maxLength: 200});
  if (!id) return null;
  const model = {id};
  for (const key of SOLUTION_DETAIL_TEXT_FIELDS) {
    if (!(key in value)) continue;
    if (value[key] === null || value[key] === undefined) continue;
    if (typeof value[key] !== "string") return null;
    const text = viewString(value[key], {required: false});
    if (text) model[key] = text;
  }
  for (const key of SOLUTION_DETAIL_LIST_FIELDS) {
    if (!(key in value)) continue;
    if (value[key] === null || value[key] === undefined) continue;
    const raw = Array.isArray(value[key]) ? value[key] : [value[key]];
    const list = SOLUTION_OBJECT_LIST_FIELDS[key]
      ? viewSolutionList(raw, key)
      : viewStringList(raw, {maxItems: 20});
    if (!list) return null;
    model[key] = list;
  }
  return model;
}

function solutionsAreSufficientlyDifferent(candidates) {
  const fields = [
    "mechanism", "summary", "why_fit", "user_flow", "mvp_pages", "features",
    "inputs", "outputs", "decision_logic", "data_requirements", "technical_components",
    "implementation_plan", "acceptance_cases", "risks", "unknowns",
  ];
  for (let left = 0; left < candidates.length; left += 1) {
    for (let right = left + 1; right < candidates.length; right += 1) {
      const differences = fields.filter((field) => normalizeDiversityValue(candidates[left][field]) !== normalizeDiversityValue(candidates[right][field]));
      if (differences.length < 2) return false;
    }
  }
  return true;
}

function toSolutionsViewModel(value) {
  if (!isPlainRecord(value) || !Array.isArray(value.candidates) || value.candidates.length !== 3) return null;
  if (hasRawViewFields(value, ["fixture_origin", "fixture_disclosure"])) return null;
  const candidates = value.candidates.map(toSolutionCandidateViewModel);
  if (candidates.some((candidate) => !candidate)) return null;
  if (new Set(candidates.map((candidate) => candidate.id)).size !== candidates.length) return null;
  if (!solutionsAreSufficientlyDifferent(value.candidates)) return null;
  return {
    candidates,
    fixture_disclosure: viewDisclosure(value.fixture_disclosure)
      || (value.fixture_origin === "STAGE_A_SYNTHETIC" ? "Stage A 演示结果 · 非真实 AI 生成" : ""),
  };
}

function toDocumentVersionViewModel(value, expectedDocType) {
  if (!isPlainRecord(value)) return null;
  const id = viewString(value.version_id || value.id, {maxLength: 200});
  const docType = viewString(value.doc_type, {maxLength: 20});
  const version = Number(value.version);
  const content = viewString(value.content, {maxLength: 2000000});
  const status = viewString(value.status, {maxLength: 40});
  const validationStatus = viewString(value.validation_status, {maxLength: 40});
  const health = isPlainRecord(value.artifact_health)
    ? viewString(value.artifact_health.health_status, {maxLength: 40})
    : null;
  if (!id || !docType || docType !== expectedDocType || !Number.isInteger(version) || version < 1 || !content
    || !status || !validationStatus || !health) return null;
  return {
    id,
    version,
    doc_type: docType,
    content,
    status,
    validation_status: validationStatus,
    created_at: viewString(value.created_at, {required: false, maxLength: 80}) || "",
    artifact_health: {health_status: health},
  };
}

function snapshotNonGoalTerms(snapshot) {
  const nonGoals = viewStringList(snapshot?.solution?.explicit_non_goals, {required: false, maxItems: 20}) || [];
  return nonGoals.flatMap((item) => item
    .replace(/^.*?(?:不做|不包含|暂不支持|禁止|不支持|will not implement|not include)\s*/i, "")
    .split(/[、，,；;]+|以及|和|\s+and\s+/i)
    .map((term) => term.trim())
    .filter((term) => term.length >= 2));
}

function documentAddsNonGoal(content, terms) {
  // A bounded prose check, not semantic proof. Scope exclusions apply only to
  // their clause; a non-goal section permits bare excluded items, not promises.
  let exclusionSection = false;
  const positive = /支持|实现|增加|加入|提供|引入|开发|集成|上线|implement|support|add|build|include/i;
  for (const line of content.split(/\r?\n/)) {
    const heading = line.match(/^\s*#{1,6}\s+(.+)$/);
    if (heading) {
      exclusionSection = /^(?:\d+[.、]\s*)?(?:非目标|明确不做|不做范围|non[- ]goals|out of scope)(?:\s|[：:]|$)/i.test(heading[1]);
    }
    const clauses = line.split(/[。！？!?；;，,]|\b(?:but|however)\b|但是|但|(?:并且|并|同时)(?=支持|实现|增加|加入|提供|引入|开发|集成|上线)/i);
    for (const clause of clauses) {
      const listedTerms = clause.replace(/^\s*(?:[-*+]|\d+[.)、])\s*/, "").trim().split(/、|以及|和|\s+and\s+/i);
      const bareExclusion = exclusionSection && listedTerms.every((item) => terms.includes(item.trim()));
      for (const term of terms) {
        let offset = clause.indexOf(term);
        while (offset !== -1) {
          const before = clause.slice(0, offset);
          const after = clause.slice(offset + term.length);
          const negated = /(?:不做|不包含|暂不支持|不会支持|不支持|不集成|不提供|不增加|不引入|不会实现|禁止|不得|will not implement|not include|not support)\s*([^：:]*)$/i.exec(before);
          const excluded = negated && !positive.test(negated[1]);
          const excludedAfter = /^\s*(?:不在本期范围内|不在范围内|不属于本期范围|is out of scope)/i.test(after);
          if (!excluded && !excludedAfter && !bareExclusion) return true;
          offset = clause.indexOf(term, offset + term.length);
        }
      }
    }
  }
  return false;
}

function documentMatchesSelectedSnapshot(content) {
  const snapshot = state.snapshot;
  if (!isPlainRecord(snapshot)) return true;
  const solution = isPlainRecord(snapshot.solution) ? snapshot.solution : {};
  const selectedTitle = viewString(solution.title, {required: false, maxLength: 300});
  const targetUser = isPlainRecord(snapshot.target_user) ? snapshot.target_user.primary : "";
  const problem = isPlainRecord(snapshot.problem) ? snapshot.problem.statement : "";
  const mvp = isPlainRecord(snapshot.mvp) ? snapshot.mvp : {};
  const flowTerms = Array.isArray(snapshot.user_flow) ? snapshot.user_flow : [];
  const pageTerms = Array.isArray(mvp.pages) ? mvp.pages : [];
  const featureTerms = Array.isArray(mvp.features) ? mvp.features : [];
  const inheritedTerms = [
    solution.summary, solution.core_idea, solution.why_fit, solution.rationale,
    targetUser, problem, ...flowTerms, ...pageTerms, ...featureTerms,
  ].map((term) => viewString(term, {required: false, maxLength: 1000})).filter(Boolean);
  const forbiddenTerms = snapshotNonGoalTerms(snapshot);
  if (selectedTitle && !content.includes(selectedTitle)) return false;
  if (inheritedTerms.some((term) => !content.includes(term))) return false;
  if (documentAddsNonGoal(content, forbiddenTerms)) return false;
  return true;
}

function toDocumentWorkspaceViewModel(workspace) {
  if (!isPlainRecord(workspace) || !["prd", "techdoc"].includes(workspace.docType)) return null;
  if (!Array.isArray(workspace.versions)) return null;
  const versions = workspace.versions.map((version) => toDocumentVersionViewModel(version, workspace.docType));
  if (versions.some((version) => !version)) return null;
  const selected = versions.find((version) => version.id === workspace.selectedVersionId) || null;
  if (selected && !documentMatchesSelectedSnapshot(selected.content)) return null;
  let draft = null;
  if (workspace.draft) {
    if (!isPlainRecord(workspace.draft)) return null;
    const draftContent = viewString(workspace.draft.content, {maxLength: 2000000});
    const baseVersionId = viewString(workspace.draft.base_version_id, {maxLength: 200});
    if (!draftContent || !baseVersionId || !selected || baseVersionId !== selected.id || !documentMatchesSelectedSnapshot(draftContent)) return null;
    draft = {content: draftContent, base_version_id: baseVersionId, revision: Number(workspace.draft.revision) || 0};
  }
  return {versions, selected, draft};
}

function toHandoffViewModel(value, snapshot) {
  if (!isPlainRecord(value) || typeof value.project_id !== "string" || !value.project_id.trim()
    || typeof value.ready !== "boolean" || !isPlainRecord(value.documents)) return null;
  const hasOwn = (key) => Object.prototype.hasOwnProperty.call(value, key);
  const currentProjectId = viewString(state.currentProjectId, {maxLength: 200});
  if (!currentProjectId || value.project_id !== currentProjectId
    || !hasOwn("canvas_version") || !hasOwn("snapshot") || !hasOwn("unresolved_acknowledgement")) return null;
  if (value.canvas_version !== null
    && (!Number.isInteger(Number(value.canvas_version)) || Number(value.canvas_version) < 1)) return null;
  if (!Array.isArray(value.missing) || !Array.isArray(value.warnings) || !Array.isArray(value.unresolved_items)
    || !Array.isArray(value.expected_files) || !isPlainRecord(value.claim_boundary)
    || !Number.isInteger(Number(value.unresolved_claim_count)) || Number(value.unresolved_claim_count) < 0
    || !Number.isInteger(Number(value.draft_unresolved_claim_count)) || Number(value.draft_unresolved_claim_count) < 0
    || typeof value.acknowledgement_required !== "boolean") return null;
  const snapshotMetadata = value.snapshot;
  if (snapshotMetadata === null) {
    if (snapshot !== null && snapshot !== undefined) return null;
  } else {
    if (!isPlainRecord(snapshotMetadata)
      || !viewString(snapshotMetadata.id, {maxLength: 200})
      || !Number.isInteger(Number(snapshotMetadata.version)) || Number(snapshotMetadata.version) < 1
      || viewString(snapshotMetadata.health_status, {maxLength: 40}) !== "current") return null;
    if (!isPlainRecord(snapshot)
      || viewString(snapshot.id, {maxLength: 200}) !== viewString(snapshotMetadata.id, {maxLength: 200})
      || !Number.isInteger(Number(snapshot.version))
      || Number(snapshot.version) !== Number(snapshotMetadata.version)) return null;
  }
  const documentSummary = {};
  for (const docType of ["prd", "techdoc"]) {
    if (!Object.prototype.hasOwnProperty.call(value.documents, docType)) return null;
    const doc = value.documents[docType];
    if (doc && !isPlainRecord(doc)) return null;
    if (!doc) {
      documentSummary[docType] = null;
      continue;
    }
    const versionId = viewString(doc.version_id, {maxLength: 200});
    const documentId = viewString(doc.document_id, {maxLength: 200});
    const actualDocType = viewString(doc.doc_type, {maxLength: 20});
    const version = Number(doc.version);
    const canvasVersion = Number(doc.canvas_version);
    const validationStatus = viewString(doc.validation_status, {maxLength: 40});
    const status = viewString(doc.status, {maxLength: 40});
    const healthStatus = viewString(doc.health_status, {maxLength: 40});
    const confirmedAt = viewString(doc.confirmed_at || doc.approved_at, {required: false, maxLength: 80});
    if (!versionId || !documentId || actualDocType !== docType || !Number.isInteger(version) || version < 1
      || !Number.isInteger(canvasVersion) || canvasVersion < 1 || !validationStatus || !status
      || !confirmedAt || healthStatus !== "current") return null;
    documentSummary[docType] = {
      version_id: versionId,
      document_id: documentId,
      doc_type: actualDocType,
      version,
      canvas_version: canvasVersion,
      validation_status: validationStatus,
      status,
      confirmed_at: confirmedAt,
      health_status: healthStatus,
    };
  }
  if (value.ready && (value.missing.length || snapshotMetadata === null
    || !documentSummary.prd?.version_id || !documentSummary.techdoc?.version_id
    || documentSummary.prd.validation_status !== "passed" || documentSummary.techdoc.validation_status !== "passed"
    || documentSummary.prd.status !== "approved" || documentSummary.techdoc.status !== "approved"
    || documentSummary.prd.health_status !== "current" || documentSummary.techdoc.health_status !== "current")) return null;
  const arrayOfStrings = (items) => viewStringList(items, {required: false, maxItems: 30}) || [];
  const snap = isPlainRecord(snapshot) ? snapshot : {};
  const mvp = isPlainRecord(snap.mvp) ? snap.mvp : {};
  const solution = isPlainRecord(snap.solution) ? snap.solution : {};
  const targetUser = isPlainRecord(snap.target_user) ? snap.target_user.primary : "";
  const problem = isPlainRecord(snap.problem) ? snap.problem.statement : "";
  const missing = value.missing.map((item) => humanizeHandoffMessage(item?.message || item)).filter(Boolean);
  const unresolved = value.unresolved_items;
  return {
    ready: value.ready,
    documents: documentSummary,
    missing,
    unresolved: unresolved.map(humanizeUnresolvedItem),
    acknowledgement_required: Boolean(value.acknowledgement_required),
    unresolved_acknowledgement: Boolean(value.unresolved_acknowledgement),
    features: arrayOfStrings(mvp.features),
    non_goals: arrayOfStrings(solution.explicit_non_goals),
    implementation_tasks: arrayOfStrings(mvp.implementation_plan),
    acceptance_cases: arrayOfStrings(mvp.acceptance_criteria),
    risks: arrayOfStrings(snap.unknowns),
    selected_solution: {
      title: viewString(solution.title, {required: false, maxLength: 300}) || "",
      summary: viewString(solution.summary || solution.core_idea, {required: false, maxLength: 1000}) || "",
      why_fit: viewString(solution.why_fit || solution.user_value, {required: false, maxLength: 1000}) || "",
      rationale: viewString(solution.rationale, {required: false, maxLength: 1000}) || "",
      problem: viewString(problem, {required: false, maxLength: 1000}) || "",
      target_user: viewString(targetUser, {required: false, maxLength: 1000}) || "",
      flow: arrayOfStrings(snap.user_flow),
    },
  };
}

const STATUS_PRESENTATION = {
  draft: {label: "草稿", next: "继续编辑并运行检查"},
  approved: {label: "已批准", next: "只能基于此版本交接；修改会创建新草稿"},
  archived: {label: "已归档", next: "如需继续编辑，请恢复为新版本"},
  passed: {label: "检查通过", next: "等待人工确认"},
  failed: {label: "检查未通过", next: "查看校验提示并修改草稿"},
  not_run: {label: "尚未检查", next: "先运行文档检查"},
  current: {label: "当前有效", next: "可用于交接"},
  stale: {label: "需要重新检查", next: "证据或依赖已变化"},
  released: {label: "额度已释放", next: "本次操作未扣除用户额度"},
  committed: {label: "额度已结算", next: "本次操作已计入用户额度"},
};

// Unified draft recovery is deliberately a recovery layer, not a second source of
// truth. Server drafts use CAS revisions; local copies only protect text that has
// not reached the server yet and are always scoped by account/project/module.
const draftRecovery = {
  timers: new Map(),
  requests: new Map(),
  revisions: new Map(),
  localPrefix: "insightforge-draft-recovery:",
};

function draftAccountKey() {
  return String(state.accountId || globalThis.__INSIGHTFORGE_ACCOUNT_ID__ || "default");
}
function draftStorageKey(projectId, scopeType, scopeKey) {
  return `${draftRecovery.localPrefix}${encodeURIComponent(draftAccountKey())}:${encodeURIComponent(projectId || "new")}:${encodeURIComponent(scopeType)}:${encodeURIComponent(scopeKey)}`;
}
function draftContext(projectId, scopeType, scopeKey) {
  return `${draftAccountKey()}|${projectId}|${scopeType}|${scopeKey}`;
}
function readRecoveryCopy(projectId, scopeType, scopeKey) {
  try { return JSON.parse(globalThis.localStorage?.getItem(draftStorageKey(projectId, scopeType, scopeKey)) || "null"); } catch (_) { return null; }
}
function writeRecoveryCopy(projectId, scopeType, scopeKey, payload, baseRevision = null) {
  try {
    globalThis.localStorage?.setItem(draftStorageKey(projectId, scopeType, scopeKey), JSON.stringify({payload, baseRevision, dirty: true, savedAt: new Date().toISOString()}));
  } catch (_) { /* local recovery is best effort; server persistence remains authoritative. */ }
}
function clearRecoveryCopy(projectId, scopeType, scopeKey) {
  try { globalThis.localStorage?.removeItem(draftStorageKey(projectId, scopeType, scopeKey)); } catch (_) {}
}
function showDraftStatus(message) {
  const node = qs("#draft-recovery-status");
  if (node) node.textContent = message;
}
async function loadUnifiedDraft(projectId, scopeType, scopeKey) {
  const context = draftContext(projectId, scopeType, scopeKey);
  const response = await api(`/api/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(scopeType)}/${encodeURIComponent(scopeKey)}`).catch(error => {
    if (error.status === 404) return null;
    throw error;
  });
  const local = readRecoveryCopy(projectId, scopeType, scopeKey);
  draftRecovery.revisions.set(context, response ? Number(response.revision) : 0);
  if (local?.dirty) {
    if (!response || Number(local.baseRevision ?? 0) >= Number(response.revision ?? 0)) {
      showDraftStatus("发现未同步内容，已暂时保留在本机。");
    } else {
      showDraftStatus("这个内容已经在其他页面更新。你的当前内容已临时保留。");
    }
  }
  return {context, server: response, local};
}
function preferredRecoveryPayload(recovered) {
  const server = recovered?.server;
  const local = recovered?.local;
  if (local?.dirty && (!server || Number(local.baseRevision ?? 0) >= Number(server.revision ?? 0))) return local.payload;
  return server?.payload || local?.payload || null;
}
function queueUnifiedDraft(projectId, scopeType, scopeKey, payload, {baseRevision = null, delay = 700} = {}) {
  if (!projectId) {
    writeRecoveryCopy("new", scopeType, scopeKey, payload, baseRevision);
    showDraftStatus("仅保存在本机，项目创建后可继续同步。");
    return;
  }
  writeRecoveryCopy(projectId, scopeType, scopeKey, payload, baseRevision);
  showDraftStatus("正在保存…");
  const key = draftContext(projectId, scopeType, scopeKey);
  if (baseRevision == null && draftRecovery.revisions.has(key)) baseRevision = draftRecovery.revisions.get(key);
  clearTimeout(draftRecovery.timers.get(key));
  const requestId = (draftRecovery.requests.get(key) || 0) + 1;
  draftRecovery.requests.set(key, requestId);
  draftRecovery.timers.set(key, setTimeout(async () => {
    try {
      const result = await api(`/api/projects/${encodeURIComponent(projectId)}/drafts/${encodeURIComponent(scopeType)}/${encodeURIComponent(scopeKey)}`, {
        method: "PUT", body: JSON.stringify({payload, base_revision: baseRevision}),
      });
      if (draftRecovery.requests.get(key) !== requestId || draftContext(projectId, scopeType, scopeKey) !== key) return;
      draftRecovery.revisions.set(key, Number(result.revision));
      clearRecoveryCopy(projectId, scopeType, scopeKey);
      showDraftStatus("已保存");
      return result;
    } catch (error) {
      if (draftRecovery.requests.get(key) !== requestId || draftContext(projectId, scopeType, scopeKey) !== key) return;
      if (error.code === "DRAFT_CONFLICT") showDraftStatus("这个内容已经在其他页面更新。你的当前内容已临时保留。");
      else showDraftStatus("已保存到本机，等待同步");
    }
  }, delay));
}
function setAccountContext(accountId) {
  state.accountId = accountId || null;
}
function recoverNewIdeaDraft() {
  const copy = readRecoveryCopy("new", "idea", "main");
  const payload = copy?.payload;
  if (!payload || typeof payload !== "object") return;
  for (const [id, value] of Object.entries({
    "quick-start-idea": payload.idea,
    "quick-start-target-user": payload.target_user,
    "quick-start-priority": payload.priority,
    "quick-start-resources": payload.resources,
  })) {
    const node = qs(`#${id}`);
    if (node && value != null) node.value = Array.isArray(value) ? value.join("\n") : value;
  }
  showDraftStatus("发现未同步内容，已暂时保留在本机。");
}
if (typeof window.addEventListener === "function") {
  window.addEventListener("insightforge-account-ready", recoverNewIdeaDraft);
}
function persistViewContext() {
  if (!state.currentProjectId) return;
  queueUnifiedDraft(state.currentProjectId, "ui_context", "main", {
    activeView: state.activeView,
    evidenceTab: state.evidenceTab,
    docType: state.documentWorkspace.docType,
  }, {delay: 250});
}

function statusPresentation(value) {
  return STATUS_PRESENTATION[value] || {label: "状态待确认", next: "查看技术详情或联系操作员"};
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

function activateView(view, {recordHistory = false} = {}) {
  const previousView = state.activeView;
  if (recordHistory && state.currentProjectId && window.history?.pushState) {
    window.history.pushState({projectId: state.currentProjectId, view}, "", `#view=${encodeURIComponent(view)}`);
  }
  persistViewContext();
  secureSettingsExit();
  state.activeView = view;
  persistViewContext();
  qsa(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  qsa(".workspace-view").forEach((node) => node.classList.toggle("hidden", node.dataset.workspaceView !== view));
  qs("#primary-nav").classList.remove("open");
  qs("#mobile-nav-button").setAttribute("aria-expanded", "false");
  if (view === "snapshot" && state.currentProjectId) trackBetaEventOnce(`snapshot:${state.currentProjectId}`, "snapshot_viewed", {}, state.currentProjectId);
  if (view === "documents" && previousView !== view && state.currentProjectId) loadDocuments().catch(reportError);
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
  if (!action || !action.title || !action.code) {
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
  mvp: ["3. MVP 与项目成果", "查看当前正式方案、MVP 页面、输入输出、实施计划、关键未知项和下一步验证任务。"],
  claims: ["4. 关键判断", "把目标用户、问题、行为、价值和可行性拆成可验证的判断。用户确认系统理解，不等于这些判断已经被市场验证。"],
  evidence: ["5. 资料影响", "添加资料后查看它支持、削弱还是与哪个判断冲突，以及这是否会影响当前决策和项目成果。"],
  documents: ["6. PRD / TechDoc", "在当前项目成果和有效资料基础上生成正式文档。你可以在线编辑、自动保存草稿、比较版本，并把旧版本恢复为一个新的不可变版本。"],
  handoff: ["7. 开发交接", "只有当前项目成果与确认且健康的 PRD / TechDoc 才进入交接。这里可以生成 Codex 等开发工具需要的正式上下文。"],
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

const STRUCTURED_LABELS = {
  data_field: "资料字段", purpose: "用途", source: "来源", risk: "风险", mitigation: "应对方式",
  step: "步骤", action: "操作", ui_hint: "页面提示", input_type: "输入类型", field: "字段",
  required: "是否必填", description: "说明", evidence: "依据", dependency: "依赖项",
  camera_quality_and_lighting: "相机拍摄质量和门店光照", camera_quality_and_lighting_requirements: "相机拍摄质量和门店光照要求",
  public_dataset_or_manual_upload: "公开数据集或人工上传", user_registration_address: "用户注册地址",
};

function parseStructuredValue(value) {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]")))) return value;
  try { return JSON.parse(trimmed); } catch (_) { return value; }
}

function presentStructuredValue(value, fallback = "待确认", depth = 0) {
  const parsed = depth === 0 ? parseStructuredValue(value) : value;
  if (parsed === null || parsed === undefined || parsed === "") return fallback;
  if (["string", "number", "boolean"].includes(typeof parsed)) return String(parsed);
  if (Array.isArray(parsed)) return parsed.map((item) => presentStructuredValue(item, fallback, depth + 1)).join("；") || fallback;
  if (typeof parsed === "object") {
    const entries = Object.entries(parsed).filter(([, item]) => item !== null && item !== undefined && item !== "");
    return entries.map(([key, item]) => `${STRUCTURED_LABELS[key] || "说明"}：${presentStructuredValue(item, fallback, depth + 1)}`).join("；") || fallback;
  }
  return fallback;
}

function presentInputOutput(value, fallback = "待确认") {
  return presentStructuredValue(value, fallback);
}

function presentProductFlow(step, index) {
  const parsed = parseStructuredValue(step);
  const title = typeof parsed === "object" && parsed !== null ? presentStructuredValue(parsed.step || parsed.title, `第 ${index + 1} 步`) : `第 ${index + 1} 步`;
  const action = typeof parsed === "object" && parsed !== null ? parsed.action || parsed.description || parsed : parsed;
  const hint = typeof parsed === "object" && parsed !== null ? parsed.ui_hint || parsed.hint : "";
  return `<article class="product-flow-step"><div class="product-flow-number">${index + 1}</div><div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(presentStructuredValue(action))}</p>${hint ? `<small>${escapeHtml(presentStructuredValue(hint))}</small>` : ""}</div></article>`;
}

function humanizeHandoffMessage(message) {
  const value = String(message || "").trim();
  if (!value) return "需要先完成当前项目成果和正式文档。";
  const known = {
    PRD_NOT_CONFIRMED: "PRD 还没有确认当前版本。",
    TECHDOC_NOT_CONFIRMED: "技术文档还没有确认当前版本。",
    DOCUMENTS_NOT_READY: "PRD 和技术文档还没有同时准备好。",
    UNRESOLVED_ACKNOWLEDGEMENT_REQUIRED: "请先确认你已了解当前仍待确认的事项。",
  };
  if (known[value]) return known[value];
  if (/^[A-Z][A-Z0-9_]{2,}$/.test(value) || /[a-z]+_[a-z_]+/.test(value)) return "还有一项交接前条件未完成。";
  if (/exception|traceback|valueerror|keyerror|snapshot|sql|\\\\|\/app\//i.test(value)) return "还有一项交接前条件未完成。";
  return /[\u3400-\u9fff]/.test(value) ? value : "还有一项交接前条件未完成。";
}

function humanizeArtifactReason(reason) {
  const value = String(reason || "").trim();
  if (!value) return "当前项目成果、判断或资料依赖发生变化";
  const known = {
    stale_evidence: "相关资料或判断已经变化，需要重新检查",
    needs_review: "这份内容需要重新检查",
    source_archived: "引用的资料已归档，需要重新检查",
  };
  if (known[value]) return known[value];
  if (/^[A-Z][A-Z0-9_]{2,}$/.test(value) || /[a-z]+_[a-z_]+/.test(value)) return "相关资料或判断发生变化，需要重新检查";
  return /[\u3400-\u9fff]/.test(value) ? value : "相关资料或判断发生变化，需要重新检查";
}

function humanizeDependency(dependency) {
  const value = String(dependency || "");
  const [kind] = value.split(":", 1);
  return ({source: "项目资料", claim: "项目判断", project_snapshot: "方案选择", competitor_snapshot: "竞品决策"})[kind] || "项目依赖";
}

function detailList(title, items = [], presenter = presentStructuredValue) {
  const values = Array.isArray(items) ? items : [items];
  const blockClass = ["输入", "输出"].includes(title) ? " input-output-block" : "";
  return `<div class="detail-block${blockClass}"><strong>${escapeHtml(title)}</strong><ul>${values.map((x, index) => `<li>${escapeHtml(presenter(x, index))}</li>`).join("") || "<li>暂无</li>"}</ul></div>`;
}

function productFlowList(items = []) {
  const values = Array.isArray(items) ? items : [items];
  return `<div class="detail-block product-flow-block"><strong>用户流程</strong><div class="product-flow">${values.map((item, index) => presentProductFlow(item, index)).join("") || "<p class=\"muted\">暂无流程，待确认。</p>"}</div></div>`;
}

function inputOutputBlocks(inputs = [], outputs = []) {
  return `<div class="input-output-grid">${detailList("输入", inputs, presentInputOutput)}${detailList("输出", outputs, presentInputOutput)}</div>`;
}

function openSolutionDetails(candidateId, trigger) {
  const rawSolution = isPlainRecord(state.solutions) && Array.isArray(state.solutions.candidates)
    ? state.solutions.candidates.find((item) => isPlainRecord(item) && item.id === candidateId)
    : null;
  const solution = toSolutionDetailViewModel(rawSolution);
  if (!solution) { toast("该方案已不可用，请重新打开方案列表。"); return; }
  const dialog = qs("#solution-detail-dialog");
  dialog.returnFocus = trigger;
  if (!dialog.detailEventsBound) {
    qs("#solution-detail-close").addEventListener("click", () => dialog.close());
    dialog.addEventListener("close", () => {
      if (dialog.returnFocus?.isConnected) dialog.returnFocus.focus();
    });
    dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const b = dialog.getBoundingClientRect();
      if (event.clientX < b.left || event.clientX > b.right || event.clientY < b.top || event.clientY > b.bottom) dialog.close();
    });
    dialog.detailEventsBound = true;
  }
  qs("#solution-detail-title").textContent = solution.title || "方案详情";
  const rows = [
    ["目标用户", solution.target_user], ["问题", solution.problem],
    ["典型场景", solution.scenarios], ["适合当前想法的原因", solution.why_fit],
    ["核心功能", solution.features], ["数据要求", solution.data_requirements], ["风险", solution.risks],
    ["最小可用版本（MVP）范围", solution.mvp_pages],
    ["实现思路", solution.implementation_plan], ["技术组成", solution.technical_components],
    ["核心判断逻辑", solution.decision_logic], ["取舍", solution.tradeoffs],
    ["待确认事项", solution.unknowns],
  ];
  qs("#solution-detail-content").innerHTML = productFlowList(solution.user_flow) + inputOutputBlocks(solution.inputs, solution.outputs) + rows.map(([title, value]) =>
    detailList(title, Array.isArray(value) && value.length ? value : value && !Array.isArray(value) ? [value] : ["已有方案未提供此项；尚待确认。"])
  ).join("");
  if (!dialog.open) dialog.showModal();
  qs("#solution-detail-close").focus();
}

function renderSolutions() {
  const target = qs("#solutions-content");
  if (!target) return;
  const rawSolutions = state.solutions;
  const solutions = toSolutionsViewModel(rawSolutions);
  if (rawSolutions && !solutions) {
    state.solutions = null;
    state.generationTerminalFailure = true;
    state.generationFailureCode = "APPLICATION_POSTPROCESS_FAILURE";
  }
  if (!solutions?.candidates?.length) {
    const confirmed = state.ideaBrief?.confirmation_status === "confirmed";
    const clarificationRequired = Boolean(state.ideaBrief?.clarification_required);
    const action = clarificationRequired
      ? `<button id="open-idea-brief-button" class="button button-primary" type="button">补充信息</button>`
      : confirmed
      ? `<label class="managed-model-choice" for="managed-model-preference">模型<select id="managed-model-preference"><option value="AUTO">自动（默认 Qwen3.7-Flash）</option><option value="QWEN">Qwen3.7-Flash</option><option value="GLM">GLM-5.2</option><option value="DEEPSEEK">DeepSeek V4 Flash</option></select></label><button id="generate-solutions-button" class="button button-primary" type="button" aria-disabled="false">${state.generationFailureCode === "APPLICATION_POSTPROCESS_FAILURE" ? "发起新的生成" : state.generationTerminalFailure ? "重新生成" : "生成方案"}</button>`
      : `<button id="open-idea-brief-button" class="button button-primary" type="button">查看并确认项目定义</button>`;
    const message = clarificationRequired
      ? "还需要补充一项信息，完成澄清后才能确认项目理解并生成方案。"
      : confirmed
      ? "确认 Idea 理解后生成恰好三个真正不同的解决路径。"
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
  const fixtureNotice = solutions.fixture_disclosure;
  target.innerHTML = `${fixtureNotice ? `<p class="fixture-disclosure status-note">${escapeHtml(fixtureNotice)}</p>` : ""}<div class="solution-grid">${solutions.candidates.map((solution, index) => `
    <article class="solution-card" data-candidate-id="${escapeHtml(solution.id)}">
      <div class="solution-card-head"><span>方案 ${String.fromCharCode(65 + index)}</span><span class="pill">${escapeHtml(mechanismLabel(solution.mechanism))}</span></div>
      <h3>${escapeHtml(solution.title)}</h3>
      <p>${escapeHtml(solution.why_fit)}</p>
       <dl class="compact-spec"><div><dt>MVP 难度</dt><dd>${escapeHtml(complexityLabel(solution.complexity))}</dd></div><div><dt>数据要求</dt><dd>${escapeHtml(solution.data_requirements[0])}</dd></div><div><dt>最大风险</dt><dd>${escapeHtml(solution.risks[0])}</dd></div></dl>
      <details><summary>查看完整实施方案</summary>
        ${productFlowList(solution.user_flow)}
        ${detailList("MVP 页面", solution.mvp_pages)}
        ${detailList("核心功能", solution.features)}
        ${inputOutputBlocks(solution.inputs, solution.outputs)}
        ${detailList("核心判断逻辑", solution.decision_logic)}
        ${detailList("数据来源", solution.data_requirements)}
        ${detailList("技术组成", solution.technical_components)}
        ${detailList("两周实施", solution.implementation_plan)}
        ${detailList("验收案例", solution.acceptance_cases)}
        ${detailList("当前未知项", solution.unknowns)}
      </details>
      <button class="button button-secondary solution-detail-button" type="button" data-candidate-id="${escapeHtml(solution.id)}">查看详情</button>
      <button class="button button-primary select-solution-button" type="button" data-candidate-id="${escapeHtml(solution.id)}">选择这个方案</button>
    </article>`).join("")}</div>`;
  qsa(".select-solution-button", target).forEach((button) => button.addEventListener("click", () => selectSolution(button.dataset.candidateId)));
  qsa(".solution-detail-button", target).forEach((button) => button.addEventListener("click", () => openSolutionDetails(button.dataset.candidateId, button)));
}

function renderSnapshot() {
  const target = qs("#snapshot-content");
  const action = qs("#snapshot-primary-action");
  const reconfirm = qs("#snapshot-health-reconfirm");
  if (!state.snapshot) {
    target.innerHTML = `<div class="empty-state"><h2>还没有项目成果</h2><p>确认一个方案后，这里会生成第一份项目成果。</p></div>`;
    action.classList.add("hidden");
    reconfirm.classList.add("hidden");
    return;
  }
  const snap = state.snapshot;
  const unknown = (snap.unknowns || [])[0] || "暂无关键未知项";
  const solutionTitle = snap.solution?.title || snap.title;
  target.innerHTML = `
    <div class="snapshot-hero"><p class="eyebrow">项目成果 · 第 V${escapeHtml(snap.version)} 版</p><h1>${escapeHtml(snap.title)}</h1><p>${escapeHtml(snap.one_liner)}</p></div>
    <div class="snapshot-grid">
      <article class="result-card"><span>目标用户</span><strong>${escapeHtml(snap.target_user?.primary || "待确认")}</strong><small>${escapeHtml(snap.target_user?.verification_status || "待验证")}</small></article>
      <article class="result-card emphasis"><span>当前方案</span><strong>${escapeHtml(solutionTitle)}</strong><small>${escapeHtml(snap.solution?.rationale || "当前信息下的首选验证路径")}</small></article>
      <article class="result-card"><span>MVP</span><strong>${escapeHtml((snap.mvp?.pages || []).length)} 个页面 · ${escapeHtml((snap.mvp?.features || []).length)} 个核心能力</strong><small>${escapeHtml((snap.mvp?.implementation_plan || [])[0] || "按最小范围实施")}</small></article>
      <article class="result-card risk"><span>当前最大未知项</span><strong>${escapeHtml(unknown)}</strong><small>优先验证会改变方案的判断</small></article>
    </div>
    <section class="snapshot-section"><h2>产品流程</h2><div class="product-flow">${(snap.user_flow || []).map((step, index) => presentProductFlow(step, index)).join("") || "<p class=\"muted\">暂无流程，待确认。</p>"}</div></section>
    <section class="snapshot-section"><h2>输入 / 输出</h2><div class="two-column"><div>${detailList("输入", snap.inputs || [], presentInputOutput)}</div><div>${detailList("输出", snap.outputs || [], presentInputOutput)}</div></div></section>`;
  const next = snap.next_action || {};
  action.textContent = humanizeSnapshotAction(next.action);
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
      <div class="proposal-head"><span>变更建议</span><strong>${escapeHtml(proposal.status)}</strong></div>
      <h3>${escapeHtml(proposal.summary)}</h3>
      <p>${escapeHtml(proposal.reason)}</p>
      <div class="proposal-meta"><span>受影响判断：${escapeHtml((proposal.affected_claims || []).length)}</span><span>受影响决策：${escapeHtml((proposal.affected_decisions || []).length)}</span></div>
      ${open ? `<div id="${escapeHtml(proposalActionsId)}" class="proposal-actions" data-proposal-actions-for="${escapeHtml(proposal.id)}" tabindex="-1"><button class="button button-primary" data-proposal-action="accept" data-proposal-id="${escapeHtml(proposal.id)}" type="button">接受修改</button><button class="button button-secondary" data-proposal-action="defer" data-proposal-id="${escapeHtml(proposal.id)}" type="button">暂不修改</button><button class="button button-quiet" data-proposal-action="reject" data-proposal-id="${escapeHtml(proposal.id)}" type="button">标记为冲突继续验证</button></div>` : `<small>该建议已由用户处理，正式版本不会被自动回写。</small>`}
    </article>`;
  }).join("");
  target.innerHTML = `${claimRows || `<div class="empty-state"><p>当前还没有可展示的证据影响。</p></div>`}${proposalRows ? `<section class="proposal-list"><h3>需要你确认的调整</h3>${proposalRows}</section>` : ""}`;
  qsa("[data-proposal-action]", target).forEach((button) => button.addEventListener("click", () => decideChangeProposal(button.dataset.proposalId, button.dataset.proposalAction)));
}

function renderSourceLibrary() {
  qs("#source-list").innerHTML = (state.sources || []).map((source) => {
    const metadata = source.metadata || {};
    const guidance = metadata.needs_confirmation ? "待确认来源" : "已记录来源";
    const limits = Array.isArray(metadata.limitations) ? metadata.limitations.join("；") : "";
    const status = source.status || "unknown";
    const readableStatus = statusPresentation(status);
    return `<article class="source-row"><div><strong>${escapeHtml(source.title)}</strong><small>${escapeHtml(sourceTypeLabel(source.source_type))} · ${escapeHtml(guidance)}</small>${limits ? `<small>边界：${escapeHtml(limits)}</small>` : ""}</div><span>${escapeHtml(readableStatus.label)}</span><details class="technical-details"><summary>技术详情</summary><code>${escapeHtml(status)}</code><span>${escapeHtml(readableStatus.next)}</span></details></article>`;
  }).join("") || "<p class=\"muted\">暂无资料。添加资料后，系统会核对它支持哪些判断，以及引用内容是否确实来自原文。</p>";
}

function renderEvidenceEntryGuidance() {
  const panel = qs("#evidence-entry-guidance");
  if (!panel) return;
  const mode = state.evidenceEntry.mode;
  if (!mode) {
    panel.innerHTML = `<div class="evidence-entry-options"><span class="evidence-entry-disabled" role="status">联网查找暂未开启</span><button class="button button-secondary" data-evidence-entry="own_material" type="button">我有自己的资料</button><button class="button button-quiet" data-evidence-entry="no_evidence" type="button">暂时没有，先继续</button></div><p class="muted">联网查找暂未开启，你可以先手动添加资料、记录已有产品，或者跳过这一步。</p>`;
    return;
  }
  if (mode === "action_guidance") {
    panel.innerHTML = '<div class="evidence-entry-choice"><strong>资料行动卡</strong><p>AI会把待确认判断整理成具体行动：找谁、问什么、拿到什么以及会影响哪个产品决定。</p><button id="evidence-guidance-generate" class="button button-primary" type="button">生成资料行动卡</button><button class="button button-quiet" data-evidence-entry="reset" type="button">返回入口选择</button></div>';
    qs("#evidence-guidance-generate")?.addEventListener("click", () => void generateEvidenceGuidance());
    renderEvidenceGuidance();
    return;
  }
  if (mode === "public_search") {
    panel.innerHTML = `<div class="evidence-entry-choice"><strong>公开资料候选</strong><p>当前未配置公开搜索后端。这里不会伪造搜索结果，也不会把模型生成的网址当成已检索事实。</p><small>后续接入搜索后，只会先展示候选来源和获取时间；你确认前不会进入正式项目 RAG。</small><button class="button button-quiet" data-evidence-entry="reset" type="button">返回入口选择</button></div>`;
    return;
  }
  if (mode === "no_evidence") {
    state.evidenceEntry.pending = true;
    panel.innerHTML = `<div class="evidence-entry-choice"><strong>先不添加资料</strong><p>可以继续形成草稿，但相关判断会明确标记为待验证，不会被写成市场事实，也不会自动绕过校验、批准或交接。</p><button class="button button-quiet" data-evidence-entry="reset" type="button">返回入口选择</button></div>`;
    return;
  }
  panel.innerHTML = `<form id="guided-evidence-form" class="evidence-form"><div class="evidence-entry-choice"><strong>添加自己的资料</strong><p>请用自然语言描述来源；系统会保留来源说明和真实性核验边界。</p><label>标题<input id="guided-source-title" maxlength="200" required placeholder="例如：客户反馈摘要 #01"></label><label>资料类型<select id="guided-source-origin"><option value="owner_input">我自己的判断或资料</option><option value="real_interview">真实访谈（仍需核验）</option><option value="official_page">官方页面</option><option value="public_report">公开报告</option><option value="unknown">其他/待确认</option></select></label><label>简短说明和内容<textarea id="guided-source-content" rows="5" maxlength="2000000" required placeholder="说明这份资料是什么、来自哪里，以及它支持或削弱什么判断。"></textarea></label><button class="button button-primary" type="submit">添加为待校验资料</button><button class="button button-quiet" data-evidence-entry="reset" type="button">返回入口选择</button></div></form>`;
}

function selectEvidenceEntry(mode) {
  state.evidenceEntry.mode = mode === "reset" ? null : mode;
  renderEvidenceEntryGuidance();
  renderEvidenceGuidance();
  if (state.currentProjectId) {
    queueUnifiedDraft(state.currentProjectId, "evidence_guidance", "entry", {mode: state.evidenceEntry.mode}, {delay: 0});
  }
  qs("#guided-evidence-form")?.addEventListener("submit", addGuidedEvidence);
  qsa("[data-evidence-entry]").forEach((button) => button.addEventListener("click", () => selectEvidenceEntry(button.dataset.evidenceEntry)));
}

async function addGuidedEvidence(event) {
  event.preventDefault();
  if (!state.currentProjectId || state.evidenceEntry.submitting) return;
  state.evidenceEntry.submitting = true;
  const payload = {title: qs("#guided-source-title").value.trim(), origin_kind: qs("#guided-source-origin").value, content: qs("#guided-source-content").value.trim(), filename: "guided_evidence.txt"};
  try {
    const result = await api(`/api/projects/${state.currentProjectId}/sources/guided`, {method: "POST", body: JSON.stringify(payload)});
    state.evidenceEntry = {mode: null, submitting: false, pending: false};
    await Promise.all([loadEvidenceData(), loadProjectNextAction()]);
    toast(result?.guidance?.needs_confirmation ? "资料已记录为待确认来源；它不会自动证明访谈或需求已经验证。" : "资料已记录；请继续完成资料与判断的关系及范围校验。");
  } catch (error) { state.evidenceEntry.submitting = false; reportError(error); }
}

const evidenceGuidancePanel = {project: null, busy: false, result: null, guidanceId: null, requestKey: null};
const evidenceGuidanceFields = [
  ["要确认什么", "question_to_validate"],
  ["为什么重要", "why_it_matters"],
  ["找谁 / 去哪里", "who_or_where"],
  ["具体怎么做", "action_steps"],
  ["可以这样问", "suggested_questions"],
  ["拿到什么就可以填写", "acceptable_artifacts"],
  ["填写模板", "fill_template"],
  ["会影响哪个产品决定", "decision_impact"],
  ["暂时拿不到怎么办", "fallback_if_unavailable"],
  ["这条材料的局限", "limitations"],
];

function appendEvidenceGuidanceBlock(parent, label, value) {
  const block = document.createElement("section");
  block.className = "evidence-coach-block";
  const heading = document.createElement("h4");
  heading.textContent = label;
  block.append(heading);
  if (Array.isArray(value)) {
    const list = document.createElement("ul");
    const items = value.length ? value : ["可按实际情况补充问题。"];
    items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = String(item || "暂未确认");
      list.append(li);
    });
    block.append(list);
  } else {
    const copy = document.createElement("p");
    copy.textContent = String(value || "暂未确认");
    block.append(copy);
  }
  parent.append(block);
}

function renderEvidenceGuidance() {
  const panel = qs("#evidence-coach-panel");
  const content = qs("#evidence-guidance-content");
  const message = qs("#evidence-guidance-message");
  if (!panel || !content || !message) return;
  const active = state.evidenceEntry.mode === "action_guidance";
  panel.classList.toggle("hidden", !active);
  if (!active) return;
  content.replaceChildren();
  if (evidenceGuidancePanel.busy) {
    message.textContent = "正在整理可以实际补充的资料…";
    return;
  }
  const rawResult = evidenceGuidancePanel.result;
  const result = toEvidenceGuidanceViewModel(rawResult);
  const cards = result?.cards || [];
  if (!cards.length) {
    message.textContent = evidenceGuidancePanel.result
      ? "这次没有生成可用的资料行动建议，请稍后重试；没有创建资料来源。"
      : "点击“生成资料行动卡”，让 AI 帮你把待确认判断变成下一步行动。";
    return;
  }
  message.textContent = "AI建议你去补这些资料，尚未加入项目资料，也不代表已经核实。";
  const fixtureNotice = result.fixture_disclosure;
  if (fixtureNotice) {
    const notice = document.createElement("p");
    notice.className = "fixture-disclosure status-note";
    notice.textContent = fixtureNotice;
    content.append(notice);
  }
  cards.forEach((card, index) => {
    const article = document.createElement("article");
    article.className = "evidence-coach-card";
    const title = document.createElement("h3");
    title.textContent = "行动卡 " + (index + 1) + "： " + String(card.title || "待确认事项");
    article.append(title);
    evidenceGuidanceFields.forEach(([label, key]) => appendEvidenceGuidanceBlock(article, label, card[key]));
    const status = document.createElement("p");
    status.className = "status-note";
    status.textContent = "AI建议，仍需你结合实际情况判断；这不是已验证资料。";
    article.append(status);
    content.append(article);
  });
}

async function loadEvidenceGuidance() {
  const project = state.currentProjectId;
  evidenceGuidancePanel.project = project;
  evidenceGuidancePanel.busy = false;
  evidenceGuidancePanel.result = null;
  evidenceGuidancePanel.guidanceId = null;
  evidenceGuidancePanel.requestKey = project ? "evidence-guidance-" + project : null;
  if (!project) {
    renderEvidenceGuidance();
    return;
  }
  try {
    const recoveredEntry = preferredRecoveryPayload(await loadUnifiedDraft(project, "evidence_guidance", "entry"));
    if (recoveredEntry?.mode) state.evidenceEntry.mode = recoveredEntry.mode;
  } catch (_) {}
  try {
    const stored = await api("/api/projects/" + encodeURIComponent(project) + "/evidence-guidance");
    if (stored?.status === "completed" && toEvidenceGuidanceViewModel(stored.result)) {
      evidenceGuidancePanel.result = stored.result;
      evidenceGuidancePanel.guidanceId = stored.id || null;
    }
  } catch (_) {}
  if (!evidenceGuidancePanel.result) {
    try {
      const recoveredResult = preferredRecoveryPayload(await loadUnifiedDraft(project, "evidence_guidance", "result"));
      if (toEvidenceGuidanceViewModel(recoveredResult?.result)) evidenceGuidancePanel.result = recoveredResult.result;
    } catch (_) {}
  }
  renderEvidenceEntryGuidance();
  renderEvidenceGuidance();
}

async function generateEvidenceGuidance() {
  if (!state.currentProjectId || evidenceGuidancePanel.busy) return;
  evidenceGuidancePanel.project = state.currentProjectId;
  evidenceGuidancePanel.result = null;
  evidenceGuidancePanel.guidanceId = null;
  evidenceGuidancePanel.busy = true;
  evidenceGuidancePanel.requestKey ||= "evidence-guidance-" + state.currentProjectId;
  renderEvidenceGuidance();
  try {
    const response = await api("/api/projects/" + encodeURIComponent(state.currentProjectId) + "/evidence-guidance", {
      method: "POST",
      body: JSON.stringify({idempotency_key: evidenceGuidancePanel.requestKey}),
    });
    if (!response?.id || !toEvidenceGuidanceViewModel(response.result)) {
      throw Object.assign(new Error("invalid evidence guidance response"), {code: "MODEL_OUTPUT_SCHEMA_INVALID"});
    }
    evidenceGuidancePanel.result = response.result;
    evidenceGuidancePanel.guidanceId = response.id;
    await queueUnifiedDraft(state.currentProjectId, "evidence_guidance", "result", {result: evidenceGuidancePanel.result}, {delay: 0});
    renderEvidenceGuidance();
  } catch (_) {
    evidenceGuidancePanel.result = null;
    const message = qs("#evidence-guidance-message");
    if (message) message.textContent = "这次没有生成可用的资料行动建议，请稍后重试；没有创建资料来源。";
  } finally {
    evidenceGuidancePanel.busy = false;
    renderEvidenceGuidance();
  }
}

function renderEvidence() {
  renderEvidenceClaims();
  renderImpactHistory();
  renderEvidenceEntryGuidance();
  renderEvidenceGuidance();
  qs("#guided-evidence-form")?.addEventListener("submit", addGuidedEvidence);
  qsa("[data-evidence-entry]").forEach((button) => button.addEventListener("click", () => selectEvidenceEntry(button.dataset.evidenceEntry)));
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
  const dependencyLabels = (doc.dependencies || []).map((dep) => humanizeDependency(dep.dependency_type)).slice(0, 8);
  let statusCopy = "当前草稿";
  if (confirmed && stale) statusCopy = "历史确认 · 当前证据已变化";
  else if (confirmed && health === "current") statusCopy = "已确认 · 当前有效";
  else if (doc.validation_status === "passed" && health === "current") statusCopy = "系统检查通过 · 等待用户确认";
  else if (stale) statusCopy = "当前版本需要重新检查";
  const warning = stale ? `<div class="document-warning"><strong>受影响：</strong>${escapeHtml(humanizeArtifactReason(doc.artifact_health?.reason))}${dependencyLabels.length ? `<small>受影响依赖：${escapeHtml(dependencyLabels.join("、"))}</small>` : ""}<small>历史内容保持不变；请基于当前资料重新生成或检查，而不是覆盖旧版本。</small></div>` : "";
  const canConfirm = !confirmed && doc.validation_status === "passed" && health === "current";
  return `<article class="document-card ${stale ? "document-stale" : ""}">
    <div class="document-card-head"><h3>${title}</h3><span>v${escapeHtml(doc.version)}</span></div>
    <p>${description}</p><p class="document-state">${escapeHtml(statusCopy)}</p>${warning}
    <div class="document-actions">
      ${canConfirm ? `<button class="button button-primary" data-confirm-doc="${escapeHtml(doc.id)}" type="button">确认此版本</button>` : ""}
      <button class="button button-secondary" ${generateAttribute} type="button">${stale ? "基于当前证据重新生成" : "生成新版本"}</button>
      <a class="button button-quiet" href="/api/documents/${encodeURIComponent(doc.id)}/export?format=md">导出 MD</a>
    </div>
    <details class="technical-details"><summary>查看技术详情</summary><span>检查状态：${escapeHtml(statusPresentation(doc.validation_status || "not_run").label)}</span><span>版本状态：${escapeHtml(statusPresentation(doc.lifecycle_status || doc.status || "draft").label)}</span><span>关联资料数量：${escapeHtml(String((doc.dependencies || []).length))}</span></details>
  </article>`;
}

function renderDocuments() {
  qs("#documents-content").innerHTML = `<div class="document-grid">${renderDocumentCard("prd", "PRD", "从当前项目成果、项目级判断和有效资料生成。")}${renderDocumentCard("techdoc", "TechDoc", "把当前 MVP 范围、技术约束与验收边界转成开发上下文。")}</div>`;
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
  const errorNode = qs("#document-workspace-error");
  const viewModel = workspace.error ? null : toDocumentWorkspaceViewModel(workspace);
  if (!workspace.error && !viewModel) workspace.error = {code: "DOCUMENT_CONTENT_INVALID"};
  if (workspace.error) {
    if (errorNode) {
      errorNode.classList.remove("hidden");
      const humanMessage = humanizeErrorMessage(workspace.error, "文档版本暂时无法加载，请稍后重试。");
      const code = stableErrorCode(workspace.error) || "DOCUMENT_VERSION_LOAD_FAILED";
      errorNode.innerHTML = `<strong>文档版本暂时无法加载</strong><span>${escapeHtml(humanMessage)}</span><details class="technical-details"><summary>技术详情</summary><code>错误代码：${escapeHtml(code)}</code><span>原始错误仅保留在服务端日志中。</span></details>`;
    }
    editor.value = "";
    editor.disabled = true;
    list.innerHTML = `<div class="empty-state"><p>未加载到可编辑版本，请稍后重试。</p></div>`;
    qs("#document-save-version").disabled = true;
    qs("#document-validate-selected").disabled = true;
    qs("#document-restore-selected").disabled = true;
    qs("#document-export-selected").disabled = true;
    return;
  }
  errorNode?.classList.add("hidden");
  const selected = viewModel.selected;
  const draftMatches = Boolean(viewModel.draft && selected && viewModel.draft.base_version_id === selected.id);
  const expectedContent = draftMatches ? viewModel.draft.content : selected?.content || "";
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

  list.innerHTML = viewModel.versions.length ? viewModel.versions.map((version) => {
    const selectedClass = version.id === workspace.selectedVersionId ? " selected" : "";
    const compareClass = version.id === workspace.compareVersionId ? " compare" : "";
    const health = version.artifact_health?.health_status || "unknown";
    const lifecycle = statusPresentation(version.status || "draft");
    const validation = statusPresentation(version.validation_status || "not_run");
    const healthCopy = statusPresentation(health);
    return `<article class="document-version-row${selectedClass}${compareClass}">
      <div><strong>v${escapeHtml(version.version)}</strong><span>${escapeHtml(lifecycle.label)} · ${escapeHtml(validation.label)} · ${escapeHtml(healthCopy.label)}</span><small>${escapeHtml(formatProjectDate(version.created_at))}</small></div>
      <details class="technical-details"><summary>技术详情</summary><span>版本状态：${escapeHtml(lifecycle.label)}</span><span>检查状态：${escapeHtml(validation.label)}</span><span>资料状态：${escapeHtml(healthCopy.label)}</span></details>
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
  workspace.error = null;
  qs("#document-editor-type").value = docType;
  try {
    workspace.versions = await api(`/api/projects/${state.currentProjectId}/documents/${docType}/versions`);
  } catch (error) {
    workspace.versions = [];
    workspace.selectedVersionId = null;
    workspace.compareVersionId = null;
    workspace.draft = null;
    workspace.dirty = false;
    workspace.error = {code: error.code || "DOCUMENT_VERSION_LOAD_FAILED", message: error.message || "无法加载文档版本"};
    renderDocumentWorkspace();
    return;
  }
  if (!workspace.versions.some((version) => version.id === workspace.selectedVersionId)) {
    workspace.selectedVersionId = workspace.versions[0]?.id || null;
    workspace.compareVersionId = workspace.versions[1]?.id || null;
  }
  try {
    const draftPath = DOCUMENT_DRAFT_PATHS[docType];
    workspace.draft = await api(`/api/projects/${state.currentProjectId}${draftPath}`);
  } catch (error) {
    if (error.status === 404) workspace.draft = null;
    else workspace.error = {code: error.code || "DOCUMENT_DRAFT_LOAD_FAILED", message: error.message || "无法加载文档草稿"};
  }
  const selected = selectedDocumentVersion();
  if (selected) {
    const local = readRecoveryCopy(state.currentProjectId, "document", `${docType}:${selected.id}`);
    if (local?.dirty) {
      if (!workspace.draft || Number(local.baseRevision ?? 0) >= Number(workspace.draft.revision ?? 0)) {
        workspace.draft = {...(workspace.draft || {}), base_version_id: selected.id, content: local.payload?.content || "", revision: local.baseRevision ?? workspace.draft?.revision ?? null, recovered_locally: true};
        showDraftStatus("发现未同步内容，已暂时保留在本机。");
      } else {
        showDraftStatus("这个内容已经在其他页面更新。你的当前内容已临时保留。");
      }
    }
  }
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
    if (node.dataset.loadedPair === pair) node.textContent = humanizeErrorMessage(error, "暂时无法获取版本差异，请稍后重试。");
  }
}

function scheduleDocumentAutosave() {
  const workspace = state.documentWorkspace;
  const selected = selectedDocumentVersion();
  if (!state.currentProjectId || !selected) return;
  workspace.dirty = true;
  const content = qs("#document-editor").value;
  const draftScopeKey = `${workspace.docType}:${selected.id}`;
  writeRecoveryCopy(state.currentProjectId, "document", draftScopeKey, {content}, workspace.draft?.revision ?? null);
  const requestProject = state.currentProjectId;
  const requestVersion = selected.id;
  const requestRevision = workspace.draft?.revision ?? null;
  const requestContext = draftContext(requestProject, "document", draftScopeKey);
  qs("#document-autosave-status").textContent = "草稿有修改 · 正在等待自动保存…";
  clearTimeout(workspace.autosaveTimer);
  workspace.autosaveTimer = setTimeout(async () => {
    const latestContent = qs("#document-editor").value;
    if (!latestContent.trim()) {
      qs("#document-autosave-status").textContent = "草稿为空，不会覆盖已保存内容";
      return;
    }
    try {
      const draftPath = DOCUMENT_DRAFT_PATHS[workspace.docType];
      const result = await api(`/api/projects/${requestProject}${draftPath}`, {method: "PUT", body: JSON.stringify({base_version_id: requestVersion, base_revision: requestRevision, content: latestContent})});
      if (requestContext !== draftContext(state.currentProjectId, "document", draftScopeKey) || requestProject !== state.currentProjectId || requestVersion !== selectedDocumentVersion()?.id) return;
      workspace.draft = result;
      clearRecoveryCopy(requestProject, "document", `${workspace.docType}:${requestVersion}`);
      workspace.dirty = false;
      qs("#document-autosave-status").textContent = `草稿已自动保存 · 基于 v${selected.version}`;
    } catch (error) {
      if (requestContext !== draftContext(state.currentProjectId, "document", draftScopeKey)
        || requestProject !== state.currentProjectId
        || requestVersion !== selectedDocumentVersion()?.id) return;
      if (error.code === "DRAFT_CONFLICT") qs("#document-autosave-status").textContent = "这个内容已经在其他页面更新。当前内容已临时保留。";
      else qs("#document-autosave-status").textContent = "自动保存失败，正式版本未被修改";
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
      workspace.draft = await api(`/api/projects/${state.currentProjectId}${draftPath}`, {method: "PUT", body: JSON.stringify({base_version_id: selected.id, base_revision: workspace.draft?.revision ?? null, content: qs("#document-editor").value})});
      workspace.dirty = false;
      clearRecoveryCopy(state.currentProjectId, "document", `${workspace.docType}:${selected.id}`);
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
  const h = toHandoffViewModel(state.handoff, state.snapshot) || {
    ready: false, documents: {prd: null, techdoc: null}, missing: [], unresolved: [],
    acknowledgement_required: false, unresolved_acknowledgement: false,
    features: [], non_goals: [], implementation_tasks: [], acceptance_cases: [], risks: [],
    selected_solution: {},
  };
  const mvp = {features: h.features};
  const nonGoals = h.non_goals;
  const implementationTasks = h.implementation_tasks;
  const acceptanceCases = h.acceptance_cases;
  const docSummary = h?.documents || {};
  const risks = h.risks;
  const selectedSolution = h.selected_solution || {};
  const selectedSolutionBlock = selectedSolution.title ? `
    <section class="handoff-section"><h3>当前选中方案</h3>
      <p><strong>${escapeHtml(selectedSolution.title)}</strong></p>
      ${selectedSolution.summary ? `<p>${escapeHtml(selectedSolution.summary)}</p>` : ""}
      ${selectedSolution.why_fit ? `<p>适配理由：${escapeHtml(selectedSolution.why_fit)}</p>` : ""}
      ${selectedSolution.rationale ? `<p>选择依据：${escapeHtml(selectedSolution.rationale)}</p>` : ""}
      ${selectedSolution.problem ? `<p>问题：${escapeHtml(selectedSolution.problem)}</p>` : ""}
      ${selectedSolution.target_user ? `<p>目标用户：${escapeHtml(selectedSolution.target_user)}</p>` : ""}
      ${selectedSolution.flow?.length ? productFlowList(selectedSolution.flow) : ""}
    </section>` : "";
  const missing = h?.missing || [];
  const unresolved = h?.unresolved || [];
  const acknowledgement = h?.unresolved_acknowledgement;
  const acknowledgementBlock = h?.acknowledgement_required && !acknowledgement ? `
    <div class="handoff-acknowledgement">
      <p>当前版本仍有以下内容尚未验证。你可以继续交接，但建议在真实开发或测试过程中进一步确认。</p>
      <label><input id="handoff-unresolved-confirm" type="checkbox"> 我已了解，确认当前版本仍有待确认事项</label>
      <button id="handoff-acknowledge-button" class="button button-secondary" type="button" disabled>确认当前版本仍有待确认事项</button>
    </div>` : (acknowledgement ? "<p class=\"status-note\">已记录你对待确认事项的了解；这不表示这些事项已经被事实验证。</p>" : "");
  qs("#handoff-content").innerHTML = `
    <div class="handoff-status ${h.ready ? "handoff-ready" : "handoff-blocked"}"><strong>${escapeHtml(h.ready ? "开发交接已具备正式上下文" : "当前还不能安全交接")}</strong><span>${escapeHtml(h.ready ? "当前项目成果、PRD 和 TechDoc 均满足交接条件。" : humanizeHandoffMessage(missing[0]))}</span></div>
    ${selectedSolutionBlock}
    <section class="handoff-section"><h3>MVP 范围</h3>${detailList("本版包含", mvp.features || [])}</section>
    <section class="handoff-section"><h3>明确不做</h3>${detailList("本版暂不包含", nonGoals.length ? nonGoals : ["当前 Snapshot 暂未声明额外非目标；交接前不要擅自扩展范围。"])}</section>
    <section class="handoff-section"><h3>实施任务</h3>${detailList("实施顺序", implementationTasks)}</section>
    <section class="handoff-section"><h3>验收案例</h3>${detailList("验收案例", acceptanceCases)}</section>
    <section class="handoff-section"><h3>已确认文档</h3><div class="handoff-docs"><span>PRD：${escapeHtml(handoffDocumentLabel(docSummary.prd))}</span><span>TechDoc：${escapeHtml(handoffDocumentLabel(docSummary.techdoc))}</span></div></section>
     <section class="handoff-section"><h3>仍需确认的事项</h3>${unresolved.length ? detailList("事项", unresolved) : "<p>当前没有从文档中提取到待确认事项；资料是否充分仍需按实际来源判断。</p>"}${acknowledgementBlock}</section>
    <section class="handoff-section"><h3>未解决风险</h3>${detailList("仍需确认", risks.length ? risks : ["当前方案未记录关键未知项。"])}${missing.length ? detailList("阻塞项", missing.map((item) => humanizeHandoffMessage(item))) : ""}</section>
     <section class="handoff-section"><h3>复制/导出</h3><div class="handoff-actions"><button id="copy-handoff-button" class="button button-secondary" type="button">复制当前开发上下文</button><button id="export-handoff-button" class="button button-primary" type="button" ${h.ready ? "" : "disabled"}>导出 Codex 交接包</button><button id="load-handoff-button" class="button button-quiet" type="button">重新检查准备度</button></div></section>
    <details class="handoff-section advanced-panel"><summary>高级：MCP</summary><p>MCP 只作为已有确认上下文的高级读取/交接接口；当前 P0 不把远程 MCP 或企业权限作为主卖点。</p></details>`;
  qs("#load-handoff-button")?.addEventListener("click", loadHandoff);
  qs("#copy-handoff-button")?.addEventListener("click", copyHandoffContext);
  qs("#export-handoff-button")?.addEventListener("click", exportHandoff);
  qs("#handoff-unresolved-confirm")?.addEventListener("change", (event) => { qs("#handoff-acknowledge-button").disabled = !event.target.checked; });
  qs("#handoff-acknowledge-button")?.addEventListener("click", acknowledgeUnresolvedHandoff);
}

function handoffDocumentLabel(documentSummary) {
  if (!documentSummary || !documentSummary.version_id
    || documentSummary.status !== "approved"
    || documentSummary.validation_status !== "passed"
    || documentSummary.health_status !== "current") return "未确认";
  const version = documentSummary.version ? ` v${documentSummary.version}` : "";
  return `已确认${version}`;
}

function humanizeUnresolvedItem(item) {
  const safeText = (value, fallback) => {
    const text = viewString(value);
    if (!text) return fallback;
    if (/traceback|exception|valueerror|keyerror|sql|stack trace|[A-Z][A-Z0-9_]{2,}|[a-z]+_[a-z_]+|(?:^|[\\/])(?:app|src|var|tmp)(?:[\\/]|$)/i.test(text)) return fallback;
    return text;
  };
  if (typeof item === "string") return safeText(item, "还有一项内容需要确认");
  const subject = safeText(item?.item, "还有一项内容需要确认");
  const why = safeText(item?.why, "当前还没有足够依据");
  const how = safeText(item?.how_to_verify, "补充资料或进行一次实际验证");
  return `${subject}；${why}；建议：${how}`;
}

async function acknowledgeUnresolvedHandoff() {
  if (!state.currentProjectId) return;
  try {
    await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/handoff/acknowledge-unresolved`, {method:"POST", body:JSON.stringify({human_confirmed:true, note:"用户确认当前版本仍有待确认事项"})});
    await loadHandoff();
    toast("已记录确认；待确认事项仍会保留在交接中。");
  } catch (error) { reportError(error); }
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
    clearRecoveryCopy("new", "idea", "main");
    state.ideaBrief = result.idea_brief;
    state.runtimeMode = result.runtime_mode || result.ai_trace?.runtime_mode || state.runtimeMode;
    renderRuntimeDisclosure();
    await Promise.all([loadProjects(), loadHistory(), loadHomeNextAction()]);
    // Quick-start creates the project without going through loadProject().
    // Initialise the project-scoped AI reference state here as well, so the
    // first visit to the solutions view can generate or recover its reference.
    await loadAIReference();
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

function renderGenerationProgress(result = state.activeGeneration || {}) {
  const validatedResult = result?.status === "SUCCEEDED" && !toSolutionsViewModel(result)
    ? {...result, status: "FAILED", error_code: "MODEL_OUTPUT_SCHEMA_INVALID"}
    : result;
  const running = ["PENDING", "RUNNING"].includes(validatedResult.status);
  const failed = validatedResult.status === "FAILED";
  const message = validatedResult.error_code === "ASYNC_GENERATION_CANCELLED"
    ? "任务已停止。已发生的模型调用记录仍保留，停止任务不代表远端费用已取消。"
    : validatedResult.status === "SUCCEEDED" ? "方案已生成。"
    : failed ? humanizeErrorMessage({code: validatedResult.error_code, message: validatedResult.message, payload: validatedResult}, "这次生成没有完成，你的项目内容已保留，请重新生成。")
    : validatedResult.cancel_requested ? "正在停止任务……请等待服务端确认。" : "方案正在生成，请稍候……";
  if (qs("#generation-progress-state")) qs("#generation-progress-state").textContent = message;
  if (qs("#generation-stop")) qs("#generation-stop").disabled = !running || Boolean(validatedResult.cancel_requested);
  if (qs("#generation-progress-retry")) {
    qs("#generation-progress-retry").hidden = !failed;
    qs("#generation-progress-retry").disabled = false;
  }
  if (qs("#generation-progress-open")) qs("#generation-progress-open").hidden = !state.activeGeneration;
  if (validatedResult.status === "SUCCEEDED" && qs("#generation-progress-dialog")?.open) closeGenerationProgress();
}
function showGenerationProgress() {
  renderGenerationProgress();
  const dialog = qs("#generation-progress-dialog");
  if (dialog && !dialog.open) dialog.showModal();
}
function closeGenerationProgress() {
  qs("#generation-progress-dialog")?.close();
  qs("#generation-progress-open")?.focus();
}
async function retryFailedGeneration() {
  if (state.generationInFlight || !state.generationTerminalFailure || !state.currentProjectId) return;
  state.activeGeneration = null;
  closeGenerationProgress();
  await generateSolutions({newIntent: true});
}
async function cancelActiveGeneration() {
  const task = state.activeGeneration;
  if (!task || !["PENDING", "RUNNING"].includes(task.status) || task.cancel_requested) return;
  qs("#generation-stop").disabled = true;
  try {
    const result = await api(`/api/projects/${encodeURIComponent(task.projectId)}/solutions/generate/${encodeURIComponent(task.runId)}/cancel`, {method: "POST"});
    if (state.activeGeneration === task) {
      Object.assign(task, result);
      renderGenerationProgress(task);
    }
  } catch (error) { renderGenerationProgress(task); reportError(error); }
}
function rememberGeneration(projectId, runId) {
  // Only opaque task references; no content, credentials, cached policy or terminal state.
  if (state.generationReferenceKey) {
    try { sessionStorage.setItem(state.generationReferenceKey, JSON.stringify({projectId, runId})); } catch (_) {}
  }
}
async function restoreGenerationReference() {
  try {
    const account = await api("/api/auth/me");
    state.generationReferenceKey = `insightforge-generation:${account.id}`;
    const saved = JSON.parse(sessionStorage.getItem(state.generationReferenceKey) || "null");
    if (!saved || typeof saved.projectId !== "string" || typeof saved.runId !== "string") return;
    // Authoritative scoped GET must succeed before exposing or loading a saved project.
    const result = await api(`/api/projects/${encodeURIComponent(saved.projectId)}/solutions/generate/${encodeURIComponent(saved.runId)}`);
    if (result?.status === "SUCCEEDED" && !toSolutionsViewModel(result)) {
      state.activeGeneration = {...saved, ...result, status: "FAILED", error_code: "MODEL_OUTPUT_SCHEMA_INVALID"};
      renderGenerationProgress(state.activeGeneration);
      if (state.currentProjectId === saved.projectId) {
        state.solutions = null;
        state.generationTerminalFailure = true;
        state.generationFailureCode = "MODEL_OUTPUT_SCHEMA_INVALID";
        renderSolutions();
        showRecoveryPayload({error_code: "MODEL_OUTPUT_SCHEMA_INVALID"}, "solution_generation");
      }
      return result;
    }
    await loadProject(saved.projectId);
    state.activeGeneration = {...saved, ...result};
    renderGenerationProgress();
    const request = pollSolutionGeneration(saved.runId, saved.projectId);
    state.generationInFlight = request;
    try { await request; } finally { if (state.generationInFlight === request) state.generationInFlight = null; }
  } catch (_) { /* Missing/expired task references never authorize access or dispatch a new task. */ }
}

async function generateSolutions({newIntent = false} = {}) {
  if (state.generationInFlight) return state.generationInFlight;
  state.solutions = null;
  state.activeGeneration = null;
  renderSolutions();
  if (newIntent || !state.generationIntentId) {
    state.generationIntentId = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
  state.generationTerminalFailure = false;
  state.generationFailureCode = null;
  clearSolutionGenerationFailureNotice();
  const button = qs("#generate-solutions-button");
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
    button.textContent = "正在生成方案…";
  }
  const attemptId = state.generationIntentId;
  const projectId = state.currentProjectId;
  const loading = beginLoading("正在提交方案生成任务，请勿重复提交…");
  let request;
  request = (async () => {
    try {
      const result = await api(`/api/projects/${projectId}/solutions/generate`, {
        method: "POST",
        headers: {
          "X-Idempotency-Key": attemptId,
          "X-Generation-Mode": "async",
          "X-Managed-Model-Preference": state.managedModelPreference || "AUTO",
          "X-Use-Competitor-Snapshot": String(Boolean(state.useCompetitorSnapshot)),
          ...(state.useCompetitorSnapshot && state.competitorSnapshotId
            ? {"X-Competitor-Snapshot-Id": state.competitorSnapshotId}
            : {}),
        },
      });
      if (["PENDING", "RUNNING"].includes(result.status) && result.generation_run_id) {
        state.activeGeneration = {projectId, runId: result.generation_run_id, ...result};
        rememberGeneration(projectId, result.generation_run_id);
        showGenerationProgress();
        loading.update("方案正在处理中，正在等待结果。请勿重复提交…");
        return await pollSolutionGeneration(result.generation_run_id, projectId);
      }
      if (isRecoveryPayload(result)) {
        state.solutions = null;
        state.generationTerminalFailure = true;
        state.generationFailureCode = result.error_code || null;
        renderSolutions();
        showRecoveryPayload(result, "solution_generation");
        return result;
      }
      if (!toSolutionsViewModel(result)) {
        throw Object.assign(new Error("invalid solution response"), {code: "MODEL_OUTPUT_SCHEMA_INVALID"});
      }
      state.solutions = result;
      state.generationIntentId = null;
      state.generationTerminalFailure = false;
      state.generationFailureCode = null;
      clearSolutionGenerationFailureNotice();
      renderSolutions();
      await loadProjectNextAction();
      return result;
    } catch (error) {
      state.solutions = null;
      state.generationTerminalFailure = true;
      state.generationFailureCode = error?.code || null;
      reportError(error);
      return null;
    } finally {
      loading.finish();
      if (state.generationInFlight === request) state.generationInFlight = null;
      if (button?.isConnected && !state.solutions?.candidates?.length) {
        button.disabled = false;
        button.setAttribute("aria-disabled", "false");
        button.textContent = state.generationFailureCode === "APPLICATION_POSTPROCESS_FAILURE" ? "发起新的生成" : state.generationTerminalFailure ? "重新生成" : "生成方案";
      }
    }
  })();
  state.generationInFlight = request;
  return request;
}

async function pollSolutionGeneration(runId, projectId = state.currentProjectId) {
  while (true) {
    const result = await api(`/api/projects/${encodeURIComponent(projectId)}/solutions/generate/${encodeURIComponent(runId)}`);
    const validatedSolutions = result?.status === "SUCCEEDED" ? toSolutionsViewModel(result) : null;
    if (result?.status === "SUCCEEDED" && !validatedSolutions) {
      if (state.activeGeneration?.runId === runId) {
        Object.assign(state.activeGeneration, result, {status: "FAILED", error_code: "MODEL_OUTPUT_SCHEMA_INVALID"});
        renderGenerationProgress(state.activeGeneration);
      }
      if (state.currentProjectId !== projectId) return result;
      state.solutions = null;
      state.generationTerminalFailure = true;
      state.generationFailureCode = "MODEL_OUTPUT_SCHEMA_INVALID";
      renderSolutions();
      showRecoveryPayload({error_code: "MODEL_OUTPUT_SCHEMA_INVALID"}, "solution_generation");
      return result;
    }
    if (state.activeGeneration?.runId === runId) {
      Object.assign(state.activeGeneration, result);
      renderGenerationProgress(result);
    }
    if (["PENDING", "RUNNING"].includes(result.status)) {
      await new Promise((resolve) => setTimeout(resolve, Number(result.poll_after_ms || 2000)));
      continue;
    }
    if (state.currentProjectId !== projectId) return result;
    if (isRecoveryPayload(result) || result.status === "FAILED") {
      state.solutions = null;
      state.generationTerminalFailure = true;
      state.generationFailureCode = result.error_code || null;
      renderSolutions();
      showRecoveryPayload(result, "solution_generation");
      return result;
    }
    if (!validatedSolutions && !toSolutionsViewModel(result)) {
      state.solutions = null;
      state.generationTerminalFailure = true;
      state.generationFailureCode = "MODEL_OUTPUT_SCHEMA_INVALID";
      renderSolutions();
      showRecoveryPayload({error_code: "MODEL_OUTPUT_SCHEMA_INVALID"}, "solution_generation");
      return result;
    }
    state.solutions = validatedSolutions || result;
    state.generationIntentId = null;
    state.generationTerminalFailure = false;
    state.generationFailureCode = null;
    clearSolutionGenerationFailureNotice();
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

function m1SetField(id, value) {
  const node = qs(`#${id}`);
  if (node) node.value = Array.isArray(value) ? value.join("\n") : String(value ?? "");
}

function m1ListValue(id) {
  return String(qs(`#${id}`)?.value || "")
    .split(/\r?\n/)
    .map(item => item.trim())
    .filter(Boolean);
}

function m2SetField(id, value) {
  const node = qs(`#${id}`);
  if (node) node.value = Array.isArray(value) ? value.join("\n") : String(value ?? "");
}

function m2ListValue(id) {
  return String(qs(`#${id}`)?.value || "")
    .split(/\r?\n/)
    .map(item => item.trim())
    .filter(Boolean);
}

function renderM2BuildSlice() {
  const panel = qs("#m2-build-slice-panel");
  if (!panel) return;
  const slice = state.buildSlice;
  const quality = state.buildSliceQuality || {};
  const action = state.projectIntent?.first_action;
  const readyForSlice = Boolean(action?.confirmed);
  const status = qs("#m2-build-slice-status");
  const gate = qs("#m2-build-slice-gate");
  const saveButton = qs("#m2-build-slice-save");
  const confirmButton = qs("#m2-build-slice-confirm");
  const fields = [
    ["m2-in-scope", slice?.in_scope],
    ["m2-out-of-scope", slice?.out_of_scope],
    ["m2-minimal-flow", slice?.minimal_flow],
    ["m2-acceptance-criteria", slice?.acceptance_criteria],
    ["m2-confirmed-constraints", slice?.confirmed_constraints],
    ["m2-inputs", slice?.inputs],
    ["m2-expected-outputs", slice?.expected_outputs],
    ["m2-error-handling", slice?.error_handling],
    ["m2-unknowns", slice?.unknowns],
    ["m2-constraint-notes", slice?.constraint_notes],
  ];
  fields.forEach(([id, value]) => m2SetField(id, value));
  m2SetField("m2-build-slice-purpose", slice?.purpose || state.projectIntent?.intent?.purpose);
  panel.hidden = !state.currentProjectId;
  qsa("#m2-build-slice-form textarea, #m2-build-slice-form input").forEach(node => { node.disabled = !readyForSlice; });
  if (saveButton) saveButton.disabled = !readyForSlice;
  if (confirmButton) confirmButton.disabled = !readyForSlice || !slice || slice.status === "CONFIRMED" || quality.p0_status !== "PASS";
  if (gate) gate.textContent = readyForSlice ? "M2 只记录你确认的范围，不执行外部行动。" : "请先确认 M1 第一行动卡，才能定义 Build Slice。";
  if (status) status.textContent = slice
    ? `Build Slice · ${slice.status || "DRAFT"} · 第 ${slice.revision || 1} 版`
    : "尚未定义 Build Slice。";
  const metricSummary = quality.metrics ? ` · 质量指标已记录：${Object.keys(quality.metrics).length} 项` : "";
  const qualityNode = qs("#m2-build-slice-quality");
  if (qualityNode) qualityNode.textContent = `P0 ${quality.p0_status || "未评估"}${metricSummary} · 不代表已执行、已测试或已部署。`;
}

async function loadM2Artifacts() {
  if (!state.currentProjectId) return;
  const projectId = encodeURIComponent(state.currentProjectId);
  try { state.buildSlice = await api(`/api/projects/${projectId}/build-slice`); } catch (_) { state.buildSlice = null; }
  try { state.buildSliceQuality = await api(`/api/projects/${projectId}/build-slice/quality`); } catch (_) { state.buildSliceQuality = null; }
  renderM2BuildSlice();
}

async function saveBuildSlice(event) {
  event.preventDefault();
  if (!state.currentProjectId || !state.projectIntent?.first_action?.confirmed) return;
  const current = state.buildSlice;
  try {
    state.buildSlice = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/build-slice`, {
      method: "PUT",
      body: JSON.stringify({
        slice_id: current?.slice_id || null,
        expected_revision: current ? current.revision : null,
        expected_snapshot_id: state.snapshot?.snapshot_id || state.snapshot?.id || null,
        expected_intent_revision: state.projectIntent?.intent?.revision || null,
        confirmed_constraints: m2ListValue("m2-confirmed-constraints"),
        in_scope: m2ListValue("m2-in-scope"),
        out_of_scope: m2ListValue("m2-out-of-scope"),
        minimal_flow: m2ListValue("m2-minimal-flow"),
        acceptance_criteria: m2ListValue("m2-acceptance-criteria"),
        inputs: m2ListValue("m2-inputs"),
        expected_outputs: m2ListValue("m2-expected-outputs"),
        error_handling: m2ListValue("m2-error-handling"),
        unknowns: m2ListValue("m2-unknowns"),
        constraint_notes: m2ListValue("m2-constraint-notes"),
      }),
    });
    state.buildSliceQuality = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/build-slice/quality`);
    renderM2BuildSlice();
    toast("Build Slice 已保存。请检查范围和验收标准后再确认。");
  } catch (error) { reportError(error); }
}

async function confirmBuildSlice() {
  const slice = state.buildSlice;
  if (!state.currentProjectId || !slice || slice.status === "CONFIRMED") return;
  try {
    state.buildSlice = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/build-slice/confirm`, {
      method: "POST",
      body: JSON.stringify({expected_revision: slice.revision}),
    });
    state.buildSliceQuality = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/build-slice/quality`);
    renderM2BuildSlice();
    toast("Build Slice 已确认。下一步可以生成一份可编辑的 Prototype Task 计划。");
  } catch (error) { reportError(error); }
}

function renderProjectIntent() {
  const payload = state.projectIntent;
  const intent = payload?.intent;
  const action = payload?.first_action;
  const actionPanel = qs("#m1-action-panel");
  const intentStatus = qs("#m1-intent-status");
  const actionStatus = qs("#m1-action-status");
  const actionState = qs("#m1-action-state");
  const confirmButton = qs("#m1-action-confirm");
  if (!actionPanel || !intentStatus || !actionStatus || !actionState || !confirmButton) return;
  qs("#m1-purpose").value = intent?.purpose || "UNSPECIFIED";
  m1SetField("m1-raw-idea", intent?.raw_idea);
  if (!intent || !action) {
    actionPanel.hidden = true;
    intentStatus.textContent = "尚未保存目的；保存后会生成一张本地行动卡。";
    actionStatus.textContent = "";
    qs("#m1-quality").textContent = "M1 默认不调用 Provider 或 Search。";
    return;
  }
  actionPanel.hidden = false;
  intentStatus.textContent = `目的已保存 · 第 ${intent.revision} 版`;
  m1SetField("m1-goal", action.goal);
  m1SetField("m1-why-now", action.why_now);
  m1SetField("m1-inputs", action.inputs);
  m1SetField("m1-steps", action.steps);
  m1SetField("m1-expected-artifact", action.expected_artifact);
  m1SetField("m1-checks", action.checks);
  m1SetField("m1-branches", action.branches);
  m1SetField("m1-stop-condition", action.stop_condition);
  m1SetField("m1-prohibited-actions", action.prohibited_actions);
  actionState.textContent = action.confirmed ? "已确认" : action.status === "READY" ? "待确认" : "需要修改";
  actionState.className = `evidence-status ${action.confirmed ? "status-supported" : action.status === "READY" ? "status-unverified" : "status-contradicted"}`;
  confirmButton.disabled = action.confirmed || action.status !== "READY";
  actionStatus.textContent = `行动卡第 ${action.revision} 版 · ${action.confirmed ? "已确认" : "可继续编辑"}`;
  const quality = payload.quality || {};
  const coverage = quality.structural_coverage || {};
  qs("#m1-quality").textContent = `结构完整度 ${coverage.covered || 0}/${coverage.required || 9} · 目的对齐 ${quality.purpose_alignment || "未评估"} · Provider 0 · Search 0 · 仅记录计划，未执行、未验证。`;
}

async function loadProjectIntent() {
  if (!state.currentProjectId) return;
  try { state.projectIntent = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/intent`); }
  catch (_) { state.projectIntent = null; }
  renderProjectIntent();
  renderM2BuildSlice();
}

async function saveProjectIntent(event) {
  event.preventDefault();
  if (!state.currentProjectId) return;
  const current = state.projectIntent?.intent;
  try {
    state.projectIntent = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/intent`, {
      method: "PUT",
      body: JSON.stringify({
        purpose: qs("#m1-purpose").value,
        raw_idea: qs("#m1-raw-idea").value.trim(),
        expected_revision: current ? current.revision : null,
      }),
    });
    renderProjectIntent();
    toast("目的已保存，第一张行动卡已生成。你可以先修改，再确认。");
  } catch (error) { reportError(error); }
}

async function saveFirstAction(event) {
  event.preventDefault();
  const action = state.projectIntent?.first_action;
  if (!state.currentProjectId || !action) return;
  try {
    state.projectIntent = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/actions/${encodeURIComponent(action.task_id)}`, {
      method: "PATCH",
      body: JSON.stringify({
        expected_revision: action.revision,
        goal: qs("#m1-goal").value.trim(),
        why_now: qs("#m1-why-now").value.trim(),
        inputs: m1ListValue("m1-inputs"),
        steps: m1ListValue("m1-steps"),
        expected_artifact: qs("#m1-expected-artifact").value.trim(),
        checks: m1ListValue("m1-checks"),
        branches: m1ListValue("m1-branches"),
        stop_condition: qs("#m1-stop-condition").value.trim(),
        prohibited_actions: m1ListValue("m1-prohibited-actions"),
      }),
    });
    renderProjectIntent();
    toast("行动卡新版本已保存，仍需你确认。");
  } catch (error) { reportError(error); }
}

async function confirmFirstAction() {
  const action = state.projectIntent?.first_action;
  if (!state.currentProjectId || !action || action.confirmed) return;
  try {
    state.projectIntent = await api(`/api/projects/${encodeURIComponent(state.currentProjectId)}/actions/${encodeURIComponent(action.task_id)}/confirm`, {
      method: "POST",
      body: JSON.stringify({expected_revision: action.revision}),
    });
    renderProjectIntent();
    toast("行动卡已确认。系统只记录计划，不代表行动已经执行或结果已经验证。");
  } catch (error) { reportError(error); }
}

async function loadProject(projectId) {
  if (state.currentProjectId !== projectId) {
    state.generationIntentId = null;
    state.generationTerminalFailure = false;
  }
  state.evidenceEntry = {mode: null, submitting: false, pending: false};
  state.currentProjectId = projectId;
  state.projectIntent = null;
  state.buildSlice = null;
  state.buildSliceQuality = null;
  state.prototypeTask = null;
  state.prototypeTaskQuality = null;
  state.documentWorkspace = {...state.documentWorkspace, versions: [], selectedVersionId: null, compareVersionId: null, draft: null, dirty: false, error: null};
  renderProjectPicker();
  showProjectShell();
  renderProjectIntent();
  renderM2BuildSlice();
  try { state.ideaBrief = await api(`/api/projects/${projectId}/idea-brief`); } catch (_) { state.ideaBrief = null; }
  try { state.solutions = await api(`/api/projects/${projectId}/solutions`); } catch (_) { state.solutions = null; }
  try { state.snapshot = await api(`/api/projects/${projectId}/snapshot`); } catch (_) { state.snapshot = null; }
  try {
    const project = await api(`/api/projects/${projectId}`);
    state.competitorSnapshotId = project.current_competitor_snapshot_id || null;
  } catch (_) { state.competitorSnapshotId = null; }
  state.useCompetitorSnapshot = Boolean(state.competitorSnapshotId);
  renderIdeaBrief();
  renderSolutions();
  renderSnapshot();
  try {
    const recovered = await loadUnifiedDraft(projectId, "ui_context", "main");
    const context = preferredRecoveryPayload(recovered);
    if (context && Object.prototype.hasOwnProperty.call(context, "useCompetitorSnapshot")) {
      const recoveredSnapshotId = context.competitorSnapshotId || null;
      // Preserve an explicit SNAPSHOT mode even when its binding is missing.
      // The server must reject that broken new record; silently turning it into
      // SKIPPED would be fail-open and could change document provenance.
      state.useCompetitorSnapshot = Boolean(context.useCompetitorSnapshot);
      state.competitorSnapshotId = recoveredSnapshotId;
    }
    if (context?.evidenceTab) state.evidenceTab = context.evidenceTab;
    if (context?.activeView && WORKSPACE_VIEWS.has(context.activeView) && context.activeView !== state.activeView) {
      activateView(context.activeView);
    }
  } catch (_) { /* recovery must not prevent the project from opening */ }
  await Promise.all([loadEvidenceData(), loadDocuments(), loadHandoff(), loadAIReference(), loadEvidenceGuidance(), loadProjectNextAction(), loadProjectModelProfile(), loadWalkthrough(), loadProjectIntent(), loadM2Artifacts()]);
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
    toast(action === "accept" ? "已创建新的项目成果；历史版本保持不变。" : "已记录你的决定；系统没有自动改写正式版本。");
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
  const workspace = state.documentWorkspace;
  workspace.docType = docType;
  workspace.versions = [];
  workspace.selectedVersionId = null;
  workspace.compareVersionId = null;
  workspace.draft = null;
  workspace.dirty = false;
  workspace.error = null;
  const editor = qs("#document-editor");
  if (editor) { editor.value = ""; editor.dataset.loadedVersionId = ""; editor.disabled = true; }
  renderDocumentWorkspace();
  try {
    const useSnapshot = Boolean(state.useCompetitorSnapshot);
    const result = await api(`/api/projects/${state.currentProjectId}/documents/generate`, {
      method: "POST",
      body: JSON.stringify({
        doc_type: docType,
        competitor_snapshot_id: useSnapshot && state.competitorSnapshotId ? state.competitorSnapshotId : null,
        use_competitor_snapshot: useSnapshot,
      }),
    });
    const generated = toDocumentVersionViewModel(result, docType);
    if (!generated || !documentMatchesSelectedSnapshot(generated.content)) {
      throw Object.assign(new Error("invalid document response"), {code: "DOCUMENT_VERSION_SCHEMA_INVALID"});
    }
    toast(`${docType.toUpperCase()} 已生成：${generated.id}`);
    await Promise.all([loadDocuments(), loadHandoff(), loadProjectNextAction()]);
  } catch (error) {
    workspace.error = {code: error?.code || "DOCUMENT_VERSION_SCHEMA_INVALID"};
    workspace.versions = [];
    workspace.selectedVersionId = null;
    workspace.compareVersionId = null;
    workspace.draft = null;
    workspace.dirty = false;
    renderDocumentWorkspace();
    reportError(error);
  }
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

const aiReferencePanel = {project: null, busy: false, result: null, decisions: [], referenceId: null, requestKey: null};
const AI_REFERENCE_GROUPS = [
  ["possible_target_users", "可能的目标用户"], ["possible_scenarios", "可能出现的场景"],
  ["possible_user_problems", "可能需要解决的问题"], ["missing_information", "目前还缺什么信息"],
  ["mvp_thoughts", "第一版可以怎么收敛"], ["questions_to_validate", "建议继续确认的问题"],
  ["research_directions", "后续可以去找哪些资料"],
];
function aiReferenceDraftPayload() { return {result: aiReferencePanel.result, decisions: aiReferencePanel.decisions}; }
function readAIReferenceDecisions() { return [...qsa("#ai-reference-content select")].map((select) => ({category: select.dataset.aiCategory, item: select.dataset.aiItem, decision: select.value, rationale: qs(`[data-ai-rationale-for="${CSS.escape(select.dataset.aiItem)}"]`)?.value.trim() || ""})); }
function rememberAIReferenceDraft() {
  if (qs("#ai-reference-content select")) aiReferencePanel.decisions = readAIReferenceDecisions();
  if (aiReferencePanel.project && aiReferencePanel.result) queueUnifiedDraft(aiReferencePanel.project, "ai_reference", "result", aiReferenceDraftPayload(), {delay: 500});
}
function renderAIReference() {
  const content = qs("#ai-reference-content"); if (!content) return;
  content.replaceChildren(); const rawResult = aiReferencePanel.result; if (!rawResult) return;
  const result = toAIReferenceViewModel(rawResult);
  if (!result) {
    const empty = document.createElement("p"); empty.className = "empty-state"; empty.textContent = "这次没有生成可用建议，请重新尝试。"; content.append(empty);
    return;
  }
  const notice = document.createElement("p"); notice.className = "status-note"; notice.textContent = result.uncertainty_notice; content.append(notice);
  const fixtureNotice = result.fixture_disclosure;
  if (fixtureNotice) {
    const disclosure = document.createElement("p"); disclosure.className = "fixture-disclosure status-note"; disclosure.textContent = fixtureNotice; content.append(disclosure);
  }
  AI_REFERENCE_GROUPS.forEach(([key, label]) => {
    const values = Array.isArray(result[key]) ? result[key] : []; if (!values.length) return;
    const section = document.createElement("section"); section.className = "secondary-panel ai-reference-group";
    const heading = document.createElement("h3"); heading.textContent = label; section.append(heading);
    values.forEach((item) => {
      const row = document.createElement("div"); row.className = "ai-reference-item";
      const itemText = typeof item === "string" ? item : presentStructuredValue(item, "待确认");
      const itemKey = typeof item === "string" ? item : JSON.stringify(item);
      const itemContent = document.createElement("div"); itemContent.className = "ai-reference-item-content";
      const itemLabel = document.createElement("strong"); itemLabel.textContent = "具体建议";
      const text = document.createElement("p"); text.textContent = itemText; itemContent.append(itemLabel, text);
      const prior = aiReferencePanel.decisions.find((decision) => decision.category === key && decision.item === itemKey);
      const select = document.createElement("select"); select.dataset.aiCategory = key; select.dataset.aiItem = itemKey;
      [["adopt", "采用"], ["modify", "修改"], ["ignore", "忽略"]].forEach(([value, title]) => { const option = document.createElement("option"); option.value = value; option.textContent = title; select.append(option); });
      select.value = prior?.decision || "ignore";
      select.addEventListener("change", rememberAIReferenceDraft);
      const rationale = document.createElement("input"); rationale.type = "text"; rationale.placeholder = "可填写原因（可选）"; rationale.dataset.aiRationaleFor = itemKey;
      rationale.value = prior?.rationale || ""; rationale.className = "ai-reference-item-explanation"; rationale.addEventListener("input", rememberAIReferenceDraft);
      const controls = document.createElement("div"); controls.className = "ai-reference-item-controls";
      const decisionLabel = document.createElement("label"); decisionLabel.textContent = "如何处理这条建议"; decisionLabel.append(select);
      controls.append(decisionLabel, rationale); row.append(itemContent, controls); section.append(row);
    }); content.append(section);
  });
  const actions = document.createElement("div"); actions.className = "handoff-actions";
  const apply = document.createElement("button"); apply.id = "ai-reference-apply"; apply.type = "button"; apply.className = "button button-primary"; apply.textContent = "应用到项目"; apply.addEventListener("click", () => void applyAIReference()); actions.append(apply); content.append(actions);
}
async function loadAIReference() {
  aiReferencePanel.project = state.currentProjectId; aiReferencePanel.result = null; aiReferencePanel.decisions = []; aiReferencePanel.referenceId = null;
  if (!aiReferencePanel.project) { renderAIReference(); return; }
  try {
    const stored = await api(`/api/projects/${encodeURIComponent(aiReferencePanel.project)}/ai-reference`);
    if (stored?.result && toAIReferenceViewModel(stored.result)) { aiReferencePanel.result = stored.result; aiReferencePanel.referenceId = stored.id; }
  } catch (_) { /* no reference yet */ }
  const recovered = await loadUnifiedDraft(aiReferencePanel.project, "ai_reference", "result").catch(() => null); const payload = preferredRecoveryPayload(recovered);
  if (payload?.result && !aiReferencePanel.result && toAIReferenceViewModel(payload.result)) aiReferencePanel.result = payload.result;
  if (payload?.decisions) aiReferencePanel.decisions = payload.decisions;
  renderAIReference();
}
async function generateAIReference() {
  if (aiReferencePanel.busy || !aiReferencePanel.project) return;
  aiReferencePanel.result = null; aiReferencePanel.referenceId = null; aiReferencePanel.decisions = [];
  renderAIReference();
  aiReferencePanel.busy = true; qs("#ai-reference-generate").disabled = true; qs("#ai-reference-message").textContent = "正在理解你的想法并整理参考建议…";
  try {
    aiReferencePanel.requestKey ||= `ai-reference-${aiReferencePanel.project}`;
    const response = await api(`/api/projects/${encodeURIComponent(aiReferencePanel.project)}/ai-reference`, {method:"POST", body:JSON.stringify({idempotency_key: aiReferencePanel.requestKey})});
    const result = toAIReferenceViewModel(response?.result);
    if (!result || !response?.id) throw Object.assign(new Error("invalid ai reference response"), {code: "MODEL_OUTPUT_SCHEMA_INVALID"});
    aiReferencePanel.referenceId = response.id; aiReferencePanel.result = response.result; aiReferencePanel.decisions = []; renderAIReference(); rememberAIReferenceDraft();
    qs("#ai-reference-message").textContent = "AI参考已生成，请阅读后选择要采用、修改或忽略的内容。";
  } catch (error) {
    aiReferencePanel.result = null; aiReferencePanel.referenceId = null; aiReferencePanel.decisions = [];
    qs("#ai-reference-message").textContent = humanizeErrorMessage(error, "AI参考生成失败，请稍后重试；没有创建资料来源。");
  }
  finally { aiReferencePanel.busy = false; qs("#ai-reference-generate").disabled = false; }
}
async function applyAIReference() {
  if (aiReferencePanel.busy || !aiReferencePanel.referenceId) return;
  const decisions = [...qsa("#ai-reference-content select")].map((select) => ({category: select.dataset.aiCategory, item: select.dataset.aiItem, decision: select.value, rationale: qs(`[data-ai-rationale-for="${CSS.escape(select.dataset.aiItem)}"]`)?.value.trim() || ""}));
  aiReferencePanel.decisions = decisions; rememberAIReferenceDraft(); qs("#ai-reference-message").textContent = "正在保存你的选择…";
  try { await api(`/api/projects/${encodeURIComponent(aiReferencePanel.project)}/ai-reference/apply`, {method:"POST", body:JSON.stringify({reference_id: aiReferencePanel.referenceId, decisions})}); qs("#ai-reference-message").textContent = "已保存为项目中的待验证参考，不会自动变成证据。"; }
  catch (_) { qs("#ai-reference-message").textContent = "保存选择失败，你当前的选择仍保留在本机恢复草稿中。"; }
}

// Only ephemeral per-project input here; this is not the cross-module draft system.
const competitorPanel = {project: null, opener: null, busy: false, revision: 0, drafts: new Map(), candidates: [], comparison: null, decisionDraft: null};
function competitorDecisionDraftPayload() {
  if (!competitorPanel.comparison) return null;
  const decisions = [...qs("#competitor-decisions").querySelectorAll("select")].map(select => ({
    candidate_id: select.dataset.candidateId,
    decision: select.value,
    rationale: qs(`[data-reason-for="${CSS.escape(select.dataset.candidateId)}"]`).value.trim(),
  }));
  return {comparison: competitorPanel.comparison, decisions};
}
function rememberCompetitorDecisionDraft() {
  if (!competitorPanel.project) return;
  const payload = competitorDecisionDraftPayload();
  if (!payload) return;
  competitorPanel.decisionDraft = payload;
  queueUnifiedDraft(competitorPanel.project, "competitor_decision", "result", payload, {delay: 500});
}
function rememberCompetitorInput() {
  if (!competitorPanel.project) return;
  const payload = Object.fromEntries(["name", "url", "description"].map(key => [key, qs(`#competitor-${key}`).value]));
  competitorPanel.drafts.set(competitorPanel.project, [payload.name, payload.url, payload.description]);
  queueUnifiedDraft(competitorPanel.project, "competitor_decision", "form", payload, {delay: 500});
}
function closeCompetitors() {
  rememberCompetitorInput();
  qs("#competitor-dialog").close();
  competitorPanel.opener?.focus();
}
function skipCompetitorComparison() {
  state.competitorSnapshotId = null;
  state.useCompetitorSnapshot = false;
  if (state.currentProjectId) {
    queueUnifiedDraft(state.currentProjectId, "ui_context", "main", {
      activeView: state.activeView,
      evidenceTab: state.evidenceTab,
      docType: state.documentWorkspace.docType,
      useCompetitorSnapshot: false,
      competitorSnapshotId: null,
    }, {delay: 0});
  }
  closeCompetitors();
  toast("本次生成不使用竞品比较；你仍可继续完善方案。");
}
async function openCompetitors() {
  if (!state.currentProjectId) { toast("请先创建或打开一个项目。"); return; }
  rememberCompetitorInput();
  competitorPanel.project = state.currentProjectId;
  competitorPanel.opener = document.activeElement;
  const recovered = await loadUnifiedDraft(competitorPanel.project, "competitor_decision", "form").catch(() => null);
  const payload = preferredRecoveryPayload(recovered);
  const draft = payload ? [payload.name || "", payload.url || "", payload.description || ""] : (competitorPanel.drafts.get(competitorPanel.project) || ["", "", ""]);
  ["name", "url", "description"].forEach((key, i) => { qs(`#competitor-${key}`).value = draft[i]; });
  qs("#competitor-dialog").showModal();
  await loadCompetitors();
  const recoveredResult = await loadUnifiedDraft(competitorPanel.project, "competitor_decision", "result").catch(() => null);
  const resultPayload = preferredRecoveryPayload(recoveredResult);
  if (resultPayload?.comparison) {
    renderCompetitorComparison(resultPayload.comparison, resultPayload.decisions || []);
    qs("#competitor-message").textContent = "已恢复上次未完成的比较参考，请继续确认你的决定。";
  }
}
async function loadCompetitors() {
  const project = competitorPanel.project, revision = ++competitorPanel.revision;
  competitorPanel.comparison = null;
  qs("#competitor-comparison").hidden = true;
  qs("#competitor-comparison-content").replaceChildren();
  qs("#competitor-decisions").replaceChildren();
  qs("#competitor-message").textContent = "正在读取候选产品…";
  qs("#competitor-list").replaceChildren();
  try {
    const result = await api(`/api/projects/${encodeURIComponent(project)}/competitors`);
    if (revision !== competitorPanel.revision) return;
    qs("#competitor-message").textContent = result.candidates.length ? "候选只是参考，加入比较不等于事实已经核实。" : "还没有候选产品，可以添加，也可以直接继续。";
    competitorPanel.candidates = result.candidates;
    qs("#competitor-compare").hidden = !result.candidates.some(candidate => candidate.selected);
    const list = qs("#competitor-list");
    result.candidates.forEach(candidate => {
      const card = document.createElement("article");
      card.className = "secondary-panel";
      card.dataset.candidate = candidate.id;
      card.innerHTML = `<h3>${escapeHtml(candidate.name)}</h3><p>用户提供，尚未核实 · ${candidate.selected ? "已加入" : "候选产品"}</p><p>${escapeHtml(candidate.description || "暂未确认")}</p><p>${escapeHtml(candidate.url || "未提供网址")}</p>`;
      const details = document.createElement("p"); details.hidden = true;
      details.textContent = "目标用户、主要流程、可以借鉴和不适合照搬之处：暂未确认。此处仅展示用户输入，不是已完成的 AI 比较。";
      const view = document.createElement("button"); view.type = "button"; view.className = "button button-secondary"; view.textContent = "查看";
      view.setAttribute("aria-expanded", "false");
      view.onclick = () => { details.hidden = !details.hidden; view.setAttribute("aria-expanded", String(!details.hidden)); };
      const select = document.createElement("button"); select.type = "button"; select.className = "button button-secondary";
      select.textContent = candidate.selected ? "移出本次比较" : "加入本次比较";
      select.onclick = () => mutateCompetitors(`/api/projects/${encodeURIComponent(project)}/competitors/${encodeURIComponent(candidate.id)}/selection`, {method:"PUT", body:JSON.stringify({selected:!candidate.selected})});
      const remove = document.createElement("button"); remove.type = "button"; remove.className = "button button-quiet"; remove.textContent = "移除候选";
      remove.onclick = () => mutateCompetitors(`/api/projects/${encodeURIComponent(project)}/competitors/${encodeURIComponent(candidate.id)}`, {method:"DELETE"});
      card.append(view, select, remove, details); list.append(card);
    });
  } catch(error) {
    if (revision === competitorPanel.revision) qs("#competitor-message").textContent = "候选产品读取失败，请关闭后重新打开。你的输入仍保留在当前页面。";
  }
}
function renderCompetitorComparison(comparison, savedDecisions = []) {
  competitorPanel.comparison = comparison;
  competitorPanel.decisionDraft = {comparison, decisions: savedDecisions};
  const panel = qs("#competitor-comparison");
  const content = qs("#competitor-comparison-content");
  const decisions = qs("#competitor-decisions");
  panel.hidden = false;
  content.replaceChildren();
  decisions.replaceChildren();
  const result = comparison.comparison || {};
  (result.competitors || []).forEach(item => {
    const card = document.createElement("article");
    card.className = "secondary-panel";
    const title = document.createElement("h4"); title.textContent = item.name || "候选产品"; card.append(title);
    [["目标用户", item.target_users], ["解决的问题", item.core_problem], ["主要流程", item.main_flow], ["核心输出", item.main_output], ["使用门槛", item.adoption_barrier], ["可以借鉴", item.strengths_to_learn], ["不适合照搬", item.things_not_to_copy], ["对当前项目的影响", item.impact_on_current_project], ["待确认", item.uncertainties]].forEach(([label, value]) => {
      const row = document.createElement("p"); row.textContent = `${label}：${value || "暂未确认"}`; card.append(row);
    });
    content.append(card);
    const candidateId = item.candidate_id || (comparison.candidate_ids || [])[0];
    const field = document.createElement("label"); field.textContent = `${item.name || "候选产品"}的决定`;
    const select = document.createElement("select"); select.dataset.candidateId = candidateId;
    [["adopt", "加入我的方案"], ["avoid", "这版先不做"], ["defer", "以后再考虑"]].forEach(([value, label]) => { const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option); });
    const saved = savedDecisions.find(decision => decision.candidate_id === candidateId);
    if (saved?.decision) select.value = saved.decision;
    const reason = document.createElement("input"); reason.type = "text"; reason.placeholder = "原因（可选）"; reason.dataset.reasonFor = candidateId;
    if (saved?.rationale) reason.value = saved.rationale;
    select.addEventListener("change", rememberCompetitorDecisionDraft);
    reason.addEventListener("input", rememberCompetitorDecisionDraft);
    field.append(select, reason); decisions.append(field);
  });
}
async function compareCompetitors() {
  if (competitorPanel.busy) return;
  const selected = competitorPanel.candidates.filter(candidate => candidate.selected).map(candidate => candidate.id);
  if (!selected.length) { qs("#competitor-message").textContent = "请先加入至少一个候选产品。"; return; }
  competitorPanel.busy = true; renderCompetitorBusy(); qs("#competitor-message").textContent = "正在生成比较参考…";
  try {
    const result = await api(`/api/projects/${encodeURIComponent(competitorPanel.project)}/competitor-comparisons`, {method:"POST", body:JSON.stringify({candidate_ids:selected})});
    renderCompetitorComparison(result);
    rememberCompetitorDecisionDraft();
    qs("#competitor-message").textContent = "比较参考已生成，请先阅读并做出你的决定。";
  } catch(error) { qs("#competitor-message").textContent = "比较参考生成失败，请稍后重试。"; }
  finally { competitorPanel.busy = false; renderCompetitorBusy(); }
}
async function saveCompetitorSnapshot() {
  if (competitorPanel.busy || !competitorPanel.comparison) return;
  const decisions = [...qs("#competitor-decisions").querySelectorAll("select")].map(select => ({candidate_id: select.dataset.candidateId, decision: select.value, rationale: qs(`[data-reason-for="${CSS.escape(select.dataset.candidateId)}"]`).value.trim()}));
  competitorPanel.busy = true; renderCompetitorBusy(); qs("#competitor-message").textContent = "正在保存你的决策…";
  try {
    const snapshot = await api(`/api/projects/${encodeURIComponent(competitorPanel.project)}/competitor-snapshots`, {method:"POST", body:JSON.stringify({comparison_id:competitorPanel.comparison.id, decisions})});
    state.competitorSnapshotId = snapshot.id || snapshot.decision_snapshot?.id || null;
    state.useCompetitorSnapshot = Boolean(state.competitorSnapshotId);
    queueUnifiedDraft(competitorPanel.project, "ui_context", "main", {
      activeView: state.activeView,
      evidenceTab: state.evidenceTab,
      docType: state.documentWorkspace.docType,
      useCompetitorSnapshot: state.useCompetitorSnapshot,
      competitorSnapshotId: state.competitorSnapshotId,
    }, {delay: 0});
    qs("#competitor-message").textContent = "本次比较已保存，可继续完善方案。";
  }
  catch(error) { qs("#competitor-message").textContent = "保存决策失败，当前页面内容仍保留。"; }
  finally { competitorPanel.busy = false; renderCompetitorBusy(); }
}
function renderCompetitorBusy() {
  qsa("#competitor-form input, #competitor-form textarea, #competitor-form button, #competitor-list button, #competitor-compare, #competitor-save-snapshot, #competitor-decisions select, #competitor-decisions input")
    .forEach(control => { control.disabled = competitorPanel.busy; });
}
async function mutateCompetitors(path, options, adding = false) {
  if (competitorPanel.busy) return;
  if (competitorPanel.project !== state.currentProjectId) { closeCompetitors(); toast("项目已切换，请重新打开候选产品。"); return; }
  competitorPanel.busy = true;
  const project = competitorPanel.project;
  renderCompetitorBusy();
  qs("#competitor-message").textContent = "正在保存…";
  try {
    await api(path, options);
    if (adding) { competitorPanel.drafts.delete(project); clearRecoveryCopy(project, "competitor_decision", "form"); }
    if (competitorPanel.project === project) {
      if (adding) { qs("#competitor-form").reset(); rememberCompetitorInput(); }
      await loadCompetitors();
    }
  } catch(error) {
    if (competitorPanel.project === project) qs("#competitor-message").textContent = "保存未完成，你的输入仍保留在当前页面。请稍后重试。";
  } finally {
    competitorPanel.busy = false;
    renderCompetitorBusy();
  }
}
function wireEvents() {
  qs("#m1-intent-form")?.addEventListener("submit", saveProjectIntent);
  qs("#m1-action-form")?.addEventListener("submit", saveFirstAction);
  qs("#m1-action-confirm")?.addEventListener("click", () => void confirmFirstAction());
  qs("#m2-build-slice-form")?.addEventListener("submit", saveBuildSlice);
  qs("#m2-build-slice-confirm")?.addEventListener("click", () => void confirmBuildSlice());
  qs("#ai-reference-generate")?.addEventListener("click", () => void generateAIReference());
  qs("#evidence-coach-open")?.addEventListener("click", () => selectEvidenceEntry("action_guidance"));
  qs("#competitor-open")?.addEventListener("click", openCompetitors);
  qs("#competitor-close")?.addEventListener("click", closeCompetitors);
  qs("#competitor-skip")?.addEventListener("click", skipCompetitorComparison);
  qs("#competitor-dialog")?.addEventListener("cancel", event => { event.preventDefault(); closeCompetitors(); });
  qs("#competitor-form")?.addEventListener("submit", event => {
    event.preventDefault();
    const body = Object.fromEntries(["name", "url", "description"].map(key => [key, qs(`#competitor-${key}`).value.trim()]));
    void mutateCompetitors(`/api/projects/${encodeURIComponent(competitorPanel.project)}/competitors`, {method:"POST", body:JSON.stringify(body)}, true);
  });
  ["name", "url", "description"].forEach(key => qs(`#competitor-${key}`)?.addEventListener("input", rememberCompetitorInput));
  qs("#competitor-compare")?.addEventListener("click", () => void compareCompetitors());
  qs("#competitor-save-snapshot")?.addEventListener("click", () => void saveCompetitorSnapshot());
  qs("#generation-progress-open")?.addEventListener("click", showGenerationProgress);
  qs("#generation-progress-close")?.addEventListener("click", closeGenerationProgress);
  qs("#generation-progress-retry")?.addEventListener("click", () => void retryFailedGeneration());
  qs("#generation-progress-dialog")?.addEventListener("cancel", (event) => { event.preventDefault(); closeGenerationProgress(); });
  qs("#generation-stop")?.addEventListener("click", cancelActiveGeneration);
  qs("#beta-feedback-button")?.addEventListener("click", () => qs("#beta-feedback-dialog")?.showModal());
  qs("#beta-feedback-cancel")?.addEventListener("click", () => qs("#beta-feedback-dialog")?.close());
  qs("#beta-feedback-form")?.addEventListener("submit", submitBetaFeedback);
  qs("#home-button").addEventListener("click", (event) => { event.preventDefault(); showQuickStart(); });
  qs("#quick-start-form").addEventListener("submit", quickStart);
  ["idea", "target-user", "priority", "resources"].forEach(key => qs(`#quick-start-${key}`)?.addEventListener("input", () => {
    queueUnifiedDraft(null, "idea", "main", {
      idea: qs("#quick-start-idea")?.value || "",
      target_user: qs("#quick-start-target-user")?.value || "",
      priority: qs("#quick-start-priority")?.value || "",
      resources: qs("#quick-start-resources")?.value || "",
    }, {delay: 500});
  }));
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
  qsa(".nav-item").forEach((button) => button.addEventListener("click", () => activateView(button.dataset.view, {recordHistory: true})));
  window.addEventListener("popstate", event => {
    const view = event.state?.projectId === state.currentProjectId ? event.state.view : null;
    if (view && WORKSPACE_VIEWS.has(view)) activateView(view);
  });
  qsa("[data-evidence-tab]").forEach((button) => button.addEventListener("click", () => setEvidenceTab(button.dataset.evidenceTab)));
  qs("#add-evidence-form")?.addEventListener("submit", addEvidence);
  qs("#guided-evidence-form")?.addEventListener("submit", addGuidedEvidence);
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
  recoverNewIdeaDraft();
}

const recoveryTestHooks = window.__INSIGHTFORGE_TEST__ ? {
  __test: {
    beginLoading,
    showRecoveryPayload,
    showGenerationProgress,
    closeGenerationProgress,
    retryFailedGeneration,
    renderGenerationProgress,
    cancelActiveGeneration,
    state,
    quickStart,
    confirmIdeaBrief,
    openIdeaBriefReview,
    renderIdeaBrief,
    renderAIReference,
    generateAIReference,
    setTestAIReference(result, decisions = []) { aiReferencePanel.result = result; aiReferencePanel.decisions = decisions; aiReferencePanel.referenceId = "test-reference"; renderAIReference(); },
    setTestEvidenceGuidance(result) {
      state.evidenceEntry.mode = "action_guidance";
      evidenceGuidancePanel.busy = false;
      evidenceGuidancePanel.result = result;
      evidenceGuidancePanel.guidanceId = result ? "test-guidance" : null;
      renderEvidenceGuidance();
    },
    renderSolutions,
    renderDocuments,
    renderHandoff,
    activateView,
    setEvidenceTab,
    renderGuidanceCard,
    openSolutionDetails,
    generateSolutions,
    restoreGenerationReference,
    isRecoveryPayload,
    renderRuntimeDisclosure,
    loadDocumentWorkspace,
    renderDocumentWorkspace,
    renderEvidenceEntryGuidance,
    renderEvidenceGuidance,
    loadEvidenceGuidance,
    generateEvidenceGuidance,
    generateDocument,
    pollSolutionGeneration,
    selectEvidenceEntry,
    addGuidedEvidence,
    createGuidanceNavigator,
    parseGuidanceAction,
    renderImpactHistory,
    reconfirmSnapshotHealth,
    loadUnifiedDraft,
    preferredRecoveryPayload,
    queueUnifiedDraft,
    setAccountContext,
    readRecoveryCopy,
    writeRecoveryCopy,
    clearRecoveryCopy,
    draftStorageKey,
    draftContext,
  },
} : {};
window.InsightForgeUi = {api, escapeHtml, reportError, toast, secureSettingsExit, applyGuidanceAction, setAccountContext, ...recoveryTestHooks};

async function bootstrap() {
  wireEvents();
  try {
    await ensureBetaConsent();
    const health = await api("/api/health");
    state.runtimeMode = health.structured_runtime_mode || health.runtime_mode || health.llm_mode || null;
    const mode = await api("/api/settings/mode");
    state.managedModelMode = Boolean(mode.managed_beta_mode);
    await loadUsagePolicy();
    renderRuntimeDisclosure();
    await Promise.all([loadProjects(), loadExamples(), loadHistory(), loadHomeNextAction()]);
    showQuickStart();
    renderEvidence();
    renderDocuments();
    renderHandoff();
    void restoreGenerationReference();
  } catch (error) { reportError(error); }
}

document.addEventListener("DOMContentLoaded", bootstrap);

async function loadUsagePolicy() {
  const element = qs("#usage-policy");
  // Policy is server-owned and deliberately never persisted in browser storage.
  state.usagePolicy = null;
  try {
    const policy = await api("/api/usage/policy");
    if (typeof policy.daily_user_limits_enabled !== "boolean") throw new Error("Invalid usage policy");
    state.usagePolicy = policy;
    if (element) {
      element.textContent = policy.daily_user_limits_enabled
        ? "当前按操作分别执行每日次数限制；以提交时的服务端检查为准。"
        : "方案生成与资料分析不设每日次数限制；仍记录使用情况，并保留排队、超时和重复提交保护。";
      element.hidden = false;
    }
  } catch (_) {
    if (element) {
      element.textContent = "暂时无法读取使用政策；操作是否可用以服务端实际响应为准。";
      element.hidden = false;
    }
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") void loadUsagePolicy();
});
