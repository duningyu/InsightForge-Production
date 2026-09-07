from __future__ import annotations

import json
from typing import Any

from app.db import Database, utc_now
from app.schemas import SolutionSetDraft
from app.services.ai_runtime import sha256_payload
from app.services.artifact_health import ArtifactHealthService
from app.services.canvas_projection import CanvasProjectionService
from app.services.decisions import DecisionService
from app.services.document_versions import DocumentVersionService
from app.services.legacy_migration import LegacyMigrationService
from app.services.loop import DocumentLoop
from app.services.project_claims import ProjectClaimService
from app.services.projects import ProjectService
from app.services.retrieval_service import ProjectRetrievalService
from app.services.snapshots import SnapshotService
from app.services.solution_design import SolutionDesignService


def _candidate(
    *,
    title: str,
    mechanism: str,
    summary: str,
    why_fit: str,
    required_data_class: str,
    automation_level: str,
    human_role: str,
    core_decision_logic: str,
    major_dependency: str,
    requires_llm_runtime: bool = False,
) -> dict[str, Any]:
    return {
        "title": title,
        "mechanism": mechanism,
        "summary": summary,
        "why_fit": why_fit,
        "user_flow": ["录入或导入必要信息", "查看系统建议", "人工确认并记录原因"],
        "mvp_pages": ["工作台", "建议详情", "确认记录"],
        "features": ["结构化输入", "可解释建议", "人工确认", "历史记录"],
        "inputs": [required_data_class, "人工备注"],
        "outputs": ["建议清单", "建议原因", "待人工确认项"],
        "decision_logic": [core_decision_logic],
        "data_requirements": [required_data_class],
        "technical_components": ["FastAPI", "SQLite", "规则或评分服务", "Web UI"],
        "implementation_plan": ["第一周实现输入与决策逻辑", "第二周实现确认、审计与验收"],
        "acceptance_cases": ["给定完整输入时输出可解释建议且必须由人确认"],
        "risks": [f"关键依赖不稳定：{major_dependency}"],
        "unknowns": ["真实使用效果尚未通过试点验证"],
        "complexity": "medium" if automation_level == "high" else "low",
        "provenance": "model_hypothesis",
        "required_data_class": required_data_class,
        "automation_level": automation_level,
        "human_role": human_role,
        "core_decision_logic": core_decision_logic,
        "major_dependency": major_dependency,
        "requires_llm_runtime": requires_llm_runtime,
        "requires_rag_runtime": False,
        "requires_agent_runtime": False,
    }


class _CanonicalExampleRuntime:
    mode = "deterministic_demo"
    provider = "fixture"
    model = "canonical-example-v1"
    prompt_version = "canonical-example-v1"
    schema_version = "v3-p0-1"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1

    def __init__(self, candidates: list[dict[str, Any]]):
        self.candidates = candidates

    def design_solutions(self, _brief) -> SolutionSetDraft:
        return SolutionSetDraft.model_validate(
            {"candidates": self.candidates, "llm_core_required": False}
        )


_EXAMPLES: list[dict[str, Any]] = [
    {
        "id": "project_example_inventory_alert",
        "title": "示例｜便利店智能补货提醒",
        "summary": "帮助小型便利店在畅销商品断货前，用每天五分钟得到可执行补货清单。",
        "canvas": {
            "problem": "店主依靠记忆和手写进货本盘货，畅销商品卖完后才发现，临时补货成本高且影响顾客体验。",
            "target_users": "单店便利店店主与负责日常补货的一线店员。",
            "goals": ["每天生成五种最需要补货的商品", "支持店主手动确认并记录原因", "在不接入复杂 ERP 的前提下完成试点"],
            "non_goals": ["不自动下采购订单", "不替代财务或供应商管理系统"],
            "success_metrics": ["店主每天使用不超过五分钟", "试点商品的断货次数较基线下降 20%", "建议清单被手动确认的比例达到 60%"],
            "constraints": ["本地优先", "单人可维护", "不接入现有 ERP", "四周内完成试点"],
        },
        "sources": [
            {"title": "店主试点约束", "filename": "owner_constraints.md", "source_type": "user_input", "authority": 0.9, "content": "店主确认：每天最多使用五分钟；首期只看五种商品；不接 ERP；建议必须允许人工确认。", "authority_basis": "项目所有者确认的范围与约束。"},
            {"title": "模拟缺货记录", "filename": "simulated_stockouts.txt", "source_type": "simulated_research", "authority": 0.4, "content": "这是人工构造的演示材料，不是真实经营数据。示例显示矿泉水、纸巾和面包在周末下午出现缺货，店主在晚间盘货后才发现。", "authority_basis": "明确标注为模拟材料，只用于演示流程。"},
            {"title": "盘货表字段说明", "filename": "inventory_fields.md", "source_type": "implementation_evidence", "authority": 0.85, "content": "MVP 输入字段包括商品名、当前库存、近七日销量、供应提前期和人工备注。当前原型支持本地 CSV 导入与手动确认，不支持自动采购。", "authority_basis": "可复核的原型字段与实现状态。"},
            {"title": "公开库存控制方法说明", "filename": "public_inventory_method.md", "source_type": "public_source", "authority": 0.7, "content": "公开库存管理方法通常用当前库存、历史消耗和补货提前期计算再订货点。该材料只说明通用方法，不证明便利店愿意采用本示例产品，也不代表真实市场调研。", "authority_basis": "公开方法的演示性摘要，适用范围限于通用库存计算。"},
        ],
        "solutions": [
            _candidate(title="库存阈值提醒", mechanism="rule_based", summary="库存低于安全阈值时生成补货提醒。", why_fit="数据要求最低，适合先验证提醒是否有用。", required_data_class="当前库存与安全库存", automation_level="low", human_role="维护阈值并确认补货建议", core_decision_logic="当前库存低于安全库存时进入提醒清单", major_dependency="库存输入及时且准确"),
            _candidate(title="销量速度推荐", mechanism="recommendation_based", summary="结合近七日销量与供应提前期排序补货优先级。", why_fit="能在有限清单中优先处理更可能断货的商品。", required_data_class="当前库存、近七日销量与供应提前期", automation_level="medium", human_role="复核推荐排序并决定补货量", core_decision_logic="按预计断货天数和供应提前期计算优先级", major_dependency="连续销量记录可用"),
            _candidate(title="人工盘货工作流", mechanism="human_in_the_loop", summary="以固定盘货流程收集异常并由店主逐项确认。", why_fit="保留人工判断，适合数据质量尚不稳定的试点。", required_data_class="人工盘货结果与备注", automation_level="low", human_role="完成盘货、解释异常并最终确认", core_decision_logic="按盘货缺口和人工备注生成待办", major_dependency="店主持续完成简短盘货"),
        ],
    },
    {
        "id": "project_example_procurement_workflow",
        "title": "示例｜B2B 采购审批助手",
        "summary": "减少中型企业采购申请被反复退回的次数，并让申请人知道下一步应补什么、找谁。",
        "canvas": {
            "problem": "采购申请常因金额、合同、预算归属或审批人信息不完整被退回；申请人不知道缺什么和由谁处理，审批周期被拉长。",
            "target_users": "中型企业的采购申请人、部门负责人和财务审批人员。",
            "goals": ["提交前检查必填信息", "显示当前审批节点与下一位处理人", "记录退回原因并形成改进清单"],
            "non_goals": ["不绕过既有合规审批", "不直接修改 ERP 中的财务凭证"],
            "success_metrics": ["试点流程退回率下降 20%", "审批中位时长下降 15%", "申请人能在一次页面内看到下一步动作"],
            "constraints": ["兼容现有 ERP", "保留审批审计", "一个季度内试点", "敏感采购数据不离开企业环境"],
        },
        "sources": [
            {"title": "采购审批制度摘录", "filename": "procurement_policy.md", "source_type": "public_source", "authority": 0.75, "content": "制度摘录：金额超过五万元的采购申请需要部门负责人和财务负责人两级审批；申请必须附预算归属和供应商报价。该材料仅说明制度规则，不证明实际退回率。", "authority_basis": "可复核的制度说明，适用范围限于规则本身。"},
            {"title": "项目负责人试点目标", "filename": "pilot_goal.md", "source_type": "user_input", "authority": 0.9, "content": "项目负责人确认：首期只做提交前检查、审批状态和退回原因；不得替代 ERP 或绕过人工审批。", "authority_basis": "项目所有者确认的试点范围。"},
            {"title": "合成退回工单样本", "filename": "simulated_return_cases.txt", "source_type": "simulated_research", "authority": 0.4, "content": "这是人工构造的示例，不代表真实客户数据。案例 A 因预算编码缺失被退回；案例 B 因报价附件缺失被退回。", "authority_basis": "明确标注为模拟材料。"},
            {"title": "审批助手演示实现记录", "filename": "approval_prototype.md", "source_type": "implementation_evidence", "authority": 0.85, "content": "演示原型已实现必填字段校验、审批节点展示和人工退回原因记录。该记录只证明演示实现状态，不证明真实企业采用、退回率下降或审批提速。", "authority_basis": "可复核的演示原型能力边界。"},
        ],
        "solutions": [
            _candidate(title="提交前规则检查", mechanism="rule_based", summary="按金额、预算和附件规则检查申请完整性。", why_fit="直接针对常见退回原因且不改变既有审批权限。", required_data_class="申请字段、金额规则与附件清单", automation_level="low", human_role="修正缺失信息并决定是否提交", core_decision_logic="逐项匹配制度规则并输出缺失项", major_dependency="审批制度规则可维护"),
            _candidate(title="审批路由工作流", mechanism="workflow_based", summary="展示当前节点、下一处理人和退回补充动作。", why_fit="减少申请人在跨部门流程中的等待和询问。", required_data_class="组织角色、审批节点与申请状态", automation_level="medium", human_role="审批人保留通过或退回决定", core_decision_logic="按金额和部门映射审批路径及下一节点", major_dependency="组织与审批路由数据准确"),
            _candidate(title="退回原因解释助手", mechanism="assistant", summary="把制度条款和缺失字段整理成可读的补充建议。", why_fit="可降低申请人理解退回原因的成本，但不能替代审批。", required_data_class="退回原因、制度条款与申请字段", automation_level="high", human_role="核对解释并完成材料补充", core_decision_logic="基于已知规则生成解释草稿并要求人工确认", major_dependency="制度文本版本受控且模型输出可审计", requires_llm_runtime=True),
        ],
    },
]


class ExampleProjectSeeder:
    """Seed legacy-shaped examples that startup migrates into explicit 3.0 Snapshots.

    Simulated example sources remain simulated; migration never upgrades them into
    real user validation. Keeping the legacy shape also exercises compatibility.
    """

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectService(db)

    def seed(self) -> None:
        for example in _EXAMPLES:
            self._seed_one(example)
        migration = LegacyMigrationService(self.db)
        for example in _EXAMPLES:
            migration.migrate_project(example["id"])
            # Canonical synthetic examples are curated fixtures, not user legacy data.
            # Their brief is intentionally confirmed so the fixture enrichment can
            # generate its deterministic solution/document graph.
            self.db.execute(
                """UPDATE idea_briefs SET confirmation_status='confirmed', confirmed_at=COALESCE(confirmed_at, created_at)
                   WHERE project_id=? AND confirmation_status='inferred'""",
                (example["id"],),
            )
            self._enrich_one(example)

    def _seed_one(self, example: dict[str, Any]) -> None:
        project_id = example["id"]
        if self.db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,)) is None:
            now = utc_now()
            self.db.execute(
                "INSERT INTO projects(id, title, summary, status, created_at, updated_at) VALUES (?, ?, ?, 'example', ?, ?)",
                (project_id, example["title"], example["summary"], now, now),
            )
        self.db.execute(
            "UPDATE projects SET project_origin='demo', exclude_from_beta_metrics=1 WHERE id=?",
            (project_id,),
        )
        canvas = example["canvas"]
        if self.db.get_canvas(project_id) is None:
            self.projects.update_canvas(project_id, actor="example_seed", **canvas)
        for source in example["sources"]:
            self.db.add_source(project_id=project_id, **source)

    def _enrich_one(self, example: dict[str, Any]) -> None:
        project_id = example["id"]
        project = self.db.fetch_one(
            "SELECT * FROM projects WHERE id=? AND status='example'", (project_id,)
        )
        if project is None:
            return

        runtime = _CanonicalExampleRuntime(example["solutions"])
        existing_run = self.db.fetch_one(
            """SELECT sr.* FROM solution_runs sr
               WHERE sr.project_id=? AND sr.provider=? AND sr.model=?
                 AND sr.status='completed'
                 AND (SELECT COUNT(*) FROM solution_candidates sc WHERE sc.run_id=sr.id)=3
               ORDER BY sr.created_at,sr.id LIMIT 1""",
            (project_id, runtime.provider, runtime.model),
        )
        solution_service = SolutionDesignService(self.db, runtime)
        if existing_run is None:
            solution_service.generate(project_id, actor="example_seed")
            existing_run = self.db.fetch_one(
                """SELECT * FROM solution_runs
                   WHERE project_id=? AND provider=? AND model=? AND status='completed'
                   ORDER BY created_at DESC,id DESC LIMIT 1""",
                (project_id, runtime.provider, runtime.model),
            )
        assert existing_run is not None
        candidate_rows = self.db.fetch_all(
            "SELECT * FROM solution_candidates WHERE run_id=? ORDER BY created_at,id",
            (existing_run["id"],),
        )
        candidates = [solution_service._serialize_candidate(row) for row in candidate_rows]
        if len(candidates) != 3:
            raise RuntimeError("canonical example requires exactly three solution candidates")

        self._curate_selected_snapshot(project_id, candidates, runtime)
        loop = DocumentLoop(self.db)
        versions = []
        for doc_type in ("prd", "techdoc"):
            version = loop.run(
                project_id,
                doc_type,
                idempotency_key=f"canonical-example:{project_id}:{doc_type}:v1",
                require_snapshot=True,
                # These deterministic demo documents predate the competitor
                # decision feature.  Preserve their historical no-competitor
                # context instead of requiring or inventing a current
                # competitor snapshot during application startup.
                use_competitor_snapshot=False,
            )
            if version["validation_status"] != "passed":
                raise RuntimeError(
                    f"canonical {doc_type} failed validation: {version.get('issues', [])}"
                )
            versions.append(version)
        documents = DocumentVersionService(self.db)
        for version in versions:
            documents.confirm(
                version["version_id"],
                actor="example_seed",
                note="产品内置演示文档确认；不代表真实市场验证。",
                human_confirmed=True,
            )

    def _curate_selected_snapshot(
        self,
        project_id: str,
        candidates: list[dict[str, Any]],
        runtime: _CanonicalExampleRuntime,
    ) -> None:
        project = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        snapshot = self.db.fetch_one(
            "SELECT * FROM project_snapshots WHERE id=?", (project["current_snapshot_id"],)
        )
        brief_row = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE id=?", (snapshot["idea_brief_id"],)
        )
        assert project is not None and snapshot is not None and brief_row is not None
        retrieval = ProjectRetrievalService(self.db)
        project_claims = ProjectClaimService(
            db=self.db, retrieval=retrieval, runtime=runtime
        )
        snapshots = SnapshotService(
            self.db,
            self.projects,
            DecisionService(),
            project_claims,
            CanvasProjectionService(),
            ArtifactHealthService(self.db),
        )
        brief = snapshots._deserialize_brief(brief_row)
        selected = candidates[0]
        next_action = json.loads(snapshot["next_action_json"])
        rationale = "内置示例选择最低数据门槛方案作为 MVP；该选择用于演示，不构成真实业务验证。"
        payload = snapshots._build_snapshot_payload(
            project=project,
            brief=brief,
            selected=selected,
            evolution=candidates[1:],
            rationale=rationale,
            next_action=next_action,
        )
        canvas = self.db.get_canvas(project_id) or {}
        payload["solution"]["explicit_non_goals"] = canvas.get("non_goals", [])
        option_ids_json = json.dumps(
            [item["id"] for item in candidates], ensure_ascii=False
        )
        decision_payload_json = json.dumps(
            {
                "strategy": "single",
                "candidate_ids": [selected["id"]],
                "canonical_example": True,
                "market_validation": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        desired_hash = sha256_payload(payload)
        decision = self.db.fetch_one(
            "SELECT * FROM project_decisions WHERE id=?", (snapshot["decision_id"],)
        )
        health = self.db.fetch_one(
            """SELECT * FROM artifact_health
               WHERE artifact_type='project_snapshot' AND artifact_id=?""",
            (snapshot["id"],),
        )
        health_reason = "canonical example curated without upgrading simulated evidence"
        if (
            snapshot["content_sha256"] == desired_hash
            and decision is not None
            and decision["decision_type"] == "solution_selection"
            and decision["options_json"] == option_ids_json
            and decision["selected_option_id"] == selected["id"]
            and decision["rationale"] == rationale
            and decision["status"] == "confirmed"
            and decision["decision_key"] == "current_solution"
            and decision["decision_payload_json"] == decision_payload_json
            and health is not None
            and health["health_status"] == "current"
            and health["reason"] == health_reason
        ):
            return
        now = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                """UPDATE project_decisions
                   SET decision_type='solution_selection', options_json=?, selected_option_id=?,
                       rationale=?, status='confirmed', decision_key='current_solution',
                       decision_version=1, decision_payload_json=?, confirmed_by='example_seed',
                       confirmed_at=COALESCE(confirmed_at,?)
                   WHERE id=?""",
                (
                    option_ids_json,
                    selected["id"],
                    rationale,
                    decision_payload_json,
                    now,
                    snapshot["decision_id"],
                ),
            )
            connection.execute(
                """UPDATE project_snapshots SET
                       title=?,one_liner=?,target_user_json=?,problem_json=?,solution_json=?,
                       mvp_json=?,user_flow_json=?,inputs_json=?,outputs_json=?,
                       technical_plan_json=?,unknowns_json=?,next_action_json=?,content_sha256=?
                   WHERE id=?""",
                (
                    payload["title"], payload["one_liner"],
                    json.dumps(payload["target_user"], ensure_ascii=False),
                    json.dumps(payload["problem"], ensure_ascii=False),
                    json.dumps(payload["solution"], ensure_ascii=False),
                    json.dumps(payload["mvp"], ensure_ascii=False),
                    json.dumps(payload["user_flow"], ensure_ascii=False),
                    json.dumps(payload["inputs"], ensure_ascii=False),
                    json.dumps(payload["outputs"], ensure_ascii=False),
                    json.dumps(payload["technical_plan"], ensure_ascii=False),
                    json.dumps(payload["unknowns"], ensure_ascii=False),
                    json.dumps(payload["next_action"], ensure_ascii=False),
                    desired_hash, snapshot["id"],
                ),
            )
            connection.execute(
                """UPDATE artifact_health SET health_status='current',
                       reason=?,
                       trigger_source_id=NULL,updated_at=?
                   WHERE artifact_type='project_snapshot' AND artifact_id=?""",
                (health_reason, now, snapshot["id"]),
            )
