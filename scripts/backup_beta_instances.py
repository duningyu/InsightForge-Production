"""Create one validated, participant-scoped closed-beta SQLite snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.beta_backup import BetaBackupError, backup_participant


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instances-root", required=True)
    parser.add_argument("--participant", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--release-id", required=True)
    args = parser.parse_args()
    try:
        receipt = backup_participant(
            instances_root=args.instances_root,
            participant_id=args.participant,
            output_dir=args.output_dir,
            release_id=args.release_id,
        )
    except (BetaBackupError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
