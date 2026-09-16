# InsightForge｜AI 输出质量评测规范 R1.1
**适用基准：IF-GUIDE-R1｜日期：2026-09-15**

## 1. 目的
本规范补充 R1 的内容质量量化，不改变 R1 的产品主线和 M0—M4 顺序。

## 2. 不使用模糊 Accuracy
开放式生成优先使用：
- Requirement Recall / Critical Recall
- Alignment Precision
- Coverage
- Factual Precision
- Unsupported Claim Rate
- Inheritance Accuracy
- Critical Contradiction Rate
- Completeness
- Actionability

身份、版本、权限等确定性问题可以使用 Accuracy=100% 的硬约束。

## 3. Ground Truth
- Idea Provider：purpose、需求、约束、选择、最终 fidelity
- Independent Human Reviewer：需求映射、事实性、继承、矛盾、可执行性
- LLM-as-Judge：只做候选提取与辅助，不作唯一真值

## 4. Gold Set
Gold requirement：
- id
- canonical_text
- CRITICAL / SECONDARY
- source
- confirmed_by
- revision

覆盖：
`COVERED / PARTIAL / NOT_COVERED / CONTRADICTED / NOT_APPLICABLE`

同时报告 strict recall 与 weighted recall。

## 5. Artifact rubrics

### First Action Card
- Purpose Alignment
- Critical Requirement Recall
- Structural Coverage
- Action Specificity
- Resource Feasibility
- Checkability Coverage
- Branch Coverage
- Stop-condition Coverage
- Unsupported Claim Rate

### Prototype Task
- Scope Recall
- Scope Precision
- Acceptance Coverage
- Acceptance Testability
- Constraint Preservation
- Dependency Clarity
- Unsupported Claim Rate

### Action Review / Decision
- Evidence Sufficiency
- Review Accuracy
- Result→Decision Traceability
- Unsupported Conclusion Rate
- Recovery Specificity

### Solutions（条件式）
- Solution Set Recall
- Selected Solution Recall
- Alignment Precision
- Decision Dimension Coverage
- Differentiation
- Unsupported Claim Rate

### PRD
- Requirement Coverage Recall
- Critical Requirement Coverage
- Selected-solution Inheritance
- Scope Consistency
- Mandatory Section Coverage
- Acceptance Criteria Coverage/Testability
- Unsupported Claim Rate
- Completeness
- Actionability
- Critical Contradiction Rate

### TechDoc
- PRD Traceability Recall
- Critical Technical Coverage
- NFR Coverage
- Feasibility Accuracy
- Implementation Actionability
- Completeness
- Unsupported Technical Claim Rate
- Critical Contradiction Rate

### Handoff
- Exact Version Binding Accuracy
- Artifact Completeness
- Unresolved-item Coverage
- Evidence Limitation Visibility
- Decision Binding Accuracy
- Package Integrity

## 6. Cross-stage
- Purpose→Action Alignment
- Result→Decision Traceability
- Scope→Prototype Task Inheritance
- Solution→PRD Inheritance
- PRD→TechDoc Traceability
- PRD+TechDoc→Handoff Binding
- Critical Contradiction Rate

## 7. P0/P1/P2
P0：schema、权限、版本、必填、假执行声明、硬矛盾等确定性 Gate。  
P1：Recall、Precision、Coverage、Factuality、Inheritance、Completeness、Actionability。  
P2：人工 Ground Truth 与 adjudication。

## 8. M1 最小接入
M1 只强制：
- schema / required fields
- purpose alignment deterministic checks
- structural coverage
- ownership/revision
- persistence/reopen
- no Provider/Search
- rubric/version hook

其他人工指标可用 fixture/reviewer 表格先建立基线，不为 M1 建完整评测后台。

## 9. M4
8—12 人，覆盖三种目的。比较：
A 静态模板；
B 通用 AI + 清晰 Prompt；
C IF 状态化引导。

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
- Decision Traceability
- Actionability

只作探索性描述，不宣称统计显著性。
