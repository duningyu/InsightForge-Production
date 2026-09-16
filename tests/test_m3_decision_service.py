from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.action_review import ActionReviewService
from app.services.action_submission import ActionSubmissionService
from app.services.m3_decision import M3DecisionService
from tests.test_if_guide_m3_review import _review_payload, _submitted


def _pass_review(client, db):
    submission = _submitted(client, db)
    review = ActionReviewService(db).review(
        actor="m3-owner", **_review_payload(submission)
    )
    return submission, review


def test_recommend_requires_exact_review_and_confirm_is_separate_from_action_state(
    client, db
):
    submission, review = _pass_review(client, db)
    service = M3DecisionService(db)

    decision = service.recommend(
        actor="m3-owner",
        project_id=submission["project_id"],
        submission_id=submission["submission_id"],
        review_id=review["review_id"],
        review_revision=review["revision"],
        decision="CONTINUE",
        rationale="结果已记录，继续执行当前最小流程。",
        recommendation="保留当前流程并进入下一次用户操作。",
        remaining_unknowns=["尚未验证长期使用意愿"],
    )

    assert decision["confirmed"] is False
    assert decision["decision"] == "CONTINUE"
    assert decision["recommendation"]
    assert decision["remaining_unknowns"] == ["尚未验证长期使用意愿"]
    with db.connect() as connection:
        task_state = connection.execute(
            "SELECT execution_state FROM first_action_cards WHERE task_id = ?",
            (submission["task_id"],),
        ).fetchone()["execution_state"]
    assert task_state == "CLOSED"

    confirmed = service.confirm(
        actor="m3-owner",
        project_id=submission["project_id"],
        decision_id=decision["decision_id"],
        expected_revision=decision["revision"],
    )
    assert confirmed["confirmed"] is True
    assert confirmed["confirmed_by"] == "m3-owner"
    assert service.get_current(submission["project_id"], actor="m3-owner")["confirmed"] is True


@pytest.mark.parametrize("decision", ["CONTINUE", "NARROW", "CHANGE", "STOP", "FINISH"])
def test_all_m3_decisions_are_allowed_and_finish_is_not_deployment(client, db, decision):
    submission, review = _pass_review(client, db)
    result = M3DecisionService(db).recommend(
        actor="m3-owner",
        project_id=submission["project_id"],
        submission_id=submission["submission_id"],
        review_id=review["review_id"],
        review_revision=review["revision"],
        decision=decision,
        rationale="用户确认本次结果后的下一步选择。",
        recommendation="基于当前证据给出下一步建议。",
        remaining_unknowns=[],
    )
    assert result["decision"] == decision
    assert result["confirmed"] is False
    assert "deployed" not in result


def test_decision_rejects_wrong_review_owner_and_stale_confirmation(client, db):
    submission, review = _pass_review(client, db)
    service = M3DecisionService(db)
    with pytest.raises(ConflictError, match="M3_DECISION_REVIEW_REVISION_CONFLICT"):
        service.recommend(
            actor="m3-owner",
            project_id=submission["project_id"],
            submission_id=submission["submission_id"],
            review_id=review["review_id"],
            review_revision=review["revision"] + 1,
            decision="STOP",
            rationale="停止当前流程。",
            recommendation="保留结果并停止。",
            remaining_unknowns=[],
        )
    with pytest.raises(PermissionError):
        service.recommend(
            actor="other-account",
            project_id=submission["project_id"],
            submission_id=submission["submission_id"],
            review_id=review["review_id"],
            review_revision=review["revision"],
            decision="STOP",
            rationale="停止当前流程。",
            recommendation="保留结果并停止。",
            remaining_unknowns=[],
        )
    decision = service.recommend(
        actor="m3-owner",
        project_id=submission["project_id"],
        submission_id=submission["submission_id"],
        review_id=review["review_id"],
        review_revision=review["revision"],
        decision="STOP",
        rationale="停止当前流程。",
        recommendation="保留结果并停止。",
        remaining_unknowns=[],
    )
    with pytest.raises(ConflictError, match="M3_DECISION_REVISION_CONFLICT"):
        service.confirm(
            actor="m3-owner",
            project_id=submission["project_id"],
            decision_id=decision["decision_id"],
            expected_revision=decision["revision"] + 1,
        )


def test_decision_requires_source_review_and_user_confirmation(client, db):
    project_id, task_id, task_revision = _submitted.__globals__["_m2_ready_action"](client)
    submission = ActionSubmissionService(db).submit(
        actor="m3-owner",
        project_id=project_id,
        task_id=task_id,
        task_revision=task_revision,
        submission_kind="BLOCKED",
        description="无法完成当前检查。",
        attachment_refs=[],
        check_results=[],
        execution_claim={},
        source_identity="USER_INPUT",
    )
    with pytest.raises(KeyError):
        M3DecisionService(db).recommend(
            actor="m3-owner",
            project_id=project_id,
            submission_id=submission["submission_id"],
            review_id="missing-review",
            review_revision=1,
            decision="CONTINUE",
            rationale="没有评审不能确认。",
            recommendation="等待评审。",
            remaining_unknowns=["缺少评审证据"],
        )
