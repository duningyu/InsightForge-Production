# InsightForge｜工作区开发启动说明 R1.1

**版本：IF-GUIDE-R1.1｜日期：2026-09-16**  
**性质：R1 的启动说明补充；不替代 `CODEX_START.md`，不改变 R1 的 M0 → M1 → M2 → M3 → M4 顺序。**

> 本文件补齐 R1.1 的启动与评测接入规则。  
> R1 决定产品主线与里程碑；R1.1 只补充 AI 输出质量量化、跨阶段继承评测和 M4 真实用户评测。  
> 当前真实仓库的文件、接口、已实现状态始终以工作区实际检查为准。

---

## 1. 推荐阅读顺序

进入 InsightForge 当前工作区后，按以下顺序读取：

1. `MAINLINE_RULES.md`
2. `TECHNICAL_ROUTE.md`
3. `WORKSPACE_RULES_APPEND.md`
4. `FULL_MAINLINE_AND_EVALUATION_R1_1.md`
5. `AI_OUTPUT_QUALITY_EVALUATION_R1_1.md`
6. `M0_M4_EVALUATION_MAP_R1_1.md`
7. `CODE_ARCHITECTURE_R1_1.md`（若当前仓库已有）
8. `SOURCES.md`
9. `WORKSPACE_MAP.md`（若已完成 M0）

同时读取当前工作区实际 `AGENTS.md`、分支、未提交修改和局部开发约束。

**不要使用旧压缩包或历史记忆覆盖当前仓库事实。**

---

## 2. 权威顺序

发生冲突时：

```text
R1 MAINLINE_RULES / TECHNICAL_ROUTE
→ R1.1 evaluation extension
→ current repo / WORKSPACE_MAP
→ current implementation plan
```

解释：

- R1 决定产品应该如何推进；
- R1.1 决定如何量化内容质量与跨阶段一致性；
- 当前 repo 决定已有能力、真实文件、接口、schema、测试和可复用模块；
- 计划只能在前三者一致时执行。

历史 QuickStart → Solutions → PRD → TechDoc → Handoff 仍可作为现有能力复用，但不再是所有项目的默认用户主线。

---

## 3. 产品主线

R1/R1.1 的主线是：

```text
Idea / 真实问题 / 半成品
→ 明确本次目的
→ 一个低成本判断动作
→ 第一条可用流程
→ coding 任务与验收
→ 用户结果回传
→ CONTINUE / NARROW / CHANGE / STOP / FINISH
```

目的：

```text
LEARNING
PERSONAL_USE
FOR_OTHERS
UNSPECIFIED
```

PRD、TechDoc、Formal Handoff 保留，但属于条件式正式化能力，不是每个项目的默认完成标准。

---

## 4. 评测主线

R1.1 在产品主线旁增加：

```text
Purpose Ground Truth
→ Requirement Gold Set
→ Action Quality
→ Result Evidence
→ Decision Traceability
→ Scope / Prototype Task Quality
→ PRD Inheritance
→ TechDoc Traceability
→ Handoff Binding
→ Product Outcome
→ Production Cost / Reliability
```

开放式输出不使用一个模糊的“Accuracy”代替所有质量。

优先使用：

- Requirement Recall / Critical Recall
- Alignment Precision
- Coverage
- Factual Precision
- Unsupported Claim Rate
- Inheritance Accuracy
- Critical Contradiction Rate
- Completeness
- Actionability

结构身份、版本、权限类问题可以使用明确的 100% 硬约束。

---

## 5. Ground Truth 与 LLM-as-Judge 边界

### Idea Provider / 用户
负责确认：

- purpose
- 需求与约束
- 关键选择
- 最终是否符合原意

### Independent Human Reviewer
负责：

- requirement mapping
- factuality
- semantic inheritance
- contradiction
- completeness / actionability

### LLM-as-Judge
只能辅助：

- requirement candidate extraction
- claim extraction
- contradiction candidate detection
- reviewer 待核项整理

不能：

```text
模型自己定义 Gold Set
→ 模型自己评分
→ 模型宣布自己准确
```

---

## 6. M0 启动方式

如果当前工作区尚未完成 M0：

先读取：

- 当前分支与未提交修改
- 实际启动链
- Project / Account / Storage
- frontend entry
- revision / concurrency
- history / reopen
- IdeaBrief / Solutions / Snapshot / Documents / Handoff
- 当前 Quality / Evaluation 能力
- migration
- tests / feature flags

生成：

`docs/mainline/IF_GUIDE_R1/WORKSPACE_MAP.md`

只记录查到的事实，不猜路径、命令或当前部署状态。

### M0 质量复用映射

必须额外记录是否已有：

- ArtifactQualityEvaluation 或等价物
- Requirement Gold Set / annotation
- P0 / P1 / P2
- claim / factuality
- inheritance / contradiction
- evaluation storage / revision

已有则复用；禁止新建第二套平行质量账本。

M0 完成后进入当前获准里程碑，不停在盘点。

---

## 7. M1 启动与停止

M1：

```text
Project
→ Purpose
→ First Action Card
→ Edit
→ Save
→ Reopen
```

首次行动卡必须包含：

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

M1 默认：

```text
Provider = 0
Search = 0
```

先用版本化受控模板。

### M1 最小质量接入

必须有：

- schema / required fields
- Purpose Alignment 的确定性检查
- Structural Coverage
- ownership
- revision / 409
- persistence / reopen
- source identity 不升级
- rubric/version hook
- no Provider/Search

不要因为 R1.1 已定义 PRD/TechDoc/Handoff 指标，就在 M1 建完整评测后台。

M1 完成后停止，不自动进入 M2。

---

## 8. M2 启动与停止

M2：

```text
当前 Action / 已确认上下文
→ First Usable Flow / BUILD_SLICE
→ in-scope / out-of-scope
→ 用户确认范围
→ PROTOTYPE_TASK
→ Acceptance
```

`PROTOTYPE_TASK != FORMAL_HANDOFF`

M2 质量指标：

- Scope Recall
- Scope Precision
- Acceptance Coverage
- Acceptance Testability
- Constraint Preservation
- Dependency Clarity
- Unsupported Claim Rate

M2 默认仍为：

```text
Provider = 0
Search = 0
```

未知技术依赖必须保留 UNKNOWN，不能捏造文件、命令、API 或部署状态。

M2 完成后停止，不自动进入 M3。

---

## 9. M3 启动与停止

M3：

```text
我做完了 / 我卡住了
→ ActionSubmission
→ ActionReview
→ PASS / FAIL / UNKNOWN / NOT_APPLICABLE
→ Recovery（若需要）
→ 用户确认 Decision
→ CONTINUE / NARROW / CHANGE / STOP / FINISH
```

复核层级：

```text
USER_REPORTED
ARTIFACT_CHECKED
AUTHORIZED_RUN
```

`AUTHORIZED_RUN` 只有真实授权运行后才能使用。

### M3 质量指标

- Evidence Sufficiency
- Review Accuracy
- Result → Decision Traceability
- Unsupported Conclusion Rate
- Recovery Specificity

硬语义边界：

```text
CLOSED ≠ FINISH
PASS ≠ FINISH
PASS ≠ 市场验证
STOP ≠ 失败
FINISH ≠ 已上线
```

M3 第一版默认：

```text
Provider = 0
Search = 0
```

系统可推荐 Decision，但不能替用户确认。

M3 完成后停止，不自动进入 M4。

---

## 10. M4 启动边界

M4 是受控真实用户评测，不是继续堆功能。

R1 定义：

- 8—12 名真实目标用户
- 覆盖 LEARNING / PERSONAL_USE / FOR_OTHERS
- 自带 Idea 或半成品
- 小样本用于发现阻塞，不证明市场显著性

比较：

```text
A. 静态模板
B. 通用 AI + 清晰 Prompt
C. InsightForge 状态化引导
```

产品主指标：

- 首次有效行动率
- 独立验收率
- 有依据决策率
- 首条可用流程完成率

内容副指标：

- Critical Requirement Recall
- Alignment Precision
- Checkability Coverage
- Unsupported Claim Rate
- Result → Decision Traceability
- Actionability

运营指标：

- 完成时间
- Provider calls
- cost
- timeout/failure
- 人工支持时间
- 卡点恢复率

正式阈值在看结果前确定。

---

## 11. P0 / P1 / P2

### P0｜确定性硬 Gate
适用时检查：

- schema
- 必填
- ownership
- revision
- exact version/project binding
- placeholder
- false execution / verified claims
- deterministic contradiction
- permission / idempotency

### P1｜结构化质量评测
计算/恢复：

- Recall
- Precision
- Coverage
- Factuality
- Inheritance
- Contradiction
- Completeness
- Actionability

### P2｜人工审计
用于：

- Gold Set
- 事实语义 adjudication
- semantic inheritance
- final fidelity

P0/P1 PASS 不能显示成 P2 human reviewed。

---

## 12. 来源身份

统一使用：

```text
USER_INPUT
MODEL_HYPOTHESIS
REAL_OBSERVATION
SIMULATION
IMPLEMENTATION_EVIDENCE
```

不可静默升级。

例如：

```text
用户说“跑通了”
≠ AUTHORIZED_RUN
模拟访谈
≠ REAL_OBSERVATION
本地测试通过
≠ production deployed
```

---

## 13. 工作区执行规则

每轮：

1. 读取真实 repo
2. 复用已有能力
3. 做当前最小里程碑
4. 先写失败测试
5. 最小实现
6. 相关回归
7. browser / actual lifecycle 验证
8. 事实回执
9. 停在当前里程碑边界

不要：

- 自动扩成后续 M
- 无关全项目治理盘点
- 重复全量 SHA / authority / membership 审计
- 用 mock 结果冒充真实 Provider / 浏览器 / 云验证

---

## 14. Provider / Search / 外部动作

新增真实调用必须有明确：

- operation
- environment
-次数
- budget
- permission
- failure / retry
- evaluation contract

规则模板不是 Provider request。

默认里程碑如果没有批准真实外联：

```text
real_provider_requests = 0
real_search_requests = 0
```

未经授权不得：

- 购买服务
- 对第三方发送消息
- GitHub 写入
- 终端执行用户上传代码
- 云数据库写入
- Railway 部署
- 公开发布

---

## 15. 当前工作区已完成里程碑时的恢复规则

如果当前仓库已经完成 M0/M1/M2：

不要重跑旧里程碑来“证明权威文档生效”。

应：

1. 核验当前 commit / WORKSPACE_MAP / tests
2. 确认已有实现与 R1/R1.1 没有 load-bearing 冲突
3. 从 `next_legal_action` 对应里程碑继续

同一 SHA、同一状态下已有新鲜验证证据可复用；只有代码/配置/环境变化或证据不足时才扩大回归。

---

## 16. 每轮最终回执

只报告事实：

```text
work_item
baseline_head
candidate_head
changed_files
rules_covered
tests actually run
tests not run
browser actions actually completed
Provider/Search/network
migration/cache impact
production/cloud access
known limits
remaining blocker
next legal action
```

没有运行的内容写 `NOT_RUN` / `NOT_VERIFIED`。

不能从：

- test count
- HTTP 202
- ZIP 导出成功
- 用户口头“不错”

推导出更大的产品结论。

---

## 17. 当前 R1.1 总停止原则

每个里程碑完成后停止。

```text
M1 完成 → 评审后再 M2
M2 完成 → 评审后再 M3
M3 完成 → 评审后再 M4
M4 完成 → 根据真实结果决定是否进入发布/商业化阶段
```

**不要为了流程完整而自动前进。真实结果可以支持 CONTINUE、NARROW、CHANGE、STOP 或 FINISH。**
