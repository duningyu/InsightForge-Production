from pathlib import Path

from app.config import Settings


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_data_root_derives_persistent_paths_when_explicit_paths_are_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("INSIGHTFORGE_DATA_ROOT", str(tmp_path / "railway-data"))
    monkeypatch.delenv("INSIGHTFORGE_DATABASE_PATH", raising=False)
    monkeypatch.delenv("RUNTIME_DIR", raising=False)
    monkeypatch.delenv("INSIGHTFORGE_ACCOUNTS_DIR", raising=False)

    settings = Settings.from_env()

    assert settings.database_path == tmp_path / "railway-data" / "insightforge.sqlite3"
    assert settings.runtime_dir == tmp_path / "railway-data" / "runtime"
    assert settings.accounts_dir == tmp_path / "railway-data" / "accounts"


def test_explicit_legacy_paths_still_override_data_root(monkeypatch, tmp_path):
    data_root = tmp_path / "railway-data"
    database = tmp_path / "legacy.sqlite3"
    runtime = tmp_path / "legacy-runtime"
    accounts = tmp_path / "legacy-accounts"
    monkeypatch.setenv("INSIGHTFORGE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("INSIGHTFORGE_DATABASE_PATH", str(database))
    monkeypatch.setenv("RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("INSIGHTFORGE_ACCOUNTS_DIR", str(accounts))

    settings = Settings.from_env()

    assert settings.database_path == database
    assert settings.runtime_dir == runtime
    assert settings.accounts_dir == accounts


def test_docker_command_uses_railway_port_with_local_default():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "${PORT:-8000}" in dockerfile


def test_docker_healthcheck_uses_effective_port():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "os.getenv('PORT', '8000')" in dockerfile
    assert "127.0.0.1:{port}" in dockerfile
    assert "CMD-SHELL" not in dockerfile


def test_dockerignore_excludes_deployment_secrets_and_runtime_data():
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "private/" in dockerignore
    assert "private_backups/" in dockerignore
    assert "credentials/" in dockerignore
    assert "*.sqlite3" in dockerignore
