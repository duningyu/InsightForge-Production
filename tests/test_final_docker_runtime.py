from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_dockerfile_contains_deterministic_demo_fixture_for_beta_runtime():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY tests/fixtures ./tests/fixtures" in dockerfile
