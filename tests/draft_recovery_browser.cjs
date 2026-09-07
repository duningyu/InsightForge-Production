const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

async function login(page, input, account) {
  await page.goto(input.url + '/login');
  await page.locator('[name=username]').fill(account.username);
  await page.locator('[name=password]').fill(account.password);
  await page.locator('button[value=login]').click();
  await page.locator('#account-controls').waitFor({state:'visible'});
  const accept = page.locator('#beta-consent-dialog #beta-consent-accept');
  if (await accept.waitFor({state:'visible', timeout:5000}).then(() => true).catch(() => false)) await accept.click();
  await page.waitForLoadState('networkidle');
}

async function openProject(page, input, projectId) {
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.goto(input.url + '/');
    await page.locator('#account-controls').waitFor({state:'visible'});
    await page.waitForFunction(id => Boolean(document.querySelector(`[data-open-project="${id}"]`)), projectId);
    const projectCard = page.locator(`[data-open-project="${projectId}"]:visible`).first();
    await projectCard.waitFor({state:'visible', timeout:30000});
    // Use a real Playwright click so the test waits for the current home render
    // and exercises the same browser event path as a user click.
    await projectCard.click();
    try {
      await page.locator('#project-shell').waitFor({state:'visible', timeout:5000});
      break;
    } catch (error) {
      if (attempt === 1) {
        const projects = await page.locator('[data-open-project]').evaluateAll(nodes => nodes.map(n => ({id:n.getAttribute('data-open-project'), text:n.textContent}))).catch(() => []);
        const body = (await page.locator('body').innerText().catch(() => '')).slice(0, 3000);
        throw new Error(`project did not open id=${projectId} url=${page.url()} projects=${JSON.stringify(projects)} body=${JSON.stringify(body)}`);
      }
    }
  }
  await page.waitForFunction(() => {
    const node = document.querySelector('#solutions-content');
    return Boolean(node && node.innerHTML.trim());
  });
  // loadProject() restores the saved view after its parallel project loads.
  // Let that lifecycle settle before the next user navigation action.
  await page.waitForTimeout(500);
}

async function openCompetitors(page) {
  const solutionsNav = page.locator('[data-view=solutions]:visible').first();
  await page.locator('#project-shell').waitFor({state:'visible', timeout:30000}).catch(async () => {
    throw new Error(`project shell not visible before competitors url=${page.url()} shell=${await page.locator('#project-shell').getAttribute('class')} login=${await page.locator('#account-controls').getAttribute('class')} body=${JSON.stringify((await page.locator('body').innerText()).slice(0, 1800))}`);
  });
  await page.locator('#primary-nav').waitFor({state:'visible', timeout:30000});
  await solutionsNav.waitFor({state:'visible', timeout:30000}).catch(async () => {
    throw new Error(`solutions nav not visible url=${page.url()} shell=${await page.locator('#project-shell').getAttribute('class')} nav=${await page.locator('#primary-nav').getAttribute('class')} body=${JSON.stringify((await page.locator('body').innerText()).slice(0, 2000))}`);
  });
  await solutionsNav.evaluate((node) => node.click());
  const competitorOpen = page.locator('#solutions-view #competitor-open').first();
  await competitorOpen.waitFor({state:'attached', timeout:30000});
  await competitorOpen.evaluate((node) => node.click());
  await page.locator('#competitor-dialog').waitFor({state:'visible'});
}

async function clickView(page, view) {
  const nav = page.locator(`[data-view=${view}]:visible`).first();
  await nav.waitFor({ state: 'visible', timeout: 30000 }).catch(async () => {
    throw new Error(`view nav not visible view=${view} url=${page.url()} shell=${await page.locator('#project-shell').getAttribute('class')} nav=${await page.locator('#primary-nav').getAttribute('class')} navCount=${await page.locator('[data-view]').count()} body=${JSON.stringify((await page.locator('body').innerText()).slice(0, 1800))}`);
  });
  await nav.click();
  // Navigation is handled asynchronously by the app.  Wait for the target
  // workspace to become visible before asserting restored content; otherwise
  // a hidden card from the previous render can be mistaken for a lost draft.
  await page.locator(`#${view}-view`).waitFor({ state: 'visible', timeout: 30000 });
}

async function ensureIdeaBriefConfirmed(page) {
  const generate = page.locator('#generate-solutions-button').first();
  const review = page.locator('#open-idea-brief-button').first();
  const action = page.locator('#generate-solutions-button, #open-idea-brief-button').first();
  await action.waitFor({state:'attached', timeout:30000}).catch(async () => {
    throw new Error(`idea brief action unavailable url=${page.url()} solutions=${JSON.stringify(await page.locator('#solutions-content').innerText().catch(() => ''))} html=${JSON.stringify((await page.locator('#solutions-content').innerHTML().catch(() => '')).slice(0, 2000))}`);
  });
  if ((await generate.count()) === 0) {
    await review.click();
    await page.locator('#idea-brief-dialog').waitFor({state:'visible'});
    const response = page.waitForResponse(r => r.url().includes('/idea-brief/confirm') && r.request().method() === 'POST');
    await page.locator('#idea-brief-confirm').click();
    assert.equal((await response).status(), 200);
  }
  await generate.waitFor({state:'attached'});
}

async function addCandidate(page, name) {
  await page.locator('#competitor-name').fill(name);
  await page.locator('#competitor-url').fill('');
  await page.locator('#competitor-description').fill(`${name} synthetic candidate`);
  const response = page.waitForResponse(r => r.url().includes('/competitors') && r.request().method() === 'POST');
  await page.locator('#competitor-add').click();
  assert.equal((await response).status(), 201);
  await page.locator('#competitor-list .secondary-panel').filter({hasText:name}).first().waitFor({state:'visible', timeout:30000});
}

async function selectCandidate(page, name) {
  const card = page.locator('#competitor-list .secondary-panel').filter({hasText:name}).first();
  await card.waitFor({state:'visible', timeout:30000});
  const response = page.waitForResponse(r => r.url().includes('/selection') && r.request().method() === 'PUT');
  await card.getByRole('button', {name:'加入本次比较'}).click({force:true});
  assert.equal((await response).status(), 200);
  await page.locator('#competitor-compare:visible').waitFor({state:'visible', timeout:30000});
}

(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({
    headless:true,
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})
  });
  const context = await browser.newContext({viewport:{width:1366,height:768}});
  let external = 0, generationPosts = 0, comparisonPosts = 0, snapshotPosts = 0, documentVersionPosts = 0;
  let pollGetCount = 0, lateHeld = false;
  await context.route('**/*', route => {
    const request = route.request();
    const url = request.url();
    if (!url.startsWith(input.url + '/')) { external++; return route.abort(); }
    if (request.method() === 'POST' && /\/solutions\/generate$/.test(url)) generationPosts++;
    if (request.method() === 'GET' && /\/solutions\/generate\//.test(url)) pollGetCount++;
    if (request.method() === 'POST' && /\/competitor-comparisons$/.test(url)) comparisonPosts++;
    if (request.method() === 'POST' && /competitor-snapshots/.test(url)) snapshotPosts++;
    if (request.method() === 'POST' && /document-versions/.test(url)) documentVersionPosts++;
    return route.continue();
  });
  const page = await context.newPage();
  const result = {
    flowA:false, flowB:false, flowC:false, flowD:false, flowE:false, flowF:false,
    external:0, generationPosts:0, pollGetCount:0, comparisonPosts:0, snapshotPosts:0, documentVersionPosts:0,
    generationUiActions:0, logicalTaskCount:0, fakeProviderCalls:{generation:0, comparison:0}
  };
  try {
    await login(page, input, input.userA);
    const projectA = input.projectA;
    await openProject(page, input, projectA);

    // A: generation is submitted once, restored by navigation and refresh, then released.
    await clickView(page, 'solutions');
    await ensureIdeaBriefConfirmed(page);
    const generateButton = page.locator('#generate-solutions-button').first();
    await generateButton.waitFor({state:'attached'});
    await generateButton.waitFor({state:'attached'});
    await generateButton.evaluate(el => { if (el.disabled) throw new Error('generation button unexpectedly disabled'); });
    const generateResponse = page.waitForResponse(r => r.url().includes('/solutions/generate') && r.request().method() === 'POST', {timeout: 60000});
    await generateButton.evaluate((node) => node.click());
    result.generationUiActions++;
    assert.equal((await generateResponse).status(), 202);
    result.logicalTaskCount = 1;
    await page.locator('#generation-progress-close').click();
    await clickView(page, 'evidence');
    await clickView(page, 'solutions');
    await page.waitForTimeout(300);
    fs.closeSync(fs.openSync(input.releasePath, 'w'));
    await page.locator('#solutions-content .solution-card').first().waitFor({state:'visible', timeout:15000});
    await page.reload();
    await openProject(page, input, projectA);
    await clickView(page, 'solutions');
    await page.locator('#solutions-content .solution-card').first().waitFor({state:'visible', timeout:15000});
    result.flowA = true;

    // B: synchronous comparison result and unsaved decisions are restored without another POST.
    await openCompetitors(page);
    await addCandidate(page, '浏览器候选A');
    await addCandidate(page, '浏览器候选B');
    await selectCandidate(page, '浏览器候选A');
    const compareResponse = page.waitForResponse(r => r.url().endsWith('/competitor-comparisons') && r.request().method() === 'POST');
    await page.locator('#competitor-compare').click();
    assert.equal((await compareResponse).status(), 201);
    const decision = page.locator('#competitor-decisions select').first();
    if (await decision.count()) await decision.selectOption({index:1});
    const rationale = page.locator('#competitor-decisions input').first();
    if (await rationale.count()) await rationale.fill('浏览器恢复测试保留的决策原因');
    await page.waitForTimeout(800);
    await page.locator('#competitor-close').click();
    await openCompetitors(page);
    await page.locator('#competitor-decisions select').first().waitFor({state:'attached', timeout:15000});
    assert.match(await page.locator('#competitor-decisions').textContent(), /浏览器恢复测试保留的决策原因|采用|暂不采用|以后再考虑/);
    await page.reload();
    await openProject(page, input, projectA);
    await openCompetitors(page);
    await page.locator('#competitor-decisions select').first().waitFor({state:'attached', timeout:15000});
    assert.match(await page.locator('#competitor-decisions').textContent(), /浏览器恢复测试保留的决策原因|采用|暂不采用|以后再考虑/);
    result.flowB = true;
    await page.locator('#competitor-close').click();

    // C: history state navigation changes modules without action POSTs.
    const countsBeforeHistory = [generationPosts, comparisonPosts, snapshotPosts, documentVersionPosts];
    await clickView(page, 'snapshot');
    await clickView(page, 'solutions');
    await clickView(page, 'documents');
    await page.goBack(); await page.waitForTimeout(150);
    await page.goBack(); await page.waitForTimeout(150);
    await page.goForward(); await page.waitForTimeout(150);
    assert.ok(await page.locator('[data-view=solutions].active, #solutions-view:visible').count());
    assert.deepEqual([generationPosts, comparisonPosts, snapshotPosts, documentVersionPosts], countsBeforeHistory);
    result.flowC = true;

    // D: hold a unique A draft response, switch to B, then release it.
    const uniqueA = 'A-迟到响应专属内容';
    const lateGate = new Promise(resolve => { page.__releaseLate = resolve; });
    const lateResponse = page.waitForResponse(r => r.url().includes(`/api/projects/${projectA}/drafts/competitor_decision/form`) && r.request().method() === 'PUT' && (r.request().postData() || '').includes(uniqueA), {timeout: 30000});
    await context.route(`**/api/projects/${projectA}/drafts/competitor_decision/form`, async route => {
      const body = route.request().postData() || '';
      if (!lateHeld && body.includes(uniqueA) && route.request().method() === 'PUT') {
        lateHeld = true; await lateGate; return route.continue();
      }
      return route.continue();
    });
    await openCompetitors(page);
    await page.locator('#competitor-name').fill(uniqueA);
    await page.waitForTimeout(700);
    assert.equal(lateHeld, true);
    await page.locator('#competitor-close').click();
    // Keep A's page/request alive while B uses an isolated browser context.
    // Switching cookies in the same context would cancel A's in-flight request,
    // which would test navigation cancellation rather than late-response safety.
    const contextB = await browser.newContext({ ignoreHTTPSErrors: true });
    await contextB.route('**/*', async route => {
      if (!route.request().url().startsWith(input.url)) { external += 1; return route.abort(); }
      return route.continue();
    });
    const pageB = await contextB.newPage();
    await login(pageB, input, input.userB);
    await openProject(pageB, input, input.projectB);
    await openCompetitors(pageB);
    assert.notEqual(await pageB.locator('#competitor-name').inputValue(), uniqueA);
    page.__releaseLate();
    await lateResponse;
    await page.waitForTimeout(300);
    await contextB.close();
    await page.goto(input.url + '/');
    await openProject(page, input, projectA); await openCompetitors(page);
    assert.equal(await page.locator('#competitor-name').inputValue(), uniqueA);
    result.flowD = true;

    // E: fresh account switch does not expose A's draft to B.
    await page.locator('#competitor-close').click();
    await page.locator('#account-logout').click(); await page.waitForURL('**/login');
    await login(page, input, input.userB);
    await openProject(page, input, input.projectB); await openCompetitors(page);
    assert.notEqual(await page.locator('#competitor-name').inputValue(), uniqueA);
    result.flowE = true;

    // F: two tabs use the server revision/CAS path, not a JS-only helper.
    await login(page, input, input.userA);
    await openProject(page, input, projectA); await openCompetitors(page);
    const tab2 = await context.newPage();
    await login(tab2, input, input.userA); await openProject(tab2, input, projectA); await openCompetitors(tab2);
    await page.locator('#competitor-name').fill('Tab A 最新内容'); await page.waitForTimeout(900);
    await tab2.locator('#competitor-name').fill('Tab B 旧版本内容'); await tab2.waitForTimeout(900);
    assert.match(await tab2.locator('#draft-recovery-status').innerText(), /其他页面更新|临时保留|冲突/);
    assert.equal(await page.locator('#competitor-name').inputValue(), 'Tab A 最新内容');
    await tab2.close(); result.flowF = true;

    result.external = external; result.generationPosts = generationPosts; result.pollGetCount = pollGetCount;
    result.comparisonPosts = comparisonPosts; result.snapshotPosts = snapshotPosts; result.documentVersionPosts = documentVersionPosts;
    assert.equal(external, 0); assert.equal(generationPosts, 1); assert.equal(comparisonPosts, 1);
    assert.deepEqual([result.flowA,result.flowB,result.flowC,result.flowD,result.flowE,result.flowF], [true,true,true,true,true,true]);
    console.log(JSON.stringify(result));
  } catch (error) {
    result.external = external; result.generationPosts = generationPosts; result.pollGetCount = pollGetCount;
    result.comparisonPosts = comparisonPosts; result.snapshotPosts = snapshotPosts; result.documentVersionPosts = documentVersionPosts;
    console.error(JSON.stringify(result)); console.error(error.stack); process.exitCode = 1;
  } finally { await browser.close(); }
})();
