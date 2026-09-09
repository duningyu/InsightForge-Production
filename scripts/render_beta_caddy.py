"""Render participant-isolated Caddy routes without accepting plaintext passwords."""

from __future__ import annotations

import argparse
import ipaddress
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.beta_runtime import validate_participant_id


USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
BCRYPT_RE = re.compile(r"^\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}$")


def _credential(value: str) -> tuple[str, str, str]:
    try:
        participant, username, password_hash = value.split(":", 2)
    except ValueError as exc:
        raise ValueError("CADDY_CREDENTIAL_INVALID") from exc
    validate_participant_id(participant)
    if not USERNAME_RE.fullmatch(username):
        raise ValueError("CADDY_USERNAME_INVALID")
    if not BCRYPT_RE.fullmatch(password_hash):
        raise ValueError("CADDY_HASH_REQUIRED")
    return participant, username, password_hash


def render(template: str, *, public_ip: str, credentials: list[str]) -> str:
    ipaddress.ip_address(public_ip)
    parsed = [_credential(item) for item in credentials]
    identities_by_participant: dict[str, list[tuple[str, str]]] = {}
    for participant, username, password_hash in parsed:
        identities = identities_by_participant.setdefault(participant, [])
        if any(existing_username == username for existing_username, _ in identities):
            raise ValueError("CADDY_DUPLICATE_USERNAME")
        identities.append((username, password_hash))
    blocks = []
    for participant in sorted(identities_by_participant):
        service = participant.replace("_", "")
        auth_lines = "\n".join(
            f"    {username} {password_hash}"
            for username, password_hash in identities_by_participant[participant]
        )
        blocks.append(
            f"{service}.{public_ip}.nip.io {{\n"
            "  basic_auth {\n"
            f"{auth_lines}\n"
            "  }\n"
            f"  reverse_proxy {service}:8000\n"
            "}"
        )
    if "{{SITES}}" not in template:
        raise ValueError("CADDY_TEMPLATE_SITES_MARKER_MISSING")
    return template.replace("{{SITES}}", "\n\n".join(blocks)).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", required=True)
    parser.add_argument("--public-ip", required=True)
    parser.add_argument("--credential", action="append", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        rendered = render(
            Path(args.template).read_text(encoding="utf-8"),
            public_ip=args.public_ip,
            credentials=args.credential,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
