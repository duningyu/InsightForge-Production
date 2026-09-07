# 开放测试改版：源码增量与未完成边界

## 当前状态摘要（AI补充思路与无资料人工确认交接）

开发检查点：`d3a8d474159083921529a088fbd86a6b79d0e737` 的后继工作区；账号基线、竞品决策切片和统一草稿恢复保持已通过，本轮未部署、未调用真实 Provider/Search。

- 已接入“AI帮我补充思路”：复用现有结构化模型 runtime、Provider/model 解析与 Adapter，一次有界批处理返回目标用户、场景、问题、MVP 思路、待确认问题和研究方向；结果明确标记为 AI 参考，不创建 source，也不升级为证据。
- AI 参考支持按项目保存、幂等恢复、部分采用/修改/忽略及原因，采用内容保留 `AI_REFERENCE` / `UNRESOLVED` 语义，并进入后续方案 context；前端入口和中文展示已接入统一页面。
- 无资料文档校验已区分 warning 与 blocking：诚实披露无来源时，缺引用和未解决主张为 warning；结构缺失仍为 blocking。PRD/TechDoc 可在人工确认后进入交接，交接包保留“仍需确认的事项”和人工确认记录。
- Fresh 后端：`py -3.12 -m pytest tests/test_ai_reference_no_source.py tests/test_v2_handoff.py tests/test_v3_handoff_and_tools.py tests/test_competitor_decision_slice.py -q --tb=short`：22 passed；`py -3.12 tests/run_open_test_regressions.py`：146 passed，外部连接尝试 0。
- Fresh 真实 Chromium 草稿恢复：`py -3.12 tests/run_draft_recovery_browser.py`：FLOW A–F PASS，generation POST 1、logical task 1、comparison POST 1、外部连接 0；该 runner 覆盖既有草稿/任务恢复，不等同于本轮 AI 参考与无资料完整浏览器链。
- `node --check app/static/app.js`、`py -3.12 -m compileall -q app tests`、`git diff --check` 已通过。Chromium 可用的是现有 bundled Playwright runner；本轮未新增第二套浏览器依赖。AI 参考、无资料确认交接的专门真实 Chromium 流程仍未运行。
- 当前整体仍为 `INSIGHTFORGE_USER_FIRST_OPEN_TEST_IMPLEMENTATION_PARTIAL`。后续保留：AI 参考/无资料流程的专门 Chromium 证据、来源补入后的旧版本不变性专测，以及完整中文、有结果布局、125%/150% 缩放和最终登录到交接 E2E。

## 当前状态摘要（竞品决策贯通链 fresh 验证）

开发检查点：`646598975e5b3b6e1e56b9fc6d117a5c67e5fa8b` 的后继工作区；账号批次保持 PASS，竞品决策切片本轮完成，整体开放测试仍为 PARTIAL；未部署。

- 贯通链已接通：已选候选 → 复用方案生成的业务模型服务/Adapter 做一次有界比较 → 用户采用/暂不采用/以后再考虑及原因 → 项目级不可变竞品决策快照 → 方案生成 context → PRD/TechDoc 精确 `competitor_snapshot_id` 引用。
- 竞品上下文为显式 opt-in。普通生成和“暂时不比较”不会继承项目最新竞品快照；文档生成仍保留既有项目 Snapshot 完整性校验，不因跳过竞品而放宽文档门槛。
- Fresh 后端证据：`py -3.12 -m pytest -q tests/test_v3_document_health.py tests/test_competitor_decision_slice.py --tb=short`：13 passed；`py -3.12 tests/run_open_test_regressions.py`：146 passed，外部连接尝试 0。
- Fresh 真实 Chromium：`py -3.12 tests/run_account_browser.py --competitor` PASS，覆盖候选→比较→三类决策→快照→方案→PRD/TechDoc 快照引用，以及跳过比较不注入旧快照；fake transport 仅用于隔离验证，Provider/Search 真实请求 0。
- 搜索仍为 `NOT_CONFIGURED`，未显示 fake 搜索结果。真实 Provider verification 未运行。整体仍待：统一草稿浏览器完整证据、完整 AI 补充思路、无资料人工确认交接、完整中文/有结果布局/缩放、最终登录到交接 E2E。

## 当前状态摘要（统一草稿恢复与多标签冲突增量）

开发基线：`0100891113e8151d744d31a361e63cca262bc069`，本轮保留此前账号隔离与竞品决策改动，未部署、未调用真实 Provider/Search。

- 已增加服务端统一草稿存储：按认证账号、项目、模块作用域保存，使用 revision compare-and-swap；旧 revision 写入返回冲突，不覆盖新内容。
- 已为 PRD/TechDoc 文档草稿接入 `base_revision` 冲突保护；正式 document version、已批准版本和竞品 snapshot 仍是独立权威状态。
- 已接入前端本地恢复副本、按账号/项目/作用域隔离的恢复 key、debounce autosave、模块上下文保存、Idea/竞品/文档草稿恢复，以及迟到响应上下文保护。未同步内容显示为“仅保存在本机”或冲突提示，不伪称已同步。
- Fresh 定向证据：`tests/test_unified_drafts.py` 3 passed（含真实 claim/login 会话的账号隔离）；`tests/draft_recovery_behavior_harness.js` PASS；generation/loading/document/solution harness、JS syntax、compileall、git diff --check PASS。真实 Chromium 草稿流程因环境缺少 Playwright（`Cannot find module 'playwright'`）未运行，不能写成浏览器 E2E PASS。
- 当前批次仍为 PARTIAL，未完成项为真实 Chromium 的草稿恢复/双标签冲突/账号切换流程，以及既有的完整 AI 补充思路、无资料人工确认交接、完整中文/有结果布局/125%与150%缩放、最终登录到交接 E2E、竞品完整浏览器串联。

## 当前状态摘要（竞品决策垂直切片）

开发基线：`646598975e5b3b6e1e56b9fc6d117a5c67e5fa8b`，当前工作区保留其改动并继续完成竞品决策切片；账号批次保持 PASS，整体开放测试仍为 PARTIAL，未部署。

- 竞品候选页面与服务端候选 API 已完成：手动添加、查看、显式选择、移除、跳过；搜索仍 `NOT_CONFIGURED`，不产生真实搜索结果。
- 本轮新增并验证：一次有界 AI 比较调用复用现有业务 runtime/`AsyncModelAdapter`；比较结果与用户采用/暂不采用/以后再考虑决策保存为项目级不可变快照；快照按项目/账号隔离。
- 方案生成 context 已实际读取快照中的观察与取舍；PRD/TechDoc 文档版本保存精确 `competitor_snapshot_id`，后续新快照不回写旧版本。以上后端行为由 `tests/test_competitor_decision_slice.py` 覆盖。
- Fresh `py -3.12 tests/run_open_test_regressions.py`：`143 passed`，`0` 外部网络尝试；定向集合，不代表全库。
- Fresh `py -3.12 tests/run_account_browser.py --competitor`：真实 Chromium 候选/比较页面流程 PASS；比较 fake transport `1` 次、snapshot `1` 次，generation/analysis `0`；文档生成链的真实 Chromium 证据仍未运行。
- 当前竞品浏览器证据覆盖候选→比较→决策→保存快照与跳过；方案/文档快照链接已由隔离业务测试验证，但完整浏览器串联仍是未完成项，不虚构为 E2E PASS。
- 仍待后续：统一跨模块草稿与冲突、完整 AI 补充思路、无资料人工确认交接、完整中文/有结果布局/125%与150%缩放、登录到交接最终 E2E，以及竞品完整浏览器串联。

## 当前状态摘要（从 0bf26ce 接续：候选页面增量）

账号批次 PASS，保持关闭；竞品切片 PARTIAL；整体开放测试 PARTIAL，未部署。

- 已完成候选页面：方案页“看看已有产品”，手动添加、查看、显式加入/移出比较、移除候选、关闭/Esc/焦点恢复。
  复用现有候选表与项目/账号服务，仅增加 scoped DELETE；不创建来源，不自动进入 RAG，不新增模型配置。
- 搜索 NOT_CONFIGURED，页面明确披露且无搜索执行按钮。选择仍是用户意向，不证明真实性。
  输入仅在当前页面内按项目暂存，关闭可恢复；不宣称刷新恢复或统一跨模块草稿已完成。
- 当前未完成：AI 比较与异步接线、比较/决策快照持久化及权限、实际方案 context 取舍、
  PRD/TechDoc 精确快照引用和旧版本稳定性、竞品完整与跳过到文档 Chromium 流程。
  候选页面跳过只证明关闭不删候选、不创建来源，不能替代方案/文档跳过验收。
- 新 DELETE 回归有效 RED：1 failed / 4 passed（15.17s），foreign 请求405，缺少删除路由；
  GREEN：5 passed（14.72s），owner删除、foreign/匿名拒绝、拒绝不改变对象、可信审计、其他来源/候选保留。
- Chromium 有效 RED：缺少 `#competitor-open`；另有保存期间关闭按钮禁用的受控请求失败；
  修复后关闭不撤销请求，保存期间输入锁定，避免新输入被覆盖。
  模拟503另取得有效 RED：错误文案错误附带网址诊断；GREEN改为中性错误并保留输入。
  一次前置导航超时不计产品 RED：账号控件先于首页 bootstrap 出现，runner改为等待初始网络空闲后创建项目。
- Fresh `py -3.12 tests/run_open_test_regressions.py`：143 passed（238.11s），0失败/跳过，
  blocked_external_attempts=0、real_external_connections=0；是定向集合，不是全库。
- Fresh `py -3.12 tests/run_account_browser.py --competitor`：Chromium 候选页面 PASS（最终9.37s），
  正常领取/登录/创建项目/添加2个/查看不选择/选择1个/关闭与重开/移除/跳过；模拟503保留输入。
  Provider/Search请求尝试0，实际 lifespan 执行，真实外部连接0。
  合成截图：`artifacts/competitor-browser/panel.png`、`candidates.png`；1366×768 面板已人工查看。
  失败图按 runner 约定保留在忽略目录。
  这不是 AI→快照→方案→文档 E2E。
- Fresh 账号 browser 与 `--cancel` PASS；取消：生成1/取消1/fake传输1，释放1/活动预留0，刷新无新增调用。
  8个现有 Node harness、JS语法、compileall、git diff --check PASS。
  9个改动文件 credential pattern扫描0命中、完整diff人工审查；只含合成测试口令，无真实凭据。
  账号结项不重新打开。
- 下一具体实现位置：`ai_runtime.py` / `provider_adapters.py` 复用配置的一次比较调用；
  `async_generation.py` 现有任务执行/结果判定扩展；`competitors.py` 服务端比较与不可变快照；
  `solution_design.py` 实际 context；`snapshots.py` 与文档版本精确引用。上述代码本增量未修改。
- 整体旧缺口不变：统一草稿恢复与冲突、完整 AI 补充思路、无资料人工确认交接、完整中文、
  有结果布局、125%/150%缩放、登录到交接最终 E2E。无生产修改或真实服务请求。

## 历史记录：0bf26ce 候选后端增量（非当前未完成清单）

账号批次 PASS，已经结束；竞品切片 PARTIAL；整体开放测试 PARTIAL，未部署。

- 本增量只实现候选后端：项目范围手动添加、列表、详情、显式选择。
  使用现有账号 child SQLite、项目服务与可信 actor；候选不创建 source、不自动进入 RAG，选择仍为 UNVERIFIED。
- 新表 `competitor_candidates` 是 additive；项目永久删除沿用现有显式删除图。
  URL 仅保存合法 HTTP(S) 引用，不抓取、不判定其真实或可靠；禁止带用户名密码的 URL。
- `tests/test_competitor_candidates.py` RED：3 failed（5.51s），缺失路由404。
  GREEN：4 passed（11.17s），涵盖同账号跨项目、跨账号及同局部ID、匿名拒绝、可信审计、
  重复选择不重复审计、候选/来源分离、重开数据库以及项目删除兼容。网络尝试0。
- 竞品页面 NOT_IMPLEMENTED；AI 比较、搜索 adapter 业务路径、决策快照、生成上下文、文档版本引用均 NOT_IMPLEMENTED。
  新 GET 列表返回 NOT_CONFIGURED 和中文说明，但尚未接入页面，不能称浏览器披露通过。
- 下一接线位置：`app/static/app.js` / `index.html` 方案入口；`app/services/competitors.py` 候选服务；
  现有 `ai_runtime.py` / `provider_adapters.py` 的模型配置与传输；`solution_design.py` 实际 brief/context；
  `snapshots.py`、文档生成/版本机制的不可变引用。每段继续 RED/GREEN，不复制参考包模型或鉴权实现。
- 本增量 fresh 验证：`py -3.12 tests/run_open_test_regressions.py`：142 passed（241.57s），
  blocked_external_attempts=0、real_external_connections=0；这是定向集合，不是全库。
  候选补充匿名/foreign create 断言后单独重跑：4 passed（11.15s），外部连接0。
  `py -3.12 tests/run_account_browser.py` 与 `--cancel` 均 PASS，实际 Chromium、lifespan 已执行；
  前者 claim/login/create/save/reload/logout/switch/denial，generation=0；后者 UI生成1、取消1、fake传输1，刷新无新增调用。
  八个现有 Node harness、compileall、git diff --check PASS；本增量9个文件 secret pattern扫描0命中并人工检查。
  没有竞品 Chromium 流程证据，不能把账号浏览器通过写成竞品页面通过。
- 整体旧缺口仍保留：统一跨模块草稿与多标签页冲突、完整 AI 补充思路、无资料人工确认交接、
  完整中文/布局/125%与150%缩放/登录到交接 E2E。多进程 NOT_VERIFIED。

## 已完成：从 16c0056 接续的账号结项

账号批次 PASS：取消闭环及既有账号 gate 已 fresh 验证；整体 PARTIAL，生产未部署。
当前现存私有资源没有未解释 NOT_RUN；未来统一跨模块草稿不计入账号结项 gate。

- 新入口：POST `/api/projects/{project}/solutions/generate/{run}/cancel`。
  服务端账号 actor、workspace scoped 查找；客户端身份字段不参与路由选择。
- PENDING 直接持久化 FAILED/ASYNC_GENERATION_CANCELLED，不进入 executor；RUNNING 请求由当前 worker 取消。
  取消预留释放与 Provider 事实分开；已进入边界但结果未知，仍是不确定调用，不改成未调用。
- 完成/取消竞争遵循已有同步提交合同：提交阶段完成可胜出；run/intent 终态 CAS 防止重复回调覆盖。
- UI 明确区分关闭与停止；只缓存当前账号的 opaque task reference，刷新 GET 原任务，不重新 POST。
  这不是统一跨模块草稿实现。浏览器取消使用合成已确认 brief 作为前置，不冒充完整 Idea 流程。
- Phase A 已结束，不再扩充账号安全矩阵；下一步进入可选竞品垂直切片。
- 整体剩余：统一草稿/冲突、完整 AI 补充思路、无资料人工确认交接、中文/布局（含顶部控件重叠）、
  125%/150% 缩放、登录到交接完整 E2E。多进程 NOT_VERIFIED；不调用真实服务、不部署。

### 16c0056 后取消闭环证据

- RED：async regression 3 failed / 7 passed（11.64s）：缺少 request_cancel，以及重复 finish 覆盖 intent；
  实际账号业务 1 failed / 6 passed（28.05s）：取消 HTTP 404；Node harness：缺少进度取消函数。
- GREEN：最终业务文件 8 passed（34.20s）：真实 worker/Adapter/fake transport，取消或失败后重建不重发；
  同步 commit barrier 控制实际成功/取消竞争，成功 COMMITTED=1、RESERVED=0、RELEASED=0、usage=1。
- dispatch integration 6 passed（7.69s）：真实 Adapter 到 fake 边界产生 permit=1/CALL_BOUNDARY_ENTERED；
  取消保留原事件与 permit，分类 POSSIBLY_DISPATCHED_INDETERMINATE；同执行身份重放不再发送。
  普通账号未提供 strict dispatch context 的路径可能无这些 ledger 行，不能把 run.provider_call_count 当真实 ledger。
- `py -3.12 tests/run_account_browser.py --cancel`：Chromium UI 生成1次、取消1次、fake传输1次；
  FAILED/ASYNC_GENERATION_CANCELLED，RELEASED=1、RESERVED=0；关闭/重开不取消，刷新不重发，foreign404。
  截图 `artifacts/account-cancel-browser/cancelled.png`（忽略的合成测试产物）。
- `py -3.12 tests/run_account_browser.py --business`：Chromium 4生成动作/4任务/4传输，
  1分析动作/6claim/6传输；成功终态持久化，COMMITTED=10、RESERVED=0，刷新 policy 正确。
- `py -3.12 tests/run_account_browser.py`：领取/登录/创建保存/刷新/退出换账号/隔离 PASS。
- 八个 Node harness、compileall、git diff --check PASS。以上网络 tripwire 均为外部尝试0。
- 最终 `py -3.12 tests/run_open_test_regressions.py`：138 passed（281.78s），0失败/跳过，外部连接尝试0。
  这是定向集合，不是全库测试。最终八个 Node harness、compileall、diff check 复跑 PASS。
- 本批14个改动文件 secret scan：0匹配（密钥形态、私钥标记、Bearer及长字面量秘密赋值）；
  人工完整 diff 审查未见生产内容/凭据。仅提交源码、测试、两份现有进度文档。

## 历史状态摘要（从 a585f32 接续）

账号批次 PARTIAL；整体 PARTIAL；生产未部署。以下历史章节保留当时的状态，
不作为当前未完成清单。

- 已完成：独立账号、已有项目/文档隔离、v206 fixture/当前 schema 显式归属、
  默认不限政策、页面真实读取 policy（null 不作为 0）、目标示例配置离线加载。
- 已完成：运行任务退出/匿名/换账号/伪造身份检查、busy 回收保留原 child；
  该既有用例走真实 worker/Adapter，fake 传输 1 次。保留布局、详情侧窗和加载反馈。
- 本轮已验证：资料上传/读取/归档/恢复及项目内检索、持久化检索结果，
  实际交接 ZIP 导出、全局快照、变更提案 accept/reject/defer，用户模型配置读写/默认/绑定，
  文档草稿 commit。修复 commit 审计 actor 信任客户端的问题；账号模式改用服务端认证主体。
- 新增 VERIFIED：文档 diff 双端版本、md/json/docx 私有版本下载、跨账号 confirm/approve、
  audit 内容、settings test/live-test 真实 Adapter/fake HTTP、相同局部 profile ID=1。
  confirm/approve 的 actor 改为服务端账号身份，非账号入口保留原合同。
- 新增 VERIFIED：真实 Chromium 正常按钮完成同账号 4 次生成及一次 6 claim 分析；
  fake transport 分别 4/6 次，终态及持久化结果成功，10 次 COMMITTED、0 活动预留；刷新 policy 正确。
- 新增 VERIFIED：真实 worker 传输失败及 shutdown cancellation 后释放预留，空闲回收、
  登录重建、同 key 重放保持原 FAILED，不再次调用。取消此前存在实际 reservation 泄漏，已最小修复。
- 新增 VERIFIED：在真实 fake 传输等待时 SQLite backup 捕获 RUNNING，原测试 writer 停止后
  仅恢复隔离库快照再重建 child；保留 RUNNING/RESERVED、不重新领取、不重复调用，foreign404。
- 剩余明确差距：用户取消 HTTP 入口当前 NOT_IMPLEMENTED；worker.stop 的取消测试不等于
  本次要求的 owner/foreign 取消 API 流程。没有用这个内部控制测试宣称 Phase A 的用户取消 gate 通过。
- 账号通过后：可选竞品候选→服务端项目快照→生成上下文→文档版本引用的最小切片。
- 后续仍未完成：统一用户草稿恢复/冲突检测、同模型 AI 参考完整体验、
  无资料人工确认交接、完整中文/缩放/登录到交接 E2E。统一跨模块草稿接口 NOT_IMPLEMENTED；
  多进程 NOT_VERIFIED。真实模型/搜索未验收，不自动部署。

### a585f32 后本轮验证记录

- 有效 RED：confirm/approve 的两个用例因 audit.actor 为 forged-body 失败；修复后资源矩阵 12 passed（56.63s）。
- 有效 RED：取消 fake 传输后 run FAILED，但 RESERVED=1，业务测试 1 failed / 4 passed（17.16s）。
  `ManagedQwenStructuredRuntime._call_async` 显式捕获 CancelledError，只释放用户预留并重新抛出；
  不修改 Provider ledger 或将已进入边界的调用改成未调用。GREEN 5 passed（17.23s）。
- `py -3.12 tests/run_account_browser.py --business`：真实 Chromium 正常 UI 4 个生成动作、
  4 个终态任务，1 个分析动作、6 个不同 claim、6 次 fake HTTP；真实 lifespan，外部连接尝试 0。
  合成 confirmed brief/claim 为前置 fixture，未写成功状态、计数或结果；不宣称完成 Idea 到交接 E2E。
- `py -3.12 tests/run_account_browser.py`：原账号领取/登录/创建保存/刷新/退出换账号/后端拒绝 PASS；
  生成 0、外部连接尝试 0。截图在被忽略的 artifacts/account-browser/，不含生产数据。
- 业务浏览器复跑 PASS；终态截图分别在 artifacts/account-business-browser/
  fourth-generation-terminal.png 和 six-claim-analysis-terminal.png，刷新截图 completed.png 不是终态证据。
  截图人工检查发现项目页顶部账号控件挤压/重叠，留在整体布局缺口；本批浏览器 PASS 仅指业务操作与隔离，不代表布局验收。
- 七个 `tests/*harness.js` PASS；Python compileall 与 git diff --check PASS。
- `py -3.12 tests/run_open_test_regressions.py`：fresh 130 passed（181.21s），0失败/跳过，外部尝试0；
  随后加入中断快照覆盖并加强重放断言，业务文件 fresh 6 passed（20.99s），外部尝试0。
  130项为定向集合，不是全库；不把新增后的6项结果与130简单相加。
- 最终重新执行同一完整定向命令：131 passed（178.51s），0失败/跳过，外部尝试0。
  七个 Node harness、compileall 再次 PASS；9个改动文件的秘密模式扫描0命中，人工diff未发现真实凭据/用户内容。
- Phase A 尚未结项，因此 Phase B NOT_STARTED；不是搜索未配置导致阻塞。

### 历史：上一轮验证记录

- 有效 RED：新增资料/草稿两项测试初跑 1 failed / 1 passed（9.69s）；
  草稿 commit audit.actor 实为客户端 forged-body，而非认证账号 ID。
  `app/main.py::commit_document_edit_draft` 改用可信 workspace_account；旧非账号入口保留原合同。
  GREEN 两项 2 passed（9.13s）。其余新增项属于既有行为覆盖，未人为制造产品 RED。
- `py -3.12 tests/run_open_test_regressions.py test_account_resource_matrix.py`：
  最终 7 passed（32.99s），外部连接尝试/真实连接均 0。
- `py -3.12 tests/run_open_test_regressions.py`：最终 fresh 123 passed（155.63s），
  0 failed / 0 skipped，包含原 116 项与新增 7 项；定向回归，不是全库测试。
  blocked_external_attempts=0，real_external_connections=0。
- `py -3.12 tests/run_account_browser.py`：真实 Chromium 账号领取/登录、policy、
  创建保存项目、刷新、退出换账号和跨账号拒绝 PASS；真实 lifespan，外部连接/生成均 0。
  不是第4次生成/第6个claim的浏览器业务证明。截图沿用本地忽略的 artifacts/account-browser/。
- `node tests/loading_progress_harness.js` PASS（mock请求）；变更 Python compileall、
  git diff --check PASS。五份变更文件常见真实密钥模式 0 命中；人工复核只有合成口令，
  未读取真实凭据。此扫描不宣称全仓库安全认证。
- 当前未覆盖入口及组合已在顶部和资源矩阵明确列出，非工具/授权阻塞，属于尚未完成工作。
  本次只提交资源权限增量；账号未结项，竞品垂直切片 NOT_STARTED。

## 历史实现记录（以下按当时状态保留）

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

## 追加：旧库绑定与资源边界定向补齐（2026-09-06，仍为 PARTIAL）

- 从 84617b 接续，保留既有认证、加载提示、文档 UX、不限默认值和生产卷配置。
- 资源证据附件：`docs/OPEN_TEST_RESOURCE_ISOLATION_MATRIX.md`。按实际路由列出已有证据及
  缺口，不把不存在的接口或随机 ID 的404视为完整资源隔离。
- 修复旧库签发/领取准入：只读检查 v206 基础结构；拒绝空库、无关库和截断库。
  事务内检查已签发/已绑定路径及物理文件别名，避免同一旧库重复分配。
  新增操作员服务级幂等撤销邀请，保留原记录；没有新增公开签发/撤销入口。
- 合成 v206 fixture 经显式绑定、实际登录、两次已有 additive migration 后原项目 ID/内容保留。
  当前 schema 的旧归属控制测试复用。仅此明确范围有证据，不保证所有历史 schema。
  发布仍须先停用旧写入者、保持映射路径稳定；没有访问生产旧库。
- 新增同局部项目 ID 的两个真实文档草稿隔离测试：owner 读写、匿名拒绝、伪造 actor、
  user_id/participant/workspace/database_path 参数不能选择另一用户库，另一份资源保持不变。
- 新增撤销/过期邀请、双线程同邀请领取唯一所有者、30分钟滑动闲置过期、退出失效，
  缺自定义头403、失效会话不降级到共享空间。不是完整安全认证。

### 本轮实际 RED / GREEN 与 fresh 验证

- `py -3.12 -m pytest tests/test_account_registry_boundaries.py -q --tb=short`：
  RED **5 failed, 3 passed in 4.44s**。三种不支持旧库未拒绝、硬链接重复绑定未拒绝、
  缺少 revoke_invite；最小修复后 GREEN **8 passed in 3.40s**。
  草稿/请求头新增测试覆盖已有正确行为，没有人为制造 RED。
- `py -3.12 tests/run_open_test_regressions.py`：**109 passed in 106.93s**；
  blocked_external_attempts=0、real_external_connections=0。包含账号、v206迁移及原
  quota/异步/文档/ledger/strict acceptance 定向控制，不是全库测试。
- `py -3.12 tests/run_account_browser.py`：实际 Chromium 账号领取/登录/建项目/保存/刷新/
  退出/换账号/跨账号拒绝 PASS；应用 lifespan 执行，外部连接与生成请求0。
  截图本地 `artifacts/account-browser/`，不提交。范围为1366×768已有账号流程，
  不等于不限政策浏览器、真实缩放或想法到交接 E2E。
- 加载提示回归 `node tests/loading_progress_harness.js` PASS；不是浏览器布局证明。
  一次误写的 loading_progress_behavior.cjs 命令因文件不存在失败，已纠正到现有入口。
- `py -3.12 -m compileall -q app/account_registry.py tests/test_account_registry_boundaries.py tests/test_open_accounts.py`
  PASS；git diff --check PASS；本轮六个变更文件常见真实凭据模式扫描0命中，人工检查仅合成测试值。
  不读取真实私密配置，不修改生产运行状态或数据。

### 本批仍未闭环（必须先完成，再进入用户级草稿恢复）

1. 矩阵内真实任务、资料、导出、设置及其他全局资源的 owner/foreign/匿名组合。
2. 实际 worker + Adapter fake 的跨账号任务归属、重建和同幂等键证明。
3. 第4次方案、第6次分析完整业务终态测试；前端不限政策及无秘密目标配置读取验证。
4. app/worker 空闲回收策略、并发首次初始化和运行中任务保护；多进程未验证。

整体后续仍包括模块/刷新草稿与冲突检测、同模型AI参考、无资料人工确认交接、
中文/布局/缩放和完整浏览器任务。当前增量不构成开放测试版本可发布证据。

## 追加：真实业务链与单进程空闲回收（2026-09-06，账号批次仍 PARTIAL）

- 接续 069b043，不修改生产配置、数据库、凭据或运行实例。
- 新增 WorkspacePool：同账号复用 child app/worker；ASGI 响应（包括流式响应）完成前持有租约。
  每30秒检查，闲置30分钟且无 PENDING/RUNNING 任务才回收。检查失败保留对象。
  状态不确定的 RUNNING 不自动重试，也不被空闲清理。仅单进程范围，多进程 NOT_VERIFIED。
- `tests/test_account_workspace_lifecycle.py`：可控时钟/事件验证并发首次初始化唯一、
  租约及 busy 保留、真实账号 worker 复用、退出后空闲回收和持久项目重开。
- `tests/test_account_business_paths.py`：真实账号 HTTP、业务 worker、Adapter，仅替换 httpx transport。
  同一合成日期，A连续4次方案成功，B用相同幂等键独立成功一次；共5次传输，每个 intent/run 各一次。
  全部终态 SUCCEEDED，业务响应201，run quota_status 为既有 CHARGED，reservation 为 COMMITTED；
  使用记录 A=4/B=1，活动 reservation=0。重放、轮询、已完成任务回收重建未增加调用。
  B读取A真实任务并伪造 workspace/user_id/participant 被拒绝。
- 6个不同 claim 各执行实际 evidence/analyze，真实 ModelAdapter fake传输6次；
  非缓存命中，全部处理完成，usage=6、COMMITTED=6、RESERVED=0。
  当前计量单元是 claim，不把一个多claim HTTP动作写成一次分析。
  合成无来源输入返回空关系，不制造来源。测试未修改计数来跨过旧限额。

### 本轮 RED/GREEN 与 fresh 结果

- 空闲生命周期新增测试初始 RED：2 failed（缺少 WorkspacePool）；最小实现后2 passed in 0.58s。
  并发首次访问及完整业务链是新增覆盖，没有人为破坏已有正确行为制造RED。
- 完整业务链开发中两次失败分别因测试误断言响应200（实际201）、run状态COMMITTED（实际CHARGED）。
  已按既有合同修正测试，不修改生产终态语义；不把这些测试构造错误当产品缺陷。
- `py -3.12 tests/run_open_test_regressions.py test_account_business_paths.py`：2 passed in 11.19s。
- 最终 `py -3.12 tests/run_open_test_regressions.py`：114 passed in 164.31s，0 failed/0 skipped；
  保留原109项并新增5项；blocked_external_attempts=0、real_external_connections=0。不是全库测试。
- `py -3.12 tests/run_account_browser.py`：真实 Chromium 1366×768账号领取/登录/创建/保存/刷新/
  退出/换账号/后端拒绝 PASS；lifespan已执行，生成0、外部连接及阻断尝试0。
  这是既有账号流程复跑，**不限政策超过旧限额的浏览器流程 NOT_RUN**。
- `node tests/loading_progress_harness.js` PASS；相关4个Python文件 compileall PASS；git diff --check PASS。

### 本批具体剩余项（不进入发布）

1. 资源矩阵仍为分组清单，尚未逐个(method,path)穷举计数；详见原矩阵逐行 NOT_RUN。
   资料/检索、交接导出、设置及全局对象还缺真实owner/foreign/匿名组合，文档草稿commit仍缺跨账号测试。
2. 真实Adapter阻塞期间退出/切账号、运行中worker重建、任务匿名访问，以及取消/失败后回收组合尚未验证。
   已完成任务重建和pool层busy保护不能替代这些组合。
3. 第4/第6次后端完整链已通过；前端实际policy超额提交/刷新、旧耗尽缓存与文案、
   无秘密开放测试目标配置实际加载仍未闭环。
4. 旧库兼容范围保持v206 fixture和当前schema，不扩大；统一跨模块草稿 NOT_IMPLEMENTED。
   完成以上缺口后才进入用户级草稿恢复与冲突检测，后续AI参考/无资料交接/完整中文布局E2E仍待做。

## 追加：竞品包读取及账号前置收口增量（2026-09-06）

接续3e26b402fa174338a3f5f86969ed2e93bd749afd，初始工作区干净，未回退。
已从用户提供ZIP读取README.md、docs/02_竞品到方案闭环规格.md、
docs/03_整合与验收边界.md、CODEX_TASK.md。包内说明作为设计输入，
不能覆盖当前工程权限/持久化合同；没有执行参考包代码、联网取证或导入八个示例产品。

### 实际文件/接口映射与未完成边界

| 接入点 | 当前实际位置 | 本次状态 |
| --- | --- | --- |
| 账号与项目归属 | app/accounts.py、app/account_registry.py；会话绑定账号子app/数据库 | 运行中任务退出换账号补测通过；完整资源矩阵仍PARTIAL |
| 不限政策 | app/main.py GET /api/usage/policy；app/static/app.js、index.html | 页面接入权威policy；不把null当0，不缓存政策；目标示例离线加载验证 |
| 手动项目资料 | app/services/source_guidance.py、sources.py；POST /api/projects/{id}/sources/guided | 未来复用点；本次未增加竞品候选与确认API |
| 方案读取/选择 | app/services/solution_design.py、snapshots.py；GET solutions、POST solutions/select | 未来复用点；未改已有人工选择；不能直接把客户端confirmed当竞品事实凭据 |
| 文档与版本 | app/services/document_workspace.py、document_versions.py；draft、draft/commit及版本接口 | 保留原实现；未增加竞品决策快照字段 |
| 项目快照 | GET /api/projects/{id}/snapshots、GET /api/project-snapshots/{id} | 待新增服务端项目范围引用验证后接入；未实现 |
| 看看已有产品/AI补充思路 | 必须走现有业务模型服务与Adapter传输边界 | 本次NOT_IMPLEMENTED；尚未证明竞品生产模型接线或候选采纳链 |

八产品仅为InsightForge自身研究示例，不作为任何用户项目默认答案。
来源引用存在/一致不证明事实真实；公开页不转成真实用户研究。
搜索能力没有在本批配置或调用，不能声称实时搜索可用。

### 已完成的前置增量与证据

- 新增 deploy/beta/open-test.env.example：账号开启、持久化路径引用、日限额关闭、HTTPS secure cookie。
  测试先加载该文件覆盖合成旧限额true，核对Settings；构造app前改为临时路径及本地HTTP cookie。
  真实claim/login及policy返回false/null通过。不代表线上配置启用或任何未来override都安全。
- 页面新增权威policy说明，初始化/返回可见页面重新读取；失败明确说明无法读取，不锁死操作，
  不宣称免费或无Provider成本。没有增加次数限制，没有删除历史/结算保护。
- 有效RED：真实Chromium等待#usage-policy超时5秒；修复页面接线后GREEN。
  实际浏览器覆盖登录、policy、创建/保存项目、刷新、退出、换账号及外来项目拒绝；1366×768。
  不包含浏览器第4次生成或完整交接。截图 artifacts/account-browser/（本地忽略，不提交）。
- 新运行中任务测试走HTTP→真实worker/AsyncModelAdapter→fake httpx，传输边界用线程事件同步。
  A owner读200、退出匿名401、B伪造身份参数读404；busy回收保留原child；A重登终态SUCCEEDED。
  该任务fake传输1、COMMITTED1、RESERVED0。未向任务表注入完成状态。
- 此测试初次1 failed/2 passed是测试跨线程asyncio.Event唤醒错误，不是产品RED；
  使用worker循环call_soon_threadsafe后3 passed in 16.20s，外部连接尝试0。
- 配置/不限定向5 passed in 8.07s；真实Chromium和加载提示harness PASS，外部调用0。
- 最终fresh `py -3.12 tests/run_open_test_regressions.py`：116 passed in 169.31s，
  0 failed/0 skipped；blocked_external_attempts=0、real_external_connections=0；这是定向而非全库测试。
  `py -3.12 tests/run_account_browser.py` PASS，实际lifespan，外部连接/阻断尝试/生成均0。
  `node tests/loading_progress_harness.js`、两份变更JS语法检查、两份变更Python compileall、
  git diff --check PASS；八份变更文件常见真实密钥模式扫描0命中，人工review仅合成凭据。

账号批次仍PARTIAL：资料/检索、实际交接导出、设置/全局对象、文档草稿commit跨账号组合仍未补齐；
运行中worker重建、取消/失败回收组合及浏览器超过旧限额提交仍未验证。
因此竞品功能最小接入尚未开始，不能把读包或前置测试写成竞品集成PASS。
统一草稿、AI参考、无资料交接、完整中文/缩放/E2E仍按原依赖顺序待做；不新增重复清单。

## 2026-09-07 草稿恢复真实 Chromium 收口

本轮接续 `833771524cf6f697a638036181d17784075acf09`。审查了此前未跟踪的
`tests/draft_recovery_browser.cjs` 与 `tests/run_draft_recovery_browser.py`：二者是正式的
隔离草稿浏览器 runner，不是截图、trace、缓存或调试产物；未包含绝对工程路径、真实账号、
凭据或真实数据库。它们已整理并纳入测试版本控制。Python runner 使用项目既有 bundled
Node Playwright/Chromium 运行时，在隔离 ASGI 应用、合成账号、临时 SQLite/runtime 中运行；
Provider 仅在 Adapter 传输边界使用 `httpx.MockTransport`，外部连接被 loopback tripwire 阻断。

真实 Chromium 流程 fresh PASS：generation restore（generation POST=1、逻辑任务=1、
fake generation transport=1、poll GET=11）；竞品比较恢复（comparison POST=1、fake comparison
transport=1，结果/选择/未保存取舍可恢复）；Idea→竞品→PRD 的 back/forward 无新增动作 POST；
迟到 draft 响应不污染另一账号页面；登出隔离和双标签页 HTTP/CAS 冲突均通过。

本轮 fresh：`py -3.12 tests/run_draft_recovery_browser.py` PASS（外部连接0）；
`py -3.12 tests/test_unified_drafts.py` PASS；`node tests/draft_recovery_behavior_harness.js`
PASS；`py -3.12 tests/run_open_test_regressions.py` 为 146 passed、0 failed、0 skipped，
network tripwire blocked_external_attempts=0、real_external_connections=0；JS syntax、
compileall、git diff --check PASS。

统一草稿恢复代码级能力及真实 Chromium 证据已收口；本轮不涉及真实 Provider/Search、生产部署、
AI 补充思路或无资料人工确认交接。整体开放测试版本仍为 PARTIAL。
