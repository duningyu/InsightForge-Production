/* Real Chromium + actual UI startup, all transport intercepted. No production data. */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROMIUM_EXECUTABLE});
  const out='artifacts/loading-progress-browser'; fs.mkdirSync(out,{recursive:true});
  const results=[];
  try {
    for (const [width,height] of [[1366,768],[1440,900],[1920,1080],[390,844]]) {
      const context=await browser.newContext({viewport:{width,height},serviceWorkers:'block'});
      const page=await context.newPage(); const unexpected=[], errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      let release; const healthGate=new Promise(r=>release=r);
      const fixtures={
        '/api/beta/consent':{beta_mode:false,consented:true},
        '/api/health':{structured_runtime_mode:'managed'},
        '/api/settings/mode':{managed_beta_mode:true},
        '/api/projects':[], '/api/examples':[],
        '/api/projects/history':{items:[],total:0,pages:1}, '/api/home/next-action':null,
        '/api/usage/policy':{daily_user_limits_enabled:false,limit:null,remaining:null},
      };
      await page.route('**/*',async route=>{
        const url=new URL(route.request().url());
        const assets={'/':'index.html','/static/app.js':'app.js','/static/styles.css':'styles.css','/static/model-settings.js':'model-settings.js','/static/account-session.js':'account-session.js'};
        if (url.origin==='http://insightforge.test' && assets[url.pathname]) {
          return route.fulfill({body:fs.readFileSync('app/static/'+assets[url.pathname]),contentType:url.pathname.endsWith('.js')?'text/javascript':url.pathname.endsWith('.css')?'text/css':'text/html'});
        }
        if (url.pathname==='/api/auth/me') return route.fulfill({status:404,body:'Not found',contentType:'text/plain'});
        if (url.origin!=='http://insightforge.test'||route.request().method()!=='GET'||!(url.pathname in fixtures)) {
          unexpected.push(route.request().method()+' '+url.pathname); return route.abort();
        }
        if (url.pathname==='/api/health') await healthGate;
        return route.fulfill({json:fixtures[url.pathname]});
      });
      await page.goto('http://insightforge.test/',{waitUntil:'domcontentloaded'});
      await page.locator('#loading-status').waitFor({state:'visible'});
      assert.equal(await page.locator('#loading-progress').evaluate(el=>el.position),-1,'native indeterminate progress, no invented percentage');
      assert.match(await page.locator('#loading-message').innerText(),/加载/);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:`${out}/pending-${width}x${height}.png`,fullPage:true});
      release();
      await page.waitForLoadState('networkidle');
      await page.locator('#loading-status').waitFor({state:'hidden'});
      assert.deepEqual(unexpected,[]); assert.deepEqual(errors,[]);
      results.push({width,height,loading:'PASS',completion:'PASS',unexpected_requests:0});
      await context.close();
    }
    fs.writeFileSync(`${out}/result.json`,JSON.stringify({method:'real Chromium startup with synthetic intercepted GET transport',results,zoom:'NOT_RUN',full_user_flow:'NOT_RUN'},null,2));
    console.log('Chromium loading PASS: 4 viewports; actual bootstrap pending/complete; indeterminate progress; external requests 0');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
