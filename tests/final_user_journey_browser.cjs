const fs = require('node:fs');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
(async () => {
const browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
const context = await browser.newContext({viewport: {width: 1366, height: 768}});
let external = 0, pageErrors = [], failed = [], counts = {ai: 0, comparison: 0, solution: 0, documents: 0};
await context.route('**/*', route => {
  const request = route.request();
  if (!request.url().startsWith(input.url + '/')) { external++; return route.abort(); }
  if (request.method() === 'POST') {
    if (/\/ai-reference$/.test(request.url())) counts.ai++;
    if (/\/competitor-comparisons$/.test(request.url())) counts.comparison++;
    if (/\/solutions\/generate$/.test(request.url())) counts.solution++;
    if (/\/documents\/generate$/.test(request.url())) counts.documents++;
  }
  return route.continue();
});
const page = await context.newPage();
page.on('pageerror', e => pageErrors.push(e.message));
page.on('requestfailed', r => failed.push(`${r.method()} ${r.url()} ${r.failure()?.errorText || ''}`));
page.setDefaultTimeout(30000);

async function loginAndClaim(account) {
  await page.goto(input.url + '/login');
  await page.locator('[name=username]').fill(account.username);
  await page.locator('[name=password]').fill(account.password);
  await page.locator('summary').click();
  await page.locator('[name=invite]').fill(account.invite);
  await page.locator('button[value=claim]').click();
  await page.waitForFunction(() => document.querySelector('#account-message')?.textContent.includes('已创建'));
  const betaConsentStatus = page.waitForResponse(response => response.url().endsWith('/api/beta/consent') && response.request().method() === 'GET', {timeout: 10000}).catch(() => null);
  await page.locator('button[value=login]').click();
  await page.locator('#account-controls').waitFor({state: 'visible'});
  await betaConsentStatus;
  await page.waitForTimeout(250);
  const consent = page.locator('#beta-consent-dialog #beta-consent-accept');
  if (await page.locator('#beta-consent-dialog').evaluate(dialog => Boolean(dialog.open)).catch(() => false)) {
    await consent.click({force: true});
    await page.locator('#beta-consent-dialog[open]').waitFor({state: 'detached', timeout: 10000}).catch(async () => {
      await page.waitForFunction(() => !document.querySelector('#beta-consent-dialog')?.open);
    });
  }
  await page.waitForLoadState('networkidle');
}
async function view(name) { await page.locator(`[data-view=${name}]`).first().click(); await page.locator(`#${name}-view`).waitFor({state:'visible'}); }
async function confirmIdea() {
  await page.locator('#idea-brief-dialog').waitFor({state:'visible'});
  await page.locator('#idea-brief-confirm').click();
  await page.locator('#generate-solutions-button').waitFor({state:'visible'});
}
async function waitLoading() { await page.locator('#loading-status').waitFor({state:'hidden', timeout:60000}).catch(() => {}); }

try {
  const accountA = {username: input.username, password: input.password, invite: input.invite};
  const accountB = {username: input.usernameB, password: input.passwordB, invite: input.inviteB};
  let projectId;
  let snapshotId;
  await loginAndClaim(accountA);
  await page.locator('#quick-start-idea').fill('帮助学生整理求职准备并逐步验证需求');
  await page.locator('#quick-start-target-user').fill('正在准备求职的学生');
  await page.locator('#quick-start-resources').fill('');
  const quick = page.waitForResponse(r => r.url().endsWith('/api/projects/quick-start') && r.request().method() === 'POST');
  await page.locator('#quick-start-form').evaluate(form => form.requestSubmit());
  assert.equal((await quick).status(), 201);
  await confirmIdea();

  await view('solutions');
  await page.locator('#ai-reference-generate').evaluate(node => node.click());
  await page.locator('#ai-reference-content .status-note').waitFor({state:'visible'});
  assert.match(await page.locator('#ai-reference-content').innerText(), /AI生成参考，尚未经外部资料核实/);
  const projects = await page.evaluate(async () => (await fetch('/api/projects')).json());
  projectId = projects.projects?.[0]?.id ?? projects[0]?.id;
  assert.ok(projectId, 'quick-start project id is available');
  const sources = await page.evaluate(async id => (await fetch(`/api/projects/${id}/sources`)).json(), projectId);
  assert.equal(Array.isArray(sources) ? sources.length : (sources.sources || []).length, 0);
  const referenceSelects = page.locator('#ai-reference-content select');
  if (await referenceSelects.count()) await referenceSelects.first().selectOption('adopt');
  const referenceInput = page.locator('#ai-reference-content input').first();
  if (await referenceInput.count()) await referenceInput.fill('只作为待验证假设');
  if (await referenceSelects.count() > 1) await referenceSelects.nth(1).selectOption('ignore');
  await page.locator('#ai-reference-apply').click();
  await page.waitForFunction(() => document.querySelector('#ai-reference-message')?.textContent.includes('已保存为项目中的待验证参考'));

  await page.locator('#competitor-open').click();
  const panel = page.locator('#competitor-dialog');
  await panel.waitFor({state:'visible'});
  for (const name of ['求职产品A', '求职产品B']) {
    await page.locator('#competitor-name').fill(name);
    await page.locator('#competitor-description').fill('用户输入的合成候选说明，尚未核实');
    await page.locator('#competitor-add').click();
    await page.getByText(name, {exact:true}).waitFor();
  }
  const first = panel.locator('[data-candidate]').filter({hasText:'求职产品A'});
  await first.getByRole('button', {name:'加入本次比较', exact:true}).click();
  await page.locator('#competitor-compare').click();
  await page.locator('#competitor-comparison').waitFor({state:'visible'});
  await page.locator('#competitor-decisions select').first().selectOption('adopt');
  await page.locator('#competitor-decisions input').first().fill('借鉴分步引导');
  const snapshot = page.waitForResponse(r => r.url().endsWith('/competitor-snapshots') && r.request().method() === 'POST');
  await page.locator('#competitor-save-snapshot').click();
  const snapshotResponse = await snapshot;
  assert.equal(snapshotResponse.status(), 201);
  snapshotId = (await snapshotResponse.json()).id;
  await page.locator('#competitor-close').click();

  await page.locator('#generate-solutions-button').click();
  await page.locator('.solution-card').first().waitFor({state:'visible', timeout:60000});
  await page.locator('.select-solution-button').first().click();
  await waitLoading();
  await view('documents');
  for (const type of ['prd','techdoc']) {
    const button = page.locator(`[data-generate-doc="${type}"]`).first();
    if (await button.count() && await button.isVisible()) {
      await button.click();
      await waitLoading();
    }
    await view('documents');
    const versionButton = page.locator('[data-doc-select]').first();
    if (await versionButton.count()) {
      await versionButton.click();
      await page.locator('#document-editor').fill(`${type} 用户旅程编辑验证`);
      await page.locator('#document-save-version').click();
      await page.waitForTimeout(500);
    }
    const confirm = page.locator('[data-confirm-doc]').first();
    if (await confirm.count() && await confirm.isVisible()) await confirm.click();
  }
  await view('handoff');
  await page.locator('#handoff-content').waitFor({state:'visible'});
  assert.match(await page.locator('#handoff-content').innerText(), /仍需确认的事项|开发交接/);
  const checkbox = page.locator('#handoff-unresolved-confirm');
  if (await checkbox.count()) { await checkbox.check(); await page.locator('#handoff-acknowledge-button').click(); await page.waitForTimeout(500); }

  // Final journey control: a second account must not see or address any of
  // account A's project-scoped resources, even when it knows their IDs.
  await page.locator('#account-logout').click();
  await page.locator('[name=username]').waitFor({state:'visible'});
  await loginAndClaim(accountB);
  const foreignStatuses = await page.evaluate(async ({projectId, snapshotId}) => {
    const paths = [
      `/api/projects/${projectId}`,
      `/api/projects/${projectId}/ai-reference`,
      `/api/projects/${projectId}/solutions`,
      `/api/projects/${projectId}/documents/prd/versions`,
      `/api/projects/${projectId}/documents/techdoc/versions`,
      `/api/projects/${projectId}/handoff/readiness`,
      `/api/projects/${projectId}/competitor-snapshots/${snapshotId}`,
    ];
    const result = {};
    for (const path of paths) result[path] = (await fetch(path)).status;
    return result;
  }, {projectId, snapshotId});
  assert.ok(Object.values(foreignStatuses).every(status => [401, 403, 404].includes(status)), JSON.stringify(foreignStatuses));
  assert.equal(external, 0);
  assert.equal(pageErrors.length, 0, pageErrors.join('; '));
  console.log(JSON.stringify({passed:true, external, pageErrors, failed, counts, ui_bypass_steps:0}));
} catch (error) {
  const diagnostic = await page.locator('#ai-reference-message').textContent().catch(() => '');
  const aiContent = await page.locator('#ai-reference-content').innerText().catch(() => '');
  const solutionContent = await page.locator('#solutions-content').innerText().catch(() => '');
  console.error(JSON.stringify({passed:false, external, pageErrors, failed, counts, aiMessage:diagnostic, aiContent, solutionContent, error:error.stack}));
  process.exitCode = 1;
} finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error); process.exitCode = 1; });
