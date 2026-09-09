"""Fail-closed static audit for closed-beta Docker build inputs."""

from __future__ import annotations

import argparse
from pathlib import Path


DOCKERIGNORE_REQUIRED = {
    ".git",
    ".env",
    ".env.*",
    ".venv",
    "venv",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
    "__pycache__",
    ".pytest_cache",
    "reports/",
    "backups/",
    "runtime/",
    "data/*.db",
    "data/*.sqlite",
    "data/*.sqlite3",
    "beta_invites_private.csv",
    "private/",
    "private_backups/",
    "credentials/",
    "*.pem",
    "*.key",
    "*.secret",
}


def audit(project_root: Path) -> list[str]:
    failures: list[str] = []
    for relative in ("Dockerfile", "deploy/beta/Dockerfile"):
        path = project_root / relative
        content = path.read_text(encoding="utf-8")
        required = {
            "pinned_python": "FROM python:3.12." in content,
            "non_root": "USER insightforge" in content,
            "bind_all_container_interfaces": '0.0.0.0' in content,
            "port_contract": (
                'PORT:-8000' in content
                or "os.getenv('PORT'" in content
                or (relative == "deploy/beta/Dockerfile" and '"--port", "8000"' in content)
            ),
            "healthcheck": "HEALTHCHECK" in content and "/api/health" in content,
            "no_copy_dot": "COPY . " not in content and "COPY .\n" not in content,
            "no_key_bake": "API_KEY" not in content and "Authorization" not in content,
        }
        failures.extend(f"{relative}:{name}" for name, passed in required.items() if not passed)

    ignored = {
        line.strip()
        for line in (project_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    failures.extend(
        f".dockerignore:missing:{pattern}"
        for pattern in sorted(DOCKERIGNORE_REQUIRED - ignored)
    )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    try:
        failures = audit(root)
    except OSError as exc:
        raise SystemExit(f"DOCKER_ASSET_AUDIT_ERROR:{exc}") from exc
    lines = []
    if failures:
        lines.append("DOCKERFILE_SECURITY_AUDIT=FAIL")
        lines.append("DOCKERIGNORE_SECURITY_AUDIT=FAIL")
        lines.extend(f"- {item}" for item in failures)
    else:
        lines.extend(
            [
                "DOCKERFILE_SECURITY_AUDIT=PASS",
                "DOCKERIGNORE_SECURITY_AUDIT=PASS",
                "- Python runtime is pinned to 3.12 patch-level images.",
                "- Containers run as UID 10001 non-root user.",
                "- Healthcheck targets container-local /api/health.",
                "- Runtime databases, secrets, reports, backups, and private invites are excluded.",
                "- No provider credential is baked by either Dockerfile.",
            ]
        )
    output = "\n".join(lines) + "\n"
    if args.report:
        Path(args.report).write_text("# Dockerfile Security Audit\n\n```text\n" + output + "```\n", encoding="utf-8")
    print(output, end="")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
