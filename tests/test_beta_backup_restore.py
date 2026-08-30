from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.db import Database
from app.services.beta_backup import (
    BetaBackupError,
    backup_participant,
    restore_participant,
)
from app.services.projects import ProjectService


FIXED_NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _business_hash(path: Path) -> str:
    database = sqlite3.connect(path)
    try:
        payload: dict[str, list[list[object]]] = {}
        for table in (
            "projects",
            "documents",
            "document_versions",
            "beta_consents",
            "product_events",
            "beta_feedback",
            "beta_daily_usage",
        ):
            columns = [row[1] for row in database.execute(f"PRAGMA table_info({table})")]
            rows = database.execute(
                f"SELECT * FROM {table} ORDER BY " + ", ".join(columns)
            ).fetchall()
            payload[table] = [list(row) for row in rows]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
    finally:
        database.close()


def _seed_instance(root: Path, participant: str, *, filename: str, marker: str) -> Path:
    path = root / participant / filename
    database = Database(path)
    database.init_schema()
    project = ProjectService(database).create_project(
        title=f"{participant}-{marker}", summary=f"业务内容-{marker}", actor="fixture"
    )
    now = "2026-08-31T08:00:00+00:00"
    database.execute(
        """
        INSERT INTO beta_consents(id, participant_id, beta_release_id, consent_version, consented_at)
        VALUES (?, ?, ?, 1, ?)
        """,
        (f"consent-{participant}", participant, "closed-beta-v1", now),
    )
    database.execute(
        """
        INSERT INTO product_events(
            id, participant_id, session_id, project_id, event_name,
            properties_json, beta_release_id, occurred_at
        ) VALUES (?, ?, ?, ?, 'project_opened', '{}', 'closed-beta-v1', ?)
        """,
        (f"event-{participant}", participant, f"session-{participant}", project["id"], now),
    )
    database.execute(
        """
        INSERT INTO beta_feedback(
            id, participant_id, project_id, project_stage, rating,
            feedback_type, comment, beta_release_id, created_at
        ) VALUES (?, ?, ?, 'snapshot', 4, 'usability', ?, 'closed-beta-v1', ?)
        """,
        (f"feedback-{participant}", participant, project["id"], f"反馈-{marker}", now),
    )
    database.execute(
        """
        INSERT INTO beta_daily_usage(
            participant_id, usage_date, operation_type, request_count, updated_at
        ) VALUES (?, '2026-08-31', 'solution_generation', 3, ?)
        """,
        (participant, now),
    )
    return path


@pytest.fixture()
def participant_instances(tmp_path: Path):
    instances = tmp_path / "instances"
    beta001 = _seed_instance(
        instances, "beta_001", filename="insightforge.db", marker="original-a"
    )
    beta002 = _seed_instance(
        instances, "beta_002", filename="insightforge.sqlite3", marker="original-b"
    )
    return instances, beta001, beta002


def _backup(instances: Path, output: Path, participant: str = "beta_001") -> dict:
    return backup_participant(
        instances_root=instances,
        participant_id=participant,
        output_dir=output,
        release_id="closed-beta-v1",
        clock=lambda: FIXED_NOW,
    )


def test_backup_targets_exactly_one_participant_and_writes_safe_manifest(
    participant_instances, tmp_path
):
    instances, beta001, beta002 = participant_instances
    beta002_before = _sha(beta002)

    receipt = _backup(instances, tmp_path / "backups")
    manifest = json.loads(Path(receipt["manifest_path"]).read_text(encoding="utf-8"))

    assert receipt["participant_id"] == "beta_001"
    assert Path(receipt["backup_database"]).is_file()
    assert not list((tmp_path / "backups").rglob("beta_002*"))
    assert _sha(beta002) == beta002_before
    assert manifest == {
        "participant_id": "beta_001",
        "beta_release_id": "closed-beta-v1",
        "created_at": "2026-08-31T12:00:00+00:00",
        "source_database": str(beta001.resolve()),
        "backup_database": str(Path(receipt["backup_database"]).resolve()),
        "sha256": receipt["sha256"],
        "schema_version": 0,
        "counts": {"projects": 1, "documents": 0, "document_versions": 0},
        "integrity_check": "ok",
        "foreign_key_issue_count": 0,
        "backup_kind": "manual",
    }
    serialized = json.dumps(manifest, ensure_ascii=False)
    assert "业务内容" not in serialized
    assert "反馈" not in serialized


def test_backup_uses_sqlite_snapshot_and_sha_matches_bytes(participant_instances, tmp_path):
    instances, _beta001, _beta002 = participant_instances

    receipt = _backup(instances, tmp_path / "backups")
    backup = Path(receipt["backup_database"])

    assert receipt["sha256"] == _sha(backup)
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_restore_requires_explicit_stopped_instance(participant_instances, tmp_path):
    instances, _beta001, _beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")

    with pytest.raises(BetaBackupError, match="RESTORE_REQUIRES_STOPPED_INSTANCE"):
        restore_participant(
            instances_root=instances,
            participant_id="beta_001",
            backup_database=receipt["backup_database"],
            manifest_path=receipt["manifest_path"],
            prebackup_output_dir=tmp_path / "prebackup",
            instance_stopped=False,
            clock=lambda: FIXED_NOW,
        )


def test_restore_rejects_participant_mismatch_before_touching_target(
    participant_instances, tmp_path
):
    instances, _beta001, beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups", participant="beta_001")
    before = _business_hash(beta002)

    with pytest.raises(BetaBackupError, match="PARTICIPANT_BACKUP_MISMATCH"):
        restore_participant(
            instances_root=instances,
            participant_id="beta_002",
            backup_database=receipt["backup_database"],
            manifest_path=receipt["manifest_path"],
            prebackup_output_dir=tmp_path / "prebackup",
            instance_stopped=True,
            clock=lambda: FIXED_NOW,
        )

    assert _business_hash(beta002) == before


def test_restore_rejects_sha_mismatch_and_corruption_before_target_change(
    participant_instances, tmp_path
):
    instances, beta001, _beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")
    original_hash = _business_hash(beta001)
    Path(receipt["backup_database"]).write_bytes(b"not a sqlite database")

    with pytest.raises(BetaBackupError, match="BACKUP_SHA256_MISMATCH"):
        restore_participant(
            instances_root=instances,
            participant_id="beta_001",
            backup_database=receipt["backup_database"],
            manifest_path=receipt["manifest_path"],
            prebackup_output_dir=tmp_path / "prebackup",
            instance_stopped=True,
            clock=lambda: FIXED_NOW,
        )

    assert _business_hash(beta001) == original_hash


def test_restore_rejects_corrupt_backup_even_when_manifest_sha_is_recomputed(
    participant_instances, tmp_path
):
    instances, beta001, _beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")
    original_hash = _business_hash(beta001)
    backup = Path(receipt["backup_database"])
    backup.write_bytes(b"not a sqlite database")
    manifest_path = Path(receipt["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sha256"] = _sha(backup)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(BetaBackupError, match="BACKUP_DATABASE_INVALID"):
        restore_participant(
            instances_root=instances,
            participant_id="beta_001",
            backup_database=backup,
            manifest_path=manifest_path,
            prebackup_output_dir=tmp_path / "prebackup",
            instance_stopped=True,
            clock=lambda: FIXED_NOW,
        )

    assert _business_hash(beta001) == original_hash


def test_restore_creates_automatic_prebackup_and_restores_all_participant_state(
    participant_instances, tmp_path
):
    instances, beta001, _beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")
    backed_up_business_hash = _business_hash(Path(receipt["backup_database"]))
    ProjectService(Database(beta001)).create_project(
        title="later mutation", summary="must be replaced", actor="fixture"
    )
    mutated = Database(beta001)
    mutated.execute(
        "UPDATE beta_daily_usage SET request_count=9 WHERE participant_id='beta_001'"
    )
    mutated.execute("DELETE FROM beta_feedback WHERE participant_id='beta_001'")
    mutated.execute("DELETE FROM product_events WHERE participant_id='beta_001'")
    mutated.execute("DELETE FROM beta_consents WHERE participant_id='beta_001'")
    before_restore_hash = _business_hash(beta001)

    restored = restore_participant(
        instances_root=instances,
        participant_id="beta_001",
        backup_database=receipt["backup_database"],
        manifest_path=receipt["manifest_path"],
        prebackup_output_dir=tmp_path / "prebackup",
        instance_stopped=True,
        clock=lambda: FIXED_NOW,
    )

    assert restored["status"] == "RESTORE_COMPLETE"
    assert _business_hash(beta001) == backed_up_business_hash
    prebackup = Path(restored["pre_restore_backup_database"])
    assert prebackup.is_file()
    assert _business_hash(prebackup) == before_restore_hash
    assert restored["integrity_check"] == "ok"
    assert restored["foreign_key_issue_count"] == 0
    assert restored["backup_sha256"] == receipt["sha256"]
    assert restored["project_count"] == 1
    assert restored["document_count"] == 0
    assert restored["rollback_performed"] is False
    restored_db = Database(beta001)
    assert restored_db.fetch_one(
        "SELECT request_count FROM beta_daily_usage WHERE participant_id='beta_001'"
    )["request_count"] == 3
    assert restored_db.fetch_one(
        "SELECT COUNT(*) AS n FROM beta_consents WHERE participant_id='beta_001'"
    )["n"] == 1
    assert restored_db.fetch_one(
        "SELECT COUNT(*) AS n FROM product_events WHERE participant_id='beta_001'"
    )["n"] == 1
    assert restored_db.fetch_one(
        "SELECT COUNT(*) AS n FROM beta_feedback WHERE participant_id='beta_001'"
    )["n"] == 1


def test_beta001_restore_does_not_affect_beta002(participant_instances, tmp_path):
    instances, beta001, beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")
    beta002_before = _business_hash(beta002)
    ProjectService(Database(beta001)).create_project(
        title="temporary", summary="temporary", actor="fixture"
    )

    restore_participant(
        instances_root=instances,
        participant_id="beta_001",
        backup_database=receipt["backup_database"],
        manifest_path=receipt["manifest_path"],
        prebackup_output_dir=tmp_path / "prebackup",
        instance_stopped=True,
        clock=lambda: FIXED_NOW,
    )

    assert _business_hash(beta002) == beta002_before


def test_restore_cleans_exact_target_wal_and_shm_files(participant_instances, tmp_path):
    instances, beta001, _beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")
    wal = Path(f"{beta001}-wal")
    shm = Path(f"{beta001}-shm")
    wal.write_bytes(b"stale")
    shm.write_bytes(b"stale")

    restore_participant(
        instances_root=instances,
        participant_id="beta_001",
        backup_database=receipt["backup_database"],
        manifest_path=receipt["manifest_path"],
        prebackup_output_dir=tmp_path / "prebackup",
        instance_stopped=True,
        clock=lambda: FIXED_NOW,
    )

    assert not wal.exists()
    assert not shm.exists()


def test_post_replace_validation_failure_rolls_back_to_automatic_prebackup(
    participant_instances, tmp_path, monkeypatch
):
    import app.services.beta_backup as backup_module

    instances, beta001, _beta002 = participant_instances
    receipt = _backup(instances, tmp_path / "backups")
    ProjectService(Database(beta001)).create_project(
        title="state immediately before restore",
        summary="must survive a failed restore",
        actor="fixture",
    )
    before_restore_hash = _business_hash(beta001)
    real_checks = backup_module._database_checks
    target_checks = 0

    def fail_only_first_post_replace(path: Path):
        nonlocal target_checks
        if Path(path).resolve() == beta001.resolve():
            target_checks += 1
            if target_checks == 2:
                raise BetaBackupError("SIMULATED_POST_REPLACE_FAILURE")
        return real_checks(path)

    monkeypatch.setattr(backup_module, "_database_checks", fail_only_first_post_replace)

    with pytest.raises(BetaBackupError, match="RESTORE_ROLLED_BACK"):
        restore_participant(
            instances_root=instances,
            participant_id="beta_001",
            backup_database=receipt["backup_database"],
            manifest_path=receipt["manifest_path"],
            prebackup_output_dir=tmp_path / "prebackup",
            instance_stopped=True,
            clock=lambda: FIXED_NOW,
        )

    assert _business_hash(beta001) == before_restore_hash


def test_ambiguous_participant_database_names_fail_closed(tmp_path):
    instances = tmp_path / "instances"
    _seed_instance(instances, "beta_001", filename="insightforge.db", marker="one")
    (instances / "beta_001" / "insightforge.sqlite3").write_bytes(b"ambiguous")

    with pytest.raises(BetaBackupError, match="AMBIGUOUS_PARTICIPANT_DATABASE"):
        _backup(instances, tmp_path / "backups")


def test_invalid_participant_id_cannot_escape_instances_root(tmp_path):
    with pytest.raises(ValueError, match=r"beta_\[0-9\]\{3\}"):
        backup_participant(
            instances_root=tmp_path / "instances",
            participant_id="../beta_001",
            output_dir=tmp_path / "backups",
            release_id="closed-beta-v1",
        )


def test_backup_and_restore_cli_are_directly_executable():
    project_root = Path(__file__).resolve().parents[1]

    for script in ("backup_beta_instances.py", "restore_beta_instance.py"):
        result = subprocess.run(
            [sys.executable, str(project_root / "scripts" / script), "--help"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "--participant" in result.stdout
        if script == "restore_beta_instance.py":
            assert "--confirm-instance-stopped" in result.stdout
