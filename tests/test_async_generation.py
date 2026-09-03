from __future__ import annotations

import time

from app.db import Database
from app.services.async_generation import AsyncGenerationRepository, AsyncGenerationWorker


def repo(tmp_path):
    db = Database(tmp_path / "async.sqlite")
    db.init_schema()
    return db, AsyncGenerationRepository(db)


def test_same_intent_replay_is_one_durable_run(tmp_path):
    db, repository = repo(tmp_path)
    first = repository.create_or_replay("beta001", "project-a", "intent-a", resolved_model_id="glm-5.2")
    replay = repository.create_or_replay("beta001", "project-a", "intent-a", resolved_model_id="glm-5.2")

    assert first.generation_run_id == replay.generation_run_id
    assert first.generation_intent_id == replay.generation_intent_id
    assert replay.request_count == 2
    assert replay.replay_count == 1
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM solution_generation_intents").fetchone()[0] == 1


def test_same_intent_model_change_is_rejected(tmp_path):
    _, repository = repo(tmp_path)
    repository.create_or_replay("beta001", "project-a", "intent-a", resolved_model_id="glm-5.2")
    try:
        repository.create_or_replay("beta001", "project-a", "intent-a", resolved_model_id="qwen3.7-flash")
    except ValueError as error:
        assert str(error) == "IDEMPOTENCY_MODEL_MISMATCH"
    else:
        raise AssertionError("model change must require a new intent")


def test_failed_terminal_replay_does_not_claim_or_call_again(tmp_path):
    _, repository = repo(tmp_path)
    first = repository.create_or_replay("beta001", "project-a", "intent-a")
    claimed = repository.claim_next()
    assert claimed and claimed.generation_run_id == first.generation_run_id
    repository.mark_provider_call(first.generation_run_id)
    repository.finish(first.generation_run_id, {"error_code": "PROVIDER_TIMEOUT"}, status_code=503)

    replay = repository.create_or_replay("beta001", "project-a", "intent-a")
    assert replay.status == "FAILED"
    assert replay.provider_call_count == 1
    assert repository.claim_next() is None


def test_worker_executes_each_run_once_and_persists_success(tmp_path):
    _, repository = repo(tmp_path)
    run = repository.create_or_replay("beta001", "project-a", "intent-a")
    calls = []
    worker = AsyncGenerationWorker(repository, lambda item: calls.append(item.generation_run_id) or {"candidates": [{"id": "c1"}]}, poll_seconds=0.01)
    worker.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline and repository.get("beta001", "project-a", run.generation_run_id).status != "SUCCEEDED":
            time.sleep(0.01)
    finally:
        worker.stop()
    completed = repository.get("beta001", "project-a", run.generation_run_id)
    assert calls == [run.generation_run_id]
    assert completed.status == "SUCCEEDED"
    assert completed.provider_call_count == 1


def test_worker_persists_empty_candidates_as_controlled_failure(tmp_path):
    _, repository = repo(tmp_path)
    run = repository.create_or_replay("beta001", "project-a", "intent-empty")
    worker = AsyncGenerationWorker(repository, lambda item: {"candidates": []}, poll_seconds=0.01)
    worker.start()
    try:
        deadline = time.time() + 2
        while time.time() < deadline:
            current = repository.get("beta001", "project-a", run.generation_run_id)
            if current.status == "FAILED":
                break
            time.sleep(0.01)
    finally:
        worker.stop()
    completed = repository.get("beta001", "project-a", run.generation_run_id)
    assert completed.status == "FAILED"
    assert completed.status_code == 503


def test_same_key_isolated_by_participant_and_project(tmp_path):
    _, repository = repo(tmp_path)
    a = repository.create_or_replay("beta001", "project-a", "same-key")
    b = repository.create_or_replay("beta002", "project-a", "same-key")
    c = repository.create_or_replay("beta001", "project-b", "same-key")
    assert len({a.generation_run_id, b.generation_run_id, c.generation_run_id}) == 3
