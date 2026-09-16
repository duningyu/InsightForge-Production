# InsightForge｜IF-GUIDE-R1.1 代码架构设计
**版本：R1.1 Code Architecture Design｜日期：2026-09-15**

> **定位**  
> 本文是 `IF_GUIDE_R1` + `R1.1 评测扩展` 的代码层设计。  
> 它不是对当前真实仓库文件路径的断言；Codex 必须先执行 M0，映射实际模块，再把本文的逻辑边界落到现有代码中。  
> 如果当前仓库已有等价能力，优先复用/扩展，禁止为了文档名机械创建第二套同义服务、表或状态机。

---

# 1. 设计目标

M1 的唯一产品目标：

```text
零资料 Project
→ 用户确认 Purpose
→ 系统生成 First Action Card
→ 用户编辑
→ 保存
→ 刷新/重新进入后恢复
```

同时满足：

- 不新增真实 Provider 请求；
- 不新增 Search；
- 不要求 Snapshot / PRD / TechDoc；
- 不破坏现有 Solutions / Snapshot / Documents / Formal Handoff；
- 新对象进入现有账号、项目、数据库与权限体系；
- 使用 revision / expected_revision 防止静默覆盖；
- 预留质量评测 hook，但不在 M1 建完整 M4 评测后台。

---

# 2. 代码设计原则

## 2.1 Reuse-first

逻辑对象：

```text
ProjectIntent
ActionTask
ActionQuality
```

不代表必须新建：

```text
project_intents 表
action_tasks 表
action_quality 表
```

M0 必须先查：

- Project 是否已有 metadata / settings / revision；
- 是否已有 task/run/action 类对象；
- 是否已有 ArtifactQualityEvaluation 或同类能力；
- 是否已有 optimistic concurrency；
- 是否已有 project child-resource repository。

只有真实仓库无法安全表达时才 additive 增量。

---

## 2.2 一个 Project 根，不做平行产品

逻辑关系：

```text
Project
├── Existing IdeaBrief
├── Existing Solutions
├── Existing Snapshot
├── Existing Documents / Handoff
├── ProjectIntent          # M1
└── ActionTask             # M1 first action
```

M2/M3 才增加：

```text
ActionSubmission
ActionReview
PrototypeTask export
Recovery
Decision
```

M1 不提前实现这些未来对象。

---

## 2.3 Template-first, AI-on-demand

M1：

```text
Purpose
+ minimal project context
+ versioned deterministic template
→ First Action Card
```

禁止：

```text
Purpose
→ Provider
→ free-form action
```

受控模板不登记为 Provider request，不消耗模型预算。

---

# 3. 建议逻辑模块

> 文件名仅是建议职责名；M0 必须映射到真实仓库现有文件。

## 3.1 `ProjectIntentService`

职责：

- 读取当前 ProjectIntent；
- 用户确认/更新 purpose；
- 校验 project ownership；
- 管理 revision；
- purpose 改变时触发 ActionTask 重评；
- 历史项目缺失 intent 时返回 `UNSPECIFIED` 逻辑视图，不强制回填。

建议接口：

```python
class ProjectIntentService:
    def get_current(
        self,
        *,
        actor_id: str,
        project_id: str,
    ) -> ProjectIntentView:
        ...

    def set_intent(
        self,
        *,
        actor_id: str,
        project_id: str,
        purpose: Purpose,
        goal: str | None,
        constraints: list[str],
        expected_revision: int | None,
        confirmed_by: str,
    ) -> ProjectIntentView:
        ...
```

要求：

- 不接受客户端传入 `database_path/workspace/actor` 来决定权限；
- 可信 actor 从现有认证上下文获得；
- stale revision → `409 Conflict`；
- purpose 改变不能静默覆盖旧记录。

---

## 3.2 `GuidedActionService`

职责：

- 基于当前 purpose 生成/确保 First Action；
- 保存 ActionTask revision；
- 编辑；
- confirm/ready；
- 读取当前 action；
- 根据 purpose revision 判断 action 是否 stale / needs reevaluation。

建议接口：

```python
class GuidedActionService:
    def ensure_first_action(
        self,
        *,
        actor_id: str,
        project_id: str,
        intent_revision: int,
        idempotency_key: str | None = None,
    ) -> ActionTaskView:
        ...

    def get_action(
        self,
        *,
        actor_id: str,
        project_id: str,
        task_id: str,
    ) -> ActionTaskView:
        ...

    def update_action(
        self,
        *,
        actor_id: str,
        project_id: str,
        task_id: str,
        patch: ActionTaskPatch,
        expected_revision: int,
    ) -> ActionTaskView:
        ...

    def confirm_action(
        self,
        *,
        actor_id: str,
        project_id: str,
        task_id: str,
        expected_revision: int,
    ) -> ActionTaskView:
        ...
```

M1 的 `ensure_first_action()` 不允许调用 Provider。

---

## 3.3 `FirstActionTemplateRegistry`

职责：

- 按 Purpose 选择模板；
- 保存 `template_version`；
- 输出结构化 Action Draft；
- 不读写 DB；
- 无外联；
- 同样输入 + 同样模板版本 → 可预测输出结构。

建议：

```python
class FirstActionTemplateRegistry:
    def render(
        self,
        *,
        purpose: Purpose,
        context: FirstActionContext,
    ) -> ActionDraft:
        ...
```

Purpose：

```python
class Purpose(str, Enum):
    LEARNING = "LEARNING"
    PERSONAL_USE = "PERSONAL_USE"
    FOR_OTHERS = "FOR_OTHERS"
    UNSPECIFIED = "UNSPECIFIED"
```

不要为了 Python 3.10 兼容去改生产主线；实际 enum 形式遵循当前 Python 版本和仓库规范。

---

## 3.4 `ActionValidator`

P0 确定性检查。

职责：

- required fields；
- placeholder / empty；
- Purpose Alignment 可确定规则；
- prohibited actions；
- false execution claim；
- source identity；
- schema；
- allowed state transition。

建议：

```python
class ActionValidator:
    def validate_draft(
        self,
        *,
        intent: ProjectIntentView,
        action: ActionDraft | ActionTaskView,
    ) -> ValidationResult:
        ...
```

`ValidationResult`：

```python
@dataclass
class ValidationResult:
    passed: bool
    hard_fail_reasons: list[str]
    warnings: list[str]
    structural_coverage: float
```

---

## 3.5 `ActionQualityAdapter`

M1 不新建第二套完整评测平台。

M0 判断：

### 如果已有统一质量系统

例如存在：

```text
ArtifactQualityEvaluation
QualityEvaluationService
rubric registry
```

则：

```python
class ActionQualityAdapter:
    ARTIFACT_TYPE = "ACTION_CARD"
    RUBRIC_VERSION = "IF_ACTION_CARD_R1_1_V1"

    def build_summary(
        self,
        action: ActionTaskView,
        p0: ValidationResult,
    ) -> QualitySummary:
        ...
```

### 如果没有

只保存：

```text
artifact_type
rubric_version
structural_coverage
p0_status
```

不要为了 M1 建：

- RequirementGold tables；
- ClaimAnnotation tables；
- DecisionTrace tables；

这些留到需要时再正式接入。

---

# 4. 逻辑数据结构

## 4.1 `ProjectIntent`

```python
@dataclass
class ProjectIntent:
    project_id: str
    purpose: Purpose
    goal: str | None
    constraints: list[str]
    confirmed_by: str | None
    revision: int
    created_at: datetime
    updated_at: datetime
```

语义：

- 无真实记录时，读取层可返回 `UNSPECIFIED revision=0`；
- 不把旧项目批量写成 `FOR_OTHERS`；
- 用户第一次确认才形成正式 intent revision；
- purpose change → revision +1。

---

## 4.2 `ActionTask`

```python
@dataclass
class ActionTask:
    task_id: str
    project_id: str

    kind: ActionKind
    state: ActionState

    goal: str
    why_now: str
    inputs: list[ActionInput]
    steps: list[ActionStep]
    expected_artifact: str
    checks: list[ActionCheck]
    branches: list[ActionBranch]
    stop_condition: str
    prohibited_actions: list[str]

    intent_revision: int
    snapshot_version: str | None

    template_version: str
    revision: int

    created_at: datetime
    updated_at: datetime
```

M1 Action kind 建议：

```python
OBSERVE
MANUAL_TEST
LEARNING_EXERCISE
```

不要因为全局 TaskKind 有 6 类就在 M1 一次性产生 BUILD_SLICE / ACCEPTANCE / RECOVERY。

---

## 4.3 `ActionState`

R1 全生命周期：

```text
DRAFT
READY
IN_PROGRESS
SUBMITTED
CLOSED
NEEDS_REVISION
PAUSED
```

M1 只真正使用：

```text
DRAFT
READY
NEEDS_REVISION
```

不要伪造：

```text
SUBMITTED
CLOSED
```

因为 Submission / Review 尚未实现。

---

# 5. First Action 模板设计

## 5.1 公共模板合同

所有模板必须返回：

```json
{
  "goal": "...",
  "why_now": "...",
  "inputs": [],
  "steps": [],
  "expected_artifact": "...",
  "checks": [],
  "branches": [],
  "stop_condition": "...",
  "prohibited_actions": []
}
```

字段缺失直接 P0 fail。

---

## 5.2 LEARNING

目标：完成一个可解释的能力练习。

示例逻辑：

```python
if purpose == LEARNING:
    kind = LEARNING_EXERCISE
    goal = "完成一个与目标能力直接相关的小练习，并能解释结果"
    inputs = ["用户当前想学习的能力", "一个可使用的练习材料"]
    checks = [
        "是否真的完成一个产物",
        "用户能否用自己的话解释结果",
        "是否知道哪里通过、哪里失败",
    ]
```

禁止自动加入：

- 市场规模；
- 用户访谈；
- 商业转化；
- 付费意愿。

---

## 5.3 PERSONAL_USE

目标：比较真实任务前后差异。

```python
if purpose == PERSONAL_USE:
    kind = MANUAL_TEST
    inputs = [
        "一份用户自己的真实任务输入",
        "当前处理方法或当前结果",
    ]
```

核心：

- current method；
- small intervention；
- before/after；
- limitation。

禁止要求证明需求普遍存在。

---

## 5.4 FOR_OTHERS

目标：观察真实行为或进行手工测试。

```python
if purpose == FOR_OTHERS:
    kind = OBSERVE
```

建议：

- 一次具体行为观察；
- 一次手工测试；
- 一次原型反馈。

禁止：

```text
1 次观察
→ “需求已验证”
```

输出中应明确：

```text
这是探索线索，不代表市场已经验证。
```

---

## 5.5 UNSPECIFIED

目标：低风险可逆探索。

禁止自动：

- 商业化；
- 市场判断；
- 第三方消息；
- 支付；
- 公开发布；
- 敏感数据处理。

---

# 6. Revision 与并发

所有 mutation：

```text
expected_revision
```

服务层必须：

```python
if current_revision != expected_revision:
    raise Conflict409(...)
```

不要：

```text
last-write-wins
```

Frontend 收到 409：

- 保留本地草稿；
- 显示“当前项目已在其他位置更新”；
- 提供重新载入/比较；
- 不自动覆盖。

Purpose change：

```text
intent rev 3 → rev 4
```

若 current action 绑定 intent rev 3：

```text
action.state = NEEDS_REVISION
```

或按仓库既有 revision 机制创建新 revision。

不能静默让旧行动继续显示为 READY。

---

# 7. 幂等设计

`ensure_first_action()` 应具备可重入语义。

推荐业务约束：

```text
(project_id, intent_revision, first_action_slot/template_version)
```

同一 intent revision 下：

- 页面刷新；
- 多次点击；
- 重试；

不得生成多张不同首次行动卡。

如果用户明确选择“重新生成/重置行动”，那是新的用户意图，应使用新 action/revision，而不是利用网络重试隐式创建。

---

# 8. API 设计

实际 URL 以 M0 为准。

建议语义：

## 8.1 Intent

```http
GET /api/projects/{project_id}/intent
```

Response：

```json
{
  "purpose": "UNSPECIFIED",
  "goal": null,
  "constraints": [],
  "revision": 0,
  "confirmed": false
}
```

```http
PUT /api/projects/{project_id}/intent
```

Request：

```json
{
  "purpose": "PERSONAL_USE",
  "goal": "减少我整理课程通知的遗漏",
  "constraints": ["不自动发送消息"],
  "expected_revision": 0
}
```

---

## 8.2 First Action

```http
POST /api/projects/{project_id}/actions/first
```

语义：

> ensure current first action

不是：

> 每调用一次就新生成一次。

Response：

```json
{
  "task_id": "...",
  "kind": "MANUAL_TEST",
  "state": "DRAFT",
  "revision": 1,
  "intent_revision": 1,
  "template_version": "first_action_personal_use_v1",
  "goal": "...",
  "why_now": "...",
  "inputs": [],
  "steps": [],
  "expected_artifact": "...",
  "checks": [],
  "branches": [],
  "stop_condition": "...",
  "quality": {
    "p0_status": "PASS",
    "structural_coverage": 1.0,
    "rubric_version": "IF_ACTION_CARD_R1_1_V1"
  }
}
```

---

## 8.3 Action update

```http
PATCH /api/projects/{project_id}/actions/{task_id}
```

Request：

```json
{
  "expected_revision": 1,
  "goal": "...",
  "steps": [...]
}
```

Response revision +1。

---

## 8.4 Confirm

```http
POST /api/projects/{project_id}/actions/{task_id}/confirm
```

M1 只把：

```text
DRAFT → READY
```

不生成 Submission / Decision。

---

# 9. Repository / transaction design

如果当前 repo 使用 SQLite + per-account child DB：

所有新写入必须进入：

```text
current authenticated user's legal DB/storage
```

不能接受客户端：

```text
database_path
workspace
actor_id
```

来决定数据位置。

建议事务边界：

### set intent

```text
verify owner
→ read current revision
→ compare expected_revision
→ append/update intent revision
→ mark incompatible current action NEEDS_REVISION
→ commit
```

### ensure first action

```text
verify owner
→ read current intent
→ find existing current first action
→ if exists and compatible: return
→ render deterministic template
→ P0 validate
→ persist action revision
→ persist minimum quality metadata
→ commit
```

没有 Provider transaction。

---

# 10. Migration 设计

M0 后分三类：

## A. 现有表可扩展
优先 additive columns / metadata。

## B. 现有通用 child-resource table 可表达
复用。

## C. 无等价结构
才新增最小表。

概念 SQL 仅作参考：

```sql
CREATE TABLE project_intents (
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    purpose TEXT NOT NULL,
    goal TEXT,
    constraints_json TEXT NOT NULL,
    confirmed_by TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, revision)
);
```

```sql
CREATE TABLE action_tasks (
    task_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    intent_revision INTEGER NOT NULL,
    snapshot_version TEXT,
    template_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(task_id, revision)
);
```

注意：

- 物理实现必须服从现有 migration convention；
- 不要直接复制以上 SQL；
- 历史项目不批量回填假 purpose；
- migration 不触碰已有 documents / budgets / provider receipts。

---

# 11. Quality 代码设计

## 11.1 M1 P0

```python
def validate_action_card(action: ActionTaskView) -> ValidationResult:
    required = [
        action.goal,
        action.why_now,
        action.expected_artifact,
        action.stop_condition,
    ]

    hard_fail = []

    if any(not normalized_text(x) for x in required):
        hard_fail.append("MISSING_REQUIRED_FIELD")

    if not action.steps:
        hard_fail.append("MISSING_STEPS")

    if not action.checks:
        hard_fail.append("MISSING_CHECKS")

    if not action.branches:
        hard_fail.append("MISSING_BRANCHES")

    coverage = compute_structural_coverage(action)

    return ValidationResult(
        passed=not hard_fail,
        hard_fail_reasons=hard_fail,
        warnings=[],
        structural_coverage=coverage,
    )
```

---

## 11.2 Structural Coverage

8 个核心结构：

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

```python
def structural_coverage(action) -> float:
    flags = [
        present(action.goal),
        present(action.why_now),
        bool(action.inputs),
        bool(action.steps),
        present(action.expected_artifact),
        bool(action.checks),
        bool(action.branches),
        present(action.stop_condition),
    ]
    return sum(flags) / 8
```

这不是完整质量分数，只是结构覆盖率。

---

## 11.3 Purpose Alignment — deterministic baseline

M1 不用 LLM judge。

示例规则：

```text
LEARNING
→ 不能要求市场访谈/付费验证

PERSONAL_USE
→ 至少要求用户自己的真实输入或当前做法

FOR_OTHERS
→ 可以要求观察/手工测试
→ 不允许输出“市场已验证”

UNSPECIFIED
→ 不允许自动商业化/公开发布/付费行为
```

复杂语义评审留给 P2/M4。

---

## 11.4 Source identity

Action 字段中涉及来源时，必须显式标识：

```text
USER_INPUT
MODEL_HYPOTHESIS
REAL_OBSERVATION
SIMULATION
IMPLEMENTATION_EVIDENCE
```

M1 模板不应制造：

```text
REAL_OBSERVATION
IMPLEMENTATION_EVIDENCE
```

除非用户/系统真实提供。

---

# 12. Frontend 代码设计

R1 历史线索是原生 HTML/CSS/JS；实际以 M0 为准。

不要重写整个页面。

建议局部组件：

```text
ProjectPurposePanel
CurrentActionCard
ActionEditPanel
RevisionConflictBanner
```

如果是原生 JS，可按职责函数组织：

```javascript
loadProjectIntent(projectId)
saveProjectIntent(projectId, payload)

ensureFirstAction(projectId)
loadAction(projectId, taskId)
saveAction(projectId, taskId, payload)
confirmAction(projectId, taskId)

renderPurposePanel(state)
renderCurrentAction(state)
renderRevisionConflict(conflict)
```

账号切换：

```text
clear current in-memory project/action view
→ reload using new authenticated context
```

不能通过前端缓存让 A 账号看到 B 账号 action。

---

# 13. 浏览器用户路径

必须走真实业务链：

```text
登录
→ 打开/创建零资料项目
→ 选择 Purpose
→ 保存 Intent
→ ensure First Action
→ 页面渲染 Action Card
→ 编辑
→ PATCH 保存
→ 刷新
→ GET 恢复
→ 退出/重新进入项目
→ 恢复
```

再验证：

```text
账号切换
→ 原 Action 不可读取
```

历史项目：

```text
no intent row
→ 仍能打开
→ purpose 显示未确认/UNSPECIFIED
→ 原 Solutions/Documents/History 不失效
```

---

# 14. Feature Flag

只有当前 repo 已有 feature flag pattern 时才复用。

逻辑 flag：

```text
guided_actions_r1
```

要求：

```text
OFF → 原页面行为
ON  → Purpose + Current Action 增量出现
```

不要为了 M1 专门引入复杂 feature-flag 平台。

---

# 15. 错误处理

## 15.1 409 revision conflict

```json
{
  "error": "REVISION_CONFLICT",
  "current_revision": 4
}
```

Frontend：

- 保留用户本地编辑；
- 不自动覆盖；
- 提示重新加载。

## 15.2 invalid purpose

400 / current repo equivalent。

## 15.3 ownership failure

404 或 403 按现有安全约定，不改变整个项目现有行为。

## 15.4 template validation fail

不得保存半残 Action 作为 READY。

可：

```text
DRAFT + P0_FAILED
```

或 transaction fail，服从当前 repo pattern。

---

# 16. 测试设计

## 16.1 Unit

### Template Registry
- LEARNING 不出现市场验证要求；
- PERSONAL_USE 含自己的真实输入/对照；
- FOR_OTHERS 是行为观察/手工测试；
- UNSPECIFIED 不默认商业化。

### Validator
- 8 项完整 → structural coverage 1.0；
- 缺 checks → P0 fail；
- 缺 branches → P0 fail；
- fake verified claim → reject/warning by rule。

---

## 16.2 Service

- set intent；
- stale revision = 409；
- purpose change increments revision；
- action becomes stale/needs revision；
- ensure first action idempotent；
- no Provider/Search；
- cross-account denied；
- historical project fallback UNSPECIFIED。

---

## 16.3 API

- trusted identity only；
- cannot supply DB/workspace override；
- expected_revision required for mutation；
- response contains allowed state；
- no Provider run created.

---

## 16.4 Frontend

- 3 purpose buttons；
- action card render；
- edit/save；
- refresh/reopen；
- 409 local draft preserved；
- account switch isolation；
- historical project works。

---

## 16.5 Regression

重点只回归：

- Project；
- Account/Auth；
- History；
- existing homepage；
- Solutions/Documents/Handoff navigation。

M1 不跑无关：

- Real Idea Batch budget matrix；
- PRD/TechDoc/Handoff full quality suite；
- M2/M3/M4；
- governance/provenance audits。

---

# 17. Observability

M1 最小事件：

```text
intent_confirmed
first_action_created
first_action_edited
first_action_ready
revision_conflict
```

不要记录完整私人内容。

建议安全字段：

```text
project_id hash/opaque id
purpose
template_version
action_kind
revision
status
latency
```

Provider metrics：

```text
new_provider_request_count = 0
new_search_request_count = 0
```

---

# 18. M1 质量回执

M1 完成时需要能够回答：

```text
Purpose 是否持久化？
First Action 是否结构完整？
Purpose 与行动是否匹配？
是否没有新增 Provider/Search？
编辑是否保存？
刷新是否恢复？
历史项目是否兼容？
账号是否隔离？
revision 冲突是否安全？
```

不需要回答：

```text
PRD Recall 是多少？
TechDoc NFR Coverage 是多少？
Handoff Binding Accuracy 是多少？
```

这些不是 M1 任务。

---

# 19. M2 / M3 / M4 代码扩展点

## M2
新增/扩展：

```text
BuildSlice
PrototypeTaskExporter
AcceptanceRubric
```

评测：

```text
Scope Recall
Scope Precision
Acceptance Coverage
Acceptance Testability
Constraint Preservation
```

## M3
新增/扩展：

```text
ActionSubmissionService
ActionReviewService
RecoveryRouter
DecisionService
```

评测：

```text
Evidence Sufficiency
Review Accuracy
Result→Decision Traceability
Recovery Specificity
```

## M4
新增/扩展：

```text
ExperimentCondition
HumanAnnotation
RequirementGoldSet
MetricAggregation
```

比较：

```text
Static Template
General AI
IF Stateful Guidance
```

不要在 M1 提前实现。

---

# 20. 与现有 ArtifactQualityEvaluation 的接轨原则

如果 M0 确认仓库已存在完整：

```text
ArtifactQualityEvaluation
Requirement Gold Set
Claim Annotation
Decision Annotation
P0/P1/P2
```

则不废弃。

建议映射：

```text
artifact_type = ACTION_CARD
rubric_version = IF_ACTION_CARD_R1_1_V1
```

M1 只填：

```text
P0 status
structural coverage
purpose alignment deterministic result
template version
artifact/revision refs
```

P2：

```text
NOT_REVIEWED
```

不能因为 P0 PASS 就伪装成人工评测已通过。

---

# 21. 禁止的实现方式

以下实现直接视为偏离 R1：

```text
用户一选 purpose 就调用 LLM
每次刷新都重新生成 Action
用 start_sample/旧 Real Idea Batch 代替 ActionTask
把 First Action 写进 PRD 才允许继续
历史项目批量猜 FOR_OTHERS
用户确认 = 市场验证
模拟观察 = REAL_OBSERVATION
P0 PASS = 人工质量通过
为 M1 重构整个前端
为 M1 新建第二套 auth/storage
为 M1 恢复旧 Real Idea Batch
```

---

# 22. Codex M0 映射清单

Codex 在真实仓库必须回答：

```text
1. Project model/service 在哪？
2. 当前账号/ownership guard 在哪？
3. 当前 per-account DB/storage 怎么拿？
4. migration 机制是什么？
5. 是否已有 revision/base-version？
6. 是否已有 project metadata 可承载 intent？
7. 是否已有 task/action 类资源？
8. 是否已有 ArtifactQualityEvaluation？
9. 首页入口文件是哪一个？
10. history/reopen 怎么实现？
11. 当前 tests 命令是什么？
12. feature flag pattern 是否存在？
13. 当前未提交修改/冻结是什么？
14. Real Idea Batch / extension 当前生产状态如何保护？
```

完成映射后，才把本文逻辑职责映射到具体文件。

---

# 23. 建议 Codex 输出的代码映射

最终回执必须给：

```text
project_intent:
  logical_service: ...
  actual_file: ...
  actual_storage: ...

guided_action:
  logical_service: ...
  actual_file: ...
  actual_storage: ...

template_registry:
  actual_file: ...

validator:
  actual_file: ...

quality_hook:
  reused_existing: true/false
  actual_file: ...

api:
  routes: [...]

frontend:
  files: [...]

migration:
  required: true/false
  files: [...]

tests:
  files: [...]
```

这样后续 M2 才能基于真实代码继续，不再重新猜架构。

---

# 24. 本轮停止点

当真实仓库达到：

```text
Purpose
→ First Action
→ Edit
→ Save
→ Refresh/Reopen
```

并且：

```text
ownership PASS
revision PASS
history compatibility PASS
Provider/Search = 0
browser path PASS
```

M1 完成。

**立即停止。**

不要顺手继续：

- M2；
- M3；
- M4；
- Real Idea Batch；
- production deployment。

---

# 25. 最终代码结构目标

R1.1 希望得到的不是一堆新模块，而是：

```text
Existing InsightForge
│
├── Project / Account / Storage           [reuse]
├── IdeaBrief / Solutions / Snapshot      [reuse, conditional]
├── Documents / Formal Handoff            [reuse, later]
├── ProjectIntent                         [M1 minimal]
├── GuidedAction                          [M1 minimal]
│   ├── deterministic template
│   ├── revision
│   ├── P0 validation
│   └── quality hook
├── Prototype Task                        [M2]
├── Submission / Review / Decision        [M3]
└── Evaluation / Experiment               [M4]
```

核心原则：

> **先把“用户下一步做什么”做对，再逐步增加模型自由度；先让输出可检查，再追求更多生成；先复用真实仓库，再新增结构。**
