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
  fs.mkdirSync('artifacts/m2-browser', {recursive: true});
  let projectId;

  const fill = async (selector, value) => { await page.locator(selector).fill(value); };
  const waitStatus = async (selector, pattern) => {
    await page.locator(selector).waitFor({state: 'visible'});
    try {
      await page.waitForFunction(({selector, pattern}) => new RegExp(pattern).test(document.querySelector(selector)?.textContent || ''), {selector, pattern});
    } catch (error) {
      const state = await page.locator(selector).evaluate(node => ({text: node.textContent, disabled: node.closest('section')?.querySelector('button')?.disabled}));
      console.error(`waitStatus failed selector=${selector} pattern=${pattern} state=${JSON.stringify(state)}`);
      throw error;
    }
  };
  const waitEnabled = async selector => {
    await page.locator(selector).waitFor({state: 'visible'});
    await page.waitForFunction(selector => !document.querySelector(selector)?.disabled, selector);
  };
  const putBuildSlice = async (body) => page.evaluate(async ({projectId, body}) => {
    const response = await fetch(`/api/projects/${projectId}/build-slice`, {
      method: 'PUT', headers: {'Content-Type': 'application/json', 'X-InsightForge-Request': '1'}, body: JSON.stringify(body),
    });
    return {status: response.status, body: await response.json()};
  }, {projectId, body});

  try {
    await page.goto(input.url + '/login');
    await fill('[name=username]', 'm2owner');
    await fill('[name=password]', 'SYNTHETIC-only-passphrase!');
    await page.locator('summary').click();
    await fill('[name=invite]', input.invites[0]);
    await page.locator('button[value=claim]').click();
    await page.waitForFunction(() => document.querySelector('#account-message').textContent.includes('已创建'));
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state: 'visible'});

    page.once('dialog', dialog => dialog.accept('M2 browser synthetic project'));
    const created = page.waitForResponse(response => response.url().endsWith('/api/projects') && response.request().method() === 'POST');
    await page.locator('#account-new-project').click();
    const response = await created;
    assert.equal(response.status(), 201, await response.text());
    projectId = (await response.json()).id;
    await page.locator('#m1-intent-form').waitFor({state: 'visible'});

    await page.locator('#m1-purpose').selectOption('PERSONAL_USE');
    await fill('#m1-raw-idea', '做一个只保存本地草稿并显示保存状态的小工具。');
    await page.locator('#m1-intent-form').evaluate(form => form.requestSubmit());
    await page.locator('#m1-action-panel').waitFor({state: 'visible'});
    await page.locator('#m1-action-confirm').click();
    await waitStatus('#m1-action-state', '已确认|CONFIRMED|确认');
    await page.locator('#m2-build-slice-panel').waitFor({state: 'visible'});

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

    const initialSlice = await page.evaluate(async id => (await fetch(`/api/projects/${id}/build-slice`)).json(), projectId);
    assert.equal(initialSlice.status, 'DRAFT');
    const currentBody = {
      slice_id: initialSlice.slice_id,
      expected_revision: initialSlice.revision,
      expected_snapshot_id: initialSlice.snapshot_id,
      expected_intent_revision: initialSlice.intent_revision,
      confirmed_constraints: initialSlice.confirmed_constraints,
      in_scope: [...initialSlice.in_scope, '记录本地时间'],
      out_of_scope: initialSlice.out_of_scope,
      minimal_flow: initialSlice.minimal_flow,
      acceptance_criteria: initialSlice.acceptance_criteria,
      inputs: initialSlice.inputs,
      expected_outputs: initialSlice.expected_outputs,
      error_handling: initialSlice.error_handling,
      unknowns: initialSlice.unknowns,
      constraint_notes: initialSlice.constraint_notes,
    };
    const updated = await putBuildSlice(currentBody);
    assert.equal(updated.status, 200, JSON.stringify(updated));
    const stale = await putBuildSlice({...currentBody, expected_revision: initialSlice.revision});
    assert.equal(stale.status, 409);

    await page.reload();
    await page.locator(`[data-open-project="${projectId}"]`).waitFor({state: 'visible'});
    await page.locator(`[data-open-project="${projectId}"]`).click();
    await page.locator('#m2-build-slice-panel').waitFor({state: 'visible'});
    await page.locator('#m2-build-slice-confirm').click();
    await waitStatus('#m2-build-slice-status', 'CONFIRMED');
    await page.locator('#m2-prototype-task-panel').waitFor({state: 'visible'});
    await page.locator('#m2-prototype-task-generate').click();
    await page.locator('#m2-prototype-task-form').waitFor({state: 'visible'});
    await waitStatus('#m2-prototype-task-status', 'DRAFT');

    const implementation = await page.locator('#m2-task-implementation-tasks').inputValue();
    await fill('#m2-task-implementation-tasks', `${implementation}\n保留用户确认的范围边界`);
    const acceptance = await page.locator('#m2-task-acceptance-steps').inputValue();
    await fill('#m2-task-acceptance-steps', `${acceptance}\n刷新页面并观察持久化结果`);
    await page.locator('#m2-prototype-task-form').evaluate(form => form.requestSubmit());
    await waitStatus('#m2-prototype-task-status', '第 2 版');
    await waitEnabled('#m2-prototype-task-confirm');
    await page.locator('#m2-prototype-task-confirm').click();
    await waitStatus('#m2-prototype-task-status', 'READY');

    await page.reload();
    await page.locator(`[data-open-project="${projectId}"]`).waitFor({state: 'visible'});
    await page.locator(`[data-open-project="${projectId}"]`).click();
    await page.locator('#m2-build-slice-panel').waitFor({state: 'visible'});
    await waitStatus('#m2-build-slice-status', 'CONFIRMED');
    await page.locator('#m2-prototype-task-panel').waitFor({state: 'visible'});
    await waitStatus('#m2-prototype-task-status', 'READY');
    assert.match(await page.locator('#m2-task-implementation-tasks').inputValue(), /保留用户确认的范围边界/);
    assert.match(await page.locator('#m2-task-acceptance-steps').inputValue(), /刷新页面并观察持久化结果/);

    for (const view of ['snapshot', 'solutions', 'evidence', 'documents', 'handoff']) {
      await page.locator(`[data-view="${view}"]`).click();
      await page.locator(`[data-workspace-view="${view}"]`).waitFor({state: 'visible'});
    }

    await page.locator('#account-logout').click();
    await page.waitForURL('**/login');
    await fill('[name=username]', 'm2foreign');
    await fill('[name=password]', 'SYNTHETIC-only-passphrase!');
    await page.locator('summary').click();
    await fill('[name=invite]', input.invites[1]);
    await page.locator('button[value=claim]').click();
    await page.waitForFunction(() => document.querySelector('#account-message').textContent.includes('已创建'));
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(async id => (await fetch(`/api/projects/${id}`)).status, projectId), 404);
    assert.equal(await page.evaluate(async id => (await fetch(`/api/projects/${id}/build-slice`)).status, projectId), 404);
    assert.equal(external, 0);
    assert.equal(forbidden, 0);
    await page.screenshot({path: 'artifacts/m2-browser/success.png'});
    console.log('PASS real Chromium: M1 → Build Slice → Prototype Task → edit/save/reopen/confirm; stale=409; account isolation; external=0; forbidden=0');
  } catch (error) {
    await page.screenshot({path: 'artifacts/m2-browser/failure.png'});
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
