const fs=require('node:fs');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/ASUS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
  const input=JSON.parse(fs.readFileSync(0,'utf8'));
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH || 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'});
  const context=await browser.newContext({viewport:{width:1366,height:768}});
  let external=0,posts=0,cancels=0;
  await context.route('**/*',route=>{
    const r=route.request();
    if(!r.url().startsWith(input.url+'/')) {external++;return route.abort();}
    if(r.method()==='POST' && /\/solutions\/generate$/.test(r.url()))posts++;
    if(r.method()==='POST' && /\/cancel$/.test(r.url()))cancels++;
    return route.continue();
  });
  const page=await context.newPage();
  page.on('pageerror',e=>console.error('PAGE_ERROR',e.message));
  page.on('response',r=>{if(/\/solutions\/generate/.test(r.url()))console.log('RUN_RESPONSE',r.request().method(),r.status());});
  fs.mkdirSync('artifacts/account-cancel-browser',{recursive:true});
  try {
    await page.goto(input.url+'/login');
    await page.locator('[name=username]').fill(input.username);
    await page.locator('[name=password]').fill(input.password);
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state:'visible'});
    await page.locator('#beta-consent-accept').click();
    await page.locator(`[data-open-project="${input.projects[0]}"]`).click();
    await page.locator('.nav-item[data-view=solutions]').click();
    const running=page.waitForResponse(async r=>r.request().method()==='GET' && /\/solutions\/generate\//.test(r.url()) && (await r.json()).status==='RUNNING');
    const [runningResponse]=await Promise.all([running,page.locator('#generate-solutions-button').click()]);
    const run=await runningResponse.json();
    await page.locator('#generation-progress-close').click();
    assert.equal(cancels,0);
    await page.locator('#generation-progress-open').click();
    assert.equal(posts,1);
    const terminal=page.waitForResponse(async r=>r.request().method()==='GET' && /\/solutions\/generate\//.test(r.url()) && (await r.json()).error_code==='ASYNC_GENERATION_CANCELLED');
    await page.locator('#generation-stop').click();
    await terminal;
    await page.getByText('任务已停止。已发生的模型调用记录仍保留，停止任务不代表远端费用已取消。',{exact:true}).waitFor();
    await page.screenshot({path:'artifacts/account-cancel-browser/cancelled.png'});
    await page.reload();
    await page.locator('#generation-progress-open').waitFor({state:'visible'});
    await page.locator('#generation-progress-open').click();
    await page.getByText('任务已停止。已发生的模型调用记录仍保留，停止任务不代表远端费用已取消。',{exact:true}).waitFor();
    assert.equal(posts,1);assert.equal(cancels,1);assert.equal(external,0);
    const foreign=await browser.newContext();
    const response=await foreign.request.post(input.url+'/api/auth/claim',{headers:{'X-InsightForge-Request':'1'},data:{username:'cancel-foreign',password:'SYNTHETIC-only-passphrase!',invite:input.invites[1]}});
    assert.equal(response.status(),201);
    assert.equal((await foreign.request.post(input.url+'/api/auth/login',{headers:{'X-InsightForge-Request':'1'},data:{username:'cancel-foreign',password:'SYNTHETIC-only-passphrase!'}})).status(),200);
    const denied=await foreign.request.post(`${input.url}/api/projects/${input.projects[0]}/solutions/generate/${run.generation_run_id}/cancel`,{headers:{'X-InsightForge-Request':'1'},data:{user_id:input.account,workspace:input.account}});
    assert.equal(denied.status(),404);
    await foreign.close();
    console.log('PASS Chromium owner stop/close/reopen/refresh; foreign 404; UI generate=1 cancel=1; external=0');
  } catch(e) {await page.screenshot({path:'artifacts/account-cancel-browser/failure.png'});throw e;}
  finally {await browser.close();}
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
