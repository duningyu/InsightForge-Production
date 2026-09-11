from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.beta_runtime import RuntimePaths, validate_participant_id


def _new_instance(monkeypatch, tmp_path, participant):
    monkeypatch.setenv("BETA_MODE", "true")
    monkeypatch.setenv("BETA_PARTICIPANT_ID", participant)
    monkeypatch.setenv("RUNTIME_DIR", str(tmp_path / participant / "runtime"))
    return TestClient(create_app(database_path=tmp_path / participant / "db.sqlite3", seed=False))


def test_two_real_sqlite_instances_do_not_share_projects(monkeypatch, tmp_path):
    with _new_instance(monkeypatch, tmp_path, "beta_001") as a:
        created = a.post("/api/projects/quick-start", json={"idea": "便利店补货 Project A", "target_user": None, "resources": [], "priority": "fast_mvp"})
        assert created.status_code == 201
    with _new_instance(monkeypatch, tmp_path, "beta_002") as b:
        assert all(item["title"] != "Project A" for item in b.get("/api/projects").json())


def test_runtime_paths_reject_traversal_and_validate_participant():
    paths = RuntimePaths.from_root("./tmp-beta-runtime-test")
    try:
        assert paths.child("safe.txt").parent == paths.temp
        for bad in ("../../beta002/secret.txt", r"..\..\beta002\secret.txt", "/absolute/path", r"C:\absolute\path"):
            try:
                paths.child(bad)
            except ValueError:
                pass
            else:
                raise AssertionError("path traversal accepted")
    finally:
        import shutil
        shutil.rmtree(paths.root, ignore_errors=True)
    for value in ("beta_001", "beta_999", "railway_stage_a", "railway_stage_b"):
        assert validate_participant_id(value) == value


def test_stage_participant_contract_rejects_unapproved_identities():
    import pytest

    for value in (
        "railway_stage",
        "railway_stage_c",
        "railway_prod",
        "stage_b",
        "beta_01",
        "beta_0001",
        "arbitrary_string",
    ):
        with pytest.raises(ValueError, match="approved Railway stage identities"):
            validate_participant_id(value)


def test_runtime_and_database_persist_across_app_restart(monkeypatch, tmp_path):
    with _new_instance(monkeypatch, tmp_path, "beta_001") as first:
        created = first.post("/api/projects/quick-start", json={"idea": "帮助小型便利店减少补货遗漏", "target_user": None, "resources": [], "priority": "fast_mvp"})
        assert created.status_code == 201, created.text
    with _new_instance(monkeypatch, tmp_path, "beta_001") as restarted:
        assert restarted.get("/api/projects").status_code == 200
        assert restarted.app.state.db.fetch_one("SELECT id FROM projects WHERE id = ?", (created.json()["project_id"],)) is not None


def test_runtime_roots_are_independent(tmp_path):
    from app.services.beta_runtime import RuntimePaths
    a = RuntimePaths.from_root(tmp_path / "beta_001" / "runtime")
    b = RuntimePaths.from_root(tmp_path / "beta_002" / "runtime")
    a_file = a.child("source.txt", area="uploads")
    a_file.write_text("synthetic source", encoding="utf-8")
    assert a_file.exists()
    assert not b.child("source.txt", area="uploads").exists()


def test_railway_stage_identities_keep_storage_and_context_metadata_distinct(tmp_path):
    from types import SimpleNamespace
    from app.services.beta_runtime import BetaInstanceContext

    stage_a = BetaInstanceContext.from_settings(SimpleNamespace(
        beta_participant_id="railway_stage_a",
        database_path=tmp_path / "stage-a" / "insightforge.sqlite3",
        runtime_dir=tmp_path / "stage-a" / "runtime",
        beta_mode=True,
        beta_release_id="stage-a",
    ))
    stage_b = BetaInstanceContext.from_settings(SimpleNamespace(
        beta_participant_id="railway_stage_b",
        database_path=tmp_path / "stage-b" / "insightforge.sqlite3",
        runtime_dir=tmp_path / "stage-b" / "runtime",
        beta_mode=True,
        beta_release_id="stage-b",
    ))

    assert stage_a.participant_id == "railway_stage_a"
    assert stage_b.participant_id == "railway_stage_b"
    assert stage_a.database_path != stage_b.database_path
    assert stage_a.runtime.root != stage_b.runtime.root
