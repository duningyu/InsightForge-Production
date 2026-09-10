"""Deterministic, explicitly scoped Stage A fixture runtime."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.errors import StructuredRuntimeRecoveryError, StructuredRuntimeUnavailableError
from app.schemas import (
    AIReferenceDraft,
    CompetitorComparisonDraft,
    EvidenceGuidanceDraft,
    IdeaBriefDraft,
    QuickStartRequest,
    SolutionCandidateDraft,
    SolutionSetDraft,
)

SAFE_FIXTURE_DISCLOSURE = "Stage A 演示结果 · 非真实 AI 生成"


def safe_fixture_enabled(settings: Settings) -> bool:
    return bool(
        settings.safe_fixture_mode
        and not settings.accounts_enabled
        and settings.beta_participant_id == "railway_stage_a"
    )


class StageASafeFixtureRuntime:
    mode = "deterministic_demo"
    provider = "safe_fixture"
    model = "stage-a-safe-fixture-v1"
    prompt_version = "stage-a-safe-fixture-v1"
    schema_version = "v3-p0-1"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1
    fixture_origin = "STAGE_A_SYNTHETIC"
    disclosure = SAFE_FIXTURE_DISCLOSURE

    def __init__(self, *, scenario: str = "success") -> None:
        self.scenario = scenario
        self.fixture_invocation_count = 0

    def synthetic_brief(self, idea: str) -> IdeaBriefDraft:
        return IdeaBriefDraft(
            original_idea=idea,
            target_user="正在求职、需要管理多个投递流程的求职者",
            problem="职位、面试、材料和跟进事项分散，用户容易错过下一步",
            desired_outcome="让用户在一个清晰的时间线上知道每个申请的状态和下一步",
            known_resources=["用户主动记录的职位链接和面试时间"],
            constraints=["第一版不接入招聘平台账号", "不自动替用户发送消息"],
            unknowns=["用户愿意每天维护多久", "哪些提醒真正能改变行为"],
            provenance={
                "target_user": "model_hypothesis",
                "problem": "model_hypothesis",
                "desired_outcome": "model_hypothesis",
            },
        )

    def interpret_idea(self, request: QuickStartRequest) -> IdeaBriefDraft:
        return self.synthetic_brief(request.idea.strip())

    def generate_ai_reference(self, context: dict[str, Any]) -> AIReferenceDraft:
        return AIReferenceDraft(
            possible_target_users=["并行求职的求职者", "应届毕业生", "转职者"],
            possible_scenarios=["投递后等待回复", "面试前准备材料", "多份申请并行推进"],
            possible_user_problems=["状态分散", "跟进依赖记忆", "材料与面试缺少上下文"],
            missing_information=["当前记录工具", "最常错过的步骤", "阶段模板差异"],
            mvp_thoughts=["先做手动录入和阶段状态", "每份申请保留事件时间线", "用今日待办验证持续使用"],
            questions_to_validate=["哪一步最容易忘？", "用户愿意手动更新吗？", "提醒提前多久最合适？"],
            research_directions=["访谈三位近期求职者", "观察整理材料过程", "用低保真时间线测试查找下一步"],
        )

    def generate_evidence_guidance(self, context: dict[str, Any]) -> EvidenceGuidanceDraft:
        cards = []
        specs = [
            ("确认用户如何记录申请状态", "决定第一版应优先做状态管理还是提醒。"),
            ("验证提醒是否真的改变行为", "决定提醒是否进入MVP以及提醒时机。"),
            ("确认最小时间线信息", "防止MVP收集过多字段却没有帮助决策。"),
        ]
        for title, impact in specs:
            cards.append({
                "title": title,
                "question_to_validate": "目标用户现在如何判断下一步？",
                "why_it_matters": impact,
                "who_or_where": ["最近求职的人", "求职交流社群"],
                "action_steps": ["请对方展示当前记录方式", "记录实际步骤和卡点"],
                "suggested_questions": ["哪一步最容易忘？", "什么信息会让你行动？"],
                "acceptable_artifacts": ["匿名流程截图", "用户原话", "逐步描述"],
                "fill_template": ["对象：", "当前工具：", "卡点：", "原话："],
                "decision_impact": impact,
                "fallback_if_unavailable": "先记录观察，并明确标为待确认。",
                "limitations": "少量访谈不能代表所有目标用户。",
            })
        return EvidenceGuidanceDraft(cards=cards)

    def _candidate(
        self,
        title: str,
        summary: str,
        complexity: str,
        core: str,
        *,
        mechanism: str,
        required_data_class: str,
        automation_level: str,
        human_role: str,
        major_dependency: str,
    ) -> SolutionCandidateDraft:
        return SolutionCandidateDraft(
            title=title,
            mechanism=mechanism,
            summary=summary,
            why_fit="不接入招聘平台也能验证用户是否愿意持续维护申请状态。",
            user_flow=["录入申请", "更新阶段", "查看下一步", "记录结果"],
            mvp_pages=["申请列表", "申请详情", "今日待办"],
            features=["阶段状态", "下一步任务", "时间线", "手动提醒"],
            inputs=["职位名称", "申请阶段", "下一步和截止时间"],
            outputs=["当前状态", "下一步任务", "历史时间线"],
            decision_logic=["优先显示有截止时间的待办", "缺少截止时间时不虚构提醒"],
            data_requirements=["用户主动录入的申请信息", "用户主动记录的事件"],
            technical_components=["SQLite项目数据", "状态时间线", "前端筛选"],
            implementation_plan=["建立申请与事件模型", "实现列表和详情", "补齐待办交互"],
            acceptance_cases=["新增申请后可见", "更新阶段后时间线保留", "刷新后数据仍在"],
            risks=["手动维护成本可能导致流失"],
            unknowns=["用户可接受的字段数量"],
            complexity=complexity,
            provenance="model_hypothesis",
            required_data_class=required_data_class,
            automation_level=automation_level,
            human_role=human_role,
            core_decision_logic=core,
            major_dependency=major_dependency,
        )

    def _build_solution_set(self) -> SolutionSetDraft:
        return SolutionSetDraft(
            candidates=[
                self._candidate(
                    "极简卡片流", "以一张申请卡片集中展示阶段、下一步和截止时间。", "low",
                    "先让用户快速找到并完成下一步。", mechanism="workflow_based",
                    required_data_class="用户主动录入的单份申请状态",
                    automation_level="low", human_role="用户手动更新阶段并确认下一步",
                    major_dependency="用户愿意在状态变化后更新记录",
                ),
                self._candidate(
                    "时间轴提醒型", "把申请过程组织成事件时间线，并突出即将到来的动作。", "medium",
                    "按时间顺序帮助用户减少遗漏。", mechanism="human_in_the_loop",
                    required_data_class="申请事件、截止时间和提醒偏好",
                    automation_level="medium", human_role="用户确认提醒时间并处理到期任务",
                    major_dependency="时间线事件和截止时间保持及时",
                ),
                self._candidate(
                    "自动聚合型", "从用户导入的结构化记录中聚合多份申请的阻塞点。", "high",
                    "跨申请比较状态和风险，但不访问外部平台。", mechanism="automation",
                    required_data_class="多份申请的结构化记录和阶段变更",
                    automation_level="high", human_role="用户复核聚合出的阻塞点和优先级",
                    major_dependency="导入记录字段稳定且用户允许自动归并",
                ),
            ],
            recommendation_rationale="先用低依赖的手动流程验证持续记录和下一步提醒是否有价值。",
            llm_core_required=False,
        )

    def _next_solution_set(self, brief: IdeaBriefDraft) -> SolutionSetDraft:
        self.fixture_invocation_count += 1
        if self.scenario == "solution_generation_fail_once" and self.fixture_invocation_count == 1:
            raise StructuredRuntimeRecoveryError(
                error_code="STAGE_A_FIXTURE_CONTROLLED_FAILURE",
                message="这次方案没有生成成功，你的项目内容已经保留，请重新生成。",
                recovery_actions=["检查项目内容", "点击重新生成"],
                preserved_input=brief.model_dump(mode="json"),
                safe_diagnostic={"fixture_scenario": self.scenario},
            )
        return self._build_solution_set()

    def design_solutions(self, brief: IdeaBriefDraft, **_: Any) -> SolutionSetDraft:
        return self._next_solution_set(brief)

    async def async_design_solutions(self, brief: IdeaBriefDraft, **_: Any) -> SolutionSetDraft:
        return self._next_solution_set(brief)

    def compare_competitors(self, candidates: list[dict[str, Any]], *, project_context: dict[str, Any] | None = None) -> CompetitorComparisonDraft:
        raise StructuredRuntimeUnavailableError("SAFE_FIXTURE_COMPETITOR_CONTEXT_DISABLED")

    def analyze_evidence(self, *, claim: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []
