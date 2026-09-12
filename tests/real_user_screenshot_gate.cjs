/* Real Chromium screenshot gate for user-visible regression surfaces.
 * Uses deterministic in-browser fixtures only: no Provider, Search, or business writes.
 */
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const VIEWPORTS = [
  {name: '1366x768-100', width: 1366, height: 768, deviceScaleFactor: 1},
  {name: '1366x768-125', width: 1366, height: 768, deviceScaleFactor: 1.25},
  {name: '1366x768-150', width: 1366, height: 768, deviceScaleFactor: 1.5},
  {name: '1440x900-125', width: 1440, height: 900, deviceScaleFactor: 1.25},
  {name: '1920x1080-150', width: 1920, height: 1080, deviceScaleFactor: 1.5},
];

const assets = {
  '/': 'index.html',
  '/static/app.js': 'app.js',
  '/static/model-settings.js': 'model-settings.js',
  '/static/styles.css': 'styles.css',
  '/static/account-session.js': 'account-session.js',
};

const solutions = {selected_candidate_id: 'solution-a', candidates: [
  {id: 'solution-a', title: '分步求职准备', mechanism: 'workflow', why_fit: '帮助初学者逐步整理求职材料。', complexity: 'low', data_requirements: [{data_field: '求职目标', purpose: '帮助确定下一步行动', source: '用户自己填写'}], risks: [{risk: '用户需求仍需确认', mitigation: '先做小范围访谈'}], user_flow: [{step: 1, action: '输入目标岗位', ui_hint: '在项目定义页填写'}], mvp_pages: ['项目首页'], features: ['逐步引导'], inputs: [{input_type: '文本', field: '目标岗位', required: true, description: '用户当前想申请的岗位'}], outputs: [{input_type: '清单', field: '行动建议', required: true, description: '下一步可以执行的事项'}], decision_logic: ['按用户目标收敛'], technical_components: ['Web 应用'], implementation_plan: ['先完成输入与反馈'], acceptance_cases: ['可完成一次流程'], unknowns: ['目标用户需要访谈确认']},
  {id: 'solution-b', title: '资料整理工作台', mechanism: 'workspace', why_fit: '把已有资料集中整理。', complexity: 'medium', data_requirements: ['用户资料'], risks: ['资料质量待确认'], user_flow: ['上传资料'], mvp_pages: ['资料页'], features: ['资料整理'], inputs: ['资料'], outputs: ['整理结果'], decision_logic: ['按资料类型组织'], technical_components: ['存储'], implementation_plan: ['先完成资料入口'], acceptance_cases: ['资料可查看'], unknowns: ['资料来源待确认']},
  {id: 'solution-c', title: '轻量反馈循环', mechanism: 'feedback', why_fit: '通过小步反馈验证方向。', complexity: 'medium', data_requirements: ['反馈'], risks: ['反馈样本待确认'], user_flow: ['提出问题', '记录反馈'], mvp_pages: ['反馈页'], features: ['反馈记录'], inputs: ['反馈'], outputs: ['待办事项'], decision_logic: ['按反馈排序'], technical_components: ['表单'], implementation_plan: ['先完成反馈记录'], acceptance_cases: ['反馈可保存'], unknowns: ['反馈频率待确认']},
]};

function fixtureState() {
  return `
    const h = window.InsightForgeUi.__test;
    const state = h.state;
    state.accountId = 'synthetic-user-a';
    state.currentProjectId = 'project-a';
    state.currentProject = {id: 'project-a', title: '实习求职助手', name: '实习求职助手'};
    state.runtimeMode = 'llm_structured';
    state.ideaBrief = {idea: '帮助同时投递多家公司的人记录求职进度', target_user: '准备求职的学生', problem: '容易忘记下一步'};
    state.solutions = ${JSON.stringify(solutions)};
    state.snapshot = {version: 1, title: '实习求职助手', one_liner: '帮助初学者整理求职行动。', target_user: {primary: '准备求职的学生', verification_status: '待确认'}, unknowns: ['目标用户是否真的频繁遇到这个问题'], solution: {title: '分步求职准备', rationale: '降低开始行动的门槛。', explicit_non_goals: ['本版不做团队协作']}, mvp: {pages: ['项目首页'], features: ['逐步引导'], implementation_plan: ['先完成核心流程'], acceptance_criteria: ['用户可完成一次流程']}};
    state.documents = [{id: 'prd-1', doc_type: 'prd', version: 1, status: 'draft', validation_status: 'passed', artifact_health: {health_status: 'current'}, dependencies: []}, {id: 'tech-1', doc_type: 'techdoc', version: 1, status: 'draft', validation_status: 'passed', artifact_health: {health_status: 'current'}, dependencies: []}];
    state.documentWorkspace = {docType: 'prd', versions: [{id: 'prd-1', version: 1, content: '目标用户：准备求职的学生。\\n仍需确认：用户是否真的频繁遇到这个问题。', status: 'draft', validation_status: 'passed', artifact_health: {health_status: 'current'}, created_at: '2026-09-07T00:00:00Z'}], selectedVersionId: 'prd-1', compareVersionId: null, draft: null, autosaveTimer: null, dirty: false, error: null};
    state.handoff = {ready: true, documents: {prd: {id: 'prd-1', status: 'confirmed'}, techdoc: {id: 'tech-1', status: 'confirmed'}}, unresolved_items: [{item: '目标用户是否真的频繁遇到这个问题', why: '当前来自项目假设', how_to_verify: '进行目标用户访谈或原型测试'}], acknowledgement_required: false};
    document.querySelector('#project-shell').classList.remove('hidden');
    document.querySelector('#project-context').classList.remove('hidden');
    document.querySelector('#account-controls').hidden = false;
    document.querySelector('#account-name').textContent = '测试用户';
    document.querySelector('#nav-project-title').textContent = '实习求职助手';
    h.renderSolutions();
    h.renderDocuments();
    h.renderHandoff();
    h.activateView('solutions');
    h.setTestAIReference({possible_target_users: ['准备求职的学生'], possible_scenarios: ['同时推进多家公司'], possible_user_problems: ['容易忘记下一步'], missing_information: ['真实访谈记录'], mvp_thoughts: ['先做下一步提醒'], questions_to_validate: ['用户是否愿意持续更新'], research_directions: ['访谈3–5名目标用户']}, []);
    h.setTestEvidenceGuidance({cards: [{title: '找一次真实的进度记混经历', question_to_validate: '求职者是否真的漏过下一步', who_or_where: ['最近1–3个月集中求职的人'], action_steps: ['请对方回忆最近一次同时推进多家公司时怎样记录'], suggested_questions: ['最近有没有漏掉或记混的情况？'], acceptable_artifacts: ['匿名原话和可选打码截图'], fill_template: ['对象：', '时间和场景：', '对方原话：'], decision_impact: '决定第一版优先提醒还是复杂看板', fallback_if_unavailable: '先记录自己的真实经历', limitations: '少量反馈不能代表整个市场'}]});
  `;
}

function forbiddenText(text) {
  const patterns = [
    /\[object Object\]/i,
    /Traceback|ValueError|KeyError|Exception|stack trace/i,
    /current confirmed competitor snapshot is required/i,
    /(?:^|[^\p{L}])(?:data_field|input_type|ui_hint|camera_quality_and_lighting|public_dataset_or_manual_upload|user_registration_address)(?:[^\p{L}]|$)/iu,
    /\{\s*["'][A-Za-z_][A-Za-z0-9_]*["']\s*:/,
  ];
  return patterns.filter((pattern) => pattern.test(text)).map(String);
}

(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_EXECUTABLE || undefined});
  const failures = [];
  const screenshots = [];
  try {
    for (const viewport of VIEWPORTS) {
      const context = await browser.newContext({viewport: {width: viewport.width, height: viewport.height}, deviceScaleFactor: viewport.deviceScaleFactor, serviceWorkers: 'block'});
      const page = await context.newPage();
      const unexpected = [];
      const pageErrors = [];
      page.on('pageerror', (error) => pageErrors.push(error.message));
      await page.addInitScript(() => { window.__INSIGHTFORGE_TEST__ = true; });
      await page.route('**/*', async (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== 'http://insightforge.test') { unexpected.push('external ' + url.origin); return route.abort(); }
        if (assets[url.pathname]) return route.fulfill({body: fs.readFileSync(path.join('app/static', assets[url.pathname])), contentType: url.pathname.endsWith('.css') ? 'text/css' : url.pathname.endsWith('.js') ? 'text/javascript' : 'text/html'});
        if (route.request().method() !== 'GET') {
          if (route.request().method() === 'PUT' && url.pathname.endsWith('/drafts/ui_context/main')) return route.fulfill({status: 200, json: {ok: true}});
          unexpected.push(route.request().method() + ' ' + url.pathname); return route.abort();
        }
        return route.fulfill({status: url.pathname === '/api/auth/me' ? 404 : 200, json: url.pathname === '/api/health' ? {structured_runtime_mode: 'managed'} : {}});
      });
      await page.goto('http://insightforge.test/');
      await page.waitForLoadState('networkidle');
      await page.evaluate(fixtureState());
      const output = path.join('artifacts', 'real-user-screenshots');
      fs.mkdirSync(output, {recursive: true});

      const capture = async (name, selector, extraCheck = () => {}) => {
        const locator = page.locator(selector);
        await locator.screenshot({path: path.join(output, `${name}-${viewport.name}.png`)});
        const bodyText = await locator.innerText();
        const leaks = forbiddenText(bodyText);
        if (leaks.length) failures.push(`${name}/${viewport.name}: forbidden UI text ${leaks.join(', ')}`);
        const layout = await locator.evaluate((node) => ({overflow: node.scrollWidth > node.clientWidth + 2, width: node.getBoundingClientRect().width}));
        if (layout.overflow) failures.push(`${name}/${viewport.name}: horizontal overflow`);
        await extraCheck(bodyText);
        screenshots.push({name, viewport: viewport.name, path: path.join(output, `${name}-${viewport.name}.png`), leaks, layout});
      };

      await capture('ai-reference-success', '#ai-reference-content');
      await page.evaluate(() => window.InsightForgeUi.__test.setTestAIReference({}));
      // An empty result must not create a success body; capture the containing
      // surface so the negative state remains screenshot evidence without
      // asking Chromium to screenshot a zero-sized empty content node.
      await capture('ai-reference-empty', '#solutions-view');
      await page.evaluate(() => window.InsightForgeUi.__test.activateView('evidence'));
      await page.evaluate(() => window.InsightForgeUi.__test.setEvidenceTab('sources'));
      await page.evaluate(() => window.InsightForgeUi.__test.setTestEvidenceGuidance({cards: []}));
      await capture('evidence-guidance-empty', '#evidence-coach-panel');
      await page.evaluate(() => window.InsightForgeUi.__test.setTestEvidenceGuidance({cards: [{title: '找一次真实的进度记混经历', question_to_validate: '是否真的漏过下一步', who_or_where: ['最近集中求职的人'], action_steps: ['请对方回忆一次真实经历'], acceptable_artifacts: ['匿名原话'], fill_template: ['对象：', '对方原话：'], decision_impact: '决定优先做提醒还是看板', limitations: '少量反馈不能代表市场'}]}));
      await capture('evidence-guidance-card', '#evidence-coach-panel');
      await page.evaluate(() => window.InsightForgeUi.__test.activateView('solutions'));
      await page.evaluate(() => window.InsightForgeUi.__test.renderSolutions());
      await capture('solution-cards', '#solutions-view');
      await page.evaluate(() => window.InsightForgeUi.__test.openSolutionDetails('solution-a'));
      await capture('solution-detail', '#solution-detail-dialog');
      await page.evaluate(() => { window.InsightForgeUi.__test.renderRuntimeDisclosure({failure: 'current confirmed competitor snapshot is required for this document generation'}); });
      await capture('sanitized-error', '#runtime-disclosure');
      await page.evaluate(() => window.InsightForgeUi.__test.activateView('documents'));
      await page.evaluate(() => window.InsightForgeUi.__test.renderDocuments());
      await capture('documents-skip-competitor', '#documents-view');
      await page.evaluate(() => window.InsightForgeUi.__test.activateView('handoff'));
      await page.evaluate(() => window.InsightForgeUi.__test.renderHandoff());
      await capture('handoff', '#handoff-view');
      if (pageErrors.length) failures.push(`${viewport.name}: page errors ${pageErrors.join('; ')}`);
      if (unexpected.length) failures.push(`${viewport.name}: unexpected requests ${unexpected.join('; ')}`);
      await context.close();
    }
    const summary = {method: 'real Chromium rendered primary UI screenshot gate', screenshots, failures};
    fs.mkdirSync('artifacts/real-user-screenshots', {recursive: true});
    fs.writeFileSync('artifacts/real-user-screenshots/result.json', JSON.stringify(summary, null, 2));
    assert.deepEqual(failures, []);
    console.log(JSON.stringify({passed: true, screenshots: screenshots.length, failures: []}));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
