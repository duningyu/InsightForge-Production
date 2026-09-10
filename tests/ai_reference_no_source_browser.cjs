const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function acceptBetaConsent(page) {
  const dialog = page.locator('#beta-consent-dialog');
  const accept = page.locator('#beta-consent-dialog #beta-consent-accept');
  // account-session.js exposes the account controls before app.js finishes its
  // async bootstrap.  Give ensureBetaConsent a chance to open the dialog
  // after a full-page navigation, otherwise the test can race the first render.
  await accept.waitFor({state:'visible', timeout:5000}).catch(() => {});
  if (await accept.isVisible().catch(() => false)) {
    await accept.click();
    await dialog.waitFor({state:'hidden', timeout:30000}).catch(() => {});
  }
}

async function login(page, input, account) {
  await page.goto(input.url + '/login');
  await page.locator('[name=username]').fill(account.username);
  await page.locator('[name=password]').fill(account.password);
  await page.locator('button[value=login]').click();
  await page.locator('#account-controls').waitFor({state:'visible', timeout:30000});
  await acceptBetaConsent(page);
  await page.waitForLoadState('networkidle');
}
async function openProject(page, input, projectId) {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto(input.url + '/');
    await page.locator('#account-controls').waitFor({state:'visible', timeout:30000});
    await acceptBetaConsent(page);
    await page.locator('#loading-status').waitFor({state:'hidden', timeout:30000}).catch(() => {});
    if (await page.locator('#project-shell').isVisible().catch(() => false)) break;
    try {
      await page.waitForFunction(id => Boolean(document.querySelector(`[data-open-project="${id}"]`)), projectId, {timeout:10000});
      await page.locator(`[data-open-project="${projectId}"]`).first().waitFor({state:'visible', timeout:10000});
      // loadProject() starts several asynchronous project-scoped reads after the
      // click.  Waiting only for the shell/solutions DOM is racy: those nodes
      // render before AI/evidence state has been restored, so the next action
      // can observe a stale null project and silently skip its POST.
      const aiReferenceRead = page.waitForResponse(response =>
        response.request().method() === 'GET' &&
        response.url().includes(`/api/projects/${projectId}/ai-reference`) &&
        response.status() >= 200 && response.status() < 300,
        {timeout:30000}
      );
      const evidenceGuidanceRead = page.waitForResponse(response =>
        response.request().method() === 'GET' &&
        response.url().includes(`/api/projects/${projectId}/evidence-guidance`) &&
        response.status() >= 200 && response.status() < 300,
        {timeout:30000}
      );
      await page.locator(`[data-open-project="${projectId}"]`).first().click();
      await page.locator('#project-shell').waitFor({state:'visible', timeout:10000});
      await Promise.all([aiReferenceRead, evidenceGuidanceRead]);
      break;
    } catch (error) {
      if (attempt === 1) {
        const visibleIds = await page.locator('[data-open-project]').evaluateAll(nodes => nodes.map(node => ({id: node.dataset.openProject, title: node.textContent.trim().slice(0, 160)})).slice(0, 20)).catch(() => []);
        const projects = await page.evaluate(async () => { try { const response = await fetch('/api/projects'); return {status: response.status, body: await response.json()}; } catch (fetchError) { return {error: String(fetchError)}; } });
        const diagnostics = await page.evaluate(() => ({
          readyState: document.readyState,
          hash: location.hash,
          loading: document.querySelector('#loading-status')?.textContent || null,
          error: document.querySelector('#error-message')?.textContent || null,
          account: document.querySelector('#account-name')?.textContent || null,
          betaDialogOpen: Boolean(document.querySelector('#beta-consent-dialog')?.open),
          betaConsentButtonVisible: Boolean(document.querySelector('#beta-consent-accept') && getComputedStyle(document.querySelector('#beta-consent-accept')).display !== 'none'),
          projectCards: Array.from(document.querySelectorAll('[data-open-project]')).slice(0, 20).map(node => node.dataset.openProject),
        }));
        throw new Error(`project card unavailable id=${projectId} url=${page.url()} visible=${JSON.stringify(visibleIds)} api=${JSON.stringify(projects)} diagnostics=${JSON.stringify(diagnostics)} cause=${error.message}`);
      }
    }
  }
  await page.locator('#solutions-content').waitFor({state:'attached'});
  await page.waitForFunction(() => Boolean(document.querySelector('#solutions-content')?.innerHTML.trim()), null, {timeout:30000});
}
async function view(page, name) { await page.locator(`[data-view=${name}]`).first().evaluate(n => n.click()); }
async function waitForVisible(page, selector) { await page.locator(selector).first().waitFor({state:'visible', timeout:30000}); }
async function confirmIdea(page) {
  if (await page.locator('#generate-solutions-button').count()) return;
  const review = page.locator('#open-idea-brief-button');
  if (await review.count() === 0) {
    throw new Error(`idea action unavailable body=${JSON.stringify((await page.locator('body').innerText().catch(() => '')).slice(0, 4000))} solutions=${JSON.stringify(await page.locator('#solutions-content').innerText().catch(() => ''))}`);
  }
  await review.click();
  await page.locator('#idea-brief-dialog').waitFor({state:'visible'});
  const response = page.waitForResponse(r => r.url().includes('/idea-brief/confirm') && r.request().method() === 'POST');
  await page.locator('#idea-brief-confirm').click();
  assert.equal((await response).status(), 200);
  await waitForVisible(page, '#generate-solutions-button');
}
async function openSources(page) {
  await view(page, 'evidence');
  await page.locator('[data-evidence-tab="sources"]:visible').click();
  await page.locator('#evidence-sources-panel').waitFor({state:'visible', timeout:30000});
}
function isExpectedHttpError(error) {
  if (error.status === 404 && (error.path.endsWith('/solutions') || error.path.endsWith('/snapshot') || error.path.endsWith('/walkthrough'))) return true;
  if (error.status === 404 && (error.path.includes('/drafts/') || /\/documents\/(prd|techdoc)\/draft$/.test(error.path))) return true;
  return error.status === 409 && error.method === 'PUT' && error.path.endsWith('/drafts/ui_context/main');
}
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
  const context = await browser.newContext({viewport:{width:1366,height:768}});
  let external = 0, aiPosts = 0, aiGets = 0, evidenceGuidancePosts = 0, evidenceGuidanceGets = 0, sourceGets = 0, solutionPosts = 0, documentPosts = 0;
  await context.route('**/*', async route => {
    const req = route.request(), url = req.url();
    if (!url.startsWith(input.url + '/')) { external++; return route.abort(); }
    if (req.method() === 'POST' && /\/ai-reference$/.test(url)) aiPosts++;
    if (req.method() === 'GET' && /\/ai-reference$/.test(url)) aiGets++;
    if (req.method() === 'POST' && /\/evidence-guidance$/.test(url)) evidenceGuidancePosts++;
    if (req.method() === 'GET' && /\/evidence-guidance$/.test(url)) evidenceGuidanceGets++;
    if (req.method() === 'GET' && /\/sources$/.test(url)) sourceGets++;
    if (req.method() === 'POST' && /\/solutions\/generate$/.test(url)) solutionPosts++;
    if (req.method() === 'POST' && /\/documents\/generate$/.test(url)) documentPosts++;
    return route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const pageErrors = [], consoleErrors = [], unexpectedConsoleErrors = [], httpErrors = [], requestFailures = [];
  page.on('pageerror', error => pageErrors.push(String(error?.stack || error)));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    const text = message.text();
    consoleErrors.push(text);
    if (!/Failed to load resource: the server responded with a status of (404|409)/.test(text)) {
      unexpectedConsoleErrors.push(text);
    }
  });
  page.on('response', response => {
    if (response.url().startsWith(input.url + '/') && response.status() >= 400) {
      httpErrors.push({method: response.request().method(), status: response.status(), path: new URL(response.url()).pathname});
    }
  });
  page.on('requestfailed', request => {
    if (request.url().startsWith(input.url + '/')) {
      requestFailures.push({method: request.method(), path: new URL(request.url()).pathname, error: request.failure()?.errorText || 'unknown'});
    }
  });
  const result = {aiReference:false, aiReferenceRestoreNoDuplicate:false, evidenceGuidance:false, evidenceGuidanceRestoreNoDuplicate:false, zeroSource:false, acknowledgement:false, handoff:false, external:0, aiPosts:0, aiGets:0, evidenceGuidancePosts:0, evidenceGuidanceGets:0, sourceGets:0, solutionPosts:0, documentPosts:0, pageErrors, consoleErrors, unexpectedConsoleErrors, httpErrors, expectedHttpErrors:[], unexpectedHttpErrors:[], requestFailures};
  try {
    await login(page, input, input.userA);
    await openProject(page, input, input.aiProject);
    await confirmIdea(page);
    await view(page, 'solutions');
    await page.locator('#ai-reference-generate').click();
    await waitForVisible(page, '#ai-reference-content .status-note');
    assert.match(await page.locator('#ai-reference-content').innerText(), /AI生成参考，尚未经外部资料核实/);
    assert.ok(await page.locator('#ai-reference-content .ai-reference-item-content').count() > 1, 'AI suggestions need visible content blocks');
    assert.match(await page.locator('#ai-reference-content').innerText(), /可能的目标用户|可能出现的场景|可能需要解决的问题/);
    assert.equal((await page.evaluate(async id => (await fetch(`/api/projects/${id}/sources`)).json(), input.aiProject)).length, 0);
    const selects = page.locator('#ai-reference-content select');
    assert.ok(await selects.count() > 1);
    await selects.nth(0).selectOption('adopt');
    await page.locator('#ai-reference-content input').first().fill('只作为待验证假设');
    await selects.nth(1).selectOption('ignore');
    await page.locator('#ai-reference-apply').click();
    await page.waitForFunction(() => document.querySelector('#ai-reference-message')?.textContent.includes('已保存为项目中的待验证参考'));
    result.aiReference = true;
    await view(page, 'evidence');
    await view(page, 'solutions');
    assert.match(await page.locator('#ai-reference-content').innerText(), /AI生成参考/);
    await page.reload(); await openProject(page, input, input.aiProject); await view(page, 'solutions');
    await waitForVisible(page, '#ai-reference-content .status-note');
    assert.equal(aiPosts, 1); result.aiReferenceRestoreNoDuplicate = true;

    await openSources(page);
    assert.match(await page.locator('#evidence-entry-guidance').innerText(), /联网查找暂未开启/);
    assert.equal(await page.locator('#evidence-entry-guidance [data-evidence-entry="public_search"]').count(), 0);
    await page.locator('#evidence-coach-open').click();
    await waitForVisible(page, '#evidence-guidance-message');
    await page.locator('#evidence-guidance-generate').click();
    await waitForVisible(page, '#evidence-guidance-content .evidence-coach-card');
    const guidanceText = await page.locator('#evidence-guidance-content').innerText();
    assert.match(guidanceText, /要确认什么/);
    assert.match(guidanceText, /拿到什么就可以填写/);
    assert.match(guidanceText, /会影响哪个产品决定/);
    assert.match(guidanceText, /AI建议/);
    assert.equal((await page.evaluate(async id => (await fetch(`/api/projects/${id}/sources`)).json(), input.aiProject)).length, 0);
    const guidance = await page.evaluate(async id => (await fetch(`/api/projects/${id}/evidence-guidance`)).json(), input.aiProject);
    assert.equal(guidance.source_created, false);
    assert.equal(guidance.is_evidence, false);
    result.evidenceGuidance = true;
    await view(page, 'solutions'); await openSources(page);
    await waitForVisible(page, '#evidence-guidance-content .evidence-coach-card');
    await page.reload(); await openProject(page, input, input.aiProject); await openSources(page);
    await waitForVisible(page, '#evidence-guidance-content .evidence-coach-card');
    assert.equal(evidenceGuidancePosts, 1); result.evidenceGuidanceRestoreNoDuplicate = true;

    await page.locator('#account-logout').click(); await page.waitForURL('**/login');
    await login(page, input, input.userB); await openProject(page, input, input.zeroProject); await confirmIdea(page); await view(page, 'solutions');
    await page.locator('#generate-solutions-button').click();
    await page.locator('#solutions-content .solution-card').first().waitFor({state:'visible', timeout:60000});
    await page.locator('#solutions-content .select-solution-button').first().click();
    await view(page, 'documents');
    for (const type of ['prd','techdoc']) {
      await view(page, 'documents');
      const button = page.locator(`[data-generate-doc="${type}"]:visible`).first();
      if (await button.count()) { const response = page.waitForResponse(r => r.url().endsWith('/documents/generate') && r.request().method() === 'POST', {timeout: 30000}); await button.click(); const resolved = await response; assert.equal(resolved.status(), 200); }
      await page.waitForTimeout(500);
    }
    await page.reload(); await openProject(page, input, input.zeroProject); await view(page, 'documents');
    assert.ok(await page.locator('[data-confirm-doc]').count() >= 2, 'generated documents were not ready for confirmation');
    const confirmButtons = page.locator('[data-confirm-doc]');
    while (await confirmButtons.count()) {
      const button = confirmButtons.first();
      const versionId = await button.getAttribute('data-confirm-doc');
      const response = page.waitForResponse(r => /document-versions\/.+\/confirm$/.test(r.url()) && r.request().method() === 'POST');
      await button.click();
      assert.equal((await response).status(), 200);
      await page.locator(`[data-confirm-doc="${versionId}"]`).waitFor({state:'detached', timeout:30000}).catch(() => {});
    }
    await view(page, 'handoff'); await waitForVisible(page, '#handoff-content');
    assert.match(await page.locator('#handoff-content').innerText(), /仍需确认的事项/);
    await page.locator('#handoff-unresolved-confirm').check();
    const ack = page.waitForResponse(r => r.url().includes('/handoff/acknowledge-unresolved') && r.request().method() === 'POST'); await page.locator('#handoff-acknowledge-button').click(); assert.equal((await ack).status(), 200);
    result.zeroSource = true; result.acknowledgement = true;
    await page.reload(); await openProject(page, input, input.zeroProject); await view(page, 'handoff');
    assert.match(await page.locator('#handoff-content').innerText(), /可以继续|已知晓|交接/); result.handoff = true;
    result.external=external; result.aiPosts=aiPosts; result.aiGets=aiGets; result.evidenceGuidancePosts=evidenceGuidancePosts; result.evidenceGuidanceGets=evidenceGuidanceGets; result.sourceGets=sourceGets; result.solutionPosts=solutionPosts; result.documentPosts=documentPosts;
    result.expectedHttpErrors = httpErrors.filter(isExpectedHttpError);
    result.unexpectedHttpErrors = httpErrors.filter(error => !isExpectedHttpError(error));
    assert.equal(external, 0); assert.equal(aiPosts, 1);
    assert.equal(unexpectedConsoleErrors.length, 0);
    assert.equal(result.unexpectedHttpErrors.length, 0);
    console.log(JSON.stringify(result));
  } catch (error) {
    result.external=external; result.aiPosts=aiPosts; result.aiGets=aiGets; result.evidenceGuidancePosts=evidenceGuidancePosts; result.evidenceGuidanceGets=evidenceGuidanceGets; result.sourceGets=sourceGets; result.solutionPosts=solutionPosts; result.documentPosts=documentPosts;
    result.expectedHttpErrors = httpErrors.filter(isExpectedHttpError);
    result.unexpectedHttpErrors = httpErrors.filter(error => !isExpectedHttpError(error));
    console.error(JSON.stringify(result)); console.error(error.stack); process.exitCode=1;
  } finally { await browser.close(); }
})();
