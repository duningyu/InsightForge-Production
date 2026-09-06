# 开放测试改版：源码增量与未完成边界

本记录对应 2026-09-06 的离线实现。状态为 **PARTIAL，不能据此开放注册或部署**。
没有修改生产数据库、运行容器、凭据或邀请，没有真实模型/搜索请求。

## 本次实现

- 初始想法表单由预留结果的双列改为居中单列；操作区允许换行。
- 现有方案增加只读详情侧窗，窄屏全屏；使用原方案字段，缺失字段明确说明。
  查看不选择、不请求模型；原生 dialog 支持 Esc、关闭和焦点返回。
- 不完整的下一步导航数据不再生成空白按钮。
- 后处理失败使用明确文案；仅结算状态为 RELEASED 才说明额度释放。
- 默认关闭用户每日次数准入限制：INSIGHTFORGE_DAILY_USER_LIMITS_ENABLED=false。
  API /api/usage/policy 显式返回启用状态；不限时 limit/remaining 为 null。
  历史计数、预留/提交/释放和单次验收协议保留；显式开启的旧限额作为兼容控制测试。

这不是完整开放使用实现：前端全部旧额度说明尚未清理；可扩展账号本批进展见下文。
此前测试中的 beta004/beta005 计数身份不是第四、第五名实际注册用户。

## TDD 证据

实际 RED（在对应生产修改之前执行）：

- tests/test_open_test_usage.py：3 failed, 1 passed；默认旧限额拒绝连续调用，政策 API 返回 404。
- tests/solution_detail_behavior_harness.js：缺少 openSolutionDetails 函数。
- tests/open_test_browser.cjs：1366px 初始表单宽度 366.390625px、未居中，仍预留空布局列。
- tests/open_test_messages_harness.js：未确认 RELEASED 时旧错误文案仍声称额度未消耗。

实际 GREEN：

- 默认不限与显式旧限额控制：19 passed in 24.88s。
- python tests/run_open_test_regressions.py：91 passed in 119.53s；外部连接尝试 0。
  包含配额、异步、幂等、Provider ledger、server-bound acceptance、文档与交接定向回归。
- Node：solution_detail_behavior、open_test_messages、document_evidence_ux_behavior、
  generation_recovery_behavior、guidance_navigation_behavior harness 均 PASS。
- Chromium：1366×768、1440×900、1920×1080、390×844 初始布局和详情组件 PASS。
  实际静态资源 + 合成 GET fixtures，检查原生 Esc/焦点和不改变选择；非 fixture 请求 0。
  截图和机器结果位于本地 artifacts/open-test-browser/（不提交生成文件）。

浏览器测试通过测试钩子打开详情，不等于卡片点击到后台的完整 E2E。
125%/150% 浏览器缩放 NOT_RUN；登录到交接完整任务 NOT_RUN。
这些结果不能证明新账号、跨账号隔离、AI 参考或无资料交接新规则完成。

## 统一后续清单（仍需源码实现，非部署许可）

### 追加：真实等待状态进度条（2026-09-06）

- 新增统一页面加载提示，使用原生不定进度条和中文阶段文案。后端没有完成比例时不制造百分比。
- 覆盖 API 请求、响应体读取、并发请求；成功或异常均清理对应等待状态。
- 方案生成使用独立任务等待标记，轮询间隙不闪退；重复点击不新增生成 POST。
- 不改变超时、重试、取消、Provider、quota 或认证行为；不宣称关闭页面等于取消任务。
- RED：新增 `tests/loading_progress_harness.js` 首次运行在
  `pending actual request must display loading progress` 断言失败（true !== false）。
- GREEN：loading_progress、generation_recovery、document_evidence_ux、open_test_messages、
  solution_detail、guidance_navigation 六个 Node harness 本轮 fresh PASS。
- fresh Python 定向链：`py -3.12 tests/run_open_test_regressions.py`，
  **91 passed in 117.73s**；blocked_external_attempts=0，real_external_connections=0。
  这是定向回归，不是全库测试。
- 真实 Chromium + 当前静态页面 + 拦截的合成 GET：1366×768、1440×900、1920×1080、390×844。
  实际 bootstrap 等待时进度可见、原生 progress.position=-1、响应完成后隐藏，无横向溢出；
  非预设请求 0，页面异常 0。无真实 Provider/Search 请求。
- 浏览器证据：`artifacts/loading-progress-browser/result.json` 和 `pending-*.png`（本地、不提交）。
  这是加载专项浏览器测试，不是新用户到交接 E2E；125%/150% 缩放仍 NOT_RUN。
- `node --check app/static/app.js`、compileall、git diff --check PASS；
  修改范围常见密钥模式扫描 0 命中，未读取真实凭据，未修改生产运行环境或数据。

本增量只完成新增加载提示需求；附件 A–D 的账号隔离、草稿、AI 参考、无资料交接等缺口仍在下列清单中。
尚未完成，不应部署或报告整体 PASS。

1. 完成有结果布局、折叠输入、全局按钮和弹层草稿保护；真实缩放/加载/错误状态验证。
2. 基于认证身份实现可扩展账号/workspace、旧数据归属迁移和全资源授权检查。
   不能通过移除 Basic Auth、共享账号或复制 Docker 实例替代。
3. 完成用户/项目/模块/版本作用域草稿、冲突检测、退出清理和任务 GET 恢复。
4. AI 补充思路接现有 managed 服务/Adapter，一次有界批处理；仅在传输边界 fake 测试。
5. 完成集中中文展示、前端不限政策和旧帮助文案；保留技术字段原样。
6. 将缺资料变为局部待验证事项，保留结构/身份/伪造阻断；人工确认和交接完整回归。
7. 隔离库测试第四/第五名用户，以及项目/文档/任务/文件/导出/草稿跨账号拒绝。
8. 真实浏览器从新用户登录到交接，不直接写批准状态，不额外自动生成。
9. 完成以上后再统一审查发布；本次不部署、不邀请、不真实调用。

## 追加：独立账号增量（2026-09-06，仍为 PARTIAL）

保留 0f001003 的加载反馈及此前布局/文档/配额修改，不操作生产。

- 新增受控领取 `/api/auth/claim`、登录 `/api/auth/login`、退出 `/api/auth/logout` 和 `/login` 页面。
  邀请由操作员侧 `AccountRegistry.issue_invite()` 服务签发，无公开签发接口，不设置三人上限。
- 服务端注册表绑定用户到独立 SQLite/runtime；同一进程复用原业务 app、服务和 worker，
  不要求新增 Docker 实例。客户端不能指定 workspace、数据库路径或 participant。
- 密码使用 Python/OpenSSL scrypt（随机盐）；随机会话/邀请仅存 SHA256，30分钟闲置会话可撤销。
  Cookie HttpOnly/SameSite=Strict；变更请求要求同源及自定义请求头，登录失败有短时节流。
  不将密码、邀请或会话写入前端存储、日志或文档。
- 新账号只初始化自己的库。旧库只能由操作员明确提供 database/runtime/participant 映射，
  不归给第一个注册者。本批只验证合成旧数据的显式绑定，不代表已核对线上三名用户映射。
- 页面新增退出与新建项目入口；退出后完整导航清除内存页面，BFCache 返回触发重新加载。

### 本批 RED / GREEN 与范围

- 有效 RED：`tests/test_open_accounts.py` 在实现前因 Settings 缺少 accounts_enabled 失败，
  缺失的账号入口/隔离行为尚不能执行；之后真实领取和登录接口测试转绿。
- 浏览器有效 RED：新建项目按钮提交空 summary，被现有 API 422 拒绝。
  最小修复让新项目摘要使用填写的项目名称，没有放宽原 API 校验。
- `py -3.12 -m pytest tests/test_open_accounts.py -q --tb=short`：5 passed in 22.34s
  （进一步补充全局文档 ID 用例后以最终定向回归结果为准）。
- `py -3.12 tests/run_account_browser.py`：真实 Chromium 1366×768，两个合成用户经页面领取、
  登录、新建项目、刷新读取、退出、换账号；使用直接 GET 检查另一账号项目返回404，PASS。
  应用真实 lifespan 执行；外部连接0，生成请求0。截图位于本地
  `artifacts/account-browser/`（不提交）。不是从想法到交接的完整 E2E，也不是缩放验收。
- 五名用户通过真实账号服务和 HTTP 领取/登录创建，非直接插入账号行。
  项目子路由和全局 PRD/TechDoc ID 读写/导出控制测试使用隔离库与合成文档。
  本批尚未穷尽真实已存在任务、文件下载、个人设置、草稿等全部入口的跨账号矩阵。
- 最终 fresh：`py -3.12 tests/run_open_test_regressions.py` **96 passed in 132.99s**，
  外部连接尝试0、真实外部连接0。包括上述全局文档控制测试、原 quota/ledger/acceptance/文档回归。
  这是定向链，不是全库测试。合成旧归属测试使用当前 schema，不等于所有旧 schema migration 已验证。
- 六个 Node harness fresh PASS：loading_progress、generation_recovery_behavior、
  document_evidence_ux_behavior、open_test_messages、solution_detail_behavior、guidance_navigation_behavior。
  新账号脚本 `node --check`、`py -3.12 -m compileall -q app tests/test_open_accounts.py tests/run_account_browser.py`、
  `git diff --check` PASS。修改文件常见真实密钥模式扫描0命中；人工检查仅合成测试口令，
  无生产密码/邀请/数据库/用户内容进入提交。浏览器最终复跑仍 PASS。

### 兼容配置与发布前缺口（不是本轮部署命令）

- 默认 `INSIGHTFORGE_ACCOUNTS_ENABLED=false`，保持已有单实例 Basic Auth 部署不变。
  后续启用账号模式须设置 `INSIGHTFORGE_ACCOUNTS_ENABLED=true` 和持久化的
  `INSIGHTFORGE_ACCOUNTS_DIR`；HTTPS 部署设置既有 `BETA_SESSION_COOKIE_SECURE=true`。
  不在此填真实值、不签发生产邀请、不启用线上模式。
- 账号模式以服务端会话作为工作空间边界；旧 Basic Auth 不自动变成新账号。
  旧数据绑定须事先明确所有者和路径、停用原写入者，不能让两个进程并写同一旧库。
- 保留 managed Provider 配置及严格一次性验收语义，不复制/重用任何历史授权。
- 当前每个活跃账号有一个进程内业务 app/worker，尚需资源回收与多进程运行评估。
  注册入口滥用防护及会话安全仍需发布前专项定向检查；不把功能测试当安全认证。
- 后端默认不限策略保留；第四次方案/第六次分析的真实 Adapter + fake transport 回归、
  前端所有旧额度文案和发布配置闭环仍未完成。现有12/22次计数服务测试不能替代它们。
- 下一步先完成上述账号全资源矩阵、配置/限额闭环，再做用户级草稿冲突、AI参考接线、
  无资料人工确认交接、全中文和真实缩放/完整浏览器任务。统一清单继续使用本文件。
