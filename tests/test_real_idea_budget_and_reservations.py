from __future__ import annotations

import pytest

from app.db import utc_now
from app.services.real_idea_budget import ReservationStateError, RealIdeaBudgetService


@pytest.fixture()
def budget_service(db):
    return RealIdeaBudgetService(db, durable_budget=6)


def _seed_batch_and_sample(db, *, batch_id: str = "batch-1", sample_id: str = "sample-1") -> None:
    now = utc_now()
    with db.connect() as connection:
        connection.execute(
            """
            INSERT INTO real_idea_batches(
                batch_id, batch_key, status, created_at, manifest_sha256,
                source_commit, deployment_id, model, prompt_hash, schema_hash,
                completeness_contract_version, questionnaire_version,
                sample_count, provider_policy_version, created_by
            ) VALUES (?, ?, 'CREATED', ?, 'manifest', 'source', 'deployment',
                      'model', 'prompt', 'schema', 'completeness', 'questionnaire',
                      3, 'policy', 'test')
            """,
            (batch_id, batch_id, now),
        )
        connection.execute(
            """
            INSERT INTO real_idea_samples(
                sample_id, batch_id, sample_key, source_type, raw_idea_sha256,
                redaction_version, state, sample_manifest_sha256, created_at, created_by
            ) VALUES (?, ?, 'REAL_IDEA_01', 'user', 'raw-idea', 'v1', 'CREATED',
                      'sample-manifest', ?, 'test')
            """,
            (sample_id, batch_id, now),
        )


def test_extension_is_restricted_and_batch_earmark_is_six(budget_service, db):
    _seed_batch_and_sample(db)
    budget_service.activate_extension("REAL_IDEA_BATCH_01_EXT_01", 3)

    allocation = budget_service.earmark_batch("batch-1", 6)

    assert allocation.authorized_total == 9
    assert allocation.general_spendable == 6
    assert allocation.batch_earmark == 6


def test_reservation_is_idempotent_and_does_not_consume_before_attempt(budget_service, db):
    _seed_batch_and_sample(db)
    budget_service.activate_extension("REAL_IDEA_BATCH_01_EXT_01", 3)
    budget_service.earmark_batch("batch-1", 6)

    first = budget_service.reserve("batch-1", "sample-1", "QUICKSTART", 1)
    second = budget_service.reserve("batch-1", "sample-1", "QUICKSTART", 1)

    assert first.reservation_id == second.reservation_id
    assert first.state == "RESERVED"
    assert budget_service.remaining_batch_earmark("batch-1") == 6


def test_attempted_reservation_cannot_be_released(budget_service, db):
    _seed_batch_and_sample(db)
    budget_service.activate_extension("REAL_IDEA_BATCH_01_EXT_01", 3)
    budget_service.earmark_batch("batch-1", 6)
    reservation = budget_service.reserve("batch-1", "sample-1", "QUICKSTART", 1)

    budget_service.mark_attempted(reservation.reservation_id, dispatch_id="dispatch-1", transport_id="transport-1")

    with pytest.raises(ReservationStateError):
        budget_service.release(reservation.reservation_id)

    assert budget_service.remaining_batch_earmark("batch-1") == 5


def test_sample_has_at_most_one_reservation_per_stage_and_supported_stages_only(budget_service, db):
    _seed_batch_and_sample(db)
    budget_service.activate_extension("REAL_IDEA_BATCH_01_EXT_01", 3)
    budget_service.earmark_batch("batch-1", 6)

    quickstart = budget_service.reserve("batch-1", "sample-1", "QUICKSTART", 1)
    solutions = budget_service.reserve("batch-1", "sample-1", "SOLUTIONS", 1)

    assert quickstart.reservation_id != solutions.reservation_id
    with pytest.raises(ValueError, match="unsupported evaluation transport stage"):
        budget_service.reserve("batch-1", "sample-1", "TECHDOC", 1)


def test_release_is_allowed_only_for_unattempted_reservation(budget_service, db):
    _seed_batch_and_sample(db)
    budget_service.activate_extension("REAL_IDEA_BATCH_01_EXT_01", 3)
    budget_service.earmark_batch("batch-1", 6)
    reservation = budget_service.reserve("batch-1", "sample-1", "QUICKSTART", 1)

    released = budget_service.release(reservation.reservation_id)

    assert released.state == "RELEASED"
    assert budget_service.remaining_batch_earmark("batch-1") == 6
