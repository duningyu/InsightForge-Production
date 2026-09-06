"""Open-test policy: no daily cap, but settlement remains authoritative."""
import socket

import pytest
from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app
from app.services.beta_usage import BetaUsageService
from app.config import Settings
from pathlib import Path


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


def test_open_test_target_example_overrides_old_limits_without_secret_or_production_access(tmp_path, monkeypatch):
    monkeypatch.setenv("INSIGHTFORGE_DAILY_USER_LIMITS_ENABLED", "true")
    example = Path(__file__).resolve().parents[1] / "deploy/beta/open-test.env.example"
    values = dict(line.split("=", 1) for line in example.read_text().splitlines()
                  if line.strip() and not line.startswith("#"))
    assert set(values) == {"INSIGHTFORGE_ACCOUNTS_ENABLED", "INSIGHTFORGE_ACCOUNTS_DIR",
                           "INSIGHTFORGE_DAILY_USER_LIMITS_ENABLED", "BETA_SESSION_COOKIE_SECURE"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    target = Settings.from_env()
    assert target.accounts_enabled and target.beta_session_cookie_secure
    assert not target.daily_user_limits_enabled
    assert target.accounts_dir == Path(values["INSIGHTFORGE_ACCOUNTS_DIR"])
    # Redirect persistence BEFORE constructing any application; never touch target path.
    monkeypatch.setenv("INSIGHTFORGE_ACCOUNTS_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("BETA_SESSION_COOKIE_SECURE", "false")
    app = create_app(seed=False, settings_override=Settings.from_env())
    with TestClient(app, headers={"X-InsightForge-Request": "1"}) as client:
        invitation = app.state.accounts.issue_invite()
        assert client.post("/api/auth/claim", json={"invite": invitation, "username": "target-test",
                           "password": "SYNTHETIC-only-passphrase!"}).status_code == 201
        assert client.post("/api/auth/login", json={"username": "target-test",
                           "password": "SYNTHETIC-only-passphrase!"}).status_code == 200
        policy = client.get("/api/usage/policy").json()
        assert policy["daily_user_limits_enabled"] is False
        assert all(item["remaining"] is None and item["limit"] is None
                   for item in policy["operations"].values())
