"use strict";

const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const vm = require("node:vm");

const fixtures = JSON.parse(fs.readFileSync("tests/fixtures/stage_b_generation_ux_cases.json", "utf8"));
const styles = fs.readFileSync("app/static/styles.css", "utf8");
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
    this.parentElement = null;
    this._layout = {width: 0, height: 0, clientWidth: 0, scrollWidth: 0, clientHeight: 0, scrollHeight: 0};
  }
  get innerHTML() { return this._innerHTML || this.children.map((child) => child.outerHTML || child.textContent).join(""); }
  set innerHTML(value) { this._innerHTML = String(value ?? ""); this._textContent = ""; this.children = []; }
  get textContent() { return this._innerHTML ? stripTags(this._innerHTML) : (this._textContent || this.children.map((child) => child.textContent).join("")); }
  set textContent(value) { this._innerHTML = ""; this._textContent = String(value ?? ""); this.children = []; }
  get innerText() { return this.textContent; }
  append(...nodes) { this._innerHTML = ""; nodes.forEach((node) => { if (node && typeof node === "object") { node.parentElement = this; this.children.push(node); } }); }
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
  setLayout(layout) { this._layout = {...this._layout, ...layout}; }
  getBoundingClientRect() { return {left: 0, top: 0, right: this._layout.width, bottom: this._layout.height, width: this._layout.width, height: this._layout.height}; }
  get clientWidth() { return this._layout.clientWidth || this._layout.width; }
  get scrollWidth() { return this._layout.scrollWidth || this.clientWidth; }
  get clientHeight() { return this._layout.clientHeight || this._layout.height; }
  get scrollHeight() { return this._layout.scrollHeight || this.clientHeight; }
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
function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) { return values.has(String(key)) ? values.get(String(key)) : null; },
    setItem(key, value) { values.set(String(key), String(value)); },
    removeItem(key) { values.delete(String(key)); },
    clear() { values.clear(); },
  };
}
global.localStorage = memoryStorage();
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

function parseCssRules(source) {
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = [];

  function matchingBrace(text, open) {
    let depth = 1;
    for (let index = open + 1; index < text.length; index += 1) {
      if (text[index] === "{") depth += 1;
      if (text[index] === "}") depth -= 1;
      if (!depth) return index;
    }
    throw new Error("unbalanced CSS fixture");
  }

  function declarations(block) {
    const result = {};
    for (const part of block.split(";")) {
      const separator = part.indexOf(":");
      if (separator < 0) continue;
      const property = part.slice(0, separator).trim();
      const value = part.slice(separator + 1).trim();
      if (property && value) result[property] = value;
    }
    return result;
  }

  function visit(start, end, media = {}) {
    let cursor = start;
    while (cursor < end) {
      const open = clean.indexOf("{", cursor);
      if (open < 0 || open >= end) break;
      const prelude = clean.slice(cursor, open).trim();
      const close = matchingBrace(clean, open);
      if (prelude.startsWith("@media")) {
        const max = prelude.match(/max-width\s*:\s*(\d+)px/);
        const min = prelude.match(/min-width\s*:\s*(\d+)px/);
        visit(open + 1, close, {max: max ? Number(max[1]) : null, min: min ? Number(min[1]) : null});
      } else if (!prelude.startsWith("@")) {
        for (const selector of prelude.split(",").map((item) => item.trim()).filter(Boolean)) {
          rules.push({selector, media, declarations: declarations(clean.slice(open + 1, close))});
        }
      }
      cursor = close + 1;
    }
  }

  visit(0, clean.length);
  return rules;
}

const cssRules = parseCssRules(styles);
function cssValue(selector, property, cssWidth, rules = cssRules) {
  let value = null;
  for (const rule of rules) {
    if (rule.selector !== selector) continue;
    if (rule.media.max !== null && cssWidth > rule.media.max) continue;
    if (rule.media.min !== null && cssWidth < rule.media.min) continue;
    if (rule.declarations[property] !== undefined) value = rule.declarations[property];
  }
  return value;
}

function gridColumnCount(template) {
  if (!template) return 1;
  const repeat = template.match(/^repeat\((\d+),/);
  if (repeat) return Number(repeat[1]);
  return template.startsWith("1fr") ? 1 : 2;
}

function splitCssTokens(value) {
  const tokens = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < String(value || "").length; index += 1) {
    const character = String(value)[index];
    if (character === "(") depth += 1;
    if (character === ")") depth -= 1;
    if (/\s/.test(character) && depth === 0) {
      if (index > start) tokens.push(String(value).slice(start, index));
      start = index + 1;
    }
  }
  if (start < String(value || "").length) tokens.push(String(value).slice(start));
  return tokens.filter(Boolean);
}

function gridTrackDefinitions(template) {
  if (!template) return ["1fr"];
  const repeat = String(template).match(/^repeat\((\d+),\s*(.+)\)$/);
  if (repeat) return Array.from({length: Number(repeat[1])}, () => repeat[2].trim());
  return splitCssTokens(template);
}

function gridTrack(track) {
  const minmax = String(track).match(/^minmax\(\s*(\d+(?:\.\d+)?)(?:px)?\s*,\s*(\d+(?:\.\d+)?)fr\s*\)$/);
  if (minmax) return {min: Number(minmax[1]), fr: Number(minmax[2])};
  const fraction = String(track).match(/^(\d+(?:\.\d+)?)fr$/);
  if (fraction) return {min: 0, fr: Number(fraction[1])};
  const pixels = String(track).match(/^(\d+(?:\.\d+)?)px$/);
  if (pixels) return {min: Number(pixels[1]), fixed: Number(pixels[1]), fr: 0};
  return {min: 0, fr: 1};
}

function gridTrackWidths(template, containerWidth, gap = 0) {
  const tracks = gridTrackDefinitions(template).map(gridTrack);
  const available = Math.max(0, containerWidth - Math.max(0, tracks.length - 1) * gap);
  const minimum = tracks.reduce((sum, track) => sum + track.min, 0);
  const free = Math.max(0, available - minimum);
  const totalFr = tracks.reduce((sum, track) => sum + (track.fixed === undefined ? track.fr : 0), 0);
  return tracks.map((track) => track.fixed === undefined
    ? track.min + (totalFr ? free * track.fr / totalFr : 0)
    : track.fixed);
}

function cssPixels(value, fallback = 0) {
  const match = String(value || "").match(/^(\d+(?:\.\d+)?)px$/);
  return match ? Number(match[1]) : fallback;
}

function measuredBox(className, width, {intrinsicWidth = width, overflowX = "hidden", height = 80, label} = {}) {
  const node = new Element("div");
  node.classList.add(...className.split(" ").filter(Boolean));
  const scrollWidth = Math.max(width, intrinsicWidth);
  const state = scrollWidth <= width ? "contained" : overflowX === "auto" ? "scrollable" : "overflowing";
  node.dataset.layoutState = state;
  node.dataset.readability = state === "overflowing" ? "clipped" : "readable";
  node.dataset.layoutLabel = label || className;
  node.setLayout({width, height, clientWidth: width, scrollWidth, clientHeight: height, scrollHeight: height});
  return node;
}

function measureResponsiveFixture(fixture, styleSource = styles) {
  const rules = styleSource === styles ? cssRules : parseCssRules(styleSource);
  const value = (selector, property) => cssValue(selector, property, fixture.cssWidth, rules);
  const width = Math.min(1180, fixture.cssWidth);
  const gap = cssPixels(value(".solution-grid", "gap"), 14);
  const surface = (className, options = {}) => measuredBox(className, width, {...options, label: options.label || className});
  const solutionColumns = gridColumnCount(value(".solution-grid", "grid-template-columns"));
  const solutionGrid = surface("solution-grid", {intrinsicWidth: solutionColumns * 240 + (solutionColumns - 1) * gap, height: 260, label: "solution cards"});
  for (let index = 0; index < solutionColumns; index += 1) {
    solutionGrid.append(measuredBox("solution-card", (width - (solutionColumns - 1) * gap) / solutionColumns, {intrinsicWidth: 220, height: 220, label: `solution card ${index + 1}`}));
  }

  const referenceItem = surface("ai-reference-item", {height: 220, label: "AI reference"});
  const controlTemplate = value(".ai-reference-item-controls", "grid-template-columns");
  const controlGap = cssPixels(value(".ai-reference-item-controls", "gap"), 10);
  const controlWidths = gridTrackWidths(controlTemplate, width, controlGap);
  const controlColumns = controlWidths.length;
  const controlMinWidths = [
    cssPixels(value(".ai-reference-item-controls select", "min-width")),
    cssPixels(value(".ai-reference-item-explanation", "min-width")),
  ];
  const measuredControlWidths = controlWidths.map((trackWidth, index) => Math.max(trackWidth, controlMinWidths[index] || 0));
  const controls = measuredBox("ai-reference-item-controls", width, {
    intrinsicWidth: measuredControlWidths.reduce((sum, childWidth) => sum + childWidth, 0) + Math.max(0, controlColumns - 1) * controlGap,
    height: 64,
    label: "AI reference controls",
  });
  for (let index = 0; index < controlColumns; index += 1) {
    controls.append(measuredBox(index === 0 ? "ai-reference-decision" : "ai-reference-explanation", measuredControlWidths[index], {
      intrinsicWidth: Math.max(index === 0 ? 180 : 220, controlMinWidths[index] || 0),
      height: 48,
      label: `AI reference control ${index + 1}`,
    }));
  }
  referenceItem.append(measuredBox("ai-reference-item-content", width, {intrinsicWidth: 180, height: 100, label: "AI reference content"}), controls);

  const actionCard = surface("evidence-coach-card", {intrinsicWidth: width, height: 360, label: "Action Cards"});
  actionCard.append(measuredBox("evidence-coach-block", width, {intrinsicWidth: 320, height: 80, label: "Action Card body"}));

  const progressWrap = value(".generation-progress-actions", "flex-wrap");
  const progress = surface("generation-progress-actions", {intrinsicWidth: progressWrap === "wrap" ? width : 600, height: 64, label: "generation progress"});
  progress.append(measuredBox("generation-progress-action", 180, {height: 40, label: "generation progress action"}));

  const documentTemplate = value(".document-editor-grid", "grid-template-columns");
  const documentColumns = gridColumnCount(documentTemplate);
  const documentGrid = surface("document-editor-grid", {height: 520, label: "PRD and TechDoc"});
  const documentWidths = documentColumns === 1
    ? [width]
    : fixture.cssWidth <= 1199
      ? [width - gap - 240, 240]
      : [width - gap - width * 0.35 / 1.35, width * 0.35 / 1.35];
  documentWidths.forEach((columnWidth, index) => documentGrid.append(measuredBox(index === 0 ? "document-editor-main" : "document-version-panel", columnWidth, {intrinsicWidth: index === 0 ? 360 : 220, height: 500, label: index === 0 ? "PRD/TechDoc editor" : "document versions"})));

  const handoff = surface("handoff-section", {intrinsicWidth: width, height: 180, label: "Handoff"});
  const handoffActionsWrap = value(".handoff-actions", "flex-wrap");
  handoff.append(measuredBox("handoff-actions", width, {intrinsicWidth: handoffActionsWrap === "wrap" ? width : 620, height: 56, label: "Handoff actions"}));
  return {width, surfaces: [solutionGrid, referenceItem, actionCard, progress, documentGrid, handoff]};
}

function assertMeasuredSurface(surface) {
  const rect = surface.getBoundingClientRect();
  assert.ok(rect.width > 0 && rect.height > 0, `${surface.dataset.layoutLabel} has measured geometry`);
  assert.ok(surface.clientWidth > 0, `${surface.dataset.layoutLabel} has a usable container width`);
  assert.ok(surface.scrollWidth <= surface.clientWidth, `${surface.dataset.layoutLabel} has no horizontal overflow`);
  assert.equal(surface.dataset.readability, "readable", `${surface.dataset.layoutLabel} remains readable`);
  for (const child of surface.children) {
    assert.ok(child.getBoundingClientRect().width > 0, `${child.dataset.layoutLabel} has measured width`);
    assert.ok(child.scrollWidth <= child.clientWidth, `${child.dataset.layoutLabel} is not clipped`);
  }
}

async function main() {
  await runCase("zoom-equivalent desktop fixture keeps AI reference controls readable", () => {
    const desktopFixtures = [
      {viewport: 1366, zoom: 1, cssWidth: 1366},
      {viewport: 1440, zoom: 1, cssWidth: 1440},
      {viewport: 1366, zoom: 1.25, cssWidth: 1093},
      {viewport: 1440, zoom: 1.5, cssWidth: 960},
    ];
    for (const fixture of desktopFixtures) {
      const measured = measureResponsiveFixture(fixture);
      assert.equal(cssValue(".ai-reference-item-controls", "grid-template-columns", fixture.cssWidth), fixture.cssWidth <= 1199 ? "1fr" : "minmax(180px, .35fr) minmax(220px, 1fr)", `${fixture.viewport}px at ${fixture.zoom * 100}% uses the expected control layout`);
      const reference = measured.surfaces.find((surface) => surface.dataset.layoutLabel === "AI reference");
      assertMeasuredSurface(reference);
      assert.equal(reference.children[1].children.length, fixture.cssWidth <= 1199 ? 1 : 2, `${fixture.viewport}px at ${fixture.zoom * 100}% renders measured AI reference controls in readable columns`);
    }
  });

  await runCase("responsive AI surfaces report measured containment and readability", () => {
    const fixturesToMeasure = [
      {viewport: 1366, zoom: 1, cssWidth: 1366},
      {viewport: 1440, zoom: 1, cssWidth: 1440},
      {viewport: 1366, zoom: 1.25, cssWidth: 1093},
      {viewport: 1440, zoom: 1.5, cssWidth: 960},
    ];
    for (const fixture of fixturesToMeasure) {
      const measured = measureResponsiveFixture(fixture);
      for (const surface of measured.surfaces) assertMeasuredSurface(surface);
      const solutionGrid = measured.surfaces.find((surface) => surface.dataset.layoutLabel === "solution cards");
      const documentGrid = measured.surfaces.find((surface) => surface.dataset.layoutLabel === "PRD and TechDoc");
      assert.equal(solutionGrid.children.length, fixture.cssWidth <= 760 ? 1 : fixture.cssWidth <= 1199 ? 2 : 3, `${fixture.viewport}px at ${fixture.zoom * 100}% measures the expected solution-card columns`);
      assert.equal(documentGrid.children.length, fixture.cssWidth <= 760 ? 1 : 2, `${fixture.viewport}px at ${fixture.zoom * 100}% measures the expected document columns`);
      assert.equal(cssValue(".generation-progress-actions", "flex-wrap", fixture.cssWidth), "wrap", `${fixture.viewport}px at ${fixture.zoom * 100}% keeps generation actions explicitly wrap-safe`);
      assert.equal(cssValue(".handoff-actions", "flex-wrap", fixture.cssWidth), "wrap", `${fixture.viewport}px at ${fixture.zoom * 100}% keeps Handoff actions explicitly wrap-safe`);
    }
  });

  await runCase("in-memory min-width mutation is rejected by measured geometry", () => {
    const mutatedStyles = styles.replace(
      ".ai-reference-item-controls select, .ai-reference-item-explanation { width: 100%; min-width: 0; }",
      ".ai-reference-item-controls select, .ai-reference-item-explanation { width: 100%; min-width: 1000px; }",
    );
    assert.notEqual(mutatedStyles, styles, "the regression mutation must change the in-memory stylesheet");
    const measured = measureResponsiveFixture({viewport: 1440, zoom: 1, cssWidth: 1440}, mutatedStyles);
    const reference = measured.surfaces.find((surface) => surface.dataset.layoutLabel === "AI reference");
    assert.throws(
      () => assertMeasuredSurface(reference),
      /horizontal overflow|not clipped/,
      "the geometry harness must reject the widened AI reference control",
    );
  });

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

  await runCase("incomplete Action Cards fail closed without placeholder success", () => {
    for (const field of ["who_or_where", "action_steps", "acceptable_artifacts", "fill_template"]) {
      const incomplete = JSON.parse(JSON.stringify(fixtures.action_card_complete));
      incomplete.cards[0][field] = [];
      hooks.setTestEvidenceGuidance(incomplete);
      assert.equal(getElement("#evidence-guidance-content").children.length, 0, `${field} must not render an Action Card`);
      assert.match(getElement("#evidence-guidance-message").innerText, /没有生成可用的资料行动建议/);
      assert.doesNotMatch(getElement("#evidence-guidance-content").innerText, /可按实际情况补充问题/);
    }
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

  await runCase("AI reference provider, parse, schema, and empty failures recover without stale content", async () => {
    const failureCases = [
      {
        name: "provider",
        response: jsonResponse({error_code: "PROVIDER_FAILURE", message: "Traceback: hidden-provider-wrapper", recovery_actions: ["retry_generation"]}, 503),
        safe: /AI服务暂时无法完成请求|请稍后重试/,
      },
      {
        name: "parse",
        response: {ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => { throw new SyntaxError("Unexpected token hidden-provider-wrapper"); }},
        safe: /没有生成可用内容|请稍后重试/,
      },
      {
        name: "schema",
        response: jsonResponse({id: "bad-schema", result: {possible_target_users: []}}, 200),
        safe: /方案结构不完整|没有生成可用内容|请稍后重试/,
      },
      {
        name: "empty",
        response: jsonResponse({id: "empty-result", result: {possible_target_users: [], possible_scenarios: [], possible_user_problems: [], missing_information: [], mvp_thoughts: [], questions_to_validate: [], research_directions: []}}, 200),
        safe: /方案结构不完整|没有生成可用内容|请稍后重试/,
      },
    ];
    for (const failureCase of failureCases) {
      global.localStorage.clear();
      hooks.state.currentProjectId = `surface-recovery-${failureCase.name}`;
      installSurfaceFetch({[`POST /api/projects/surface-recovery-${failureCase.name}/ai-reference`]: failureCase.response});
      await vm.runInThisContext("loadAIReference()", {filename: "app.js"});
      getElement("#ai-reference-generate").click();
      await flushSurfacePromises();
      const failureMessage = getElement("#ai-reference-message").innerText;
      assert.match(failureMessage, failureCase.safe, `${failureCase.name} exposes Chinese user-safe recovery copy`);
      assert.doesNotMatch(failureMessage, /Traceback|hidden-provider-wrapper|Unexpected token|MODEL_OUTPUT_SCHEMA_INVALID/, `${failureCase.name} does not leak raw failure details`);
      assert.equal(getElement("#ai-reference-content").children.length, 0, `${failureCase.name} does not leave stale AI content`);
      assert.equal(getElement("#loading-status").hidden, true, `${failureCase.name} clears loading after failure`);

      installSurfaceFetch({[`POST /api/projects/surface-recovery-${failureCase.name}/ai-reference`]: jsonResponse({id: `recovered-${failureCase.name}`, result: fixtures.ai_reference_complete}, 200)});
      getElement("#ai-reference-generate").click();
      await flushSurfacePromises();
      const recoveredBody = visibleBody("#ai-reference-content");
      assert.match(recoveredBody, /门店运营人员/);
      assert.equal((recoveredBody.match(/门店运营人员/g) || []).length, 1, `${failureCase.name} retries without duplicate append`);
      assert.equal(getElement("#loading-status").hidden, true, `${failureCase.name} clears loading after success`);
    }
  });

  await runCase("AI reference retry clears seeded stale content and error during GENERATING", async () => {
    global.localStorage.clear();
    hooks.state.currentProjectId = "surface-ai-reference-retry";
    installSurfaceFetch({"/api/projects/surface-ai-reference-retry/ai-reference": jsonResponse({}, 200)});
    await vm.runInThisContext("loadAIReference()", {filename: "app.js"});
    hooks.setTestAIReference(fixtures.ai_reference_complete);
    getElement("#ai-reference-message").textContent = "上一次生成失败：旧错误提示";
    assert.ok(getElement("#ai-reference-content").children.length > 0, "retry fixture must visibly seed a prior AI reference");
    assert.match(getElement("#ai-reference-content").innerText, /门店运营人员/, "retry fixture must visibly seed stale reference text");
    assert.match(getElement("#ai-reference-message").innerText, /旧错误提示/, "retry fixture must visibly seed the prior error");

    const failedRetry = deferredResponse({error_code: "PROVIDER_FAILURE", message: "hidden-provider-wrapper"}, 503);
    installSurfaceFetch({"POST /api/projects/surface-ai-reference-retry/ai-reference": failedRetry});
    const failedAttempt = hooks.generateAIReference();
    await flushSurfacePromises();
    assert.equal(failedRetry.requested, true, "the stale-reference retry must issue a POST");
    assert.equal(hooks.state.currentProjectId, "surface-ai-reference-retry");
    assert.equal(getElement("#ai-reference-content").children.length, 0, "GENERATING clears the seeded stale reference before the response resolves");
    assert.doesNotMatch(getElement("#ai-reference-content").innerText, /门店运营人员|旧错误提示/);
    assert.match(getElement("#ai-reference-message").innerText, /正在理解你的想法/);
    failedRetry.resolve();
    await failedAttempt;
    await flushSurfacePromises();
    assert.equal(getElement("#ai-reference-content").children.length, 0, "failed retry leaves no stale AI reference content");
    assert.match(getElement("#ai-reference-message").innerText, /AI服务暂时无法完成请求|请稍后重试/);
    assert.doesNotMatch(getElement("#ai-reference-message").innerText, /hidden-provider-wrapper|旧错误提示/);

    const successfulRetry = deferredResponse({id: "recovered-reference", result: fixtures.ai_reference_complete}, 200);
    installSurfaceFetch({"POST /api/projects/surface-ai-reference-retry/ai-reference": successfulRetry});
    const successfulAttempt = hooks.generateAIReference();
    await flushSurfacePromises();
    assert.equal(successfulRetry.requested, true, "the explicit second retry must issue a new POST");
    assert.equal(getElement("#ai-reference-content").children.length, 0, "GENERATING keeps stale content cleared on the successful retry too");
    successfulRetry.resolve();
    await successfulAttempt;
    await flushSurfacePromises();
    const recoveredBody = visibleBody("#ai-reference-content");
    assert.equal((recoveredBody.match(/门店运营人员/g) || []).length, 1, "successful retry replaces stale content with exactly one result");
    assert.match(getElement("#ai-reference-message").innerText, /AI参考已生成/);
    assert.doesNotMatch(getElement("#ai-reference-message").innerText, /旧错误提示|AI服务暂时无法完成请求/);
  });

  await runCase("AI reference result and Action Card result reappear after refresh from local recovery", async () => {
    global.localStorage.clear();
    hooks.state.currentProjectId = "persisted-surface-project";
    installSurfaceFetch({
      "POST /api/projects/persisted-surface-project/ai-reference": jsonResponse({id: "persisted-reference", result: fixtures.ai_reference_complete}, 200),
      "POST /api/projects/persisted-surface-project/evidence-guidance": jsonResponse({id: "persisted-guidance", result: fixtures.action_card_complete}, 201),
    });
    await vm.runInThisContext("loadAIReference()", {filename: "app.js"});
    getElement("#ai-reference-generate").click();
    await flushSurfacePromises();
    hooks.state.evidenceEntry.mode = "action_guidance";
    await hooks.generateEvidenceGuidance();
    assert.ok(global.localStorage.getItem(hooks.draftStorageKey("persisted-surface-project", "ai_reference", "result")), "AI reference is persisted locally before refresh");
    assert.ok(global.localStorage.getItem(hooks.draftStorageKey("persisted-surface-project", "evidence_guidance", "result")), "Action Card result is persisted locally before refresh");

    installSurfaceFetch({
      "/api/projects/persisted-surface-project/ai-reference": jsonResponse({}, 200),
      "/api/projects/persisted-surface-project/evidence-guidance": jsonResponse({}, 200),
    });
    await vm.runInThisContext("loadAIReference()", {filename: "app.js"});
    assert.match(visibleBody("#ai-reference-content"), /门店运营人员/);
    await hooks.loadEvidenceGuidance();
    assert.match(visibleBody("#evidence-guidance-content"), /最近一次缺货处理经历/);
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
