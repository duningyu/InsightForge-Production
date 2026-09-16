# InsightForge｜IF-GUIDE-R1.1 完整产品主线与评测主线
**版本：R1.1 补充规范｜日期：2026-09-15**

> **基准声明**  
> 本文以 `IF_GUIDE_R1` 的 `MAINLINE_RULES.md`、`TECHNICAL_ROUTE.md`、`WORKSPACE_RULES_APPEND.md`、`CODEX_START.md`、`SOURCES.md` 为产品主线基准。  
> R1.1 不推翻 R1；它只补齐“AI 输出质量量化、跨阶段继承评测、M4 真实用户评测”这条评测主线。  
> 当前真实仓库的文件、接口和已实现能力仍需在 M0 中核实；本文中的逻辑对象不是对当前源码路径的断言。

---

# 0. 一句话定位

InsightForge 的核心不是“把一个想法自动生成成 PRD”，而是：

> **帮助会使用 AI 工具、但不会拆解任务、判断优先级和验收结果的学生、转岗者及早期实践者，从一个模糊 Idea 或真实问题出发，用最低必要投入完成一个可判断的行动、第一条可用流程、必要的开发交接和真实验收，并依据结果决定继续、缩小、调整或结束。**

主线：

```text
Idea / 真实问题 / 半成品
→ 明确本次目的
→ 一个低成本判断动作
→ 第一条可用流程
→ coding 任务与验收
→ 用户结果回传
→ CONTINUE / NARROW / CHANGE / STOP / FINISH
```

PRD、TechDoc、Formal Handoff 保留，但它们是**真实决策与结果的派生产物**，不是所有项目的默认完成标准。

---

# 1. 产品主线的不可退让原则

沿用 R1：

1. **目的先于流程**：LEARNING、PERSONAL_USE、FOR_OTHERS 分别定义成功；未知目的保留 `UNSPECIFIED`。
2. **零证据可以开始**：低风险探索不要求先交市场报告、资料库或商业证明。
3. **验证不是找支持**：允许反证、缩小和停止。
4. **一次只推进一小步**：优先一个低成本动作或一条可用流程。
5. **非 AI 方案可成立**：手工、表格、低自动化也可能是正确答案。
6. **代码生成不是完成**：生成代码、任务包或导出包不等于运行、通过测试或上线。
7. **验收必须用户能做**：写清操作、输入、预期结果和失败处理。
8. **结果必须改变下一步**：系统需要消费真实结果，而不是只解锁模板。
9. **来源身份不升级**：用户输入、模型假设、真实观察、模拟材料和实现证据分开。
10. **低风险可逆推进**：敏感数据、付费、公开发布、删除等仍需适当授权。
11. **保留兼容与可靠性**：账号隔离、幂等、额度、版本、历史、恢复不能因为新主线而回退。
12. **不强造复购**：目标完成或有依据地停止都可以是正常结果。

R1.1 新增一条：

13. **生成成功不等于内容正确**：Action Card、Prototype Task、PRD、TechDoc、Handoff 的内容质量必须有可解释指标与 Ground Truth 边界。

---

# 2. 三类目的与成功定义

## 2.1 LEARNING

目标：

> 用户是否完成目标能力练习，并能够解释为什么这样做、哪里通过、哪里失败。

第一份合格材料：

- 一次练习产物；
- 用户自己的解释；
- 对检查项的实际判断。

不要求：

- 市场规模；
- 用户访谈数量；
- 付费意愿。

## 2.2 PERSONAL_USE

目标：

> 这个方法是否比用户自己当前处理真实任务的办法更有效。

第一份合格材料：

- 一份真实输入；
- 现有处理方式；
- 小方法/小流程的前后对照；
- 差异与局限。

不要求证明需求普遍存在。

## 2.3 FOR_OTHERS

目标：

> 目标用户是否真的遇到问题，以及当前办法哪里不足。

第一份合格材料：

- 一次具体行为观察；
- 一次手工测试；
- 一次原型反馈。

少量观察只能作为探索线索，不自动升级成“市场需求已验证”。

## 2.4 UNSPECIFIED

允许：

- 低风险；
- 可逆；
- 不产生商业强主张的探索。

禁止：

- 默认商业化；
- 默认市场验证；
- 自动替用户选择目的。

---

# 3. 产品主线：从 Idea 到结果

## 阶段 A：Purpose

用户首先回答：

> 这次你想完成什么？

选择：

```text
LEARNING
PERSONAL_USE
FOR_OTHERS
UNSPECIFIED
```

目的由用户确认；模型只能提议，不能代确认。

---

## 阶段 B：First Action

系统不是先要求 PRD，而是给出一张具体首次行动卡：

```text
你正在验证什么
为什么现在做
拿什么材料
具体怎样做
交回什么
怎样检查
不同结果说明什么
什么时候可以停
```

M1 先用**受控、版本化模板**生成，不默认增加真实模型调用。

---

## 阶段 C：Result Submission

用户后续可以通过：

```text
我做完了
我卡住了
```

回传实际产物、检查记录、失败步骤和安全脱敏的错误信息。

M1 只做到 Action Card；Submission/Review 进入 M3。

---

## 阶段 D：Result Review

对结果逐项使用：

```text
PASS
FAIL
UNKNOWN
NOT_APPLICABLE
```

复核层级：

```text
USER_REPORTED
ARTIFACT_CHECKED
AUTHORIZED_RUN
```

其中 `AUTHORIZED_RUN` 只有真实授权运行后才能使用。

---

## 阶段 E：Decision

单独保存：

```text
CONTINUE
NARROW
CHANGE
STOP
FINISH
```

状态结束与业务决策不混为一谈：

```text
CLOSED ≠ 成功
FINISH ≠ 上线
PASS ≠ 市场成立
```

---

## 阶段 F：First Usable Flow

当结果支持继续时，收敛一个最小用户流程。

例如课程通知工具第一版只做：

```text
粘贴通知
→ 提取事项与截止时间
→ 展示原句
→ 用户确认/修改
→ 保存
→ 重新打开
```

不自动扩成账号、支付、批量抓取或复杂提醒。

---

## 阶段 G：Coding Task

输出 `PROTOTYPE_TASK`：

- 本轮范围；
- 输入输出；
- 当前目的；
- 不能改变的已有行为；
- 明确不做；
- 已核实技术输入；
- 实施任务；
- 用户验收；
- 异常恢复；
- 需要返回的运行结果；
- 权限与风险。

`PROTOTYPE_TASK` 不等于 `FORMAL_HANDOFF`。

---

## 阶段 H：Formalization（条件式）

只有在项目需要更正式的产品定义和交付时，才进入：

```text
Solutions（如确有多种合理路径）
→ 用户选择
→ Snapshot
→ PRD
→ TechDoc
→ FORMAL_HANDOFF
```

现有正式 Handoff 的审批、版本、健康检查不能被 Prototype Task 绕过。

---

# 4. 产品核心数据对象

R1 逻辑对象：

## 4.1 ProjectIntent

最小语义：

```text
project_id
purpose
confirmed_by
goal
constraints
revision
created_at
updated_at
```

规则：

- purpose 可变；
- 历史项目默认为 `UNSPECIFIED` 语义；
- 不自动推断商业目的；
- purpose 改变后后续任务需要重评。

## 4.2 ActionTask

最小语义：

```text
task_id
project_id
kind
goal
inputs
steps
expected_artifact
checks
branches
stop_condition
snapshot_version
revision
state
template_version
```

Task kind：

```text
OBSERVE
MANUAL_TEST
LEARNING_EXERCISE
BUILD_SLICE
ACCEPTANCE
RECOVERY
```

生命周期：

```text
DRAFT
→ READY
→ IN_PROGRESS
→ SUBMITTED
→ CLOSED
```

特殊：

```text
NEEDS_REVISION
PAUSED
```

## 4.3 ActionSubmission

M3 使用：

```text
submission_id
task_id
task_revision
description
attachment_refs
execution_claim
```

保存用户实际提交，不自动等价于系统验收。

## 4.4 ActionReview

M3 使用：

```text
review_id
submission_id
check_items
known_unknown
recommendation
confirmation_record
```

---

# 5. 来源与事实身份

统一保留：

```text
USER_INPUT
MODEL_HYPOTHESIS
REAL_OBSERVATION
SIMULATION
IMPLEMENTATION_EVIDENCE
```

解释：

- `USER_INPUT`：用户自己提供；
- `MODEL_HYPOTHESIS`：模型推断或建议；
- `REAL_OBSERVATION`：用户声明并提供的真实观察记录，但不代表平台独立核实；
- `SIMULATION`：模拟材料；
- `IMPLEMENTATION_EVIDENCE`：代码、日志、运行/检查证据。

**任何层级都不能静默升级。**

---

# 6. M0—M4 产品里程碑

## M0｜当前模块映射

必须从真实仓库确认：

- 启动链；
- Project/账号/存储；
- 前端入口；
- revision/concurrency；
- 历史恢复；
- 可复用服务；
- 测试命令；
- feature flag；
- 已有等价 intent/action 能力。

输出：

`docs/mainline/IF_GUIDE_R1/WORKSPACE_MAP.md`

完成后立即进入 M1，不停在盘点。

---

## M1｜零资料首次行动

目标：

```text
Project
→ 用户确认 purpose
→ First Action Card
→ 编辑
→ 保存
→ 刷新恢复
→ 重新进入恢复
```

三类 purpose 使用不同动作逻辑。

M1 默认：

```text
Provider = 0
Search = 0
```

完成即停止。

---

## M2｜第一条可用流程与任务交接

目标：

- 根据 purpose 和已有结果收敛一个 `BUILD_SLICE`；
- 生成 `PROTOTYPE_TASK`；
- 用户确认范围；
- 有具体验收步骤；
- 不绕过 Formal Handoff。

---

## M3｜结果回传与恢复

目标：

```text
我做完了
我卡住了
```

系统：

- 检查 submission；
- 保留 UNKNOWN；
- 生成最小恢复动作；
- 形成用户确认的 Decision。

---

## M4｜评测与受控试用

目标：

比较：

```text
静态模板
vs
通用 AI + 清晰 Prompt
vs
IF 状态化引导
```

8—12 名真实目标用户，覆盖三种目的。

R1.1 在这里正式加入内容质量与链路质量评测。

---

# 7. 为什么不能只写一个“准确率”

InsightForge 的输出是开放式结构化内容，不是天然二分类。

因此不使用一个模糊的：

```text
Accuracy = 95%
```

替代真实质量。

优先使用：

- Requirement Recall；
- Critical Requirement Recall；
- Alignment Precision；
- Coverage；
- Factual Precision；
- Unsupported Claim Rate；
- Inheritance Accuracy；
- Critical Contradiction Rate；
- Completeness；
- Actionability。

对于结构/身份/版本类问题，可以使用明确的 Accuracy，并作为硬 Gate。

---

# 8. Ground Truth 体系

## 8.1 用户 / Idea Provider

最终确认：

- purpose；
- 用户真实需求；
- 关键约束；
- 是否符合原意；
- 方案选择；
- 最终用户价值反馈。

## 8.2 Independent Human Reviewer

负责：

- requirement mapping；
- claim factuality；
- semantic inheritance；
- contradiction；
- completeness/actionability；
- 技术可行性等需要专业判断的项目。

## 8.3 LLM-as-Judge

只允许辅助：

- 提取 requirement candidates；
- 提取 claim candidates；
- 找 contradiction candidates；
- 形成 reviewer 待核清单。

不能：

```text
模型定义 Gold Set
→ 模型自己评分
→ 模型宣布自己准确
```

---

# 9. Requirement Gold Set

当需要计算需求 Recall 时，先建立人工确认的需求集。

来源：

```text
用户原始输入
+ 用户确认的 purpose
+ 用户确认/修改后的需求和约束
```

建议最小项：

```text
requirement_id
canonical_text
importance = CRITICAL / SECONDARY
source
confirmed_by
revision
```

覆盖映射：

```text
COVERED
PARTIAL
NOT_COVERED
CONTRADICTED
NOT_APPLICABLE
```

M4 正式比较前冻结 rubric 与映射规则。

建议同时报告：

### Strict Recall

`PARTIAL = 0`

```text
Strict Recall =
完全覆盖的 Gold Requirements
÷
Gold Requirements 总数
```

### Weighted Recall

`PARTIAL = 0.5`

```text
Weighted Recall =
Σ coverage_weight
÷
Gold Requirements 总数
```

Critical Recall 单独计算。

---

# 10. 评测主线总览

整个产品的评测分为四组：

```text
A. 产品价值指标
B. AI / 系统内容质量指标
C. 跨阶段链路一致性指标
D. 生产工程指标
```

一个层通过不能替代另一个层。

---

# 11. A｜产品价值指标

沿用 R1：

## 11.1 首次有效行动率

```text
在约定时间内完成一个可检查动作的项目
÷
全部启动项目
```

按 purpose 分组。

## 11.2 首条可用流程完成率

```text
实际完成最小用户流程并通过对应验收的项目
÷
进入该开发任务的项目
```

另报总体转化。

## 11.3 独立验收率

用户不依赖额外代操作，就能按验收步骤判断 PASS/FAIL 的任务比例。

必须包含故意植入错误案例。

## 11.4 有依据决策率

CONTINUE/NARROW/CHANGE/STOP/FINISH 是否有：

- 可核查产物；
- 行为观察；
- 真实检查；
- 合理分析；

作为支撑。

不等于商业需求验证率。

## 11.5 卡点恢复率

```text
恢复到可继续动作的阻塞任务
÷
全部提交阻塞任务
```

未解决项不能从分母中删除。

## 11.6 严重错误与成本

统计：

- 越权；
- 重复派发；
- 伪造证据；
- 错误宣称已运行/已验证；
- Provider 调用；
- 成本；
- 人工支持时间。

---

# 12. B｜内容质量指标

## 12.1 Requirement Recall

适用于：

- Action Card；
- Prototype Task；
- PRD；
- TechDoc 的需求承接。

```text
Requirement Recall =
正确覆盖的 Gold Requirements
÷
Gold Requirements 总数
```

核心需求单独计算：

```text
Critical Requirement Recall
```

## 12.2 Requirement Alignment Precision

```text
输出中被标为需求承接的内容中
真正与 Gold Requirements 对齐的项
÷
全部声称承接需求的项
```

用于发现 AI 自行扩写、错认用户需求。

## 12.3 Coverage

Coverage 不是一个统一分数，必须写清覆盖什么。

例如：

- Action Card Structural Coverage；
- Checkability Coverage；
- Branch Coverage；
- Prototype Task Acceptance Coverage；
- PRD Mandatory Section Coverage；
- TechDoc NFR Coverage；
- Handoff Artifact Completeness。

## 12.4 Factual Precision

针对事实性断言：

```text
SUPPORTED_FACT
USER_INPUT
MODEL_HYPOTHESIS
UNVERIFIED_CLAIM
UNSUPPORTED_FACTUAL_ASSERTION
```

```text
Factual Precision =
有支持依据的事实性断言
÷
全部事实性断言
```

明确标注的模型假设不算事实错误。

## 12.5 Unsupported Claim Rate

```text
UCR =
无支持却被写成事实的断言
÷
全部事实性断言
```

在无 Search / 无外部证据场景中：

> “无依据但明确标为假设”允许存在；  
> “无依据却写成已经证实的事实”是质量风险，严重时 hard fail。

## 12.6 Completeness

Completeness 看：

> 当前 artifact 对完成它的职责来说是否缺关键组成部分。

不以字数、篇幅、标题数量替代。

## 12.7 Actionability

Actionability 看：

> 下一角色能否不重新从头理解，就根据该 artifact 继续执行。

---

# 13. M1｜First Action Card 质量指标

M1 不需要一次实现整套人工评测平台，但必须从一开始让字段可评。

## 必评维度

### Purpose Alignment

行动是否和用户确认的：

```text
LEARNING
PERSONAL_USE
FOR_OTHERS
UNSPECIFIED
```

一致。

### Requirement Recall

行动是否漏掉影响动作方向的关键要求或约束。

### Action Specificity

是否明确：

- 做什么；
- 用什么；
- 交什么；
- 如何检查。

### Resource Feasibility

用户是否真的具备需要的材料、权限、时间或条件。

### Structural Coverage

First Action 必需 8 项：

```text
goal
why_now
inputs
steps
expected_artifact
checks
branches
stop_condition
```

```text
Structural Coverage =
已完整提供的必需项
÷
8
```

### Checkability Coverage

关键预期结果中，有多少有可执行检查。

### Branch Coverage

关键 PASS/FAIL/UNKNOWN 结果是否有合理下一步。

### Unsupported Claim Rate

不得把：

- 模拟研究；
- 用户未提供事实；
- 模型推断；

写成已验证结论。

---

# 14. M2｜Prototype Task 质量指标

## Scope Recall

已确认本轮范围中，有多少正确进入任务包。

## Scope Precision

任务包中的功能/要求中，有多少真的属于本轮范围。

防止 scope creep。

## Acceptance Coverage

```text
有明确验收步骤的关键功能
÷
关键功能总数
```

## Acceptance Testability

检查是否包含：

- 输入；
- 操作；
- 预期结果；
- 异常结果。

不能只写“确认功能正常”。

## Constraint Preservation

用户/仓库确认的“不能改”事项是否被完整保留。

## Dependency Clarity

未知依赖是否明确标为未知，而不是捏造文件、命令或环境。

---

# 15. M3｜Submission / Review / Decision 质量指标

## Evidence Sufficiency

每个关键 PASS 是否有匹配的：

- 用户材料；
- artifact；
- authorized run；
- 可检查事实。

## Review Accuracy

人工 reviewer 检查：

- PASS 是否真的有依据；
- UNKNOWN 是否被正确保留；
- FAIL 是否没有被隐藏。

## Result → Decision Traceability

```text
有明确结果依据的 Decision
÷
全部 Decision
```

## Unsupported Conclusion Rate

例如一次小观察不能被总结成：

> “市场已经验证”。

## Recovery Specificity

“我卡住了”后，系统是否给一个最小恢复动作，而不是整项目重写。

---

# 16. 条件式 Solutions 评测

当项目确实进入多方案比较时：

- Solution Set Recall；
- Solution Set Critical Recall；
- Selected Solution Recall；
- Requirement Alignment Precision；
- Decision Dimension Coverage；
- Pairwise Differentiation；
- Unsupported Claim Rate；
- 用户 decision helpfulness。

Decision dimensions 至少考虑：

- core interaction；
- automation level；
- user effort；
- MVP scope/complexity；
- primary value path；
- key trade-off。

三套换皮方案不能视为高质量比较。

---

# 17. PRD 质量指标

正式化阶段才启用。

## Requirement Coverage Recall
PRD 正确承载的 Gold Requirements / Gold 总数。

## Critical Requirement Coverage
核心需求覆盖。

## Selected-solution Inheritance
用户选择的产品方向是否被 PRD 正确保留。

## Scope Consistency
PRD 是否扩大或改变已确认 MVP 范围。

## Mandatory Section Coverage
根据当前产品 PRD 合同检查必要部分，不机械套模板。

## Acceptance Criteria Coverage
关键需求有明确验收标准的比例。

## Acceptance Criteria Testability
是否可操作、可观察，而不是抽象描述。

## Unsupported Claim Rate
防止把市场、用户、技术假设写成已证实事实。

## Completeness / Actionability
分别评文档完整性和后续研发可执行性。

---

# 18. TechDoc 质量指标

## PRD Traceability Recall

分母：

> PRD 中需要技术实现/技术设计承接的项目。

不是所有自然语言句子。

## Critical Technical Coverage

关注：

- 组件/服务职责；
- 数据与存储；
- API/接口；
- 状态；
- 权限；
- 错误处理；
- 幂等；
- 外部依赖；
- 部署约束。

## NFR Coverage

按适用性评：

- reliability；
- security；
- privacy；
- observability；
- failure recovery；
- performance；
- cost。

`NOT_APPLICABLE` 需要理由。

## Feasibility Accuracy

技术建议是否符合：

- 当前架构；
- 已有依赖；
- 运行环境；
- 能力边界。

## Implementation Actionability
研发是否能据此继续拆任务。

## Critical Contradiction Rate
TechDoc 是否反向改变 PRD/选定范围。

---

# 19. Formal Handoff 质量指标

- Exact Version Binding Accuracy；
- Artifact Completeness；
- Unresolved-item Coverage；
- Evidence Limitation Visibility；
- Decision Binding Accuracy；
- Package Integrity。

结构身份类指标必须作为硬 Gate。

例如：

```text
wrong PRD version
wrong TechDoc version
wrong project/snapshot
```

不能因为文字相似而容忍。

---

# 20. C｜跨阶段链路质量

这是 InsightForge 相比单点文档生成器最重要的评测。

## 20.1 Purpose → Action Alignment
目的是否正确转化为当前行动。

## 20.2 Action Result → Decision Traceability
下一步是否真正使用实际结果。

## 20.3 Scope → Prototype Task Inheritance
已确认范围是否在 coding task 中保留。

## 20.4 Selected Solution → PRD Inheritance
条件式方案选择是否在 PRD 中保留。

## 20.5 PRD → TechDoc Traceability
产品需求是否技术承接。

## 20.6 PRD + TechDoc → Handoff Binding
正式交付是否绑定正确版本与范围。

## 20.7 Critical Contradiction Rate

```text
Critical Contradiction Rate =
被下游反向修改的关键上游决策
÷
检查的关键上游决策
```

对身份/范围/用户确认方向造成实质改变的 critical contradiction 应 hard fail。

---

# 21. D｜生产工程指标

保留 R1 的工程可靠性，同时量化：

## 性能
- P50 / P95 latency；
- task load/save latency；
- generation latency（仅发生模型调用时）。

## Provider / 成本
- Provider calls / project；
- Provider calls / completed task；
- cost / project；
- cost / completed handoff；
- failed-call cost。

## 稳定性
- timeout rate；
- recovery rate；
- duplicate dispatch rate；
- idempotency conflict rate；
- crash/reopen recovery。

## 隔离
- cross-account leakage = 0；
- cross-project leakage = 0；
- unauthorized artifact access = 0。

## Hard-gate failure
统计：
- wrong version；
- unsupported verified fact；
- critical contradiction；
- permission violation；
- duplicate charge/dispatch；
- false execution claim。

---

# 22. P0 / P1 / P2 质量层

## P0｜确定性硬 Gate

每次适用 artifact 生成/保存后立即检查：

- schema；
- 必填字段；
- placeholder；
- ownership；
- exact version binding；
- prohibited action；
- 明确可检测的 false execution claim；
- 必需结构；
- deterministic contradiction；
- idempotency/permission。

P0 失败不能显示质量通过。

## P1｜结构化质量评测

计算：

- Recall；
- Precision；
- Coverage；
- factuality；
- inheritance；
- contradiction；
- completeness；
- actionability。

可以异步，但结果必须可恢复。

## P2｜人工审计

由用户/独立 reviewer 完成：

- Gold Set；
- 语义映射；
- 事实核验；
- actionability；
- 最终 fidelity。

M4 建立可信 baseline 时必须使用 P2。

---

# 23. 评测数据设计

M0 必须先检查仓库是否已有等价质量对象；若已有，扩展，不重复建第二套。

逻辑上至少需要：

## QualityEvaluation

```text
evaluation_id
project_id
artifact_type
artifact_id/version
upstream_refs
rubric_version
evaluator_role
p0_status
p1_status
p2_status
metrics
hard_fail_reasons
warning_reasons
created_at
```

## RequirementGoldItem

```text
requirement_id
canonical_text
importance
source
confirmed_by
revision
```

## RequirementMapping

```text
requirement_id
artifact_ref
coverage_status
rationale
evaluator_role
```

## ClaimAnnotation

```text
claim_id
artifact_ref
claim_type
evidence_ref
evaluator_role
```

## DecisionTrace

```text
upstream_decision_ref
downstream_artifact_ref
inheritance_status
contradiction_severity
```

物理表/JSON 结构必须按真实仓库现有 convention 决定。

---

# 24. Hard Gate 与 Diagnostic 指标

## Hard Gate

至少包括：

- cross-account/project leakage；
- wrong version binding；
- unsupported assertion presented as verified fact（严重时）；
- critical contradiction；
- false “已运行/已上线/已验证”；
- unauthorized external action；
- duplicate paid dispatch/charge；
- mandatory structure completely missing。

## Diagnostic

主要用于发现问题：

- Requirement Recall；
- Coverage；
- Actionability；
- Decision Dimension Coverage；
- 用户评分；
- 非关键 contradiction。

M1/M4 初期不为所有 diagnostic 指标拍脑袋设置商业硬阈值。

---

# 25. M1 应实现什么评测，哪些不要提前做

M1 当前只需要落实：

## 必须实现
- First Action schema validation；
- Purpose Alignment 的确定性规则；
- Structural Coverage；
- no Provider/Search；
- ownership；
- revision；
- persistence/reopen；
- historical compatibility；
- source/fact identity 不升级；
- basic quality rubric/version hook。

## 可以记录但不要求完整人工平台
- Requirement Recall；
- Action Specificity；
- Resource Feasibility；
- Checkability Coverage；
- Unsupported Claim Rate。

可先用测试 fixture + reviewer 表格验证。

## 明确延后
- Prototype Task 全量评测 → M2；
- Result/Decision Traceability → M3；
- PRD/TechDoc/Handoff 正式人工评测 → 条件式正式化阶段；
- 8–12 人比较 → M4。

这避免把 M1 做成庞大评测平台。

---

# 26. M4 真实用户对照评测

R1 已定义：

- 8—12 名真实目标用户；
- 自带 Idea 或半成品；
- 覆盖三种目的；
- 小样本用于发现阻塞，不证明市场显著性。

R1.1 补充比较矩阵：

```text
A. 静态行动/验收模板
B. 通用 AI + 清晰 Prompt
C. InsightForge 状态化引导
```

尽量控制：

- 模型能力；
- 时间预算；
- 任务难度；
- 材料条件。

## Primary Product Metrics

- 首次有效行动率；
- 独立验收率；
- 有依据决策率；
- 第一条可用流程完成率。

## Secondary Content Metrics

- Critical Requirement Recall；
- Alignment Precision；
- Structural/Checkability Coverage；
- Unsupported Claim Rate；
- Result→Decision Traceability；
- 用户修改量；
- Actionability。

## Operational Metrics

- 完成时间；
- Provider calls；
- 成本；
- timeout/failure；
- 人工支持时间；
- 卡点恢复率。

小样本只报告：

- per-user；
- purpose 分组；
- descriptive aggregate；
- failure pattern。

不宣称统计显著性或市场优势。

正式阈值必须在看结果前确定。

---

# 27. 简历与面试如何使用这些指标

在没有真实结果前可以说：

> 设计并搭建 AI 输出评测体系，从需求召回、事实准确性、内容覆盖、跨产物继承、矛盾率和可执行性等维度评估 Action Card、PRD、TechDoc 与 Handoff，并结合首次有效行动率、独立验收率和调用成本验证产品价值。

不能写：

> “准确率 95%、召回率 93%”

除非真的有：

- 冻结分母；
- Gold Set；
- reviewer；
- 样本数；
- 计算规则；
- 可复核结果。

跑完 M4 后，简历优先选择：

1. 一个产品价值指标；
2. 一个内容质量指标；
3. 一个效率/成本指标；
4. 一个关键失败率。

不要堆十几个数字。

---

# 28. 工程主线与评测主线如何并行

```text
产品主线：
Idea
→ Purpose
→ Action
→ Result
→ Decision
→ Build Slice
→ Prototype Task
→ Formalization（条件式）
→ Handoff
→ Result

评测主线：
Purpose Ground Truth
→ Requirement Gold Set
→ Action Quality
→ Result Evidence
→ Decision Traceability
→ Scope/Task Coverage
→ PRD Inheritance
→ TechDoc Traceability
→ Handoff Binding
→ Product Outcome
→ Production Cost/Reliability
```

两条线不是先后关系，而是同一业务对象上的双视角。

---

# 29. 当前实施顺序

## 当前立即执行
M0 + M1：

```text
真实仓库映射
→ Purpose
→ First Action Card
→ Edit
→ Save
→ Reopen
→ ownership/revision
→ browser path
```

同时预留 M1 最小质量字段/rubric hook。

## M1 完成后
先评审真实实现，再设计 M2。

## 不应现在继续
- 旧式 Real Idea Batch；
- 旧 QuickStart→Solutions→PRD→TechDoc→Handoff 作为默认真实用户验证主线；
- 支付/订阅；
- 自动部署；
- 新通用 AI coding IDE。

---

# 30. 完成标准

InsightForge 的最终“完整链路”不是文档数量，而是：

```text
用户知道自己为什么做
→ 知道现在做什么
→ 能做
→ 能交回结果
→ 能检查
→ 系统不会把未知说成已验证
→ 下一步由真实结果决定
→ 需要开发时任务范围清楚
→ 需要正式化时 PRD/TechDoc/Handoff 正确继承
→ 生产成本、权限和失败可控
```

而评测体系必须能够回答：

```text
有没有漏用户需求？
有没有编造事实？
有没有覆盖关键步骤？
有没有把用户决定传错？
文档是否可执行？
用户真的完成了吗？
成本和失败率是多少？
```

这才是 IF-GUIDE-R1.1 的完整产品主线与评测主线。
