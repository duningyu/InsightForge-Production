from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scripts.verify_edge_auth import verify_target
from scripts.augment_caddy_basic_auth import augment_basic_auth


ROOT = Path(__file__).resolve().parents[1]


def _docker_available() -> bool:
    result = subprocess.run(
        ["docker", "info", "--format", "{{.ServerVersion}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    return result.returncode == 0


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _bcrypt(password: str) -> str:
    result = subprocess.run(
        ["docker", "run", "--rm", "caddy:2.10.2", "caddy", "hash-password", "--bcrypt-cost", "12", "--plaintext", password],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return result.stdout.strip()


def _basic_status(port: int, username: str, password: str) -> int:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        headers={"Authorization": f"Basic {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)


@pytest.mark.integration
def test_disposable_caddy_edge_identity_and_isolation():
    if not _docker_available():
        pytest.skip("Docker daemon unavailable")
    existing_password = "synthetic-existing-edge-password"
    verifier_password = "synthetic-deployment-verifier-password"
    existing_hash = _bcrypt(existing_password)
    verifier_hash = _bcrypt(verifier_password)
    containers: list[str] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        configs = {
            "beta001": f':8080 {{\n  basic_auth {{\n    beta001 {existing_hash}\n  }}\n  respond "ok"\n}}\n',
            "beta002": f':8080 {{\n  basic_auth {{\n    beta002 {existing_hash}\n  }}\n  respond "ok"\n}}\n',
            "beta003": f':8080 {{\n  basic_auth {{\n    beta003 {existing_hash}\n    deployment_verifier {verifier_hash}\n  }}\n  respond "ok"\n}}\n',
        }
        ports = {name: _free_port() for name in configs}
        ready = False
        try:
            for name, config in configs.items():
                config_path = temp / f"{name}.Caddyfile"
                config_path.write_text(config, encoding="utf-8")
                container_name = f"insightforge-edge-test-{os.getpid()}-{name}"
                result = subprocess.run(
                    [
                        "docker", "run", "-d", "--rm", "--name", container_name,
                        "-p", f"127.0.0.1:{ports[name]}:8080",
                        "-v", f"{config_path}:/etc/caddy/Caddyfile:ro",
                        "caddy:2.10.2", "caddy", "run", "--config", "/etc/caddy/Caddyfile",
                        "--adapter", "caddyfile",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                containers.append(container_name)
                assert result.stdout.strip()
            deadline = time.time() + 20
            while time.time() < deadline:
                try:
                    ready = (
                        _basic_status(ports["beta003"], "beta003", existing_password) == 200
                        and _basic_status(ports["beta003"], "deployment_verifier", verifier_password) == 200
                        and _basic_status(ports["beta001"], "deployment_verifier", verifier_password) == 401
                        and _basic_status(ports["beta002"], "deployment_verifier", verifier_password) == 401
                    )
                    if ready:
                        break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.25)
            if not ready:
                logs = [
                    (lambda result: result.stdout + result.stderr)(
                        subprocess.run(["docker", "logs", container_name], capture_output=True, text=True, check=False)
                    )
                    for container_name in containers
                ]
                pytest.fail("disposable Caddy did not become ready: " + " | ".join(logs))
            assert _basic_status(ports["beta003"], "beta003", existing_password) == 200
            assert _basic_status(ports["beta003"], "deployment_verifier", verifier_password) == 200
            assert _basic_status(ports["beta003"], "deployment_verifier", "wrong-password") == 401
            assert _basic_status(ports["beta003"], "unknown", verifier_password) == 401
            assert _basic_status(ports["beta001"], "deployment_verifier", verifier_password) == 401
            assert _basic_status(ports["beta002"], "deployment_verifier", verifier_password) == 401
        finally:
            for container_name in containers:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False, timeout=30)


@pytest.mark.integration
def test_disposable_caddy_rotation_and_rollback():
    if not _docker_available():
        pytest.skip("Docker daemon unavailable")
    password_v1 = "synthetic-verifier-v1"
    password_v2 = "synthetic-verifier-v2"
    hash_v1 = _bcrypt(password_v1)
    hash_v2 = _bcrypt(password_v2)
    port = _free_port()
    container_name = f"insightforge-edge-rotation-test-{os.getpid()}"
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = Path(temp_dir) / "Caddyfile"

        def write_config(password_hash: str) -> None:
            config_path.write_text(
                f':8080 {{\n  basic_auth {{\n    deployment_verifier {password_hash}\n  }}\n  respond "ok"\n}}\n',
                encoding="utf-8",
            )

        write_config(hash_v1)
        try:
            subprocess.run(
                [
                    "docker", "run", "-d", "--rm", "--name", container_name,
                    "-p", f"127.0.0.1:{port}:8080",
                    "-v", f"{config_path}:/etc/caddy/Caddyfile",
                    "caddy:2.10.2", "caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            deadline = time.time() + 20
            while time.time() < deadline and _basic_status(port, "deployment_verifier", password_v1) != 200:
                time.sleep(0.25)
            assert _basic_status(port, "deployment_verifier", password_v1) == 200
            assert _basic_status(port, "deployment_verifier", password_v2) == 401

            write_config(hash_v2)
            subprocess.run(
                ["docker", "exec", container_name, "caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            deadline = time.time() + 20
            while time.time() < deadline and _basic_status(port, "deployment_verifier", password_v2) != 200:
                time.sleep(0.25)
            assert _basic_status(port, "deployment_verifier", password_v2) == 200
            assert _basic_status(port, "deployment_verifier", password_v1) == 401

            write_config(hash_v1)
            subprocess.run(
                ["docker", "exec", container_name, "caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            deadline = time.time() + 20
            while time.time() < deadline and _basic_status(port, "deployment_verifier", password_v1) != 200:
                time.sleep(0.25)
            assert _basic_status(port, "deployment_verifier", password_v1) == 200
            assert _basic_status(port, "deployment_verifier", password_v2) == 401
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False, timeout=30)


def test_renderer_rejects_duplicate_username_for_one_participant():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "render_beta_caddy.py"),
            "--template",
            str(ROOT / "deploy" / "beta" / "Caddyfile.template"),
            "--public-ip",
            "203.0.113.10",
            "--credential",
            "beta_003:deployment_verifier:$2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6C",
            "--credential",
            "beta_003:deployment_verifier:$2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6D",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "CADDY_DUPLICATE_USERNAME" in result.stdout + result.stderr


def test_existing_caddy_config_keeps_existing_identity_and_adds_verifier():
    original = """example.test {
  basic_auth {
    existing $2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6C
  }
  reverse_proxy host.docker.internal:18003
}
"""
    updated = augment_basic_auth(
        original,
        username="deployment_verifier",
        password_hash="$2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6D",
    )
    assert "existing $2b$12$C6UzMDM.H6df" in updated
    assert "deployment_verifier $2b$12$C6UzMDM.H6df" in updated
    assert "reverse_proxy host.docker.internal:18003" in updated


def test_existing_caddy_config_rejects_duplicate_verifier_and_plaintext_hash():
    original = """example.test {
  basic_auth {
    deployment_verifier $2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6C
  }
}
"""
    with pytest.raises(ValueError, match="CADDY_DUPLICATE_USERNAME"):
        augment_basic_auth(
            original,
            username="deployment_verifier",
            password_hash="$2b$12$C6UzMDM.H6dfI/f/IKcEe.9zJkVTdgi0QoM6JSlrMju7Wn3F6oN6D",
        )
    with pytest.raises(ValueError, match="CADDY_HASH_REQUIRED"):
        augment_basic_auth(original, username="other_verifier", password_hash="plaintext")


def test_safe_consumer_returns_sanitized_result_without_exposing_authorization(tmp_path):
    secret = "VerifierPassword-should-never-appear"
    secret_file = tmp_path / "beta003-verifier.secret"
    secret_file.write_text(f"deployment_verifier\n{secret}\n", encoding="utf-8")
    captured: dict[str, str] = {}

    def request_fn(url: str, authorization: str, timeout: float):
        captured["url"] = url
        captured["authorization"] = authorization
        return 200, True

    result = verify_target(
        target="beta003",
        url="https://beta003.example.test/api/health",
        secret_file=secret_file,
        request_fn=request_fn,
    )
    serialized = json.dumps(result, sort_keys=True)
    assert result["result"] == "PASS"
    assert secret not in serialized
    assert "Authorization" not in serialized
    assert captured["authorization"] == "Basic " + base64.b64encode(
        f"deployment_verifier:{secret}".encode()
    ).decode()


def test_safe_consumer_cli_receipt_and_stderr_do_not_expose_secret(tmp_path):
    secret = "VerifierPassword-cli-sentinel"
    secret_file = tmp_path / "beta003-verifier.secret"
    receipt = tmp_path / "receipt.json"
    secret_file.write_text(f"deployment_verifier\n{secret}\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "verify_edge_auth.py"),
            "--target",
            "beta003",
            "--url",
            "https://127.0.0.1:1/api/health",
            "--secret-file",
            str(secret_file),
            "--receipt",
            str(receipt),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode != 0
    assert secret not in result.stdout
    assert secret not in result.stderr
    assert secret not in receipt.read_text(encoding="utf-8")
