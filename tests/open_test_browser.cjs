/* Real Chromium component regression: actual static assets, synthetic API only.
 * This does NOT claim authenticated backend / idea-to-handoff E2E coverage.
 * PLAYWRIGHT_MODULE and CHROMIUM_EXECUTABLE may reference an installed runtime.
 */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined});
  const failures = [], requests = [], errors = [];
  const out = 'artifacts/open-test-browser'; fs.mkdirSync(out, {recursive: true});
  try {
    for (const [width, height] of [[1366,768],[1440,900],[1920,1080],[390,844]]) {
      const context = await browser.newContext({viewport: {width,height}, serviceWorkers:'block'});
      const page = await context.newPage();
      page.on('pageerror', e => errors.push(e.message));
      await page.addInitScript(() => { window.__INSIGHTFORGE_TEST__ = true; });
      await page.route('**/*', async route => {
        const url = new URL(route.request().url());
        if (url.origin !== 'http://insightforge.test') { failures.push('external request: ' + url.origin); return route.abort(); }
        const assets = {'/':'index.html','/static/app.js':'app.js','/static/model-settings.js':'model-settings.js','/static/styles.css':'styles.css','/static/account-session.js':'account-session.js'};
        if (assets[url.pathname]) return route.fulfill({body:fs.readFileSync(path.join('app/static',assets[url.pathname])), contentType: url.pathname.endsWith('.css')?'text/css':url.pathname.endsWith('.js')?'text/javascript':'text/html'});
        if (url.pathname==='/api/auth/me') return route.fulfill({status:404,body:'Not found',contentType:'text/plain'});
        requests.push({method:route.request().method(), path:url.pathname});
        const fixtures = {
          '/api/beta/consent':{beta_mode:false,consented:true},
          '/api/health':{structured_runtime_mode:'managed'},
          '/api/settings/mode':{managed_beta_mode:true},
          '/api/projects':[], '/api/examples':[],
          '/api/projects/history':{items:[],total:0,pages:1},
          '/api/home/next-action':null,
          '/api/usage/policy':{daily_user_limits_enabled:false,limit:null,remaining:null},
        };
        if (!(url.pathname in fixtures) || route.request().method() !== 'GET') {
          failures.push('unexpected API request: '+route.request().method()+' '+url.pathname);
          return route.abort();
        }
        return route.fulfill({json:fixtures[url.pathname]});
      });
      await page.goto('http://insightforge.test/');
      await page.waitForLoadState('networkidle');
      await page.screenshot({path:`${out}/initial-${width}x${height}.png`,fullPage:true});
      const layout = await page.evaluate(() => {
        const r = document.querySelector('#quick-start-form').getBoundingClientRect();
        return {width:r.width, center:r.x+r.width/2, viewport:innerWidth, overflow:document.documentElement.scrollWidth>innerWidth};
      });
      if (layout.overflow) failures.push(`${width}: horizontal overflow`);
      if (width>1000 && (layout.width<700 || Math.abs(layout.center-width/2)>2)) failures.push(`${width}: initial form reserves an unused grid column (${JSON.stringify(layout)})`);
      await page.evaluate(() => {
        const h=window.InsightForgeUi.__test;
        h.state.solutions={candidates:[{id:'synthetic',title:'合成方案',features:['只读功能']}],selected_candidate_id:'unchanged'};
        const trigger=document.querySelector('#settings-button'); trigger.focus();
        h.openSolutionDetails('synthetic',trigger);
      });
      await page.screenshot({path:`${out}/detail-${width}x${height}.png`,fullPage:true});
      assert.equal(await page.locator('#solution-detail-dialog').evaluate(d=>d.open),true);
      await page.keyboard.press('Escape');
      await page.waitForFunction(()=>!document.querySelector('#solution-detail-dialog').open);
      assert.equal(await page.evaluate(()=>document.activeElement.id),'settings-button');
      assert.equal(await page.evaluate(()=>window.InsightForgeUi.__test.state.solutions.selected_candidate_id),'unchanged');
      await context.close();
    }
    assert.deepEqual(errors,[],'no uncaught page errors');
    fs.writeFileSync(`${out}/result.json`,JSON.stringify({method:'Chromium static-page/component + synthetic GET fixtures',zoom:'NOT_RUN',full_user_e2e:'NOT_RUN',failures,errors,requests},null,2));
    assert.deepEqual(failures,[]);
    console.log('Chromium component PASS: 1366x768,1440x900,1920x1080,390x844; native Esc/focus; zero non-fixture requests. Zoom/full-user E2E NOT_RUN.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
