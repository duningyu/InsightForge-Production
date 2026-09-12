from fastapi.testclient import TestClient

from app.main import create_app
from surface_fixtures import complete_solution_payload


def _create_project(client: TestClient) -> str:
    response = client.post(
        "/api/projects",
        json={
            "title": "Idempotency acceptance project",
            "summary": "A project used to verify durable generation replay.",
        },
    )
    assert response.status_code in (200, 201), response.text
    payload = response.json()
    return payload.get("id") or payload["project_id"]


def _timeout_result():
    return {
        "error_code": "MODEL_TIMEOUT",
        "message": "AI service timeout; input preserved.",
        "recovery_actions": ["retry"],
        "preserved_input": None,
    }


def _success_result():
    return complete_solution_payload()


def test_same_intent_after_timeout_across_app_restart_calls_provider_once(tmp_path):
    database_path = tmp_path / "durable-idempotency.sqlite3"
    first_app = create_app(database_path=str(database_path), seed=False)
    calls = []

    with TestClient(first_app) as first_client:
        project_id = _create_project(first_client)
        first_app.state.solution_design.generate = lambda *args, **kwargs: (
            calls.append("provider") or _timeout_result()
        )
        first_response = first_client.post(
            f"/api/projects/{project_id}/solutions/generate",
            headers={"X-Idempotency-Key": "intent-timeout-replay-001"},
        )
        assert first_response.status_code == 503

    second_app = create_app(database_path=str(database_path), seed=False)
    with TestClient(second_app) as second_client:
        second_app.state.solution_design.generate = lambda *args, **kwargs: (
            calls.append("provider") or _timeout_result()
        )
        replay_response = second_client.post(
            f"/api/projects/{project_id}/solutions/generate",
            headers={"X-Idempotency-Key": "intent-timeout-replay-001"},
        )

    assert replay_response.status_code == 503
    assert calls == ["provider"]


def test_same_success_intent_after_app_restart_does_not_call_provider_again(tmp_path):
    database_path = tmp_path / "durable-success-idempotency.sqlite3"
    first_app = create_app(database_path=str(database_path), seed=False)
    calls = []

    with TestClient(first_app) as first_client:
        project_id = _create_project(first_client)
        first_app.state.solution_design.generate = lambda *args, **kwargs: (
            calls.append("provider") or _success_result()
        )
        first_response = first_client.post(
            f"/api/projects/{project_id}/solutions/generate",
            headers={"X-Idempotency-Key": "intent-success-replay-001"},
        )
        assert first_response.status_code == 201

    second_app = create_app(database_path=str(database_path), seed=False)
    with TestClient(second_app) as second_client:
        second_app.state.solution_design.generate = lambda *args, **kwargs: (
            calls.append("provider") or _success_result()
        )
        replay_response = second_client.post(
            f"/api/projects/{project_id}/solutions/generate",
            headers={"X-Idempotency-Key": "intent-success-replay-001"},
        )

    assert replay_response.status_code == 201
    assert replay_response.json() == first_response.json()
    assert calls == ["provider"]


def test_same_key_is_scoped_to_participant_and_project(tmp_path):
    database_path = tmp_path / "durable-scope.sqlite3"
    first_app = create_app(database_path=str(database_path), seed=False)

    with TestClient(first_app) as client:
        project_a = _create_project(client)
        project_b = _create_project(client)
        guard = first_app.state.solution_generation_guard
        first = guard.begin("participant-a", project_a, "same-uuid")
        second = guard.begin("participant-b", project_a, "same-uuid")
        third = guard.begin("participant-a", project_b, "same-uuid")

    assert first.owner is True
    assert second.owner is True
    assert third.owner is True


def test_in_progress_replay_is_blocked_across_guard_instances(tmp_path):
    database_path = tmp_path / "durable-in-progress.sqlite3"
    first_app = create_app(database_path=str(database_path), seed=False)
    with TestClient(first_app) as client:
        project_id = _create_project(client)
        first_guard = first_app.state.solution_generation_guard
        assert first_guard.begin("participant-a", project_id, "same-intent").owner

    second_app = create_app(database_path=str(database_path), seed=False)
    with TestClient(second_app):
        replay = second_app.state.solution_generation_guard.begin(
            "participant-a", project_id, "same-intent"
        )

    assert replay.owner is False
    assert replay.error_code == "SOLUTION_GENERATION_IN_PROGRESS"
    assert replay.status_code == 409


def test_explicit_retry_uses_a_new_intent_after_terminal_failure(tmp_path):
    database_path = tmp_path / "durable-explicit-retry.sqlite3"
    app = create_app(database_path=str(database_path), seed=False)
    with TestClient(app) as client:
        project_id = _create_project(client)
        guard = app.state.solution_generation_guard
        assert guard.begin("participant-a", project_id, "intent-a").owner
        guard.complete(
            "participant-a", project_id, "intent-a", _timeout_result(), status_code=503
        )
        retry = guard.begin("participant-a", project_id, "intent-b")

    assert retry.owner is True


def test_durable_intent_tracks_one_provider_call_and_one_quota_reservation(tmp_path):
    database_path = tmp_path / "durable-ledger.sqlite3"
    app = create_app(database_path=str(database_path), seed=False)
    with TestClient(app) as client:
        project_id = _create_project(client)
        guard = app.state.solution_generation_guard
        assert guard.begin("participant-a", project_id, "intent-ledger").owner
        guard.mark_provider_call("participant-a", project_id, "intent-ledger")
        guard.complete(
            "participant-a", project_id, "intent-ledger", _timeout_result(), status_code=503
        )
        guard.begin("participant-a", project_id, "intent-ledger")

    with app.state.db.connect() as connection:
        row = connection.execute(
            """
            SELECT request_count, replay_count, provider_call_count,
                   quota_reservation_id, status
            FROM solution_generation_intents
            WHERE participant_id = ? AND project_id = ? AND idempotency_key = ?
            """,
            ("participant-a", project_id, "intent-ledger"),
        ).fetchone()

    assert tuple(row) == (2, 1, 1, row[3], "FAILED")
    assert row[3]
