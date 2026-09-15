#!/usr/bin/env python3
"""CLI-only safe metadata inspector for an IF Guide R1.1 M2 project."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import Database  # noqa: E402
from app.services.if_guide_m2_inspector import IFGuideM2Inspector  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect safe IF Guide R1.1 M2 metadata")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--actor")
    parser.add_argument(
        "--database-path",
        default=os.environ.get("INSIGHTFORGE_DATABASE_PATH")
        or os.environ.get("DATABASE_PATH")
        or "insightforge.sqlite3",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = IFGuideM2Inspector(Database(Path(args.database_path))).inspect_project(
        args.project_id, actor=args.actor
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
