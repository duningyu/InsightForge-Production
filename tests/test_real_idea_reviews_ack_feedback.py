import json

import pytest

from app.db import utc_now
from app.services.real_idea_evaluation import RealIdeaEvaluationService, ReviewGateError
from tests.test_stage_b_phase2_local_techdoc_handoff import (
    _phase2_database,
    _prepare_confirmed_handoff_documents,
)


def _real_idea_service_fixture(tmp_path):
    database, project_id, prd_version_id, _solution_id, snapshot_id = _phase2_database(tmp_path)
    techdoc_version_id = _prepare_confirmed_handoff_documents(
        database, project_id, prd_version_id, snapshot_id
    )
    service = RealIdeaEvaluationService(database, durable_budget=6)
    service.start_batch("batch-review")
    allocation = database.fetch_one(
        "SELECT allocation_id FROM real_idea_budget_allocations WHERE batch_id=?",
        ("batch-review",),
    )
    now = utc_now()
    database.execute(
        """INSERT INTO real_idea_samples(
            sample_id,batch_id,sample_key,source_type,project_id,raw_idea_sha256,
            redaction_version,state,brief_version_id,solutions_evaluation_id,
            selected_solution_id,snapshot_id,prd_version_id,techdoc_version_id,
            sample_manifest_sha256,budget_allocation_id,created_at,created_by
        ) VALUES (?,?,'REAL_IDEA_01','raw_user_idea',?,'raw-hash','v1',
                  'AWAITING_SOLUTION_REVIEW',NULL,NULL,NULL,?,?,?,?,?,?,?)""",
        (
            "sample-review", "batch-review", project_id, snapshot_id,
            prd_version_id, techdoc_version_id, "manifest", allocation["allocation_id"],
            now, "test",
        ),
    )
    return service


def test_document_review_requires_exact_versions_and_explicit_ack(tmp_path):
    service = _real_idea_service_fixture(tmp_path)

    with pytest.raises(ReviewGateError):
        service.acknowledge_evidence("sample-review", explicit=False)

    acknowledgement = service.acknowledge_evidence("sample-review", explicit=True)
    assert acknowledgement.confirmed is True
    assert acknowledgement.externally_verified is False
    assert acknowledgement.provider_transport_count == 0


def test_feedback_attestation_is_user_reported_not_ground_truth(tmp_path):
    service = _real_idea_service_fixture(tmp_path)

    feedback = service.record_feedback("sample-review", ratings={"idea_fidelity": 5})

    assert feedback.attested_by == "idea_provider"
    assert feedback.used_as_requirement_ground_truth is False

    stored = service.database.fetch_one(
        "SELECT score_payload, raw_feedback_text, feedback_attestation FROM real_idea_feedback WHERE sample_id=?",
        ("sample-review",),
    )
    assert json.loads(stored["score_payload"]) == {"idea_fidelity": 5}
    assert stored["raw_feedback_text"] is None
    assert stored["feedback_attestation"] == 1
