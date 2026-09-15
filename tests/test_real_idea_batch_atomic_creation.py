from __future__ import annotations

import json

import pytest

from app.db import Database
from app.services.real_idea_budget import (
    BATCH_EARMARK,
    BOUND,
    EXTENSION_CREDITS,
    EXTENSION_ID,
    UNBOUND_RESTRICTED,
    RealIdeaBudgetService,
)
from app.services.real_idea_evaluation import RealIdeaEvaluationService


def test_create_batch_with_slots_is_atomic_and_freezes_empty_manifest(tmp_path):
    database = Database(tmp_path / "real-idea-atomic.db")
    database.init_schema()
    budget = RealIdeaBudgetService(database, durable_budget=6)
    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)
    service = RealIdeaEvaluationService(database, durable_budget=6)

    batch = service.create_batch_with_slots(
        batch_id="REAL_IDEA_BATCH_01",
        source_commit="candidate-sha",
        deployment_id="deployment-id",
    )

    assert batch.batch_id == "REAL_IDEA_BATCH_01"
    assert service.read_batch(batch.batch_id).status == "CREATED"

    with database.connect() as connection:
        samples = connection.execute(
            "SELECT * FROM real_idea_samples WHERE batch_id = ? ORDER BY sample_key",
            (batch.batch_id,),
        ).fetchall()
        stored_batch = connection.execute(
            "SELECT * FROM real_idea_batches WHERE batch_id = ?",
            (batch.batch_id,),
        ).fetchone()

    assert [row["sample_key"] for row in samples] == [
        "REAL_IDEA_01",
        "REAL_IDEA_02",
        "REAL_IDEA_03",
    ]
    assert all(row["state"] == "CREATED" for row in samples)
    assert all(row["project_id"] is None for row in samples)
    assert all(row["raw_idea_sha256"] for row in samples)
    assert all(row["budget_allocation_id"] for row in samples)

    manifest = json.loads(stored_batch["safe_counts_json"])
    assert stored_batch["source_commit"] == "candidate-sha"
    assert stored_batch["deployment_id"] == "deployment-id"
    assert stored_batch["manifest_sha256"]
    assert manifest["batch_id"] == "REAL_IDEA_BATCH_01"
    assert manifest["budget_extension_id"] == EXTENSION_ID
    assert manifest["sample_hard_cap"] == 2
    assert manifest["batch_hard_cap"] == BATCH_EARMARK
    assert manifest["search"] is False

    extension = budget.inspect_extension()
    assert extension["state"] == BOUND
    assert extension["bound_batch_id"] == batch.batch_id
    assert budget.accounting_summary() == {
        "authorized_total": 9,
        "general_spendable": 3,
        "restricted_unbound": 0,
        "bound_allocation": 6,
        "safe_ceiling": 8,
    }

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM real_idea_budget_allocations WHERE batch_id = ?",
            (batch.batch_id,),
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT batch_earmark FROM real_idea_budget_allocations WHERE batch_id = ?",
            (batch.batch_id,),
        ).fetchone()[0] == 6
        assert connection.execute(
            "SELECT COUNT(*) FROM real_idea_transport_reservations"
        ).fetchone()[0] == 0


def test_create_batch_with_slots_rejects_wrong_extension_before_mutation(tmp_path):
    database = Database(tmp_path / "real-idea-atomic-wrong-extension.db")
    database.init_schema()
    budget = RealIdeaBudgetService(database, durable_budget=6)
    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)
    service = RealIdeaEvaluationService(database, durable_budget=6)

    with pytest.raises(ValueError):
        service.create_batch_with_slots(
            batch_id="REAL_IDEA_BATCH_01",
            source_commit="candidate-sha",
            deployment_id="deployment-id",
            extension_id="WRONG_EXTENSION",
        )

    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM real_idea_batches").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM real_idea_samples").fetchone()[0] == 0

    extension = budget.inspect_extension()
    assert extension["state"] == UNBOUND_RESTRICTED
    assert extension["bound_batch_id"] is None
    assert budget.accounting_summary() == {
        "authorized_total": 9,
        "general_spendable": 6,
        "restricted_unbound": 3,
        "bound_allocation": 0,
        "safe_ceiling": 8,
    }


def test_create_batch_with_slots_rejects_already_bound_extension_before_mutation(tmp_path):
    database = Database(tmp_path / "real-idea-atomic-bound-extension.db")
    database.init_schema()
    budget = RealIdeaBudgetService(database, durable_budget=6)
    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)
    service = RealIdeaEvaluationService(database, durable_budget=6)

    # Use the existing lifecycle service only to create an isolated conflicting
    # binding; the fixed Batch creation path must fail closed before touching
    # REAL_IDEA_BATCH_01.
    service.start_batch("OTHER_BATCH")

    with pytest.raises(ValueError, match="not unbound"):
        service.create_batch_with_slots(
            batch_id="REAL_IDEA_BATCH_01",
            source_commit="candidate-sha",
            deployment_id="deployment-id",
        )

    with database.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM real_idea_batches WHERE batch_id = ?",
            ("REAL_IDEA_BATCH_01",),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM real_idea_samples WHERE batch_id = ?",
            ("REAL_IDEA_BATCH_01",),
        ).fetchone()[0] == 0
    extension = budget.inspect_extension()
    assert extension["state"] == BOUND
    assert extension["bound_batch_id"] == "OTHER_BATCH"


def _assert_atomic_rollback(database, budget):
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM real_idea_batches").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM real_idea_samples").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM real_idea_budget_allocations").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM real_idea_transport_reservations").fetchone()[0] == 0
    extension = budget.inspect_extension()
    assert extension["state"] == UNBOUND_RESTRICTED
    assert extension["bound_batch_id"] is None
    assert budget.accounting_summary() == {
        "authorized_total": 9,
        "general_spendable": 6,
        "restricted_unbound": 3,
        "bound_allocation": 0,
        "safe_ceiling": 8,
    }


def _new_atomic_fixture(tmp_path, name):
    database = Database(tmp_path / f"{name}.db")
    database.init_schema()
    budget = RealIdeaBudgetService(database, durable_budget=6)
    budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)
    return database, budget, RealIdeaEvaluationService(database, durable_budget=6)


def test_sample_creation_failure_rolls_back_everything(tmp_path, monkeypatch):
    database, budget, service = _new_atomic_fixture(tmp_path, "sample-failure")
    import app.services.real_idea_evaluation as evaluation_module

    monkeypatch.delitem(evaluation_module.SAMPLE_SOURCE_TYPES, "REAL_IDEA_03")
    with pytest.raises(KeyError):
        service.create_batch_with_slots(
            batch_id="REAL_IDEA_BATCH_01",
            source_commit="candidate-sha",
            deployment_id="deployment-id",
        )
    _assert_atomic_rollback(database, budget)


def test_manifest_failure_rolls_back_everything(tmp_path, monkeypatch):
    database, budget, service = _new_atomic_fixture(tmp_path, "manifest-failure")

    def fail_freeze(connection, batch_id, manifest):
        raise RuntimeError("injected manifest failure")

    monkeypatch.setattr(service, "_freeze_batch_manifest_tx", fail_freeze)
    with pytest.raises(RuntimeError, match="injected manifest failure"):
        service.create_batch_with_slots(
            batch_id="REAL_IDEA_BATCH_01",
            source_commit="candidate-sha",
            deployment_id="deployment-id",
        )
    _assert_atomic_rollback(database, budget)


def test_earmark_failure_rolls_back_everything(tmp_path, monkeypatch):
    database, budget, service = _new_atomic_fixture(tmp_path, "earmark-failure")

    def fail_earmark(connection, batch_id, amount):
        raise RuntimeError("injected earmark failure")

    monkeypatch.setattr(service.budget, "_earmark_batch_tx", fail_earmark)
    with pytest.raises(RuntimeError, match="injected earmark failure"):
        service.create_batch_with_slots(
            batch_id="REAL_IDEA_BATCH_01",
            source_commit="candidate-sha",
            deployment_id="deployment-id",
        )
    _assert_atomic_rollback(database, budget)


def test_duplicate_creation_is_idempotent_without_second_bind_or_earmark(tmp_path):
    database, budget, service = _new_atomic_fixture(tmp_path, "duplicate")
    first = service.create_batch_with_slots(
        batch_id="REAL_IDEA_BATCH_01",
        source_commit="candidate-sha",
        deployment_id="deployment-id",
    )
    second = service.create_batch_with_slots(
        batch_id="REAL_IDEA_BATCH_01",
        source_commit="candidate-sha",
        deployment_id="deployment-id",
    )
    assert first == second
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM real_idea_batches").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM real_idea_samples").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM real_idea_budget_allocations").fetchone()[0] == 1
    assert budget.inspect_extension()["state"] == BOUND
    assert budget.accounting_summary()["bound_allocation"] == 6


def test_fixed_empty_slot_is_reused_by_the_existing_sample_lifecycle(tmp_path):
    database, budget, service = _new_atomic_fixture(tmp_path, "slot-reuse")
    service.create_batch_with_slots(
        batch_id="REAL_IDEA_BATCH_01",
        source_commit="candidate-sha",
        deployment_id="deployment-id",
    )

    sample = service.start_sample(
        "REAL_IDEA_BATCH_01",
        "A real idea that is intentionally isolated to the temporary test database.",
    )

    assert sample.sample_id == "REAL_IDEA_01"
    assert sample.sample_key == "REAL_IDEA_01"
    with database.connect() as connection:
        rows = connection.execute(
            "SELECT sample_id, sample_key, state, project_id FROM real_idea_samples "
            "WHERE batch_id = ? ORDER BY sample_key",
            ("REAL_IDEA_BATCH_01",),
        ).fetchall()
    assert [row["sample_key"] for row in rows] == [
        "REAL_IDEA_01",
        "REAL_IDEA_02",
        "REAL_IDEA_03",
    ]
    assert rows[0]["state"] == "QUICKSTART_PENDING"
    assert rows[0]["project_id"] is not None
    assert budget.accounting_summary()["bound_allocation"] == 6
