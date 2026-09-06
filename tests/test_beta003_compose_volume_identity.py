"""Static regression checks for the beta003 Compose volume contract."""

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_COMPOSE = REPO_ROOT / "deploy" / "beta" / "docker-compose.yml"
BETA003_COMPOSE = REPO_ROOT / "deploy" / "beta" / "docker-compose.beta003.yml"
COMPOSE_PROJECT = "beta"


def _resolved_compose() -> dict:
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": COMPOSE_PROJECT,
            "INSIGHTFORGE_BETA003_IMAGE": "test-only-beta003-image",
            "MANAGED_QWEN_API_KEY": "TEST_ONLY_NOT_A_REAL_KEY",
        }
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            COMPOSE_PROJECT,
            "-f",
            str(BASE_COMPOSE),
            "-f",
            str(BETA003_COMPOSE),
            "config",
            "--format",
            "json",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_beta003_volumes_resolve_to_existing_runtime_names():
    compose = _resolved_compose()
    service = compose["services"]["beta003"]
    mounts = {
        mount["target"]: compose["volumes"][mount["source"]]["name"]
        for mount in service["volumes"]
    }
    volumes = compose["volumes"]

    assert mounts["/data"] == "beta_beta003_data"
    assert mounts["/runtime"] == "beta_beta003_runtime"
    assert volumes["beta003_data"]["name"] == "beta_beta003_data"
    assert volumes["beta003_runtime"]["name"] == "beta_beta003_runtime"
    assert "beta_beta_beta003_data" not in {
        volume.get("name") for volume in volumes.values()
    }
    assert "beta_beta_beta003_runtime" not in {
        volume.get("name") for volume in volumes.values()
    }
