from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.if_guide_m4_gold_set import M4GoldSetService

from test_if_guide_m4_gold_set import _create_m4_session, _requirements


def test_llm_assist_cannot_finalize_ground_truth_and_reviewer_disagreement_is_preserved(db):
    account_id, participant_id, project_id = _create_m4_session(db)
    service = M4GoldSetService(db)

    with pytest.raises(ConflictError, match="GOLD_SET_HUMAN_CONFIRMATION_REQUIRED"):
        service.finalize_gold_set(
            session_id="gold-session",
            account_id=account_id,
            participant_id=participant_id,
            project_id=project_id,
            purpose="machine extracted purpose",
            constraints=[],
            explicit_non_goals=[],
            requirements=_requirements(),
            participant_confirmed=True,
            confirmed_by="llm_assist",
            expected_session_revision=1,
        )

    service.finalize_gold_set(
        session_id="gold-session",
        account_id=account_id,
        participant_id=participant_id,
        project_id=project_id,
        purpose="human confirmed purpose",
        constraints=[],
        explicit_non_goals=[],
        requirements=_requirements(),
        participant_confirmed=True,
        expected_session_revision=1,
    )
    first = service.create_annotation(
        session_id="gold-session",
        account_id=account_id,
        project_id=project_id,
        artifact_ref="gold-set:r1",
        annotation_type="REQUIREMENT_MAPPING",
        target_id="req-1",
        label="SUPPORTED",
        evaluator_role="INDEPENDENT_REVIEWER",
        evidence_ref={"source": "reviewer-a", "location": "item-1"},
        disagreement={"present": True, "with": "reviewer-b"},
    )
    second = service.create_annotation(
        session_id="gold-session",
        account_id=account_id,
        project_id=project_id,
        artifact_ref="gold-set:r1",
        annotation_type="REQUIREMENT_MAPPING",
        target_id="req-1",
        label="PARTIAL",
        evaluator_role="INDEPENDENT_REVIEWER",
        evidence_ref={"source": "reviewer-b", "location": "item-1"},
        disagreement={"present": True, "with": "reviewer-a"},
    )
    assert first["adjudication_status"] == "PENDING"
    assert second["adjudication_status"] == "PENDING"
    assert first["annotation_id"] != second["annotation_id"]


@pytest.mark.parametrize("unsafe", [{"raw_idea": "private"}, {"transcript": "private"}, {"email": "a@b"}])
def test_annotations_reject_unsafe_private_evidence(db, unsafe):
    account_id, _, project_id = _create_m4_session(db)
    service = M4GoldSetService(db)
    with pytest.raises(ValueError, match="unsafe"):
        service.create_annotation(
            session_id="gold-session",
            account_id=account_id,
            project_id=project_id,
            artifact_ref="session",
            annotation_type="CLAIM",
            target_id="claim-1",
            label="UNVERIFIED",
            evaluator_role="LLM_ASSIST",
            evidence_ref=unsafe,
        )

