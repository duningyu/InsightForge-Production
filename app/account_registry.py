"""Operator-issued account claims and revocable opaque sessions.

Only this registry chooses database/runtime locations. No client-selected paths.
Passwords use OpenSSL scrypt, not a bespoke password hashing algorithm.
"""
from contextlib import contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768,
                          r=8, p=1, maxmem=64 * 1024 * 1024).hex()


def validate_legacy_schema(database):
    """Read-only structural floor: repository v206 and its additive successors.

    This is admission validation, not migration or proof of arbitrary historical
    schema compatibility. The old writer must be stopped before binding.
    """
    tables = {
        "projects", "project_canvas", "project_canvas_versions", "sources",
        "source_chunks", "documents", "document_versions", "generation_runs",
        "validation_issues", "guided_sessions", "guided_messages", "project_decisions",
        "retrieval_runs", "retrieval_hits", "document_claims", "claim_evidence_links",
        "handoff_runs", "audit_events",
    }
    required = {
        "projects": {"id", "title", "summary", "status", "created_at", "updated_at"},
        "documents": {"id", "project_id", "doc_type", "title", "created_at"},
        "document_versions": {"id", "document_id", "project_id", "doc_type", "version",
                              "status", "content", "created_at"},
        "sources": {"id", "project_id", "content", "source_type", "sha256"},
    }
    try:
        db = sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)
        try:
            actual = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not tables <= actual:
                raise ValueError("Unsupported legacy schema: required tables missing")
            for table, columns in required.items():
                present = {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
                if not columns <= present:
                    raise ValueError("Unsupported legacy schema: required columns missing")
        finally:
            db.close()
    except sqlite3.DatabaseError:
        raise ValueError("Unsupported legacy schema: invalid SQLite database") from None


def same_location(first, second):
    if not first or not second:
        return False
    a, b = Path(first), Path(second)
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and a.samefile(b))


def ensure_unbound(db, database, runtime, participant, *, exclude_invite=None):
    rows = db.execute("SELECT database_path, runtime_path, participant FROM accounts").fetchall()
    rows += db.execute("SELECT database_path, runtime_path, participant FROM invites "
                       "WHERE hash != ?", (exclude_invite or "",)).fetchall()
    for row in rows:
        if (same_location(database, row["database_path"]) or
                same_location(runtime, row["runtime_path"]) or participant == row["participant"]):
            raise ValueError("Legacy ownership already bound")


class AccountRegistry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    salt TEXT NOT NULL, password_hash TEXT NOT NULL,
                    database_path TEXT UNIQUE NOT NULL, runtime_path TEXT UNIQUE NOT NULL,
                    participant TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS invites (
                    hash TEXT PRIMARY KEY, expires REAL NOT NULL, claimed_by TEXT,
                    database_path TEXT UNIQUE, runtime_path TEXT UNIQUE, participant TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS sessions (
                    hash TEXT PRIMARY KEY, account_id TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS login_attempts (
                    bucket TEXT PRIMARY KEY, started REAL NOT NULL, failures INTEGER NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / "accounts.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def issue_invite(self, *, legacy_binding=None):
        """Operator-only service. Never exposed by a public HTTP endpoint.

        legacy_binding must explicitly name the old DB, runtime and participant;
        the operator must stop the old writer before activating that binding.
        No migration/copy, first-registration adoption or inferred ownership.
        """
        database = runtime = participant = None
        if legacy_binding is not None:
            database = str(Path(legacy_binding["database_path"]).resolve())
            runtime = str(Path(legacy_binding["runtime_path"]).resolve())
            participant = legacy_binding["participant"]
            if not Path(database).is_file() or not Path(runtime).is_dir():
                raise ValueError("Explicit legacy paths must already exist")
            if not re.fullmatch(r"beta_[0-9]{3}", participant):
                raise ValueError("Explicit legacy participant required")
            validate_legacy_schema(database)
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if database:
                ensure_unbound(db, database, runtime, participant)
            db.execute("INSERT INTO invites VALUES (?, ?, NULL, ?, ?, ?)",
                       (digest(token), time.time() + 86400, database, runtime, participant))
        return token

    def revoke_invite(self, token):
        """Operator-only, idempotent revocation; retain the original invite row.

        Revoking a claimed invite does not revoke its owner's account/session.
        """
        with self.connect() as db:
            db.execute("UPDATE invites SET expires=MIN(expires, ?) WHERE hash=? AND claimed_by IS NULL",
                       (time.time(), digest(token)))

    def claim(self, token, username, password):
        username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username) or not 12 <= len(password) <= 128:
            raise ValueError("账号需为3–64位字母或数字，密码需为12–128位")
        salt = secrets.token_hex(16)
        hashed = password_hash(password, salt)
        identity = "user_" + uuid.uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            invite = db.execute("SELECT * FROM invites WHERE hash=? AND claimed_by IS NULL AND expires>?",
                                (digest(token), time.time())).fetchone()
            if not invite:
                raise ValueError("邀请无效、已领取或已过期")
            if invite["database_path"]:
                validate_legacy_schema(invite["database_path"])
                ensure_unbound(db, invite["database_path"], invite["runtime_path"],
                               invite["participant"], exclude_invite=digest(token))
            workspace = self.root / "workspaces" / identity
            try:
                db.execute("INSERT INTO accounts VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (identity, username, salt, hashed,
                            invite["database_path"] or str(workspace / "data.sqlite3"),
                            invite["runtime_path"] or str(workspace / "runtime"),
                            invite["participant"] or identity))
            except sqlite3.IntegrityError:
                raise ValueError("账号或工作空间已被领取") from None
            db.execute("UPDATE invites SET claimed_by=? WHERE hash=?", (identity, digest(token)))
        return identity

    def login(self, username, password):
        username = username.strip().lower()
        if len(password) > 128 or len(username) > 64:
            return None
        now = time.time()
        bucket = digest(username)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM login_attempts WHERE bucket=?", (bucket,)).fetchone()
            if attempt and now - attempt["started"] < 300 and attempt["failures"] >= 10:
                return None
            account = db.execute("SELECT * FROM accounts WHERE username=?", (username,)).fetchone()
            salt = account["salt"] if account else "00" * 16
            actual = password_hash(password, salt)
            valid = hmac.compare_digest(actual, account["password_hash"] if account else "0" * 128)
            if not account or not valid:
                count = attempt["failures"] + 1 if attempt and now - attempt["started"] < 300 else 1
                started = attempt["started"] if count > 1 else now
                db.execute("INSERT OR REPLACE INTO login_attempts VALUES (?, ?, ?)", (bucket, started, count))
                return None
            db.execute("DELETE FROM login_attempts WHERE bucket=?", (bucket,))
            token = secrets.token_urlsafe(32)
            db.execute("DELETE FROM sessions WHERE expires<=?", (now,))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest(token), account["id"], now + 1800))
        return token

    def session(self, token):
        with self.connect() as db:
            row = db.execute("SELECT accounts.* FROM sessions JOIN accounts ON accounts.id=sessions.account_id "
                             "WHERE sessions.hash=? AND sessions.expires>?", (digest(token), time.time())).fetchone()
            if row:
                db.execute("UPDATE sessions SET expires=? WHERE hash=?", (time.time() + 1800, digest(token)))
            return dict(row) if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE hash=?", (digest(token),))
