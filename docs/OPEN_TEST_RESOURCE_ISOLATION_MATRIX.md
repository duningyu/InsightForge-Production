# 开放测试资源隔离矩阵（源码检查点 84617b 后的有限补测）

## 当前增量：a585f32 后的真实资源覆盖

新增测试位于 `tests/test_account_resource_matrix.py`，该文件现在 12 个用例。
下列状态覆盖后文相同入口的历史 NOT_RUN 标记；历史结果不作为本轮 fresh 结果。

| 实际 method/path | 正向与隔离结果 | 状态 / 测试 |
| --- | --- | --- |
| GET `/api/documents/diff` | owner A1→A2 / B1→B2 200；混合两端及完全 foreign 404；匿名401；不返回 foreign 正文 | VERIFIED `test_diff_checks_both_versions_and_private_downloads` |
| GET `/api/documents/{version}/export?format=md/json/docx` | owner200 attachment；foreign404；匿名401；原内容不变 | VERIFIED 同上，无独立裸露文件 URL |
| POST `/api/document-versions/{version}/confirm`; POST `/api/documents/{version}/approve` | owner200；foreign404；匿名401；拒绝后状态不变；伪造 actor/header 不影响真实 audit.actor | VERIFIED `test_confirmation_uses_server_actor_and_rejects_foreign_version` 两参数 |
| GET `/api/audit` | owner200含自己真实事件；foreign query/filter 不能切换 DB，不返回另一账号/项目/版本标记；匿名401 | VERIFIED `test_audit_content_is_account_scoped_even_with_foreign_filters` |
| POST `/api/settings/model-profiles/{id}/test`, `/live-test` | owner200；foreign真实UUID404且不调用；匿名401；同局部ID1只用本账号模型；secret值不返回 | VERIFIED `test_settings_transport_and_same_local_profile_id_are_workspace_scoped`，真实service/Adapter，fake HTTP 每用户3次 |

设置分类：model-profiles 为 USER_SETTING；mode 为 GLOBAL_SAFE_SETTING；api_key 为
SECRET_SETTING（使用合成内存凭据后端，不读取真实密钥）；test/live-test 为 PROVIDER_TEST_ACTION。
上述确认测试仅以 fixture 提供 validation/health 前置条件，不冒充校验到交接 E2E。

生命周期：`test_failed_transport_settles_and_reconstructed_worker_does_not_redispatch`
验证传输失败和 worker shutdown cancellation，释放后重建不重发，两个参数各 fake 1 次。
进程中断后不确定调用重建 VERIFIED：同函数 interrupted_snapshot 参数，在实际传输边界
SQLite backup 获取 RUNNING，停止原隔离 writer 后恢复测试快照；重建保留 RUNNING/RESERVED，
claim_next 不领取，原 key 返回原202，foreign404，fake调用仍1。
用户取消 HTTP 入口 NOT_IMPLEMENTED，不能将 worker.stop 当成该入口权限 PASS；
本次要求的 owner/foreign 用户取消流程仍未交付。已有 completed 重建、运行中切换账号和 busy 保留测试继续保留。
真实 Chromium 第4次生成 / 第6 claim 终态与持久化已 VERIFIED：
`tests/run_account_browser.py --business`、`tests/account_business_browser.cjs`。
账号批次仍 PARTIAL；竞品和统一跨模块草稿仍 NOT_IMPLEMENTED，多进程 NOT_VERIFIED。

## 既有资源覆盖（继续保留）

下表优先于后文历史状态。共同认证入口为服务端账号会话及 WorkspacePool 独立 DB；
下列每项均使用实际合成资源，owner 正向成功、匿名401、foreign拒绝后重新核对原资源。
测试位置统一为 `tests/test_account_resource_matrix.py`（7个用例）。

| 实际 method/path | owner / foreign / anonymous | 状态与证据函数 |
| --- | --- | --- |
| POST `/api/projects/{p}/sources/upload`; GET `…/sources` | owner201/200；foreign已有上传控制复用，读取404；匿名读取401 | VERIFIED `test_uploaded_sources_and_persisted_retrieval_are_account_and_project_scoped` |
| POST `/api/projects/{p}/sources/{s}/archive`, `/restore` | owner200；foreign422 SOURCE_SCOPE_MISMATCH；匿名401；内容不变 | VERIFIED 同上 |
| POST `/api/projects/{p}/retrieve`; GET `…/retrieval-runs`; GET `/api/retrieval/runs/{r}` | owner200且只含本项目来源；foreign404；匿名401；持久化结果不变 | VERIFIED 同上；同账号第二项目、另一账号各有不同真实资料 |
| POST `/api/projects/{p}/documents/{type}/draft/commit` | owner201新版本；foreign404；匿名401；原版本/草稿不变 | VERIFIED `test_document_draft_commit_is_scoped_and_uses_authenticated_actor`；审计actor伪造RED后修复 |
| GET `/api/project-snapshots/{s}`; GET `/api/projects/{p}/handoff/readiness`; POST `…/handoff/export` | owner200且真实ZIP；foreign404；匿名401；版本/导出记录不变 | VERIFIED `test_handoff_zip_and_global_snapshot_have_owner_positive_controls` |
| GET/POST `/api/settings/model-profiles`; PATCH/DELETE `…/{id}`; POST `…/{id}/set-default`; GET/PUT `/api/projects/{p}/model-profile` | owner创建201/修改绑定200/删除非默认204；foreign404且列表无他人profile；匿名401 | VERIFIED `test_user_profile_settings_are_private_without_reading_credentials`；默认删除409按合同保留，未读凭据 |
| GET `/api/settings/mode` | 已登录200公开运行模式元数据，不返回他人设置 | VERIFIED 同上；非秘密产品配置不是越权内容 |
| GET `/api/projects/{p}/change-proposals`; POST `/api/change-proposals/{id}/accept`, `/reject`, `/defer` | owner200；foreign404；匿名401；拒绝后提案/快照不变 | VERIFIED `test_global_change_proposal_actions_are_workspace_scoped` 三个参数用例 |

交接测试以合成 fixture 设置校验通过作为资源准备，再经实际HTTP人工确认和导出。
它只证明真实资源权限，不证明完整校验流程或浏览器交接E2E。
设置未提供API key，未读取真实凭据；test/live-test不在本次覆盖中。
资料没有独立原文件下载路由的既有结论不变，不能虚构下载验收。

本段历史 NOT_RUN 已由顶部当前增量替代；本轮列出的现存入口已覆盖，用户取消入口仍未实现。
统一跨模块草稿和竞品候选/快照接口 NOT_IMPLEMENTED；账号批次仍PARTIAL。

## 历史矩阵（保留当时状态，以顶部当前增量为准）

本文件是统一进度文件的证据附件，不是独立发布清单。全部数据为合成数据。
共同入口：`app/accounts.py::route_workspace` 验证服务端会话，经 AccountRegistry
读取固定 database/runtime/participant，创建对应业务 app；各服务只查询该 app 的 DB。
客户端的 workspace/user_id/数据库路径不参与选择。无会话 API 返回401。
隔离不依赖每个表的 owner 列，而依赖此服务端数据库绑定及业务内资源关联检查。

| 资源 | 实际接口/动作 | 归属判断及已有证据 | 本批状态/缺口 |
| --- | --- | --- | --- |
| 项目 | GET/POST `/api/projects`、GET `/{id}` | 账号 DB；test_open_accounts 五个真实领取账号、真实项目、外来 ID 拒绝 | 已有控制复用 |
| 文档/版本/下载 | `/api/documents/{version_id}`、claims/export/trash/restore/restore-as-new、DELETE | 账号 DB 内版本查询；同文件 test_explicit_legacy_mapping… 使用实际合成 PRD/TechDoc | 已有读写/导出拒绝；匿名版本下载、diff 两端 ID、人工确认还需矩阵补测 |
| 文档编辑草稿 | GET/PUT `/api/projects/{id}/documents/{type}/draft`；POST draft/commit | DocumentWorkspaceService 校验项目及 base 版本关联 | 新增 test_existing_drafts_same_local_project_id_and_anonymous_boundary：两个库同项目 ID、不同实际草稿，owner 读写成功、匿名拒绝、伪造 actor 被服务器替换、客户端路径提示无效、另一库不变；commit 跨账号矩阵待补 |
| 资料/上传 | projects/{id}/sources、sources/upload、sources/{source_id}/archive/restore | 账号 DB及项目关联；已有外来项目上传拒绝 | 已存在资料内容、修改与匿名矩阵待补；main.py 未发现单独原文件下载路由，不虚构已测下载 |
| 异步方案任务 | POST projects/{id}/solutions/generate；GET …/generate/{run_id} | 账号绑定 AsyncGenerationRepository，participant+project+run 查询 | test_account_business_paths：真实 HTTP/worker/Adapter fake，A四次、B一次；owner终态读取、B带伪造身份查询A真实任务404、同幂等键独立、重放/轮询及完成后重建不重发 VERIFIED；运行中退出/切换/重建及匿名真实任务组合 NOT_RUN |
| 检索任务 | GET `/api/retrieval/runs/{run_id}`、projects/{id}/retrieval-runs | 账号 DB | 真实已有任务 owner/foreign/匿名待补 |
| 交接 | projects/{id}/handoff/readiness、POST handoff/export | 账号 DB及项目关联 | 外来项目拒绝已测；实际可导出项目 owner 成功及 foreign 不泄露尚待补 |
| 设置 | `/api/settings/model-profiles` 及 PATCH/DELETE/{id}、操作绑定 | 账号 app 的 profile service；managed 模式只读 | 本批匿名/失效会话入口拒绝；两个账号实际 profile 相同局部 ID 修改隔离待补，不调用 test/live-test |
| 全局入口 | `/api/project-snapshots/{id}`、`/api/change-proposals/{id}/accept` 等、`/api/audit` | 同一会话 workspace 路由 | 实际已存在对象矩阵待补；audit 失效会话拒绝已测 |
| 跨模块/表单恢复 | 尚无本批实现的统一用户级恢复接口 | 不以文档草稿替代所有模块草稿 | 未实现，本批不覆盖；后续加入此矩阵 |

本矩阵总体为 PARTIAL，不能推导全部资源隔离或安全认证 PASS。
方案任务取消/恢复 HTTP 入口未在本次 main.py 路由清单发现；已有 worker 内部处理不等于公开接口。

## 旧库兼容边界

测试定义仅覆盖仓库 `tests/fixtures/v206_schema.sql` 和当前 Database.init_schema 结构。
AccountRegistry 在签发及领取时只读检查 v206 基础表和关键身份/内容列；它不是任意旧库迁移器。
空库、无关库、缺 document_versions 的截断库拒绝，原文件字节不变。
已有迁移仍由 Database.init_schema 执行；合成 v206 重复迁移保留原 project ID/content。
原有合成当前库测试证明首个新账号不会收养未映射数据。
绑定比较规范路径与 samefile，拒绝数据库硬链接、目录别名及重复 participant。
注册表事务串行化签发/领取；保留已领取及撤销记录，不自动解除旧库绑定。
操作员须先停用旧写入者并保持绑定路径稳定；不支持一边替换路径目标一边领取的发布操作。
此处没有读取、迁移或核实生产旧用户数据。

## 生命周期边界

本轮从069b043接续，新增最小 WorkspacePool：整个ASGI响应持有lease；
30分钟无请求且无PENDING/RUNNING持久化任务才回收，每30秒检查。
查询任务状态失败时保留对象；不确定RUNNING继续保留，不自动重试。
test_account_workspace_lifecycle 的可控时钟/Event验证：复用、并发首次访问初始化一次、
请求lease/忙状态保护、空闲退出、实际worker停止与原项目重开 VERIFIED。
test_account_business_paths 验证已完成真实任务在子app回收重建后仍可查询、无新fake调用 VERIFIED。
运行中真实Adapter被阻塞时退出/过期、取消/失败后的资源回收组合 NOT_RUN；忙状态单元测试不能替代它们。
单进程支持边界；多进程 NOT_VERIFIED，不宣称任意并发能力。

## 完整业务链计数证据（本轮增量）

tests/test_account_business_paths.py 使用真实账号领取/登录与业务HTTP入口，只在Adapter HTTP传输替换fake。
合成confirmed brief及claim仅作为前置fixture，不写入任务完成状态或生成结果。
固定合成日期2026-09-06、不限政策：A四次独立方案操作/B一次，五个不同run各一次传输；
每次SUCCEEDED、结果落库、async quota_status=CHARGED（原词汇）、reservation=COMMITTED；
每日usage分别4/1、无活动reservation。HTTP terminal status_code按原合同201。
六个不同claim分别经证据分析HTTP入口/真实业务/同步Adapter，六次传输、usage6、六个COMMITTED、零RESERVED。
无资料时fake合法空relations，不虚构来源；每条确实经过Adapter，不以缓存命中或202代替结果。
本矩阵仍按资源族列出，尚未建立完整(method,path)路由计数，不能把10行资源族称作10个已验收接口。

## 2026-09-06 后继补测（接续3e26b402）

`test_running_task_keeps_workspace_after_logout_and_account_switch`：真实生成POST202，
worker在真实AsyncModelAdapter的fake HTTP传输等待；owner实际任务GET200，退出后同任务GET401，
另一账号携带伪造workspace/user_id/participant/database_path查询同任务404，响应无run内容。
忙任务在可控时钟触发sweep后仍绑定原账号child；原账号重登后同run SUCCEEDED，
fake传输一次、COMMITTED一次、无活动reservation。此组合更新为VERIFIED。
不是运行中worker销毁/重建证明；后者及取消/失败回收仍NOT_RUN。

真实Chromium新验证GET /api/usage/policy驱动页面不限说明，刷新/换账号一致；
不等于浏览器执行第4次生成。开放测试env示例实际离线加载并通过HTTP账号/policy验证。
所有其他未完成矩阵项保留NOT_RUN；统一跨模块草稿及竞品候选接口NOT_IMPLEMENTED。
