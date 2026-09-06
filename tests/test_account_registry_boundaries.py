"""Synthetic registry boundary regressions; never open production data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from app.account_registry import AccountRegistry
from app.db import Database

PASSWORD = "SYNTHETIC-only-passphrase!"


def legacy(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript((Path(__file__).parent / "fixtures/v206_schema.sql").read_text())
        db.execute("INSERT INTO projects VALUES ('same-id','Synthetic legacy','preserved','active','t','t')")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    return dict(database_path=path, runtime_path=runtime, participant="beta_003")


@pytest.mark.parametrize("kind", ["empty", "unrelated", "truncated"])
def test_unsupported_legacy_schema_rejected_without_writes(tmp_path, kind):
    registry = AccountRegistry(tmp_path / "accounts")
    binding = legacy(tmp_path)
    with sqlite3.connect(binding["database_path"]) as db:
        if kind == "truncated":
            db.execute("DROP TABLE document_versions")
        else:
            for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                db.execute(f'DROP TABLE "{table}"')
            if kind == "unrelated":
                db.execute("CREATE TABLE unrelated (id TEXT)")
    before = binding["database_path"].read_bytes()
    with pytest.raises(ValueError, match="Unsupported legacy schema"):
        registry.issue_invite(legacy_binding=binding)
    assert binding["database_path"].read_bytes() == before


def test_physical_database_alias_cannot_be_bound_twice(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts")
    binding = legacy(tmp_path)
    token = registry.issue_invite(legacy_binding=binding)
    registry.claim(token, "owner-one", PASSWORD)
    alias = tmp_path / "hardlink.sqlite3"
    alias.hardlink_to(binding["database_path"])
    other_runtime = tmp_path / "other-runtime"
    other_runtime.mkdir()
    with pytest.raises(ValueError, match="already bound"):
        registry.issue_invite(legacy_binding=dict(database_path=alias,
                              runtime_path=other_runtime, participant="beta_004"))


def test_v206_explicit_binding_and_repeated_additive_migration(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts")
    binding = legacy(tmp_path)
    token = registry.issue_invite(legacy_binding=binding)
    registry.claim(token, "legacy-owner", PASSWORD)
    session = registry.login("legacy-owner", PASSWORD)
    owner = registry.session(session)
    assert owner["database_path"] == str(binding["database_path"].resolve())
    db = Database(Path(owner["database_path"]))
    db.init_schema()
    db.init_schema()
    assert db.fetch_one("SELECT title FROM projects WHERE id='same-id'") == {"title": "Synthetic legacy"}
    with pytest.raises(ValueError, match="already bound"):
        registry.issue_invite(legacy_binding=binding)


def test_revoke_invite_is_idempotent_and_retains_record(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts")
    token = registry.issue_invite()
    registry.revoke_invite(token)
    registry.revoke_invite(token)
    with pytest.raises(ValueError):
        registry.claim(token, "revoked-user", PASSWORD)
    with registry.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM invites").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 0


def test_concurrent_claim_has_one_owner(tmp_path):
    registry = AccountRegistry(tmp_path / "accounts")
    token = registry.issue_invite()
    def attempt(index):
        try:
            return registry.claim(token, f"claimant-{index}", PASSWORD)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, range(2)))
    assert sum(item is not None for item in result) == 1
    with registry.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_expired_invite_idle_session_and_logout(tmp_path, monkeypatch):
    now = [100000.0]
    monkeypatch.setattr("app.account_registry.time.time", lambda: now[0])
    registry = AccountRegistry(tmp_path / "accounts")
    expired = registry.issue_invite()
    now[0] += 86401
    with pytest.raises(ValueError):
        registry.claim(expired, "expired-user", PASSWORD)
    registry.claim(registry.issue_invite(), "valid-user", PASSWORD)
    token = registry.login("valid-user", PASSWORD)
    now[0] += 1799
    assert registry.session(token)
    now[0] += 1801
    assert registry.session(token) is None
    token = registry.login("valid-user", PASSWORD)
    registry.logout(token)
    assert registry.session(token) is None
