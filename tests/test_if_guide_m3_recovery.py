from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.action_review import ActionReviewService
from app.services.action_submission import ActionSubmissionService
from app.services.recovery import RecoveryService
from tests.test_if_guide_m3_review import _review_payload, _submitted


def _failed_review(client, db):
    submission = _submitted(client, db)
    review = ActionReviewService(db).review(
        actor="m3-owner",
        **_review_payload(
            submission,
            overall_status="FAIL",
            check_items=[
                {
                    "check_id": "result-recorded",
                    "outcome": "FAIL",
                    "evidence_refs": ["user-note-1"],
                }
            ],
            known_unknowns=["是否完成最小结果核验"],
            recommendation="补齐结果核验并重新提交。",
        ),
    )
    return submission, review


def test_failure_review_creates_one_minimal_recovery_action_without_overwriting_original(
    client, db
):
    submission, review = _failed_review(client, db)
    service = RecoveryService(db)

    recovery = service.create_from_review(
        actor="m3-owner",
        project_id=submission["project_id"],
        task_id=submission["task_id"],
        submission_id=submission["submission_id"],
        review_id=review["review_id"],
        review_revision=review["revision"],
        goal="补齐结果核验并重新提交。",
        inputs=["当前最小流程结果"],
        steps=["补齐结果核验", "重新提交结果"],
        checks=["结果核验记录存在"],
    )

    assert recovery["kind"] == "RECOVERY"
    assert recovery["parent_task_id"] == submission["task_id"]
    assert recovery["source_submission_id"] == submission["submission_id"]
    assert recovery["source_review_id"] == review["review_id"]
    assert recovery["execution_state"] == "READY"
    assert recovery["confirmed"] is False
    assert recovery["revision"] == 1

    with db.connect() as connection:
        original = connection.execute(
            "SELECT kind, execution_state FROM first_action_cards WHERE task_id = ?",
            (submission["task_id"],),
        ).fetchone()
        recoveries = connection.execute(
            "SELECT task_id FROM first_action_cards WHERE project_id = ? AND kind = 'RECOVERY'",
            (submission["project_id"],),
        ).fetchall()
    assert original["kind"] == "FIRST_ACTION"
    assert original["execution_state"] == "NEEDS_REVISION"
    assert len(recoveries) == 1


def test_recovery_is_idempotent_and_duplicate_minimal_actions_are_not_created(client, db):
    submission, review = _failed_review(client, db)
    service = RecoveryService(db)
    kwargs = {
        "actor": "m3-owner",
        "project_id": submission["project_id"],
        "task_id": submission["task_id"],
        "submission_id": submission["submission_id"],
        "review_id": review["review_id"],
        "review_revision": review["revision"],
        "goal": "补齐结果核验并重新提交。",
        "inputs": ["当前最小流程结果"],
        "steps": ["补齐结果核验", "重新提交结果"],
        "checks": ["结果核验记录存在"],
    }

    first = service.create_from_review(**kwargs)
    second = service.create_from_review(**kwargs)

    assert second["task_id"] == first["task_id"]
    assert second["revision"] == first["revision"]
    with db.connect() as connection:
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM first_action_cards WHERE project_id = ? AND kind = 'RECOVERY'",
            (submission["project_id"],),
        ).fetchone()["count"]
    assert count == 1


def test_recovery_update_confirm_and_reopen_require_owner_and_revision(client, db):
    submission, review = _failed_review(client, db)
    service = RecoveryService(db)
    recovery = service.create_from_review(
        actor="m3-owner",
        project_id=submission["project_id"],
        task_id=submission["task_id"],
        submission_id=submission["submission_id"],
        review_id=review["review_id"],
        review_revision=review["revision"],
        goal="先补齐结果核验。",
        inputs=["当前结果"],
        steps=["补齐结果核验"],
        checks=["结果核验记录存在"],
    )

    with pytest.raises(PermissionError):
        service.get_current(submission["project_id"], actor="other-account")
    with pytest.raises(ConflictError, match="RECOVERY_REVISION_CONFLICT"):
        service.update(
            actor="m3-owner",
            project_id=submission["project_id"],
            recovery_task_id=recovery["task_id"],
            expected_revision=recovery["revision"] + 1,
            goal="更新后的最小动作。",
            inputs=["当前结果"],
            steps=["更新并重提"],
            checks=["更新后的检查"],
        )

    updated = service.update(
        actor="m3-owner",
        project_id=submission["project_id"],
        recovery_task_id=recovery["task_id"],
        expected_revision=recovery["revision"],
        goal="更新后的最小动作。",
        inputs=["当前结果"],
        steps=["更新并重提"],
        checks=["更新后的检查"],
    )
    assert updated["revision"] == 2
    assert updated["confirmed"] is False

    confirmed = service.confirm(
        actor="m3-owner",
        project_id=submission["project_id"],
        recovery_task_id=recovery["task_id"],
        expected_revision=updated["revision"],
    )
    assert confirmed["confirmed"] is True
    reopened = service.get_current(submission["project_id"], actor="m3-owner")
    assert reopened["task_id"] == recovery["task_id"]
    assert reopened["confirmed"] is True


def test_recovery_is_not_created_for_pass_review(client, db):
    submission = _submitted(client, db)
    review = ActionReviewService(db).review(
        actor="m3-owner", **_review_payload(submission)
    )
    with pytest.raises(ConflictError, match="RECOVERY_NOT_REQUIRED"):
        RecoveryService(db).create_from_review(
            actor="m3-owner",
            project_id=submission["project_id"],
            task_id=submission["task_id"],
            submission_id=submission["submission_id"],
            review_id=review["review_id"],
            review_revision=review["revision"],
            goal="不应创建",
            inputs=[],
            steps=["不应创建"],
            checks=["不应创建"],
        )
