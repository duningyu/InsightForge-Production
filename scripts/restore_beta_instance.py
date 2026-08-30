"""Restore one stopped participant instance from a validated snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.beta_backup import BetaBackupError, restore_participant


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", required=True)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--instances-root", required=True)
    parser.add_argument("--prebackup-output-dir", required=True)
    parser.add_argument("--confirm-instance-stopped", action="store_true")
    args = parser.parse_args()
    try:
        receipt = restore_participant(
            instances_root=args.instances_root,
            participant_id=args.participant,
            backup_database=args.backup,
            manifest_path=args.manifest,
            prebackup_output_dir=args.prebackup_output_dir,
            instance_stopped=args.confirm_instance_stopped,
        )
    except (BetaBackupError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
