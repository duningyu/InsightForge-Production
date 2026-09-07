/* Final UI surface regression: real Chromium, synthetic GET fixtures only.
 * This checks rendered result states, Chinese user-facing labels, header layout,
 * and viewport/device-scale-factor combinations. It is not a full authenticated
 * login-to-handoff E2E and never calls a real Provider or Search service.
 */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const VIEWPORTS = [
  {name: '1366x768@100', width: 1366, height: 768, deviceScaleFactor: 1},
  {name: '1366x768@125-equivalent', width: 1366, height: 768, deviceScaleFactor: 1.25},
  {name: '1366x768@150-equivalent', width: 1366, height: 768, deviceScaleFactor: 1.5},
  {name: '1440x900@125-equivalent', width: 1440, height: 900, deviceScaleFactor: 1.25},
  {name: '1920x1080@150-equivalent', width: 1920, height: 1080, deviceScaleFactor: 1.5},
];

const assets = {
  '/': 'index.html',
  '/static/app.js': 'app.js',
  '/static/model-settings.js': 'model-settings.js',
  '/static/styles.css': 'styles.css',
  '/static/account-session.js': 'account-session.js',
};

function visibleRect(page, selector) {
  return page.locator(selector).evaluate((node) => {
    const rect = node.getBoundingClientRect();
    const style = getComputedStyle(node);
    return {left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom,
      visible: style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0};
  });
}

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined});
  const failures = [];
  const results = [];
  try {
    for (const viewport of VIEWPORTS) {
      const context = await browser.newContext({
        viewport: {width: viewport.width, height: viewport.height},
        deviceScaleFactor: viewport.deviceScaleFactor,
        serviceWorkers: 'block',
      });
      const page = await context.newPage();
      const pageErrors = [];
      const unexpected = [];
      page.on('pageerror', (error) => pageErrors.push(error.message));
      await page.addInitScript(() => { window.__INSIGHTFORGE_TEST__ = true; });
      await page.route('**/*', async (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== 'http://insightforge.test') {
          unexpected.push('external request: ' + url.origin);
          return route.abort();
        }
        if (assets[url.pathname]) {
          return route.fulfill({
            body: fs.readFileSync(path.join('app/static', assets[url.pathname])),
            contentType: url.pathname.endsWith('.css') ? 'text/css' : url.pathname.endsWith('.js') ? 'text/javascript' : 'text/html',
          });
        }
        if (route.request().method() !== 'GET') {
          unexpected.push(route.request().method() + ' ' + url.pathname);
          return route.abort();
        }
        const fixtures = {
          '/api/auth/me': null,
          '/api/beta/consent': {beta_mode: false, consented: true},
          '/api/health': {structured_runtime_mode: 'managed'},
          '/api/settings/mode': {managed_beta_mode: true},
          '/api/projects': [],
          '/api/examples': [],
          '/api/projects/history': {items: [], total: 0, pages: 1},
          '/api/home/next-action': null,
          '/api/usage/policy': {daily_user_limits_enabled: false, limit: null, remaining: null},
        };
        return route.fulfill({status: url.pathname === '/api/auth/me' ? 404 : 200, json: fixtures[url.pathname] ?? {}});
      });
      await page.goto('http://insightforge.test/');
      await page.waitForLoadState('networkidle');
      await page.evaluate(() => {
        const h = window.InsightForgeUi.__test;
        const state = h.state;
        state.accountId = 'synthetic-user-a';
        state.currentProjectId = 'project-a';
        state.currentProject = {id: 'project-a', title: '实习求职助手', name: '实习求职助手'};
        state.solutions = {selected_candidate_id: 'solution-a', candidates: [
          {id: 'solution-a', title: '分步求职准备', mechanism: 'workflow', why_fit: '帮助初学者逐步整理求职材料。', complexity: 'low', data_requirements: ['用户输入'], risks: ['用户需求仍需确认'], user_flow: ['输入目标', '获得建议'], mvp_pages: ['项目首页'], features: ['逐步引导'], inputs: ['想法'], outputs: ['行动清单'], decision_logic: ['按用户目标收敛'], technical_components: ['Web 应用'], implementation_plan: ['先完成输入与反馈'], acceptance_cases: ['可完成一次流程'], unknowns: ['目标用户需要访谈确认']},
          {id: 'solution-b', title: '资料整理工作台', mechanism: 'workspace', why_fit: '把已有资料集中整理。', complexity: 'medium', data_requirements: ['用户资料'], risks: ['资料质量待确认'], user_flow: ['上传资料'], mvp_pages: ['资料页'], features: ['资料整理'], inputs: ['资料'], outputs: ['整理结果'], decision_logic: ['按资料类型组织'], technical_components: ['存储'], implementation_plan: ['先完成资料入口'], acceptance_cases: ['资料可查看'], unknowns: ['资料来源待确认']},
          {id: 'solution-c', title: '轻量反馈循环', mechanism: 'feedback', why_fit: '通过小步反馈验证方向。', complexity: 'medium', data_requirements: ['反馈'], risks: ['反馈样本待确认'], user_flow: ['提出问题', '记录反馈'], mvp_pages: ['反馈页'], features: ['反馈记录'], inputs: ['反馈'], outputs: ['待办事项'], decision_logic: ['按反馈排序'], technical_components: ['表单'], implementation_plan: ['先完成反馈记录'], acceptance_cases: ['反馈可保存'], unknowns: ['反馈频率待确认']},
        ]};
        state.snapshot = {version: 1, title: '实习求职助手', one_liner: '帮助初学者整理求职行动。', target_user: {primary: '准备求职的学生', verification_status: '待确认'}, unknowns: ['目标用户是否真的频繁遇到这个问题'], solution: {title: '分步求职准备', rationale: '降低开始行动的门槛。', explicit_non_goals: ['本版不做团队协作']}, mvp: {pages: ['项目首页'], features: ['逐步引导'], implementation_plan: ['先完成核心流程'], acceptance_criteria: ['用户可完成一次流程']}};
        state.documents = [
          {id: 'prd-1', doc_type: 'prd', version: 1, status: 'draft', validation_status: 'passed', artifact_health: {health_status: 'current'}, dependencies: []},
          {id: 'tech-1', doc_type: 'techdoc', version: 1, status: 'draft', validation_status: 'passed', artifact_health: {health_status: 'current'}, dependencies: []},
        ];
        state.documentWorkspace = {docType: 'prd', versions: [{id: 'prd-1', version: 1, content: '目标用户：准备求职的学生。\n仍需确认：用户是否真的频繁遇到这个问题。', status: 'draft', validation_status: 'passed', artifact_health: {health_status: 'current'}, created_at: '2026-09-07T00:00:00Z'}], selectedVersionId: 'prd-1', compareVersionId: null, draft: null, autosaveTimer: null, dirty: false, error: null};
        state.handoff = {ready: true, documents: {prd: {id: 'prd-1'}, techdoc: {id: 'tech-1'}}, unresolved_items: [{item: '目标用户是否真的频繁遇到这个问题', why: '当前来自项目假设', how_to_verify: '进行目标用户访谈或原型测试'}], acknowledgement_required: false};
        document.querySelector('#project-shell').classList.remove('hidden');
        document.querySelector('#project-context').classList.remove('hidden');
        document.querySelector('#account-controls').hidden = false;
        document.querySelector('#account-name').textContent = '测试用户（较长账号名称）';
        document.querySelector('#nav-project-title').textContent = '实习求职助手';
        h.renderSolutions();
        h.renderDocuments();
        h.renderHandoff();
        for (const id of ['snapshot-view', 'evidence-view']) {
          document.querySelector('#' + id)?.classList.add('hidden');
        }
        for (const id of ['solutions-view', 'documents-view', 'handoff-view']) {
          document.querySelector('#' + id)?.classList.remove('hidden');
        }
      });

      const text = await page.locator('body').innerText();
      for (const required of ['查看详情', '选择这个方案', 'PRD', 'TechDoc', '仍需确认的事项', '本版包含', '本版暂不包含']) {
        if (!text.includes(required)) failures.push(`${viewport.name}: missing Chinese/result label ${required}`);
      }
      for (const forbidden of ['Implementation Tasks', 'Acceptance Cases', 'Unknowns / Risks', 'Explicit non-scope', 'In scope']) {
        if (text.includes(forbidden)) failures.push(`${viewport.name}: raw English heading ${forbidden}`);
      }
      for (const forbidden of ['PROJECT SNAPSHOT', 'Evidence → Claim', 'Claim 关系', 'exact-span', 'HANDOFF', 'CLOSED BETA', 'QUICK VALUE', 'GUIDED EXAMPLE', 'PROJECT HISTORY', 'PROJECT CENTER', 'SETTINGS', 'CLOSED BETA FEEDBACK']) {
        if (text.includes(forbidden)) failures.push(`${viewport.name}: technical label leaked into primary UI ${forbidden}`);
      }

      const metrics = await page.evaluate(() => {
        const rect = (selector) => Array.from(document.querySelectorAll(selector)).map((node) => {
          const r = node.getBoundingClientRect();
          const s = getComputedStyle(node);
          return {left: r.left, right: r.right, top: r.top, bottom: r.bottom, visible: s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0};
        }).filter((item) => item.visible);
        const header = ['#home-button', '#settings-button', '#project-context', '#account-controls', '#mobile-nav-button'].flatMap(rect);
        const headerOverlap = header.some((a, i) => header.slice(i + 1).some((b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top));
        const cols = getComputedStyle(document.querySelector('.solution-grid')).gridTemplateColumns.split(' ').length;
        return {overflow: document.documentElement.scrollWidth > innerWidth + 1, headerOverlap, header, solutionColumns: cols, cards: rect('.solution-card, .document-card, .handoff-section')};
      });
      if (metrics.overflow) failures.push(`${viewport.name}: horizontal overflow`);
      if (metrics.headerOverlap) failures.push(`${viewport.name}: top account/header controls overlap`);
      if (viewport.width >= 1200 && metrics.solutionColumns < 2) failures.push(`${viewport.name}: result grid collapsed unexpectedly`);
      if (metrics.cards.some((r) => r.right > viewport.width + 1 || r.left < -1)) failures.push(`${viewport.name}: result card escapes viewport`);
      results.push({...viewport, ...metrics});
      if (pageErrors.length) failures.push(`${viewport.name}: ${pageErrors.join('; ')}`);
      if (unexpected.length) failures.push(`${viewport.name}: ${unexpected.join('; ')}`);
      await context.close();
    }
    const summary = {method: 'Chromium rendered result-state/layout check with synthetic GET fixtures', zoom: 'deviceScaleFactor-equivalent 125%/150%', results, failures};
    fs.mkdirSync('artifacts/final-ui-browser', {recursive: true});
    fs.writeFileSync('artifacts/final-ui-browser/result.json', JSON.stringify(summary, null, 2));
    assert.deepEqual(failures, []);
    console.log('Final UI Chromium PASS: Chinese result surfaces, result-state layout, top account controls, and 125%/150% device-scale-factor-equivalent checks; full login-to-handoff E2E remains NOT_RUN.');
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
