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
        created = a.post("/api/projects/quick-start", json={"idea": "Project A", "target_user": None, "resources": [], "priority": "fast_mvp"})
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
    for value in ("beta_001", "beta_999"):
        assert validate_participant_id(value) == value
