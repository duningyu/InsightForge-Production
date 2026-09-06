"""Offline targeted regression entrypoint; never load production configuration.

Only loopback sockets (including Windows asyncio socketpair) are allowed.
Tests use temporary databases and fake adapter transports; no deployment tests.
"""
import os
from pathlib import Path
import socket
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    sys.path.insert(0, str(root))
    for key in list(os.environ):
        if key.startswith(("INSIGHTFORGE_", "BETA_", "MANAGED_", "OPENAI_")) or any(
            marker in key.upper() for marker in ("API_KEY", "TOKEN", "PASSWORD")
        ):
            os.environ.pop(key, None)
    original = socket.socket.connect
    blocked = []

    def guarded(sock, address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            blocked.append("external-connect-blocked")
            raise AssertionError("External network prohibited in offline regression")
        return original(sock, address)

    socket.socket.connect = guarded
    socket.socket.connect_ex = guarded
    files = [
        "test_open_accounts.py",
        "test_account_workspace_lifecycle.py",
        "test_account_business_paths.py",
        "test_account_registry_boundaries.py", "test_v3_schema_migration.py",
        "test_open_test_usage.py", "test_beta_rate_limits.py", "test_p0_hotfix_red.py",
        "test_pilot_p0_hotfix_red.py", "test_async_generation.py",
        "test_durable_solution_generation_idempotency.py",
        "test_provider_dispatch_ledger.py", "test_server_bound_acceptance_context.py",
        "test_server_bound_acceptance_context_red.py",
        "test_normal_dispatch_control_integration.py", "test_normal_dispatch_control_red.py",
        "test_v4_document_evidence_ux.py", "test_v2_document_lifecycle.py",
        "test_v3_handoff_and_tools.py", "test_v3_document_health.py",
    ]
    if len(sys.argv) > 1:
        selected = sys.argv[1:]
        if any(name not in files for name in selected):
            raise SystemExit("Select only a named test file from the offline allowlist")
        files = selected
    with tempfile.TemporaryDirectory(prefix="insightforge-open-test-") as directory:
        os.environ["INSIGHTFORGE_DATABASE_PATH"] = str(Path(directory) / "default.sqlite3")
        os.environ["RUNTIME_DIR"] = str(Path(directory) / "runtime")
        import pytest
        result = pytest.main(["-q", *[str(root / "tests" / f) for f in files]])
    print(f"Network tripwire: blocked_external_attempts={len(blocked)}; real_external_connections=0")
    return result or (1 if blocked else 0)


if __name__ == "__main__":
    raise SystemExit(main())
