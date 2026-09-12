"use strict";

// Behavior-only fake DOM. No browser/layout acceptance claim (R5 is separate).
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
class Element {
  constructor() { this.children = []; this.value = ""; this.dataset = {}; this.listeners = {}; this.hidden = false; this.classList = {add() {}, remove() {}, toggle() {}, contains() { return false; }}; }
  set innerHTML(value) { this.html = String(value); this.text = ""; this.children = []; }
  get innerHTML() { return this.html || this.textContent; }
  set textContent(value) { this.text = String(value); this.html = ""; this.children = []; }
  get textContent() { return this.html || this.text || this.children.map(c => c.textContent).join(" "); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.html = ""; this.text = ""; this.children = children; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  setAttribute(name, value) { this[name] = value; }
  removeAttribute(name) { delete this[name]; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  focus() {}
}
const elements = new Map();
const element = key => { if (!elements.has(key)) elements.set(key, new Element()); return elements.get(key); };
global.document = {body: new Element(), querySelector: element, querySelectorAll: () => [], getElementById: id => element(`#${id}`), createElement: () => new Element(), addEventListener() {}};
global.window = {__INSIGHTFORGE_TEST__: true, addEventListener() {}};
global.CSS = {escape: String};
const storage = new Map();
global.localStorage = {getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key)};
global.setTimeout = () => 0;
global.clearTimeout = () => {};
global.fetch = async () => { throw new Error("Unexpected external transport"); };
vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"), {filename: "app.js"});
const hooks = window.InsightForgeUi.__test;
const evaluate = code => vm.runInThisContext(code);
const fixtures = JSON.parse(fs.readFileSync("tests/fixtures/stage_b_generation_ux_cases.json", "utf8"));
const cases = JSON.parse(fs.readFileSync("tests/fixtures/whole_branch_value_cases.json", "utf8"));
cases.rejected.push(...Object.values(cases.rereview_rejected));
const clone = value => JSON.parse(JSON.stringify(value));
function adapter(name, value) { global.testValue = value; return evaluate(`${name}(global.testValue)`); }
function workspace(content, docType = "prd") {
  return {docType, versions: [{id: "doc-b", version: 1, doc_type: docType, content, status: "draft", validation_status: "not_run", artifact_health: {health_status: "current"}}], selectedVersionId: "doc-b", draft: null};
}
if (process.argv.includes("--document")) {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  hooks.state.snapshot = input.snapshot;
  hooks.state.documentWorkspace = workspace(input.content, input.docType);
  assert.ok(adapter("toDocumentWorkspaceViewModel", hooks.state.documentWorkspace), "generated document must satisfy actual frontend inherited snapshot adapter");
  hooks.renderDocumentWorkspace();
  assert.equal(element("#document-editor").value, input.content.trim());
  console.log("PASS generated document adapter and editor (validation status remains not_run)");
} else {
  let failed = 0, passed = 0;
  async function check(name, callback) {
    try { await callback(); passed++; console.log(`PASS ${name}`); }
    catch (error) { failed++; console.error(`FAIL ${name.replace(/\n/g, " / ")}: ${error.message.split("\n")[0]}`); }
  }
  async function main() {
    for (const [index, raw] of cases.rejected.entries()) {
      for (const [name, base, mutate] of [
        ["toAIReferenceViewModel", fixtures.ai_reference_complete, v => { v.possible_target_users = [raw]; }],
        ["toAIReferenceViewModel", fixtures.ai_reference_complete, v => { v.fixture_disclosure = raw; }],
        ["toAIReferenceViewModel", fixtures.ai_reference_complete, v => { v.uncertainty_notice = raw; }],
        ["toEvidenceGuidanceViewModel", fixtures.action_card_complete, v => { v.cards[0].title = raw; }],
        ["toEvidenceGuidanceViewModel", fixtures.action_card_complete, v => { v.cards[0].action_steps = [raw]; }],
        ["toEvidenceGuidanceViewModel", fixtures.action_card_complete, v => { v.fixture_disclosure = raw; }],
        ["toSolutionsViewModel", fixtures.solutions_complete, v => { v.candidates[0].summary = raw; }],
        ["toDocumentWorkspaceViewModel", workspace("# 文档"), v => { v.versions[0].content += `\n${raw}`; }],
      ]) {
        await check(`R1 ${name} marker ${index}`, () => { const value = clone(base); mutate(value); assert.equal(adapter(name, value), null); });
      }
      await check(`R1 renderer excludes marker ${index}`, () => {
        hooks.setTestAIReference({...clone(fixtures.ai_reference_complete), possible_target_users: [raw]});
        assert.ok(!element("#ai-reference-content").textContent.includes(raw));
        assert.match(element("#ai-reference-content").textContent, /没有生成可用建议/);
      });
      await check(`R1 document editor excludes marker ${index}`, () => {
        hooks.state.documentWorkspace = workspace(`# 文档\n${raw}`);
        hooks.renderDocumentWorkspace();
        assert.equal(element("#document-editor").value, "");
        assert.equal(element("#document-editor").disabled, true);
      });
    }
    for (const prose of cases.ordinary) {
      await check("R1 ordinary prose preserved", () => {
        const value = {...clone(fixtures.ai_reference_complete), possible_target_users: [prose]};
        assert.equal(adapter("toAIReferenceViewModel", value).possible_target_users[0], prose);
        hooks.setTestAIReference(value);
        assert.ok(element("#ai-reference-content").textContent.includes(prose));
      });
      await check("R1 ordinary JSON/prose survives all other adapters", () => {
        const guidance = clone(fixtures.action_card_complete); guidance.cards[0].title = prose;
        assert.equal(adapter("toEvidenceGuidanceViewModel", guidance).cards[0].title, prose);
        const solutions = clone(fixtures.solutions_complete); solutions.candidates[0].summary = prose;
        assert.equal(adapter("toSolutionsViewModel", solutions).candidates[0].summary, prose);
        hooks.state.documentWorkspace = workspace(prose);
        assert.ok(adapter("toDocumentWorkspaceViewModel", hooks.state.documentWorkspace));
        hooks.renderDocumentWorkspace();
        assert.equal(element("#document-editor").value, prose);
      });
    }
    await check("R2 partial reference generate, persisted load, retry", async () => {
      const result = {possible_target_users: ["唯一有效类别"]};
      hooks.state.currentProjectId = "partial-project";
      let postCount = 0;
      global.fetch = async (url, options = {}) => {
        const reference = String(url).endsWith("/ai-reference");
        if (reference && options.method === "POST") postCount++;
        return {ok: true, status: 200, headers: {get: () => "application/json"}, json: async () => reference ? {id: "partial-reference", result} : {}};
      };
      await evaluate("loadAIReference()");
      assert.match(element("#ai-reference-content").textContent, /唯一有效类别/);
      await hooks.generateAIReference();
      assert.match(element("#ai-reference-message").textContent, /AI参考已生成/);
      assert.match(element("#ai-reference-content").textContent, /唯一有效类别/);
      await hooks.generateAIReference();
      assert.equal(postCount, 2);
      assert.match(element("#ai-reference-content").textContent, /唯一有效类别/);
    });
    await check("R2 empty references rejected", () => { assert.equal(adapter("toAIReferenceViewModel", {}), null); });
    for (const field of ["who_or_where", "action_steps", "acceptable_artifacts", "fill_template"]) {
      await check(`R2 Action Card ${field} stays mandatory`, () => {
        const value = clone(fixtures.action_card_complete); value.cards[0][field] = [];
        assert.equal(adapter("toEvidenceGuidanceViewModel", value), null);
      });
    }
    const baseContent = "# SELECTED_B\nPAGE_B\n正常方案内容";
    hooks.state.snapshot = {solution: {title: "SELECTED_B", explicit_non_goals: ["不做支付", "不包含广告"]}, mvp: {pages: ["PAGE_B"]}};
    for (const exclusion of ["明确不做支付。", "本版本不包含支付和广告。", "## 非目标\n- 支付\n- 广告", "## Non-goals\n- 支付", "We will not implement 支付.", "支付不在本期范围内。", "不做广告，但不支持支付。"] ) {
      await check(`R4 honest exclusion ${exclusion}`, () => {
        const value = workspace(`${baseContent}\n${exclusion}`);
        assert.ok(adapter("toDocumentWorkspaceViewModel", value));
        value.draft = {content: `${baseContent}\n${exclusion}`, base_version_id: "doc-b"};
        assert.ok(adapter("toDocumentWorkspaceViewModel", value));
        hooks.state.documentWorkspace = value; hooks.renderDocumentWorkspace();
        assert.ok(element("#document-editor").value.includes(exclusion));
      });
    }
    for (const addition of ["增加支付功能。", "不做广告，但支持支付。", "明确不做支付。\n实现支付结算。", "## 非目标\n- 支付\n## 功能\n- 支持支付", "## 非目标\n- 支付\n### 实现方案\n- 支持支付", "We will implement 支付.", "不做广告，支付功能需要实现。", "支付不在本期范围内，但现在增加支付。", "## 非目标\n- 支持支付功能"]) {
      await check(`R4 actual scope drift ${addition}`, () => {
        assert.equal(adapter("toDocumentWorkspaceViewModel", workspace(`${baseContent}\n${addition}`)), null);
        const value = workspace(baseContent); value.draft = {content: `${baseContent}\n${addition}`, base_version_id: "doc-b"};
        assert.equal(adapter("toDocumentWorkspaceViewModel", value), null);
      });
    }
    await check("R4 selected identity and pages remain required", () => {
      assert.equal(adapter("toDocumentWorkspaceViewModel", workspace("# OTHER\nPAGE_B")), null);
      assert.equal(adapter("toDocumentWorkspaceViewModel", workspace("# SELECTED_B\nOTHER_PAGE")), null);
    });
    await check("R4 non-goal heading cannot conceal a positive commitment", () => {
      assert.equal(adapter("toDocumentWorkspaceViewModel", workspace(`${baseContent}\n## 非目标 支持支付`)), null);
    });
    for (const [label, narrative, accepted] of [
      ["honest future exclusion", "本期不会支持支付。", true],
      ["honest integration exclusion", "本期不集成支付。", true],
      ["negative under non-goal heading", "## 非目标\n- 本期不会支持支付。\n- 本期不集成支付。", true],
      ["positive completion under non-goal heading", "## 非目标\n- 支付功能将在本期完成。", false],
      ["positive commitment in heading", "## 非目标 支付功能将在本期完成", false],
      ["positive support control", "本期支持支付。", false],
      ["negative followed by positive", "本期不集成支付，但支付功能将在本期完成。", false],
      ["positive after negative in non-goals", "## 非目标\n- 本期不会支持支付。\n- 支付功能将在本期完成。", false],
    ]) {
      for (const source of ["version", "draft"]) {
        await check(`F2 ${source}: ${label}`, () => {
          const content = `${baseContent}\n${narrative}`;
          const value = workspace(source === "version" ? content : baseContent);
          if (source === "draft") value.draft = {content, base_version_id: "doc-b"};
          assert.equal(Boolean(adapter("toDocumentWorkspaceViewModel", value)), accepted);
        });
        await check(`F2 ${source} editor: ${label}`, () => {
          const content = `${baseContent}\n${narrative}`;
          const value = workspace(source === "version" ? content : baseContent);
          if (source === "draft") value.draft = {content, base_version_id: "doc-b"};
          hooks.state.documentWorkspace = value; hooks.renderDocumentWorkspace();
          assert.equal(element("#document-editor").value, accepted ? content : "");
          assert.equal(element("#document-editor").disabled, !accepted);
        });
      }
    }
    console.log(`SUMMARY passed=${passed} failed=${failed}`);
    if (failed) process.exitCode = 1;
  }
  main().catch(error => { console.error(error); process.exitCode = 1; });
}
