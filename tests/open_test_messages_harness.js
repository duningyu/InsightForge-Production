"use strict";
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
function node(key) {
  if (!nodes.has(key)) nodes.set(key, {innerHTML:'', textContent:'', classList:{add(){},remove(){}}, addEventListener(){}});
  return nodes.get(key);
}
global.document={querySelector:node,querySelectorAll:()=>[],addEventListener(){}};
global.window={__INSIGHTFORGE_TEST__:true};
global.setTimeout=()=>0;
global.fetch=()=>{throw Error('No request allowed');};
vm.runInThisContext(fs.readFileSync('app/static/app.js','utf8'));
console.error=()=>{};
const ui=window.InsightForgeUi;
ui.reportError({code:'APPLICATION_POSTPROCESS_FAILURE',payload:{}});
assert.doesNotMatch(node('#toast').textContent,/已释放|未扣除/, 'unknown settlement must not claim release');
ui.reportError({code:'APPLICATION_POSTPROCESS_FAILURE',payload:{quota_status:'COMMITTED'}});
assert.doesNotMatch(node('#toast').textContent,/已释放|未扣除/);
ui.reportError({code:'APPLICATION_POSTPROCESS_FAILURE',payload:{quota_status:'RELEASED'}});
assert.match(node('#toast').textContent,/已释放/);
const card=node('card'); card.innerHTML='stale';
ui.__test.renderGuidanceCard(card,{},'下一步');
assert.equal(card.innerHTML,'','missing guidance must not produce an empty action button');
console.log('open-test messages PASS: settlement-derived release and no blank action');
