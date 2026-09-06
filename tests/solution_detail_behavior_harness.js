"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const nodes = new Map();
let focusReturned = false;
function node(key) {
  if (!nodes.has(key)) nodes.set(key, {
    innerHTML: "", textContent: "", open: false, listeners: {},
    addEventListener(name, cb) { this.listeners[name] = cb; },
    showModal() { this.open = true; },
    close() { this.open = false; this.listeners.close?.(); },
    focus() {},
  });
  return nodes.get(key);
}
global.document = {querySelector: node, querySelectorAll: () => [], addEventListener() {}};
global.window = {__INSIGHTFORGE_TEST__: true};
global.fetch = () => { throw new Error("Details must never issue a request"); };
vm.runInThisContext(fs.readFileSync("app/static/app.js", "utf8"));
const hooks = window.InsightForgeUi.__test;
assert.equal(typeof hooks.openSolutionDetails, "function", "a read-only independent detail panel is required");
hooks.state.solutions = {candidates: [{id: "a", title: "测试方案", why_fit: "已有说明", features: ["已有功能"]}], selected_candidate_id: "b"};
const before = JSON.stringify(hooks.state.solutions);
const trigger = {isConnected: true, focus() { focusReturned = true; }};
hooks.openSolutionDetails("a", trigger);
assert.equal(node("#solution-detail-dialog").open, true);
assert.match(node("#solution-detail-content").innerHTML, /已有功能/);
assert.match(node("#solution-detail-content").innerHTML, /未提供/);
assert.equal(JSON.stringify(hooks.state.solutions), before, "viewing must not select or mutate solutions");
node("#solution-detail-close").listeners.click();
assert.equal(node("#solution-detail-dialog").open, false);
assert.equal(focusReturned, true);
console.log("solution detail behavior PASS: read-only, missing fields honest, close restores focus, zero requests");
