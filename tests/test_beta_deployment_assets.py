from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_deployment_asset_audit_cli_accepts_the_frozen_release_tree():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "audit_beta_deployment.py"),
            "--project-root",
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DOCKERFILE_SECURITY_AUDIT=PASS" in result.stdout
    assert "DOCKERIGNORE_SECURITY_AUDIT=PASS" in result.stdout


def test_compose_config_renders_without_provider_secrets_and_is_loopback_only():
    result = subprocess.run(
        ["docker", "compose", "-f", "deploy/beta/docker-compose.yml", "config"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    rendered = result.stdout
    assert "host_ip: 127.0.0.1" in rendered
    assert "published: \"18001\"" in rendered
    assert "published: \"18002\"" in rendered
    assert "beta001_data" in rendered and "beta002_data" in rendered
    assert "beta001_runtime" in rendered and "beta002_runtime" in rendered
    assert "required variable" not in rendered


def test_caddy_renderer_creates_distinct_hashed_credentials_and_service_routes():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_beta_caddy.py"),
            "--template",
            str(ROOT / "deploy" / "beta" / "Caddyfile.template"),
            "--public-ip",
            "203.0.113.10",
            "--credential",
            "beta_001:user001:$2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6C",
            "--credential",
            "beta_002:user002:$2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6D",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    rendered = result.stdout
    assert "beta001.203.0.113.10.nip.io" in rendered
    assert "beta002.203.0.113.10.nip.io" in rendered
    assert "reverse_proxy beta001:8000" in rendered
    assert "reverse_proxy beta002:8000" in rendered
    assert "user001 $2b$12$C6UzMDM.H6df" in rendered
    assert "user002 $2b$12$C6UzMDM.H6df" in rendered
    assert "reverse_proxy 127.0.0.1" not in rendered


def test_caddy_renderer_rejects_plaintext_passwords():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_beta_caddy.py"),
            "--template",
            str(ROOT / "deploy" / "beta" / "Caddyfile.template"),
            "--public-ip",
            "203.0.113.10",
            "--credential",
            "beta_001:user001:plaintext-password",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    assert "CADDY_HASH_REQUIRED" in result.stdout + result.stderr


def test_phase_a_artifact_builder_excludes_all_private_runtime_material(tmp_path):
    fixture_root = tmp_path / "source"
    (fixture_root / "app" / "static").mkdir(parents=True)
    (fixture_root / "deploy" / "beta").mkdir(parents=True)
    (fixture_root / "docs" / "beta").mkdir(parents=True)
    (fixture_root / "scripts").mkdir()
    (fixture_root / "tests").mkdir()
    required = {
        "Dockerfile": "FROM python:3.12.11-slim-bookworm\n",
        "docker-compose.yml": "services: {}\n",
        "deploy/beta/Caddyfile.template": "{{SITES}}\n",
        "app/main.py": "# app\n",
        "scripts/start.py": "# script\n",
        "tests/test_smoke.py": "# test\n",
        "docs/beta/RUNBOOK.md": "runbook\n",
    }
    for relative, content in required.items():
        path = fixture_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    private = [
        ".env",
        ".env.production",
        "data/participant.sqlite3",
        "runtime/session.txt",
        "reports/report.txt",
        "backups/backup.db",
        "beta_invites_private.csv",
        ".git/config",
        ".venv/secret.txt",
        "__pycache__/module.pyc",
    ]
    for relative in private:
        path = fixture_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE-SENTINEL", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_phase_a_artifact.py"),
            "--project-root",
            str(fixture_root),
            "--output-dir",
            str(tmp_path / "output"),
            "--date",
            "20260831",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    archive = tmp_path / "output" / "InsightForge_Closed_Beta_Phase_A_20260831.zip"
    checksum = archive.with_suffix(".sha256.txt")
    assert archive.is_file() and checksum.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        assert "InsightForge/Dockerfile" in names
        assert "InsightForge/deploy/beta/Caddyfile.template" in names
        assert not any("PRIVATE-SENTINEL" in bundle.read(name).decode("utf-8", "ignore") for name in names)
        assert not any(
            token in name
            for name in names
            for token in ("/.git/", "/.venv/", "/runtime/", "/reports/", "/backups/")
        )
        assert not any(name.endswith((".db", ".sqlite", ".sqlite3", ".pyc")) for name in names)
    digest, filename = checksum.read_text(encoding="utf-8").strip().split("  ", 1)
    assert len(digest) == 64
    assert filename == archive.name
