from __future__ import annotations

import pytest

from app.db import Database
from app.errors import StructuredRuntimeUnavailableError
from app.schemas import EvidenceActionCard, EvidenceGuidanceDraft
from app.services.evidence_coach import EvidenceCoachService
from app.services.projects import ProjectService


class FakeEvidenceCoachRuntime:
    mode = "fake"
    provider = "fake-transport"
    model = "synthetic-model"
    prompt_version = "test"
    schema_version = "test"
    max_model_rounds = 1
    max_tool_rounds = 0
    model_rounds_used = 1

    def __init__(self, result: EvidenceGuidanceDraft | None = None):
        self.calls: list[dict] = []
        self.result = result or EvidenceGuidanceDraft(
            cards=[
                EvidenceActionCard(
                    title="找一次真实的进度记混经历",
                    question_to_validate="求职者是否真的会漏掉或记混下一步",
                    why_it_matters="这会影响第一版是否需要提醒功能",
                    who_or_where=["最近集中求职、同时推进多家公司的求职者"],
                    action_steps=["请对方回忆最近一次同时推进多家公司时具体怎么记录"],
                    suggested_questions=["当时哪里最容易漏掉？"],
                    acceptable_artifacts=["一段匿名原话", "打码后的记录截图"],
                    fill_template=["对象：", "时间和场景：", "对方原话："],
                    decision_impact="如果多数人都忘记下一步，MVP优先做提醒",
                    fallback_if_unavailable="暂时找不到用户时，先记录自己的真实经历并标为待确认",
                    limitations="少量反馈不能证明整个市场都有这个问题",
                )
            ]
        )

    def generate_evidence_guidance(self, context: dict) -> EvidenceGuidanceDraft:
        self.calls.append(context)
        return self.result


def _project(db: Database) -> str:
    return ProjectService(db).create_project(
        title="行动卡项目", summary="帮助求职者记录多家公司面试进度。", actor="synthetic-user"
    )["id"]


def test_evidence_coach_returns_specific_action_cards_without_creating_sources(tmp_path):
    db = Database(tmp_path / "evidence-coach.sqlite3")
    db.init_schema()
    project_id = _project(db)
    runtime = FakeEvidenceCoachRuntime()

    result = EvidenceCoachService(db).generate(
        project_id, actor="synthetic-user", runtime=runtime, idempotency_key="coach-1"
    )

    assert len(runtime.calls) == 1
    assert result["status"] == "completed"
    assert result["is_evidence"] is False
    card = result["result"]["cards"][0]
    assert card["action_steps"]
    assert card["acceptable_artifacts"]
    assert card["fill_template"]
    assert card["decision_impact"]
    assert card["limitations"]
    assert "尚未加入项目资料" in result["result"]["disclosure"]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM sources WHERE project_id=?", (project_id,))["n"] == 0


def test_empty_evidence_guidance_is_not_saved_as_success(tmp_path):
    db = Database(tmp_path / "empty-evidence-coach.sqlite3")
    db.init_schema()
    project_id = _project(db)
    runtime = FakeEvidenceCoachRuntime(EvidenceGuidanceDraft(cards=[]))

    with pytest.raises(StructuredRuntimeUnavailableError, match="没有生成可用的资料行动建议"):
        EvidenceCoachService(db).generate(
            project_id, actor="synthetic-user", runtime=runtime, idempotency_key="coach-empty"
        )

    assert db.fetch_one(
        "SELECT COUNT(*) AS n FROM evidence_guidance_results WHERE project_id=?", (project_id,)
    )["n"] == 0


def test_evidence_coach_idempotency_reuses_the_saved_result(tmp_path):
    db = Database(tmp_path / "idempotent-evidence-coach.sqlite3")
    db.init_schema()
    project_id = _project(db)
    runtime = FakeEvidenceCoachRuntime()
    service = EvidenceCoachService(db)

    first = service.generate(
        project_id, actor="synthetic-user", runtime=runtime, idempotency_key="coach-replay"
    )
    replay = service.generate(
        project_id, actor="synthetic-user", runtime=runtime, idempotency_key="coach-replay"
    )

    assert first["id"] == replay["id"]
    assert first["content_sha256"] == replay["content_sha256"]
    assert len(runtime.calls) == 1
    assert db.fetch_one(
        "SELECT COUNT(*) AS n FROM evidence_guidance_results WHERE project_id=?", (project_id,)
    )["n"] == 1
