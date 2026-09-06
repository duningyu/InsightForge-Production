const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/ASUS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_PATH || 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'});
  const context = await browser.newContext({viewport:{width:1366,height:768}});
  let external = 0, posts = 0, analyses = 0;
  await context.route('**/*', route => {
    if (!route.request().url().startsWith(input.url + '/')) { external++; return route.abort(); }
    if (route.request().method() === 'POST') {
      if (/\/solutions\/generate$/.test(route.request().url())) posts++;
      if (/\/evidence\/analyze$/.test(route.request().url())) analyses++;
    }
    return route.continue();
  });
  const page = await context.newPage();
  fs.mkdirSync('artifacts/account-business-browser', {recursive:true});
  try {
    await page.goto(input.url + '/login');
    await page.locator('[name=username]').fill(input.username);
    await page.locator('[name=password]').fill(input.password);
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state:'visible'});
    await page.locator('#beta-consent-accept').click();
    await page.locator(`[data-open-project="${input.projects[0]}"]`).click();
    for (let i=0; i<4; i++) {
      await page.locator('#project-select').selectOption(input.projects[i]);
      await page.locator('.nav-item[data-view=solutions]').click();
      await page.locator('#generate-solutions-button').waitFor({state:'visible'});
      assert.equal(await page.locator('#generate-solutions-button').isEnabled(), true);
      assert.match(await page.locator('#usage-policy').innerText(), /不设每日次数限制/);
      const terminal = page.waitForResponse(async r => /\/solutions\/generate\//.test(r.url()) && (await r.json()).status === 'SUCCEEDED', {timeout:30000});
      await page.locator('#generate-solutions-button').click();
      await terminal;
      await page.locator('.solution-card').first().waitFor({state:'visible'});
    }
    await page.screenshot({path:'artifacts/account-business-browser/fourth-generation-terminal.png'});
    await page.locator('.nav-item[data-view=evidence]').click();
    await page.locator('[data-evidence-tab=sources]').click();
    const analyzed = page.waitForResponse(r => /\/evidence\/analyze$/.test(r.url()) && r.request().method()==='POST', {timeout:30000});
    await page.locator('#analyze-evidence-button').click();
    const response = await analyzed;
    assert.equal(response.status(),200,await response.text());
    await page.getByText('资料影响分析完成；正式项目判断不会自动修改。', {exact:true}).waitFor();
    await page.screenshot({path:'artifacts/account-business-browser/six-claim-analysis-terminal.png'});
    await page.reload();
    await page.locator('#usage-policy').waitFor({state:'visible'});
    assert.match(await page.locator('#usage-policy').innerText(), /不设每日次数限制/);
    assert.doesNotMatch(await page.locator('#usage-policy').innerText(), /剩余\s*0|每日\s*[35]\s*次/);
    assert.equal(posts,4); assert.equal(analyses,1); assert.equal(external,0);
    await page.screenshot({path:'artifacts/account-business-browser/completed.png'});
    console.log('PASS Chromium normal buttons: four terminal generations; six-claim analysis; reload policy; external=0');
  } catch(error) {
    await page.screenshot({path:'artifacts/account-business-browser/failure.png'});
    throw error;
  } finally { await browser.close(); }
})().catch(error => {console.error(error.stack); process.exitCode=1;});
