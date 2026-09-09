"""Add one hashed Basic Auth identity to an existing Caddy site config."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Keep the helper runnable both as a module and as a direct deployment-side
# script, without adding a package dependency to the application runtime.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.render_beta_caddy import BCRYPT_RE, USERNAME_RE


def augment_basic_auth(text: str, *, username: str, password_hash: str) -> str:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("CADDY_USERNAME_INVALID")
    if not BCRYPT_RE.fullmatch(password_hash):
        raise ValueError("CADDY_HASH_REQUIRED")
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.strip() == "basic_auth {"]
    if len(starts) != 1:
        raise ValueError("CADDY_EXPECTED_ONE_BASIC_AUTH_BLOCK")
    start = starts[0]
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip() == "}"), None)
    if end is None:
        raise ValueError("CADDY_BASIC_AUTH_UNCLOSED")
    identity_re = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]{2,63})\s+(\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53})\s*$")
    existing = [identity_re.fullmatch(lines[index].strip()) for index in range(start + 1, end)]
    if any(match and match.group(1) == username for match in existing):
        raise ValueError("CADDY_DUPLICATE_USERNAME")
    indent = "  "
    for index in range(start + 1, end):
        match = identity_re.fullmatch(lines[index].strip())
        if match:
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            break
    newline = "\n" if not lines or lines[end - 1].endswith("\n") else ""
    lines.insert(end, f"{indent}{username} {password_hash}{newline}")
    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--username", required=True)
    parser.add_argument("--hash-file", required=True, type=Path)
    args = parser.parse_args()
    password_hash = args.hash_file.read_text(encoding="utf-8").strip()
    rendered = augment_basic_auth(
        args.input.read_text(encoding="utf-8-sig"),
        username=args.username,
        password_hash=password_hash,
    )
    args.output.write_text(rendered, encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
