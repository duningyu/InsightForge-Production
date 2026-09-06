# 开放测试资源隔离矩阵（源码检查点 84617b 后的有限补测）

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
| 异步方案任务 | POST projects/{id}/solutions/generate；GET …/generate/{run_id} | 账号绑定 AsyncGenerationRepository，participant+project+run 查询 | 原随机 run ID 测试不够；真实 worker/Adapter fake、账号切换、同幂等键、重建完整矩阵未完成 |
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

目前进程内 lock/children 复用子 app；没有空闲回收策略。
本批未修改该生命周期，也未证明并发首次初始化/运行中回收/重建无重复调用。
仅现有单进程测试运行方式有证据，多进程尚未验证，不宣称无限并发能力。
