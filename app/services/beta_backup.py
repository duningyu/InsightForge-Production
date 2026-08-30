"""Participant-scoped SQLite snapshot and fail-closed restore operations."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.beta_runtime import validate_participant_id


class BetaBackupError(RuntimeError):
    """A stable fail-closed backup or restore error code."""


def _utc_now(clock: Callable[[], datetime] | None) -> datetime:
    value = (clock or (lambda: datetime.now(timezone.utc)))()
    if value.tzinfo is None:
        raise ValueError("backup clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _stamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H%M%SZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _participant_database(instances_root: str | Path, participant_id: str) -> Path:
    participant = validate_participant_id(participant_id)
    root = Path(instances_root).expanduser().resolve()
    directory = (root / participant).resolve()
    if directory.parent != root:
        raise BetaBackupError("PARTICIPANT_PATH_OUTSIDE_INSTANCES_ROOT")
    candidates = [
        path for path in (directory / "insightforge.db", directory / "insightforge.sqlite3")
        if path.is_file()
    ]
    if len(candidates) > 1:
        raise BetaBackupError("AMBIGUOUS_PARTICIPANT_DATABASE")
    if not candidates:
        raise BetaBackupError("PARTICIPANT_DATABASE_NOT_FOUND")
    return candidates[0]


def _database_checks(path: Path) -> dict[str, Any]:
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            schema_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            counts = {}
            for table in ("projects", "documents", "document_versions"):
                counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()
    except (sqlite3.DatabaseError, OSError) as exc:
        raise BetaBackupError("BACKUP_DATABASE_INVALID") from exc
    if integrity != "ok":
        raise BetaBackupError("SQLITE_INTEGRITY_CHECK_FAILED")
    if foreign_keys:
        raise BetaBackupError("SQLITE_FOREIGN_KEY_CHECK_FAILED")
    return {
        "integrity_check": integrity,
        "foreign_key_issue_count": len(foreign_keys),
        "schema_version": schema_version,
        "counts": counts,
    }


def _unique_backup_dir(output_dir: Path, participant_id: str, stamp: str) -> Path:
    base = output_dir.resolve() / participant_id / stamp
    candidate = base
    counter = 1
    while candidate.exists():
        counter += 1
        candidate = base.with_name(f"{base.name}-{counter}")
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def backup_participant(
    *,
    instances_root: str | Path,
    participant_id: str,
    output_dir: str | Path,
    release_id: str,
    backup_kind: str = "manual",
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    participant = validate_participant_id(participant_id)
    source = _participant_database(instances_root, participant)
    now = _utc_now(clock)
    destination_dir = _unique_backup_dir(Path(output_dir).expanduser(), participant, _stamp(now))
    destination = destination_dir / source.name
    manifest_path = destination_dir / f"{participant}.manifest.json"

    source_connection = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True, timeout=30)
    destination_connection = sqlite3.connect(destination, timeout=30)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()

    checks = _database_checks(destination)
    manifest = {
        "participant_id": participant,
        "beta_release_id": release_id,
        "created_at": now.isoformat(timespec="seconds"),
        "source_database": str(source.resolve()),
        "backup_database": str(destination.resolve()),
        "sha256": _sha256(destination),
        "schema_version": checks["schema_version"],
        "counts": checks["counts"],
        "integrity_check": checks["integrity_check"],
        "foreign_key_issue_count": checks["foreign_key_issue_count"],
        "backup_kind": backup_kind,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return {**manifest, "manifest_path": str(manifest_path.resolve())}


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BetaBackupError("BACKUP_MANIFEST_INVALID") from exc
    if not isinstance(value, dict):
        raise BetaBackupError("BACKUP_MANIFEST_INVALID")
    return value


def _remove_sqlite_sidecars(database: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = Path(f"{database}{suffix}")
        if sidecar.is_file():
            sidecar.unlink()


def restore_participant(
    *,
    instances_root: str | Path,
    participant_id: str,
    backup_database: str | Path,
    manifest_path: str | Path,
    prebackup_output_dir: str | Path,
    instance_stopped: bool,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, Any]:
    if not instance_stopped:
        raise BetaBackupError("RESTORE_REQUIRES_STOPPED_INSTANCE")
    participant = validate_participant_id(participant_id)
    target = _participant_database(instances_root, participant)
    backup = Path(backup_database).expanduser().resolve()
    manifest_file = Path(manifest_path).expanduser().resolve()
    if not backup.is_file():
        raise BetaBackupError("BACKUP_DATABASE_NOT_FOUND")
    if not manifest_file.is_file():
        raise BetaBackupError("BACKUP_MANIFEST_NOT_FOUND")

    manifest = _load_manifest(manifest_file)
    if manifest.get("participant_id") != participant:
        raise BetaBackupError("PARTICIPANT_BACKUP_MISMATCH")
    if Path(str(manifest.get("backup_database", ""))).expanduser().resolve() != backup:
        raise BetaBackupError("BACKUP_MANIFEST_PATH_MISMATCH")
    if manifest.get("sha256") != _sha256(backup):
        raise BetaBackupError("BACKUP_SHA256_MISMATCH")

    backup_checks = _database_checks(backup)
    target_checks = _database_checks(target)
    if int(manifest.get("schema_version", -1)) != backup_checks["schema_version"]:
        raise BetaBackupError("BACKUP_SCHEMA_MANIFEST_MISMATCH")
    if backup_checks["schema_version"] != target_checks["schema_version"]:
        raise BetaBackupError("BACKUP_SCHEMA_VERSION_MISMATCH")

    prebackup = backup_participant(
        instances_root=instances_root,
        participant_id=participant,
        output_dir=prebackup_output_dir,
        release_id=str(manifest.get("beta_release_id", "unknown")),
        backup_kind="pre_restore",
        clock=clock,
    )
    temporary = target.parent / f".{target.name}.restore-{uuid.uuid4().hex}.tmp"
    replaced = False
    try:
        shutil.copyfile(backup, temporary)
        _database_checks(temporary)
        _remove_sqlite_sidecars(target)
        os.replace(temporary, target)
        replaced = True
        final_checks = _database_checks(target)
    except Exception as exc:
        if temporary.exists():
            temporary.unlink()
        if replaced:
            rollback_source = Path(prebackup["backup_database"])
            rollback_temporary = target.parent / f".{target.name}.rollback-{uuid.uuid4().hex}.tmp"
            try:
                shutil.copyfile(rollback_source, rollback_temporary)
                _database_checks(rollback_temporary)
                _remove_sqlite_sidecars(target)
                os.replace(rollback_temporary, target)
                _database_checks(target)
            except Exception as rollback_exc:
                raise BetaBackupError("RESTORE_ROLLBACK_FAILED") from rollback_exc
            finally:
                if rollback_temporary.exists():
                    rollback_temporary.unlink()
            raise BetaBackupError("RESTORE_ROLLED_BACK") from exc
        if isinstance(exc, BetaBackupError):
            raise
        raise BetaBackupError("RESTORE_ATOMIC_REPLACE_FAILED") from exc

    restored_at = _utc_now(clock).isoformat(timespec="seconds")
    return {
        "status": "RESTORE_COMPLETE",
        "participant_id": participant,
        "restored_database": str(target.resolve()),
        "backup_database": str(backup),
        "backup_source": str(backup),
        "backup_sha256": manifest["sha256"],
        "manifest_path": str(manifest_file),
        "pre_restore_backup_database": prebackup["backup_database"],
        "pre_restore_backup": prebackup["backup_database"],
        "pre_restore_backup_sha256": prebackup["sha256"],
        "pre_restore_manifest_path": prebackup["manifest_path"],
        "restored_at": restored_at,
        "sha256": _sha256(target),
        "integrity_check": final_checks["integrity_check"],
        "foreign_key_issue_count": final_checks["foreign_key_issue_count"],
        "foreign_key_issues": final_checks["foreign_key_issue_count"],
        "schema_version": final_checks["schema_version"],
        "counts": final_checks["counts"],
        "project_count": final_checks["counts"]["projects"],
        "document_count": final_checks["counts"]["documents"],
        "rollback_performed": False,
    }
