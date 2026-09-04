from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import Database
from app.services.async_generation import AsyncGenerationRepository
from app.services.provider_acceptance_authorization import (
    ProviderAcceptanceAuthorizationRepository,
)


def _expires() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()


def _setup(tmp_path):
    db = Database(tmp_path / "server-auth.sqlite3")
    db.init_schema()
    auth = ProviderAcceptanceAuthorizationRepository(db)
    repo = AsyncGenerationRepository(db)
    return db, auth, repo


def test_server_redeems_single_use_authorization_and_persists_execution(tmp_path):
    db, auth, repo = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test", expires_at=_expires(), created_by="test",
    )

    run = repo.redeem_authorization_and_create(
        authorization_id=issued.authorization_id, participant_id="participant-1",
        project_id="project-1", actor_scope="operator-1", idempotency_key="acceptance-1",
        requested_model_preference="qwen", resolved_model_family="qwen",
        resolved_model_id="qwen3.7-flash",
    )

    assert run.acceptance_authorization_id == issued.authorization_id
    assert run.dispatch_control is not None
    assert run.dispatch_control.acceptance_execution_id
    assert run.dispatch_control.expected_provider == "bailian"
    assert run.dispatch_control.expected_model == "qwen3.7-flash"
    assert auth.get(issued.authorization_id).state == "REDEEMED"
    assert auth.get(issued.authorization_id).acceptance_execution_id == run.dispatch_control.acceptance_execution_id

    with db.connect() as connection:
        row = connection.execute(
            "SELECT acceptance_authorization_id, acceptance_execution_id FROM async_solution_generation_runs WHERE generation_run_id=?",
            (run.generation_run_id,),
        ).fetchone()
    assert row["acceptance_authorization_id"] == issued.authorization_id
    assert row["acceptance_execution_id"] == run.dispatch_control.acceptance_execution_id


def test_redeemed_authorization_cannot_create_second_run(tmp_path):
    _, auth, repo = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test", expires_at=_expires(), created_by="test",
    )
    repo.redeem_authorization_and_create(
        authorization_id=issued.authorization_id, participant_id="participant-1",
        project_id="project-1", actor_scope="operator-1", idempotency_key="acceptance-1",
        requested_model_preference="qwen", resolved_model_family="qwen", resolved_model_id="qwen3.7-flash",
    )

    with pytest.raises(ValueError, match="NOT_REDEEMABLE"):
        repo.redeem_authorization_and_create(
            authorization_id=issued.authorization_id, participant_id="participant-1",
            project_id="project-1", actor_scope="operator-1", idempotency_key="acceptance-2",
            requested_model_preference="qwen", resolved_model_family="qwen", resolved_model_id="qwen3.7-flash",
        )


def test_authorization_scope_and_target_are_server_enforced(tmp_path):
    _, auth, repo = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test", expires_at=_expires(), created_by="test",
    )
    with pytest.raises(ValueError, match="SCOPE_MISMATCH"):
        repo.redeem_authorization_and_create(
            authorization_id=issued.authorization_id, participant_id="participant-1",
            project_id="project-1", actor_scope="other-actor", idempotency_key="acceptance-1",
            requested_model_preference="qwen", resolved_model_family="qwen", resolved_model_id="qwen3.7-flash",
        )


def test_reconstructed_repository_replays_same_durable_context(tmp_path):
    db, auth, repo = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test", expires_at=_expires(), created_by="test",
    )
    first = repo.redeem_authorization_and_create(
        authorization_id=issued.authorization_id, participant_id="participant-1",
        project_id="project-1", actor_scope="operator-1", idempotency_key="acceptance-1",
        requested_model_preference="qwen", resolved_model_family="qwen", resolved_model_id="qwen3.7-flash",
    )
    reconstructed = AsyncGenerationRepository(db).get("participant-1", "project-1", first.generation_run_id)
    assert reconstructed.dispatch_control.acceptance_execution_id == first.dispatch_control.acceptance_execution_id


def test_authorization_evidence_has_no_secret_fields(tmp_path):
    db, auth, _ = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test", expires_at=_expires(), created_by="test",
    )
    with db.connect() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(provider_acceptance_authorizations)")}
    assert {"api_key", "authorization", "password", "secret"}.isdisjoint(columns)
    assert "secret" not in repr(issued).casefold()
    assert "api_key" not in repr(issued).casefold()


def test_expired_authorization_cannot_be_redeemed(tmp_path):
    _, auth, repo = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test",
        expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        created_by="test",
    )
    with pytest.raises(ValueError, match="ACCEPTANCE_AUTHORIZATION_EXPIRED"):
        repo.redeem_authorization_and_create(
            authorization_id=issued.authorization_id, participant_id="participant-1",
            project_id="project-1", actor_scope="operator-1", idempotency_key="expired",
            requested_model_preference="qwen", resolved_model_family="qwen",
            resolved_model_id="qwen3.7-flash",
        )


def test_no_public_authorization_issuance_route_exists(tmp_path):
    from app.main import create_app

    application = create_app(database_path=tmp_path / "routes.sqlite3", seed=False)
    routes = {
        (route.path, method)
        for route in application.routes
        for method in getattr(route, "methods", set())
    }
    assert not any("acceptance" in path.casefold() and method == "POST" for path, method in routes)


def test_concurrent_redemption_allows_one_execution_only(tmp_path):
    _, auth, repo = _setup(tmp_path)
    issued = auth.issue_pending(
        project_id="project-1", actor_scope="operator-1",
        forward_ledger_epoch_id="epoch-test", expires_at=_expires(), created_by="test",
    )

    def redeem(key):
        try:
            run = repo.redeem_authorization_and_create(
                authorization_id=issued.authorization_id, participant_id="participant-1",
                project_id="project-1", actor_scope="operator-1", idempotency_key=key,
                requested_model_preference="qwen", resolved_model_family="qwen",
                resolved_model_id="qwen3.7-flash",
            )
            return ("ok", run.generation_run_id)
        except ValueError as error:
            return ("error", str(error))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(redeem, ("concurrent-a", "concurrent-b")))
    assert [result[0] for result in results].count("ok") == 1
    assert [result[0] for result in results].count("error") == 1
