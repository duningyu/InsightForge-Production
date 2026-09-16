const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/ASUS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const split = value => String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean);

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROMIUM_PATH || 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe',
  });
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
  fs.mkdirSync('artifacts/m3-browser', {recursive: true});
  const fill = async (selector, value) => { await page.locator(selector).fill(value); };
  const waitStatus = async (selector, pattern) => {
    await page.locator(selector).waitFor({state: 'visible'});
    await page.waitForFunction(({selector, pattern}) => new RegExp(pattern).test(document.querySelector(selector)?.textContent || ''), {selector, pattern});
  };
  const waitEnabled = async selector => {
    await page.locator(selector).waitFor({state: 'visible'});
    await page.waitForFunction(selector => !document.querySelector(selector)?.disabled, selector);
  };
  const login = async (username, invite) => {
    await page.goto(input.url + '/login');
    await fill('[name=username]', username);
    await fill('[name=password]', 'SYNTHETIC-only-passphrase!');
    await page.locator('summary').click();
    await fill('[name=invite]', invite);
    await page.locator('button[value=claim]').click();
    await page.waitForFunction(() => document.querySelector('#account-message').textContent.includes('已创建'));
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state: 'visible'});
  };
  const openProject = async projectId => {
    // Return through the real home view so boot-time showQuickStart() cannot
    // race a project click and hide the freshly loaded project shell.
    await page.locator('#home-button').click();
    await page.locator(`[data-open-project="${projectId}"]`).waitFor({state: 'visible'});
    const taskLoaded = page.waitForResponse(response => response.url().endsWith(`/api/projects/${projectId}/prototype-task`) && response.request().method() === 'GET' && response.status() === 200);
    await page.locator(`[data-open-project="${projectId}"]`).click();
    await page.waitForFunction(id => {
      const shell = document.querySelector('#project-shell');
      return document.querySelector('#project-select')?.value === id
        && shell
        && !shell.classList.contains('hidden')
        && getComputedStyle(shell).display !== 'none';
    }, projectId);
    await taskLoaded;
    try {
      await page.locator('#m3-action-panel').waitFor({state: 'visible', timeout: 5000});
    } catch (error) {
      console.error('openProject debug', JSON.stringify(await page.evaluate(() => ({
        selected: document.querySelector('#project-select')?.value,
        intentState: document.querySelector('#m1-action-state')?.textContent,
        m3Hidden: document.querySelector('#m3-action-panel')?.hidden,
        m3Style: (() => { const node = document.querySelector('#m3-action-panel'); if (!node) return null; const style = getComputedStyle(node); const rect = node.getBoundingClientRect(); const ancestors = []; for (let current = node; current && ancestors.length < 8; current = current.parentElement) { const computed = getComputedStyle(current); ancestors.push({id: current.id, tag: current.tagName, hidden: current.hidden, display: computed.display, visibility: computed.visibility, width: current.getBoundingClientRect().width, height: current.getBoundingClientRect().height}); } return {display: style.display, visibility: style.visibility, opacity: style.opacity, width: rect.width, height: rect.height, ancestors}; })(),
        m3Text: document.querySelector('#m3-action-panel')?.textContent,
        projectMessage: document.querySelector('#project-message')?.textContent,
        url: location.href,
      }))));
      throw error;
    }
  };
  const createM2ReadyProject = async () => {
    page.once('dialog', dialog => dialog.accept('M3 browser synthetic project'));
    const created = page.waitForResponse(response => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
    await page.locator('#account-new-project').click();
    const response = await created;
    assert.equal(response.status(), 201, await response.text());
    const projectId = (await response.json()).id;
    await page.waitForFunction(id => document.querySelector('#project-select')?.value === id, projectId);
    await page.locator('#m1-intent-form').waitFor({state: 'visible'});
    try {
      await page.locator('#m1-purpose').selectOption('PERSONAL_USE');
    } catch (error) {
      console.error('newProject debug', JSON.stringify(await page.evaluate(() => ({
        selected: document.querySelector('#project-select')?.value,
        intentForm: (() => { const node = document.querySelector('#m1-intent-form'); if (!node) return null; const rect = node.getBoundingClientRect(); return {hidden: node.hidden, display: getComputedStyle(node).display, width: rect.width, height: rect.height}; })(),
        purpose: (() => { const node = document.querySelector('#m1-purpose'); if (!node) return null; const rect = node.getBoundingClientRect(); return {hidden: node.hidden, disabled: node.disabled, display: getComputedStyle(node).display, width: rect.width, height: rect.height}; })(),
        projectMessage: document.querySelector('#project-message')?.textContent,
      }))));
      throw error;
    }
    await fill('#m1-raw-idea', '做一个只保存本地草稿并显示保存状态的小工具。');
    await page.locator('#m1-intent-form').evaluate(form => form.requestSubmit());
    await page.locator('#m1-action-panel').waitFor({state: 'visible'});
    await page.locator('#m1-action-confirm').click();
    await waitStatus('#m1-action-state', '已确认|CONFIRMED|确认');
    await page.locator('#m2-build-slice-panel').waitFor({state: 'visible'});
    await waitEnabled('#m2-in-scope');
    const buildValues = {
      '#m2-in-scope': '保存一个本地草稿\n显示可观察的保存状态',
      '#m2-out-of-scope': '自动部署\n外部 API 调用',
      '#m2-minimal-flow': '输入草稿\n保存草稿\n观察保存状态',
      '#m2-acceptance-criteria': '保存后刷新仍可看到草稿\n保存状态明确显示成功或失败',
      '#m2-confirmed-constraints': '不调用外部服务',
      '#m2-inputs': '用户草稿文本',
      '#m2-expected-outputs': '本地草稿和保存状态',
      '#m2-error-handling': '保存失败时显示可理解的错误并保留本地输入',
      '#m2-unknowns': 'UNKNOWN：持久化实现细节待后续开发确认',
      '#m2-constraint-notes': '保持 M1 页面和现有账号隔离行为不变',
    };
    for (const [selector, value] of Object.entries(buildValues)) await fill(selector, value);
    await page.locator('#m2-build-slice-form').evaluate(form => form.requestSubmit());
    await waitStatus('#m2-build-slice-status', 'DRAFT');
    await page.locator('#m2-build-slice-confirm').click();
    await waitStatus('#m2-build-slice-status', 'CONFIRMED');
    await page.locator('#m2-prototype-task-panel').waitFor({state: 'visible'});
    await page.locator('#m2-prototype-task-generate').click();
    await page.locator('#m2-prototype-task-form').waitFor({state: 'visible'});
    await waitStatus('#m2-prototype-task-status', 'DRAFT');
    await waitEnabled('#m2-prototype-task-save');
    const implementation = await page.locator('#m2-task-implementation-tasks').inputValue();
    const acceptance = await page.locator('#m2-task-acceptance-steps').inputValue();
    await fill('#m2-task-implementation-tasks', `${implementation}\n保留已确认的范围边界`);
    await fill('#m2-task-acceptance-steps', `${acceptance}\n刷新页面后仍能观察到持久化结果`);
    await page.locator('#m2-prototype-task-form').evaluate(form => form.requestSubmit());
    await waitStatus('#m2-prototype-task-status', '第 2 版');
    await waitEnabled('#m2-prototype-task-confirm');
    await page.locator('#m2-prototype-task-confirm').click();
    await waitStatus('#m2-prototype-task-status', 'READY');
    await openProject(projectId);
    await page.locator('#m2-build-slice-panel').waitFor({state: 'visible'});
    await waitStatus('#m2-build-slice-status', 'CONFIRMED');
    await page.locator('#m2-prototype-task-panel').waitFor({state: 'visible'});
    await waitStatus('#m2-prototype-task-status', 'READY');
    await page.locator('#m3-action-panel').waitFor({state: 'visible'});
    return projectId;
  };
  const reviewSubmission = async (status, checks, recommendation, unknowns = '') => {
    await page.locator('#m3-review-status').selectOption(status);
    await page.locator('#m3-review-evidence-level').selectOption('USER_REPORTED');
    await fill('#m3-review-check-items', checks);
    await fill('#m3-review-unknowns', unknowns);
    await fill('#m3-review-recommendation', recommendation);
    await page.locator('#m3-review-form').evaluate(form => form.requestSubmit());
    await waitStatus('#m3-action-status', status);
  };
  const confirmDecision = async (decision, rationale) => {
    await page.locator('#m3-decision-select').selectOption(decision);
    await fill('#m3-decision-rationale', rationale);
    await page.locator('#m3-decision-recommend').click();
    await waitEnabled('#m3-decision-confirm');
    await page.locator('#m3-decision-confirm').click();
    await page.waitForFunction(() => document.querySelector('#m3-history-items').textContent.includes('已确认'));
  };
  try {
    await login('m3owner', input.invites[0]);
    const doneProjectId = await createM2ReadyProject();
    await page.locator('#m3-open-done-form').click();
    await fill('#m3-done-description', '完成本地草稿保存流程');
    await fill('#m3-done-result', '页面显示保存状态');
    await fill('#m3-done-attachments', 'browser-proof://local-save');
    await fill('#m3-done-check-results', '保存流程 | PASS');
    await fill('#m3-done-notes', '仅记录用户报告，不声明独立执行');
    await page.locator('#m3-done-submit').click();
    await waitStatus('#m3-action-status', 'DONE');
    await reviewSubmission('PASS', '保存流程 | PASS', '可以继续下一步');
    await confirmDecision('CONTINUE', '用户确认继续');
    await openProject(doneProjectId);
    await page.locator('#m3-action-panel').waitFor({state: 'visible'});
    assert.match(await page.locator('#m3-history-items').textContent(), /submission|decision|已确认/);

    const blockedProjectId = await createM2ReadyProject();
    await page.locator('#m3-open-blocked-form').click();
    await fill('#m3-blocked-step', '保存状态确认');
    await fill('#m3-blocked-observed', '刷新后状态不明确');
    await fill('#m3-blocked-attempted', '重新加载页面并检查结果');
    await fill('#m3-blocked-evidence', 'browser-proof://blocked');
    await page.locator('#m3-blocked-submit').click();
    await waitStatus('#m3-action-status', 'BLOCKED');
    await reviewSubmission('FAIL', '保存状态确认 | FAIL', '需要一个最小恢复动作', '待提供实现日志');
    await page.locator('#m3-recovery-panel').waitFor({state: 'visible'});
    await page.locator('#m3-recovery-create').click();
    await page.waitForFunction(() => document.querySelector('#m3-history-items').textContent.includes('recovery'));
    await confirmDecision('NARROW', '用户确认先缩小范围并补充证据');
    await openProject(blockedProjectId);
    await page.locator('#m3-action-panel').waitFor({state: 'visible'});
    assert.match(await page.locator('#m3-history-items').textContent(), /recovery|已确认/);

    const staleProjectId = await createM2ReadyProject();
    const stale = await page.evaluate(async projectId => {
      const intent = await (await fetch(`/api/projects/${projectId}/intent`)).json();
      const task = intent.first_action;
      const response = await fetch(`/api/projects/${projectId}/actions/${task.task_id}/submissions`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-InsightForge-Request': '1'},
        // A fresh M2 task starts at revision 1; use a different valid revision
        // so the API reaches its stale-revision guard rather than Pydantic's
        // minimum-value validation.
        body: JSON.stringify({task_revision: task.revision + 1, submission_kind: 'DONE', description: 'stale draft', execution_claim: {}, source_identity: 'USER_INPUT'}),
      });
      return {status: response.status, body: await response.text(), projectId, task};
    }, staleProjectId);
    assert.equal(stale.status, 409);
    await page.locator('#m3-open-done-form').click();
    await fill('#m3-done-description', '本地草稿在冲突后仍保留');
    assert.equal(await page.locator('#m3-done-description').inputValue(), '本地草稿在冲突后仍保留');

    await page.locator('#account-logout').click();
    await page.waitForURL('**/login');
    await login('m3foreign', input.invites[1]);
    assert.equal(await page.evaluate(async id => (await fetch(`/api/projects/${id}`)).status, doneProjectId), 404);
    assert.equal(await page.evaluate(async id => (await fetch(`/api/projects/${id}/m3/history`)).status, doneProjectId), 404);
    assert.equal(external, 0);
    assert.equal(forbidden, 0);
    await page.screenshot({path: 'artifacts/m3-browser/success.png'});
    console.log('PASS real Chromium: M1 → M2-ready → DONE/BLOCKED → review → recovery → decision; stale=409; account isolation; external=0; forbidden=0');
  } catch (error) {
    await page.screenshot({path: 'artifacts/m3-browser/failure.png'});
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
