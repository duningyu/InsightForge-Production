from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.beta_metrics import export_beta_metrics


def main() -> int:
    parser = argparse.ArgumentParser(description="Export privacy-safe InsightForge closed-beta metrics.")
    parser.add_argument("--instances-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    manifest = export_beta_metrics(args.instances_root, args.output_dir)
    print(json.dumps({
        "status": "PASS",
        "participant_instance_count": manifest["participant_instance_count"],
        "active_participant_count": manifest["active_participant_count"],
        "privacy_scan_status": manifest["privacy_scan_status"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
