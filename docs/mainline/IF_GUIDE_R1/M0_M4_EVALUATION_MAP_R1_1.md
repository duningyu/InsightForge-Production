# InsightForge｜IF-GUIDE-R1.1 M0—M4 评测实施映射

| 阶段 | 产品能力 | 本阶段必须评测 | 延后 |
|---|---|---|---|
| M0 | 当前仓库映射 | 找已有 Quality/Evaluation 能力；记录可复用对象 | 不实现评测平台 |
| M1 | Purpose + First Action | schema、purpose alignment、structural coverage、ownership、revision、持久化、no Provider/Search；预留 rubric/version | 人工 Gold Set 平台、PRD/TechDoc 评测 |
| M2 | Build Slice + Prototype Task | scope recall/precision、acceptance coverage/testability、constraint preservation | Result→Decision |
| M3 | Submission/Review/Recovery | evidence sufficiency、review accuracy、decision traceability、recovery specificity | M4 对照实验 |
| M4 | 真实用户受控试用 | 产品价值 + 内容质量 + 生产成本三组指标 | 商业化长期留存/付费另做 |

## M1 停止点
完成 Purpose + First Action Card 的真实 browser path 后停止。不要因为有 R1.1 评测规范就提前实现 M2—M4。

## M4 数据表建议
每个用户/任务至少记录：
- purpose
- condition(A/B/C)
- first_action_completed
- independent_acceptance
- evidence_based_decision
- first_usable_flow_completed
- critical_requirement_recall
- alignment_precision
- checkability_coverage
- unsupported_claim_rate
- decision_traceability
- actionability
- elapsed_time
- provider_calls
- cost
- support_minutes
- failure_category
