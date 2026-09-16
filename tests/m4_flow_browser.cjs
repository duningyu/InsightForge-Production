const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/ASUS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const conditions = {
  STATIC_TEMPLATE: {version: 'static-v1', content_hash: 'static-template-hash-v1', provider_allowed: false, search_allowed: false, max_calls: 0, retry_policy: 'none', timeout_seconds: 0, cost_per_call: 0},
  GENERAL_AI: {version: 'general-v1', prompt_version: 'prompt-v1', prompt_hash: 'prompt-hash-v1', model: 'general-model', provider: 'fake-provider', schema_version: 'schema-v1', schema_hash: 'schema-hash-v1', max_calls: 1, retry_policy: 'none', timeout_seconds: 30, cost_per_call: 0.01, search_allowed: false},
  INSIGHTFORGE_STATEFUL: {version: 'if-v1', source_commit: 'browser-source', deployment_id: 'browser-deploy', feature_flags: {}, rubric_versions: {quality: 'r1.1-v1'}, migration_identity: 'if-guide-m4-v1', provider_allowed: false, search_allowed: false, max_calls: 0, retry_policy: 'none', timeout_seconds: 0, cost_per_call: 0},
};

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'});
  const context = await browser.newContext({viewport: {width: 1366, height: 768}});
  let external = 0;
  let forbidden = 0;
  await context.route('**/*', route => {
    const url = route.request().url();
    if (!url.startsWith(input.url + '/')) { external++; return route.abort(); }
    if (/\/generate|\/evidence\/analyze|\/search/.test(url)) { forbidden++; return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage();
  const fill = async (selector, value) => page.locator(selector).fill(value);
  const waitText = async (selector, pattern) => page.waitForFunction(({selector, pattern}) => new RegExp(pattern).test(document.querySelector(selector)?.textContent || ''), {selector, pattern});
  const login = async () => {
    await page.goto(input.url + '/login');
    await fill('[name=username]', 'm4owner');
    await fill('[name=password]', 'SYNTHETIC-only-passphrase!');
    await page.locator('summary').click();
    await fill('[name=invite]', input.invites[0]);
    await page.locator('button[value=claim]').click();
    await page.waitForFunction(() => document.querySelector('#account-message').textContent.includes('已创建'));
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state: 'visible'});
  };
  const createOwnedProject = async () => {
    page.once('dialog', dialog => dialog.accept('M4 browser rehearsal project'));
    const responseWait = page.waitForResponse(r => r.url().endsWith('/api/projects') && r.request().method() === 'POST');
    await page.locator('#account-new-project').click();
    const response = await responseWait;
    assert.equal(response.status(), 201, await response.text());
    const projectId = (await response.json()).id;
    await page.locator('#m1-intent-form').waitFor({state: 'visible'});
    await page.locator('#m1-purpose').selectOption('LEARNING');
    await fill('#m1-raw-idea', '用本地草稿记录一个待验证的小想法。');
    await page.locator('#m1-intent-form').evaluate(form => form.requestSubmit());
    await page.locator('#m1-action-panel').waitFor({state: 'visible'});
    await page.locator('#m1-action-confirm').click();
    await waitText('#m1-action-state', '已确认|CONFIRMED|确认');
    return projectId;
  };
  const request = async (path, options = {}) => page.evaluate(async ({path, options}) => {
    const response = await fetch(path, {method: options.method || 'GET', headers: {'Content-Type': 'application/json', 'X-InsightForge-Request': '1', 'X-Actor': 'm4owner', 'X-InsightForge-Internal': '1', ...(options.headers || {})}, body: options.body ? JSON.stringify(options.body) : undefined});
    const text = await response.text();
    let body = null;
    try { body = JSON.parse(text); } catch (_) { body = text; }
    if (!response.ok) throw new Error(`${response.status} ${path}: ${text}`);
    return body;
  }, {path, options});
  const transition = async (sessionId, expectedRevision, targetState) => request(`/api/internal/m4/sessions/${sessionId}/transition`, {method: 'POST', body: {target_state: targetState, expected_revision: expectedRevision}});
  const runSession = async (sessionId, projectId, participantId) => {
    await transition(sessionId, 1, 'READY');
    await transition(sessionId, 2, 'IN_PROGRESS');
    await request(`/api/internal/m4/sessions/${sessionId}/gold-set`, {method: 'POST', body: {participant_id: participantId, project_id: projectId, purpose: 'LEARNING', constraints: ['本地草稿'], explicit_non_goals: ['外部部署'], requirements: [{requirement_id: 'r1', canonical_text: '能够保存草稿', importance: 'CRITICAL', source: 'USER_EDIT'}], participant_confirmed: true, expected_session_revision: 3}});
    await request(`/api/internal/m4/sessions/${sessionId}/annotations`, {method: 'POST', body: {project_id: projectId, artifact_ref: `m4://${sessionId}/artifact`, annotation_type: 'REQUIREMENT_MAPPING', target_id: 'r1', label: 'SUPPORTED', evaluator_role: 'independent_reviewer', evidence_ref: 'safe-ref://fixture', disagreement: {}, source_identity: 'REAL_OBSERVATION', adjudication_status: 'PENDING', expected_session_revision: 3}});
    const accounting = await request(`/api/internal/m4/sessions/${sessionId}/accounting`, {method: 'POST', body: {expected_revision: 3, elapsed_ms: 1000, time_to_first_valid_action_ms: 500, time_to_first_usable_flow_ms: 900, edit_count: 1, support_minutes: 0, provider_calls: 0, provider_cost: 0, retry_count: 0, timeout_count: 0, severe_error_count: 0, recovery_attempts: 0}});
    assert.equal(accounting.revision, 4);
    const quality = {primary: {first_valid_action_rate: 1, first_usable_flow_completion_rate: 1, independent_acceptance_rate: 1, evidence_backed_decision_rate: 1, recovery_rate: 0}, secondary: {critical_requirement_recall: 1, overall_requirement_recall: 1, alignment_precision: 1, checkability_coverage: 1, acceptance_coverage: 1, acceptance_testability: 1, unsupported_claim_rate: 0, actionability: 1, result_decision_traceability: 1}, evidence_level: 'USER_REPORTED', gold_set: {participant_confirmed: true, confirmed_by: 'idea_provider'}, p0_violations: [], provider_calls: 0, search_calls: 0};
    await request(`/api/internal/m4/sessions/${sessionId}/quality`, {method: 'POST', body: {project_id: projectId, expected_session_revision: 4, metrics: quality}});
    const final = await request(`/api/internal/m4/sessions/${sessionId}/finalize`, {method: 'POST', body: {expected_revision: 4, outcome: 'COMPLETED'}});
    assert.equal(final.state, 'FINALIZED');
  };
  try {
    await login();
    const projectId = await createOwnedProject();
    const experiment = await request('/api/internal/m4/experiments', {method: 'POST', body: {experiment_id: 'm4-browser-experiment', spec_version: 'm4-browser-v1', source_commit: 'browser-source', deployment_id: 'browser-deploy', condition_definitions: conditions, assignment_rule: 'BALANCED_BY_PURPOSE', metric_versions: {primary: 'm4-primary-v1', secondary: 'r1.1-v1'}, rubric_versions: {quality: 'r1.1-v1'}, threshold_policy: {mode: 'BASELINE_ONLY'}, operator_assistance_policy: {mode: 'NONE'}}});
    await request(`/api/internal/m4/experiments/m4-browser-experiment/freeze?expected_revision=${experiment.revision}`, {method: 'POST'});
    const assignedByPurpose = new Map();
    const purposes = [
      'LEARNING', 'LEARNING', 'LEARNING',
      'PERSONAL_USE', 'PERSONAL_USE', 'PERSONAL_USE',
      'FOR_OTHERS', 'FOR_OTHERS', 'FOR_OTHERS',
    ];
    for (const [index, purpose] of purposes.entries()) {
      const participantId = `m4-browser-p${index + 1}`;
      await request('/api/internal/m4/experiments/m4-browser-experiment/participants', {method: 'POST', body: {participant_id: participantId, purpose, prior_ai_familiarity: 'LOW', prior_product_experience: 'LOW', task_category: 'browser-fixture'}});
      const assigned = await request('/api/internal/m4/experiments/m4-browser-experiment/sessions', {method: 'POST', body: {session_id: `m4-browser-s${index + 1}`, participant_id: participantId, project_id: projectId}});
      const conditionsForPurpose = assignedByPurpose.get(purpose) || [];
      conditionsForPurpose.push(assigned.condition);
      assignedByPurpose.set(purpose, conditionsForPurpose);
      await runSession(assigned.session_id, projectId, participantId);
    }
    for (const purpose of ['LEARNING', 'PERSONAL_USE', 'FOR_OTHERS']) {
      assert.deepEqual(new Set(assignedByPurpose.get(purpose)), new Set(['STATIC_TEMPLATE', 'GENERAL_AI', 'INSIGHTFORGE_STATEFUL']));
    }
    const session = await request('/api/internal/m4/sessions/m4-browser-s1');
    const report = await request('/api/internal/m4/experiments/m4-browser-experiment/report');
    const exported = await request('/api/internal/m4/experiments/m4-browser-experiment/report/export');
    const gate = await request('/api/internal/m4/experiments/m4-browser-experiment/release-gate');
    assert.equal(session.state, 'FINALIZED');
    assert.equal(report.experiment_id, 'm4-browser-experiment');
    assert.equal(gate.release_gate.status, 'RELEASE_NOT_AUTHORIZED');
    assert.doesNotMatch(JSON.stringify(exported), /canonical_text|prior_ai_familiarity/);
    await page.locator('#m4-experiment-id').fill('m4-browser-experiment');
    await page.locator('#m4-session-id').fill('m4-browser-s1');
    await page.locator('#m4-refresh').click();
    await page.locator('#m4-report').waitFor({state: 'visible'});
    await waitText('#m4-report', 'm4-browser-experiment');
    await waitText('#m4-status', '已加载安全报告');
    fs.mkdirSync('artifacts/m4-browser', {recursive: true});
    await page.screenshot({path: 'artifacts/m4-browser/success.png'});
    assert.equal(external, 0);
    assert.equal(forbidden, 0);
    console.log('PASS real Chromium: M4 experiment freeze → 3 conditions → gold set → quality → finalize → safe report → read-only UI');
  } catch (error) {
    fs.mkdirSync('artifacts/m4-browser', {recursive: true});
    await page.screenshot({path: 'artifacts/m4-browser/failure.png'});
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
