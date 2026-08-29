"""Run explicit paid-provider connectivity checks on the user's local machine.

The command is fail-closed: no provider request is sent unless the operator passes
``--confirm-live-calls``. It uses the real ModelProfileService and OS credential
backend, never prints credential values, and never substitutes mock adapters for a
live PASS.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

TARGET_PROVIDERS = ("qwen", "kimi", "deepseek", "glm")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate configured Qwen/Kimi/DeepSeek/GLM profiles with real provider calls."
    )
    parser.add_argument(
        "--confirm-live-calls",
        action="store_true",
        help="Explicitly authorize the minimal real API requests used by this verification run.",
    )
    return parser.parse_args(argv)


def safe_error(exc: Exception) -> str:
    """Return only a bounded, single-line error summary.

    Provider adapters are required to sanitize upstream payloads before raising.
    This final boundary intentionally avoids serializing exception repr/tracebacks.
    """

    text = str(exc).strip().replace("\n", " ").replace("\r", " ")
    return text[:300] if text else type(exc).__name__


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm_live_calls:
        print(
            "Live provider verification is disabled by default. "
            "Re-run with --confirm-live-calls only after authorizing the minimal real API requests.",
            file=sys.stderr,
        )
        return 2

    # Direct script execution sets sys.path[0] to scripts/. Add the project root so
    # the same command works from a freshly deployed package without PYTHONPATH.
    project_root = Path(__file__).resolve().parents[1]
    root_text = str(project_root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    from app.__main__ import _load_local_env
    from app.config import Settings
    from app.db import Database
    from app.services.credential_store import CredentialBackendUnavailable
    from app.services.model_profiles import ModelProfileService

    _load_local_env(project_root / ".env")
    settings = Settings.from_env()
    db = Database(settings.database_path)
    db.init_schema()
    service = ModelProfileService(db)

    try:
        profiles = service.list()
    except CredentialBackendUnavailable:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": "Windows credential storage is unavailable to this process.",
                    "secret_exposed": False,
                },
                ensure_ascii=False,
            )
        )
        return 2

    results: list[dict[str, Any]] = []
    for provider in TARGET_PROVIDERS:
        matches = [p for p in profiles if p["provider"] == provider and p["enabled"]]
        if not matches:
            results.append(
                {
                    "provider": provider,
                    "status": "SKIPPED",
                    "reason": "No enabled local model profile is configured for this provider.",
                    "secret_exposed": False,
                }
            )
            continue
        profile = matches[0]
        if profile["credential_status"] != "configured":
            results.append(
                {
                    "provider": provider,
                    "profile_id": profile["id"],
                    "model_id": profile["model_id"],
                    "status": "SKIPPED",
                    "reason": "Profile exists but no credential is configured.",
                    "secret_exposed": False,
                }
            )
            continue
        try:
            checked = service.live_test_connection(
                profile["id"], actor="local_live_provider_verifier"
            )
        except Exception as exc:  # service boundary must already redact provider payloads
            results.append(
                {
                    "provider": provider,
                    "profile_id": profile["id"],
                    "model_id": profile["model_id"],
                    "status": "FAIL",
                    "reason": safe_error(exc),
                    "secret_exposed": False,
                }
            )
            continue
        results.append(
            {
                "provider": provider,
                "profile_id": checked["profile_id"],
                "model_id": checked["model_requested"],
                "model_returned": checked["model_returned"],
                "status": checked["status"],
                "latency_ms": checked["latency_ms"],
                "content_received": checked["content_received"],
                "usage_available": checked["usage_available"],
                "error_code": checked["error_code"],
                "safe_message": checked["safe_message"],
                "retryable": checked["retryable"],
                "checked_at": checked["checked_at"],
                "secret_exposed": False,
            }
        )

    print(json.dumps({"providers": results}, ensure_ascii=False, indent=2))
    # Connectivity failures are evidence, not script crashes. Return nonzero only
    # when every actually configured provider check failed.
    configured = [item for item in results if item["status"] != "SKIPPED"]
    if configured and all(item["status"] == "FAIL" for item in configured):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
