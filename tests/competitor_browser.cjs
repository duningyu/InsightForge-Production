// Candidate -> comparison -> decision -> snapshot -> generation -> document-link UI proof.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/ASUS/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const browser = await chromium.launch({headless:true, executablePath: process.env.CHROMIUM_PATH || 'C:/Users/ASUS/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'});
  const context = await browser.newContext({viewport:{width:1366,height:768}});
  let external=0, modelOrSearch=0;
  await context.route('**/*', route => {
    const url=route.request().url();
    if (!url.startsWith(input.url+'/')) { external++; return route.abort(); }
    if (/\/search/.test(url)) { modelOrSearch++; return route.abort(); }
    return route.continue();
  });
  const page=await context.newPage();
  page.on('pageerror', error => console.log(`pageerror=${error.message}`));
  page.on('requestfailed', request => console.log(`requestfailed=${request.url()} ${request.failure()?.errorText || ''}`));
  page.on('response', async response => { if (response.url().includes('/api/projects')) { console.log(`project_response=${response.status()} ${response.url()}`); if (response.url().includes('competitor-comparisons') && response.status() >= 400) console.log(`comparison_error=${await response.text().catch(()=>'<unreadable>')}`); } });
  fs.mkdirSync('artifacts/competitor-browser',{recursive:true});
  try {
    await page.goto(input.url+'/login');
    await page.locator('[name=username]').fill(input.username);
    await page.locator('[name=password]').fill(input.password);
    if (!input.prepared) {
      await page.locator('summary').click();
      await page.locator('[name=invite]').fill(input.invites[0]);
      await page.locator('button[value=claim]').click();
      await page.waitForFunction(()=>document.querySelector('#account-message').textContent.includes('已创建'));
    }
    await page.locator('button[value=login]').click();
    await page.locator('#account-controls').waitFor({state:'visible'});
    const consent=page.locator('#beta-consent-dialog');
    // Consent is bootstrapped asynchronously after account controls become
    // visible; wait briefly for it instead of racing the home project load.
    const consentButton=consent.locator('#beta-consent-accept');
    if (await consentButton.waitFor({state:'visible',timeout:5000}).then(()=>true).catch(()=>false)) {
      await consentButton.click();
      await consent.waitFor({state:'hidden'});
    }
    // Account controls can appear before the parallel home bootstrap finishes.
    await page.waitForLoadState('networkidle');
    const project=input.project;
    await page.waitForFunction((id)=>Boolean(document.querySelector(`[data-open-project="${id}"]`)), project, {timeout:10000}).catch(async error=>{
      const visibleProjects = await page.locator('#recent-project-list').innerText().catch(()=>'<missing>');
      const options = await page.locator('#project-select option').allTextContents().catch(()=>[]);
      throw new Error(`${error.message}; recent=${visibleProjects}; options=${JSON.stringify(options)}; project=${project}`);
    });
    await page.locator(`[data-open-project="${project}"]`).click();
    // The initial home bootstrap can finish after the project-card click. If it
    // wins that race, use the same user-facing "continue" action once, then
    // assert that the project shell is actually visible before navigating.
    await page.waitForTimeout(250);
    if (!(await page.locator('#project-shell').isVisible())) {
      const continueButton = page.locator('#home-next-action-card button');
      if (await continueButton.isVisible().catch(() => false)) await continueButton.click();
    }
    await page.locator('#project-shell').waitFor({state:'visible', timeout:10000});
    await page.locator('[data-view=solutions]').click();
    await page.locator('#solutions-view').waitFor({state:'visible'});
    await page.locator('#competitor-open').click({timeout:3000});
    const panel=page.locator('#competitor-dialog');
    await panel.waitFor({state:'visible'});
    await page.waitForFunction(()=>document.querySelector('#competitor-message').textContent.includes('没有候选'));
    assert.match(await panel.innerText(),/联网查找暂未开启/);
    await page.route('**/competitors',route=>route.request().method()==='POST'
      ? route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Synthetic unavailable'})})
      : route.continue());
    await page.locator('#competitor-name').fill('Unsaved synthetic draft');
    await page.locator('#competitor-add').click();
    await page.waitForFunction(()=>document.querySelector('#competitor-message').textContent.includes('保存未完成'));
    assert.doesNotMatch(await page.locator('#competitor-message').innerText(),/网址需/,'unknown save failure must not invent a validation cause');
    assert.equal(await page.locator('#competitor-name').inputValue(),'Unsaved synthetic draft');
    await page.unroute('**/competitors');
    for(const name of ['Synthetic product A','Synthetic product B']) {
      await page.locator('#competitor-name').fill(name);
      await page.locator('#competitor-description').fill('用户猜想，尚未确认');
      const added=page.waitForResponse(r=>r.url().endsWith('/competitors')&&r.request().method()==='POST');
      await page.locator('#competitor-add').click();
      assert.equal((await added).status(),201);
      await page.getByText(name,{exact:true}).waitFor();
    }
    const getCandidates=()=>page.evaluate(async p=>(await fetch(`/api/projects/${p}/competitors`)).json(),project);
    let candidates=(await getCandidates()).candidates;
    assert.equal(candidates.length,2);
    assert.ok(candidates.every(c=>!c.selected));
    const first=panel.locator('[data-candidate]').filter({hasText:'Synthetic product A'});
    await first.getByRole('button',{name:'查看',exact:true}).click();
    assert.ok((await getCandidates()).candidates.every(c=>!c.selected));
    let releaseSelection;
    const selectionGate=new Promise(resolve=>{releaseSelection=resolve;});
    await page.route('**/competitors/*/selection',async route=>{await selectionGate; await route.continue();});
    await first.getByRole('button',{name:'加入本次比较',exact:true}).click();
    assert.equal(await page.locator('#competitor-close').isEnabled(),true,'close must remain available while saving');
    assert.equal(await page.locator('#competitor-name').isDisabled(),true,'avoid losing edits entered during save');
    await page.locator('#competitor-close').click();
    await panel.waitFor({state:'hidden'});
    releaseSelection();
    await page.locator('#competitor-open').click();
    await first.getByRole('button',{name:'移出本次比较',exact:true}).waitFor();
    assert.equal((await getCandidates()).candidates.filter(c=>c.selected).length,1);
    await page.keyboard.press('Escape');
    await panel.waitFor({state:'hidden'});
    assert.equal(await page.evaluate(()=>document.activeElement.id),'competitor-open');
    await page.locator('#competitor-open').click();
    await first.getByRole('button',{name:'移出本次比较',exact:true}).waitFor();
    await page.locator('#competitor-compare').click();
    await page.locator('#competitor-comparison').waitFor({state:'visible'});
    assert.match(await page.locator('#competitor-comparison').innerText(),/AI分析参考/);
    const decision=page.locator('#competitor-decisions select').first();
    await decision.selectOption('adopt');
    await page.locator('#competitor-decisions input').first().fill('借鉴分步引导');
    const saved=page.waitForResponse(r=>r.url().endsWith('/competitor-snapshots')&&r.request().method()==='POST');
    await page.locator('#competitor-save-snapshot').click();
    const savedResponse=await saved;
    assert.equal(savedResponse.status(),201);
    const savedPayload=await savedResponse.json();
    const snapshotId=savedPayload.id || savedPayload.decision_snapshot?.id || savedPayload.snapshot_id;
    assert.ok(snapshotId,'snapshot response must expose a stable identity');
    await page.waitForFunction(()=>document.querySelector('#competitor-message').textContent.includes('本次比较已保存'));
    const second=panel.locator('[data-candidate]').filter({hasText:'Synthetic product B'});
    await second.getByRole('button',{name:'移除候选',exact:true}).click();
    await second.waitFor({state:'detached'});
    assert.equal((await getCandidates()).candidates.length,1);
    await page.screenshot({path:'artifacts/competitor-browser/panel.png'});
    await page.locator('#competitor-close').click();
    await panel.waitFor({state:'hidden'});
    await page.locator('#generate-solutions-button').click();
    await page.locator('.solution-card').first().waitFor({state:'visible',timeout:15000});
    await page.locator('.select-solution-button').first().click();
    // Selecting a solution performs async snapshot/document loading and can
    // finish after the click. Re-open Documents after that work settles so a
    // late activateView("snapshot") cannot race the document controls.
    const openDocuments = async () => {
      for (let attempt = 0; attempt < 3; attempt += 1) {
        await page.locator('[data-view=documents]').click();
        await page.locator('#documents-view').waitFor({state:'visible'});
        await page.waitForTimeout(300);
        if (await page.locator('#documents-view').isVisible()) return;
      }
      throw new Error('documents view did not remain active after navigation');
    };
    await openDocuments();
    const generateDocumentFromUI = async (docType) => {
      const button = page.locator(`[data-generate-doc="${docType}"]`).first();
      await button.waitFor({state:'visible'});
      const responsePromise = page.waitForResponse(response =>
        response.url().includes('/documents/generate') &&
        response.request().method() === 'POST'
      );
      await button.click();
      const response = await responsePromise;
      assert.equal(response.status(), 200, `${docType} generation must finish successfully`);
      await page.locator('#loading-status').waitFor({state:'hidden', timeout:15000});
    };
    await generateDocumentFromUI('prd');
    await openDocuments();
    await generateDocumentFromUI('techdoc');
    const linkedVersions=await page.evaluate(async projectId=>{
      const rows=[];
      for (const docType of ['prd','techdoc']) {
        const response=await fetch(`/api/projects/${projectId}/documents/${docType}/versions`);
        rows.push(...await response.json());
      }
      return rows;
    },project);
    assert.equal(linkedVersions.length,2,'PRD and TechDoc versions must be created');
    assert.ok(linkedVersions.every(version=>version.competitor_snapshot_id===snapshotId), 'document versions must retain the selected snapshot');
    await page.screenshot({path:'artifacts/competitor-browser/document-links.png'});
    await page.locator('[data-view=solutions]').click();
    await page.locator('#solutions-view').waitFor({state:'visible'});
    await page.locator('#competitor-open').click();
    await panel.waitFor({state:'visible'});
    await page.locator('#competitor-skip').click();
    await panel.waitFor({state:'hidden'});
    assert.equal((await getCandidates()).candidates.length,1); // skip is not delete
    assert.deepEqual(await page.evaluate(async p=>(await fetch(`/api/projects/${p}/sources`)).json(),project),[]);
    await page.screenshot({path:'artifacts/competitor-browser/candidates.png'});
    assert.equal(external,0); assert.equal(modelOrSearch,0);
    console.log('PASS Chromium competitor vertical flow: candidate -> comparison -> decisions -> snapshot -> solution -> PRD/TechDoc snapshot links; skip remains non-destructive; Provider/Search attempts=0.');
  } catch(error) {
    await page.screenshot({path:'artifacts/competitor-browser/failure.png'});
    throw error;
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
