"""Safely verify a deployment-scoped HTTP Basic Auth edge identity.

The secret file is consumed in-process and is never included in the result,
logs, command line, or exception text.
"""

from __future__ import annotations

import argparse
import base64
import json
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def _read_secret(path: Path) -> tuple[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("EDGE_SECRET_UNAVAILABLE") from exc
    if len(lines) != 2 or not lines[0] or not lines[1]:
        raise RuntimeError("EDGE_SECRET_INVALID")
    return lines[0], lines[1]


def _basic_auth(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _request(url: str, authorization: str, timeout: float) -> tuple[int, bool]:
    request = urllib.request.Request(url, headers={"Authorization": authorization})
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return int(response.status), True
    except urllib.error.HTTPError as exc:
        return int(exc.code), True
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, False


def verify_target(
    *,
    target: str,
    url: str,
    secret_file: Path,
    request_fn: Callable[[str, str, float], tuple[int, bool]] = _request,
    timeout: float = 10.0,
) -> dict[str, object]:
    username, password = _read_secret(secret_file)
    try:
        status, tls_ok = request_fn(url, _basic_auth(username, password), timeout)
    finally:
        # Drop the local references before returning the sanitized receipt.
        username = ""
        password = ""
    return {
        "target": target,
        "http_status": status,
        "tls": "PASS" if tls_ok else "FAIL",
        "result": "PASS" if tls_ok and status == 200 else "FAIL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _safe_error(exc: BaseException) -> str:
    message = str(exc)
    if any(token in message.lower() for token in ("authorization", "basic ", "password", "secret")):
        return "EDGE_VERIFICATION_FAILED"
    return message or "EDGE_VERIFICATION_FAILED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--secret-file", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    try:
        result = verify_target(target=args.target, url=args.url, secret_file=args.secret_file)
    except Exception as exc:  # pragma: no cover - exercised through CLI smoke
        result = {
            "target": args.target,
            "http_status": 0,
            "tls": "FAIL",
            "result": "FAIL",
            "error": _safe_error(exc),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    output = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if args.receipt:
        args.receipt.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
