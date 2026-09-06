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

这不是完整开放使用实现：前端全部旧额度说明尚未清理，可扩展账号也未实现。
不得把测试中的 beta004/beta005 计数身份当成第四、第五名实际注册用户。

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
