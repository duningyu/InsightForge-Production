const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
function node(key) {
  if (!nodes.has(key)) nodes.set(key, {hidden:true, textContent:'', disabled:false, open:false,
    showModal(){this.open=true;}, close(){this.open=false;}, focus(){this.focused=true;}});
  return nodes.get(key);
}
global.document={querySelector:node, querySelectorAll:()=>[], addEventListener(){}};
global.window={__INSIGHTFORGE_TEST__:true};
let calls=[];
global.fetch=async(path,options)=>{
  calls.push({path,options});
  return {ok:true,headers:{get:()=> 'application/json'},json:async()=>({status:'RUNNING',cancel_requested:true})};
};
vm.runInThisContext(fs.readFileSync('app/static/app.js','utf8'));
(async()=>{
  const t=window.InsightForgeUi.__test;
  assert.equal(typeof t.showGenerationProgress,'function','real task progress control missing');
  t.state.activeGeneration={projectId:'owner-project',runId:'owner-run',status:'RUNNING'};
  t.showGenerationProgress();
  assert.equal(node('#generation-progress-dialog').open,true);
  t.closeGenerationProgress();
  assert.equal(calls.length,0,'close must not cancel or generate');
  t.showGenerationProgress();
  t.state.currentProjectId='different-project';
  await t.cancelActiveGeneration();
  assert.equal(calls.length,1);
  assert.equal(calls[0].path,'/api/projects/owner-project/solutions/generate/owner-run/cancel');
  assert.equal(calls[0].options.method,'POST');
  assert.match(node('#generation-progress-state').textContent,/正在停止/);
  assert.doesNotMatch(node('#generation-progress-state').textContent,/未产生|免费/);
  console.log('PASS close/reopen no requests; stop scoped to original task; pending honest');
})().catch(e=>{console.error(e);process.exitCode=1;});
