const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function login(page, input, account) {
  await page.goto(input.url + '/login');
  await page.locator('[name=username]').fill(account.username);
  await page.locator('[name=password]').fill(account.password);
  await page.locator('button[value=login]').click();
  await page.locator('#account-controls').waitFor({state:'visible', timeout:30000});
  const consent = page.locator('#beta-consent-dialog #beta-consent-accept');
  if (await consent.isVisible().catch(() => false)) await consent.click();
  await page.waitForLoadState('networkidle');
}
async function openProject(page, input, projectId) {
  await page.goto(input.url + '/');
  await page.locator('#account-controls').waitFor({state:'visible', timeout:30000});
  await page.locator('#loading-status').waitFor({state:'hidden', timeout:30000}).catch(() => {});
  if (await page.locator('#project-shell').isVisible().catch(() => false)) {
    await page.locator('#solutions-content').waitFor({state:'attached'});
    await page.waitForFunction(() => Boolean(document.querySelector('#solutions-content')?.innerHTML.trim()), null, {timeout:30000});
    return;
  }
  await page.waitForFunction(id => Boolean(document.querySelector(`[data-open-project="${id}"]`)), projectId, {timeout:30000}).catch(async () => {
    throw new Error(`project card unavailable id=${projectId} url=${page.url()} body=${JSON.stringify((await page.locator('body').innerText().catch(() => '')).slice(0, 4000))}`);
  });
  await page.locator(`[data-open-project="${projectId}"]`).first().waitFor({state:'visible', timeout:30000});
  await page.locator(`[data-open-project="${projectId}"]`).first().evaluate(n => n.click());
  await page.locator('#project-shell').waitFor({state:'visible', timeout:30000});
  await page.locator('#loading-status').waitFor({state:'hidden', timeout:30000}).catch(() => {});
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
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
  const context = await browser.newContext({viewport:{width:1366,height:768}});
  let external = 0, aiPosts = 0, aiGets = 0, sourceGets = 0, solutionPosts = 0, documentPosts = 0;
  await context.route('**/*', async route => {
    const req = route.request(), url = req.url();
    if (!url.startsWith(input.url + '/')) { external++; return route.abort(); }
    if (req.method() === 'POST' && /\/ai-reference$/.test(url)) aiPosts++;
    if (req.method() === 'GET' && /\/ai-reference$/.test(url)) aiGets++;
    if (req.method() === 'GET' && /\/sources$/.test(url)) sourceGets++;
    if (req.method() === 'POST' && /\/solutions\/generate$/.test(url)) solutionPosts++;
    if (req.method() === 'POST' && /\/documents\/generate$/.test(url)) documentPosts++;
    return route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const result = {aiReference:false, aiReferenceRestoreNoDuplicate:false, zeroSource:false, acknowledgement:false, handoff:false, external:0, aiPosts:0, aiGets:0, sourceGets:0, solutionPosts:0, documentPosts:0};
  try {
    await login(page, input, input.userA);
    await openProject(page, input, input.aiProject);
    await confirmIdea(page);
    await view(page, 'solutions');
    await page.locator('#ai-reference-generate').click();
    await waitForVisible(page, '#ai-reference-content .status-note');
    assert.match(await page.locator('#ai-reference-content').innerText(), /AI生成参考，尚未经外部资料核实/);
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
    for (const button of await page.locator('[data-confirm-doc]').all()) { const response = page.waitForResponse(r => /document-versions\/.+\/confirm$/.test(r.url()) && r.request().method() === 'POST'); await button.click(); assert.equal((await response).status(), 200); }
    await view(page, 'handoff'); await waitForVisible(page, '#handoff-content');
    assert.match(await page.locator('#handoff-content').innerText(), /仍需确认的事项/);
    await page.locator('#handoff-unresolved-confirm').check();
    const ack = page.waitForResponse(r => r.url().includes('/handoff/acknowledge-unresolved') && r.request().method() === 'POST'); await page.locator('#handoff-acknowledge-button').click(); assert.equal((await ack).status(), 200);
    result.zeroSource = true; result.acknowledgement = true;
    await page.reload(); await openProject(page, input, input.zeroProject); await view(page, 'handoff');
    assert.match(await page.locator('#handoff-content').innerText(), /可以继续|已知晓|交接/); result.handoff = true;
    result.external=external; result.aiPosts=aiPosts; result.aiGets=aiGets; result.sourceGets=sourceGets; result.solutionPosts=solutionPosts; result.documentPosts=documentPosts;
    assert.equal(external, 0); assert.equal(aiPosts, 1);
    console.log(JSON.stringify(result));
  } catch (error) {
    result.external=external; result.aiPosts=aiPosts; result.aiGets=aiGets; result.sourceGets=sourceGets; result.solutionPosts=solutionPosts; result.documentPosts=documentPosts;
    console.error(JSON.stringify(result)); console.error(error.stack); process.exitCode=1;
  } finally { await browser.close(); }
})();
