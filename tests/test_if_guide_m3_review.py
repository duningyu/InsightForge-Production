from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.action_review import ActionReviewService
from app.services.action_submission import ActionSubmissionService
from tests.test_if_guide_m3_submission import _m2_ready_action, _submission


def _review_payload(submission: dict, **overrides):
    payload = {
        "project_id": submission["project_id"],
        "submission_id": submission["submission_id"],
        "submission_revision": submission["revision"],
        "task_id": submission["task_id"],
        "task_revision": submission["task_revision"],
        "check_items": [
            {"check_id": "result-recorded", "outcome": "PASS", "evidence_refs": ["user-note-1"]}
        ],
        "overall_status": "PASS",
        "known_unknowns": [],
        "evidence_level": "USER_REPORTED",
        "recommendation": "继续保留这条最小流程。",
        "reviewer_role": "system_review",
    }
    payload.update(overrides)
    return payload


def _submitted(client, db):
    project_id, task_id, task_revision = _m2_ready_action(client)
    submission = _submission(
        ActionSubmissionService(db), project_id, task_id, task_revision
    )
    return submission


def test_action_review_persists_pass_and_closes_exact_submitted_task(client, db):
    submission = _submitted(client, db)
    result = ActionReviewService(db).review(actor="m3-owner", **_review_payload(submission))

    assert result["overall_status"] == "PASS"
    assert result["submission_id"] == submission["submission_id"]
    assert result["submission_revision"] == submission["revision"]
    assert result["task_revision"] == submission["task_revision"]
    assert result["evidence_level"] == "USER_REPORTED"
    assert result["evidence_hash"]
    with db.connect() as connection:
        task = connection.execute(
            "SELECT execution_state, source_review_id FROM first_action_cards WHERE task_id = ?",
            (submission["task_id"],),
        ).fetchone()
    assert task["execution_state"] == "CLOSED"
    assert task["source_review_id"] == result["review_id"]


@pytest.mark.parametrize("status", ["FAIL", "UNKNOWN", "NOT_APPLICABLE"])
def test_action_review_preserves_non_pass_statuses(client, db, status):
    submission = _submitted(client, db)
    result = ActionReviewService(db).review(
        actor="m3-owner",
        **_review_payload(
            submission,
            overall_status=status,
            recommendation="记录当前限制并要求下一步最小恢复动作。",
        ),
    )
    assert result["overall_status"] == status
    with db.connect() as connection:
        state = connection.execute(
            "SELECT execution_state FROM first_action_cards WHERE task_id = ?",
            (submission["task_id"],),
        ).fetchone()["execution_state"]
    assert state == "NEEDS_REVISION"


def test_action_review_rejects_wrong_binding_and_unauthorized_run(client, db):
    submission = _submitted(client, db)
    service = ActionReviewService(db)

    with pytest.raises(ConflictError, match="ACTION_REVIEW_SUBMISSION_REVISION_CONFLICT"):
        service.review(
            actor="m3-owner",
            **_review_payload(submission, submission_revision=submission["revision"] + 1),
        )
    with pytest.raises(ValueError, match="AUTHORIZED_RUN_NOT_ALLOWED"):
        service.review(
            actor="m3-owner",
            **_review_payload(submission, evidence_level="AUTHORIZED_RUN"),
        )
    with pytest.raises(PermissionError):
        service.review(actor="other-account", **_review_payload(submission))


def test_action_review_requires_structured_evidence_for_pass(client, db):
    submission = _submitted(client, db)
    with pytest.raises(ValueError, match="PASS_EVIDENCE_REQUIRED"):
        ActionReviewService(db).review(
            actor="m3-owner",
            **_review_payload(
                submission,
                check_items=[{"check_id": "result-recorded", "outcome": "PASS"}],
            ),
        )
