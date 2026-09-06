"""Open-test policy: no daily cap, but settlement remains authoritative."""
import socket

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.services.beta_usage import BetaUsageService


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    original_connect = socket.socket.connect
    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] in {"127.0.0.1", "::1"}:
            return original_connect(sock, address)
        raise AssertionError("External network is forbidden in open-test regression")
    def denied(*args, **kwargs):
        raise AssertionError("External network is forbidden in open-test regression")
    monkeypatch.setattr(socket.socket, "connect", local_only)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.mark.parametrize("operation,count", [("solution_generation", 12), ("evidence_analysis", 22)])
def test_default_policy_has_no_daily_cap_and_records_committed_usage(tmp_path, operation, count):
    db = Database(tmp_path / "isolated.sqlite3")
    db.init_schema()
    usage = BetaUsageService(db, participant_id="beta_004", beta_mode=True)
    for _ in range(count):
        decision = usage.consume(operation)
        usage.commit(decision)
        usage.commit(decision)
    assert decision.limit is None
    assert decision.used == count
    assert db.fetch_one("SELECT request_count FROM beta_daily_usage")["request_count"] == count
    assert db.fetch_one("SELECT COUNT(*) n FROM beta_quota_reservations WHERE state='COMMITTED'")["n"] == count


def test_unlimited_release_is_idempotent_without_erasing_prior_usage(tmp_path):
    db = Database(tmp_path / "isolated.sqlite3")
    db.init_schema()
    usage = BetaUsageService(db, participant_id="beta_005", beta_mode=True)
    success = usage.consume("solution_generation")
    usage.commit(success)
    failure = usage.consume("solution_generation")
    usage.release(failure)
    usage.release(failure)
    usage.commit(failure)
    assert db.fetch_one("SELECT request_count FROM beta_daily_usage")["request_count"] == 1
    assert db.fetch_one("SELECT state FROM beta_quota_reservations WHERE reservation_id=?", (failure.reservation_id,))["state"] == "RELEASED"


def test_api_discloses_disabled_policy_without_zero_remaining(tmp_path, monkeypatch):
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", "beta_004")
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("BETA_MANAGED_MODE", "false")
    monkeypatch.delenv("INSIGHTFORGE_DAILY_USER_LIMITS_ENABLED", raising=False)
    with TestClient(create_app(database_path=tmp_path / "test.sqlite3", seed=False)) as client:
        response = client.get("/api/usage/policy")
        assert response.status_code == 200
        assert response.json()["daily_user_limits_enabled"] is False
        assert response.json()["operations"]["solution_generation"]["limit"] is None
        assert response.json()["operations"]["evidence_analysis"]["remaining"] is None
