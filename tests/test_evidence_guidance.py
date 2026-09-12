import pytest

from app.db import Database
from app.errors import StructuredOutputContractError
from app.schemas import EvidenceActionCard, EvidenceGuidanceDraft
from app.services.evidence_coach import EvidenceCoachService
from app.services.projects import ProjectService


def _project(db: Database) -> str:
    return ProjectService(db).create_project(
        title="行动卡完整性项目", summary="帮助学生记录求职准备中的下一步。", actor="synthetic-user"
    )["id"]


class FreshEvidenceGuidanceRuntime:
    mode = "fake"
    provider = "fake-transport"
    model = "synthetic-model"
    prompt_version = "task-3-test"
    schema_version = "task-3-test"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1

    def __init__(self, *, unsupported: bool = False):
        self.calls = []
        self.unsupported = unsupported

    def generate_evidence_guidance(self, context):
        self.calls.append(context)
        return EvidenceGuidanceDraft(
            cards=[
                EvidenceActionCard(
                    title="找一次真实的整理经历",
                    question_to_validate="目标用户是否真的需要整理下一步？",
                    why_it_matters=(
                        "研究证明所有用户都需要这个功能"
                        if self.unsupported
                        else "这会影响第一版是否需要提醒功能"
                    ),
                    who_or_where=["最近开始求职、遇到类似问题的人"],
                    action_steps=["请对方回忆最近一次具体经历并记录卡住的步骤"],
                    suggested_questions=[],
                    acceptable_artifacts=["一段匿名原话"],
                    fill_template=["对象：", "时间和场景：", "对方原话："],
                    decision_impact="决定第一版优先做提醒还是记录模板",
                    fallback_if_unavailable="先记录自己的经历并标为待确认",
                    limitations="少量反馈不能代表全部用户",
                )
            ]
        )


def test_action_card_is_complete_and_optional_questions_do_not_block(tmp_path):
    db = Database(tmp_path / "complete-action-card.sqlite3")
    db.init_schema()
    project_id = _project(db)
    runtime = FreshEvidenceGuidanceRuntime()

    result = EvidenceCoachService(db).generate(
        project_id, actor="synthetic-user", runtime=runtime, idempotency_key="task-3-card"
    )

    card = result["result"]["cards"][0]
    required = (
        "title",
        "question_to_validate",
        "why_it_matters",
        "who_or_where",
        "action_steps",
        "acceptable_artifacts",
        "fill_template",
        "decision_impact",
        "fallback_if_unavailable",
        "limitations",
    )
    assert all(card[key] for key in required)
    assert card["suggested_questions"] == []
    assert result["is_evidence"] is False
    assert result["source_created"] is False
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sources WHERE project_id=?", (project_id,))["n"] == 0


def test_unsupported_action_card_claim_is_rejected(tmp_path):
    db = Database(tmp_path / "unsupported-action-card.sqlite3")
    db.init_schema()
    project_id = _project(db)

    with pytest.raises(StructuredOutputContractError):
        EvidenceCoachService(db).generate(
            project_id,
            actor="synthetic-user",
            runtime=FreshEvidenceGuidanceRuntime(unsupported=True),
            idempotency_key="task-3-unsupported-card",
        )

    assert db.fetch_one(
        "SELECT COUNT(*) AS n FROM evidence_guidance_results WHERE project_id=?", (project_id,)
    )["n"] == 0
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sources WHERE project_id=?", (project_id,))["n"] == 0
