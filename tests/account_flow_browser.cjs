const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/ASUS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH || 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'});
  const context = await browser.newContext({viewport: {width:1366, height:768}});
  let external = 0, generation = 0;
  await context.route('**/*', route => {
    const url = route.request().url();
    if (!url.startsWith(input.url + '/')) { external++; return route.abort(); }
    if (/\/generate|\/evidence\/analyze|\/search/.test(url)) { generation++; return route.abort(); }
    return route.continue();
  });
  const page = await context.newPage();
  fs.mkdirSync('artifacts/account-browser', {recursive:true});
  let foreign;
  try {
    for (let i=0; i<2; i++) {
      await page.goto(input.url + '/login');
      await page.locator('[name=username]').fill('browser' + i);
      await page.locator('[name=password]').fill('SYNTHETIC-only-passphrase!');
      await page.locator('summary').click();
      await page.locator('[name=invite]').fill(input.invites[i]);
      await page.locator('button[value=claim]').click();
      await page.waitForFunction(() => document.querySelector('#account-message').textContent.includes('已创建'));
      await page.locator('button[value=login]').click();
      await page.locator('#account-controls').waitFor({state:'visible'});
      await page.locator('#usage-policy').waitFor({state:'visible', timeout:5000});
      assert.match(await page.locator('#usage-policy').innerText(), /不设每日次数限制/);
      assert.doesNotMatch(await page.locator('#usage-policy').innerText(), /剩余\s*0|每日\s*[35]\s*次/);
      const policy = await page.evaluate(async () => (await fetch('/api/usage/policy')).json());
      assert.equal(policy.daily_user_limits_enabled, false);
      assert.equal(policy.operations.solution_generation.remaining, null);
      if (foreign) {
        const code = await page.evaluate(async id => (await fetch('/api/projects/' + id)).status, foreign);
        assert.equal(code, 404);
      }
      page.once('dialog', dialog => dialog.accept('Browser synthetic project ' + i));
      const created = page.waitForResponse(r => r.url().endsWith('/api/projects') && r.request().method()==='POST');
      await page.locator('#account-new-project').click();
      const response = await created;
      assert.equal(response.status(), 201, await response.text());
      foreign = (await response.json()).id;
      await page.reload();
      await page.locator('#account-controls').waitFor({state:'visible'});
      await page.locator('#usage-policy').waitFor({state:'visible'});
      assert.match(await page.locator('#usage-policy').innerText(), /不设每日次数限制/);
      assert.equal(await page.evaluate(async id => (await fetch('/api/projects/' + id)).status, foreign), 200);
      await page.screenshot({path:`artifacts/account-browser/user-${i}.png`});
      await page.locator('#account-logout').click();
      await page.waitForURL('**/login');
      assert.equal(await page.evaluate(async () => (await fetch('/api/projects')).status), 401);
    }
    assert.equal(external, 0); assert.equal(generation, 0);
    console.log('PASS real Chromium: claim/login/create/save/reload/logout/account-switch/backend denial; external=0; generation=0');
  } catch(error) {
    await page.screenshot({path:'artifacts/account-browser/failure.png'});
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode=1; });
