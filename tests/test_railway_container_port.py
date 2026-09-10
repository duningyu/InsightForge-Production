import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "deploy" / "beta" / "Dockerfile"


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _run(*args: str, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
        **kwargs,
    )


@pytest.fixture(scope="session")
def railway_test_image(request):
    if not _docker_available():
        pytest.skip("Docker is required for the container-level Railway contract")

    tag = f"insightforge-railway-port-test:{uuid.uuid4().hex[:12]}"
    _run("docker", "build", "-f", str(DOCKERFILE), "-t", tag, ".")

    def cleanup() -> None:
        subprocess.run(
            ["docker", "image", "rm", "-f", tag],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

    request.addfinalizer(cleanup)
    return tag


def _wait_for_health(port: int, timeout: float = 20.0) -> int:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=1
            ) as response:
                return response.status
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise AssertionError(f"container did not serve /api/health on {port}: {last_error}")


def _wait_for_container_health(name: str, timeout: float = 30.0) -> str:
    deadline = time.monotonic() + timeout
    last_status = "unknown"
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Health.Status}}", name],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        last_status = result.stdout.strip()
        if last_status == "healthy":
            return last_status
        time.sleep(0.5)
    raise AssertionError(f"container healthcheck did not pass: {last_status}")


@pytest.mark.parametrize("port", [8765, 5000])
def test_real_container_consumes_dynamic_port(railway_test_image, port):
    name = f"if-port-test-{port}-{uuid.uuid4().hex[:8]}"
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-e",
        f"PORT={port}",
        "-e",
        "HOST=0.0.0.0",
        "-e",
        "INSIGHTFORGE_DATA_ROOT=/tmp/insightforge-data",
        "-e",
        "BETA_PARTICIPANT_ID=beta_003",
        "-e",
        "INSIGHTFORGE_ACCOUNTS_ENABLED=false",
        "-p",
        f"{port}:{port}",
        railway_test_image,
    ]
    try:
        _run(*command)
        assert _wait_for_health(port) == 200
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )


def test_real_container_keeps_default_port_when_port_is_unset(railway_test_image):
    name = f"if-port-test-default-{uuid.uuid4().hex[:8]}"
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-e",
        "HOST=0.0.0.0",
        "-e",
        "INSIGHTFORGE_DATA_ROOT=/tmp/insightforge-data",
        "-e",
        "BETA_PARTICIPANT_ID=beta_003",
        "-e",
        "INSIGHTFORGE_ACCOUNTS_ENABLED=false",
        "-p",
        "8000:8000",
        railway_test_image,
    ]
    try:
        _run(*command)
        assert _wait_for_health(8000) == 200
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )


def test_real_container_healthcheck_consumes_dynamic_port(railway_test_image):
    port = 8765
    name = f"if-port-healthcheck-{uuid.uuid4().hex[:8]}"
    command = [
        "docker",
        "run",
        "-d",
        "--name",
        name,
        "-e",
        f"PORT={port}",
        "-e",
        "HOST=0.0.0.0",
        "-e",
        "INSIGHTFORGE_DATA_ROOT=/tmp/insightforge-data",
        "-e",
        "BETA_PARTICIPANT_ID=beta_003",
        "-e",
        "INSIGHTFORGE_ACCOUNTS_ENABLED=false",
        "-p",
        f"{port}:{port}",
        railway_test_image,
    ]
    try:
        _run(*command)
        assert _wait_for_health(port) == 200
        assert _wait_for_container_health(name) == "healthy"
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
