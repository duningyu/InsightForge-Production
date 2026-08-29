import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest


def test_python_package_declares_static_assets():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["app"]
    assert "static/*" in patterns
    assert Path("app/static/index.html").is_file()
    assert Path("app/static/styles.css").is_file()
    assert Path("app/static/app.js").is_file()


def test_all_local_dependency_manifests_declare_keyring():
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project_dependencies = [item.casefold() for item in data["project"]["dependencies"]]
    requirements = [
        line.strip().casefold()
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert any(item.startswith("keyring>=") for item in project_dependencies)
    assert any(item.startswith("keyring>=") for item in requirements)


def test_runtime_dependency_verifier_uses_safe_output():
    sentinel = "sk-SENTINEL-RUNTIME-CHECK"
    environment = {**os.environ, "OPENAI_API_KEY": sentinel}
    result = subprocess.run(
        [sys.executable, "-m", "app.runtime_check"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "[InsightForge] runtime-dependencies=ok"
    assert sentinel not in result.stdout + result.stderr


@pytest.mark.skipif(os.name != "nt", reason="start.bat is the Windows launcher")
def test_start_bat_verify_only_checks_the_selected_launch_interpreter():
    sentinel = "sk-SENTINEL-START-BAT-OUTPUT"
    environment = {
        **os.environ,
        "INSIGHTFORGE_PYTHON": sys.executable,
        "INSIGHTFORGE_SKIP_INSTALL": "1",
        "INSIGHTFORGE_VERIFY_ONLY": "1",
        "OPENAI_API_KEY": sentinel,
    }
    result = subprocess.run(
        ["cmd", "/d", "/c", "start.bat"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "runtime-dependencies=ok" in result.stdout
    assert sentinel not in result.stdout + result.stderr


def test_local_env_loader_preserves_explicit_overrides_without_printing_values(
    tmp_path, monkeypatch, capsys
):
    from app.__main__ import _load_local_env

    env_file = tmp_path / ".env"
    env_file.write_text(
        "INSIGHTFORGE_DATABASE_PATH=from-file.sqlite3\n"
        "PORT=9123\n"
        "OPENAI_API_KEY=sk-SENTINEL-ENV-FILE\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("INSIGHTFORGE_DATABASE_PATH", "explicit.sqlite3")
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    _load_local_env(env_file)

    assert os.environ["INSIGHTFORGE_DATABASE_PATH"] == "explicit.sqlite3"
    assert os.environ["PORT"] == "9123"
    assert os.environ["OPENAI_API_KEY"] == "sk-SENTINEL-ENV-FILE"
    captured = capsys.readouterr()
    assert "sk-SENTINEL-ENV-FILE" not in captured.out + captured.err
