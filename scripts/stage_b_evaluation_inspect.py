"""Read-only, sanitized Stage B evaluation receipt inspector.

This operator tool intentionally exposes metadata only.  It never prints the
private prompt/response artifact and never performs a provider operation.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.db import Database
from app.services.stage_b_evaluation import StageBEvaluationReceiptStore


def _database_path() -> Path:
    data_root = Path(os.environ.get("INSIGHTFORGE_DATA_ROOT", "data"))
    return data_root / "insightforge.sqlite3"


def inspect_receipt(database: Database, evaluation_id: str) -> dict[str, object]:
    row = StageBEvaluationReceiptStore(database=database).inspect(evaluation_id)
    allowed = {
        "evaluation_id", "execution_id", "evaluation_type", "execution_mode",
        "participant_id", "provider", "model", "operation", "retry_ordinal",
        "status", "dispatch_count", "transport_count", "transport_attempted",
        "latency_ms", "input_token_count", "output_token_count", "total_token_count",
        "failure_classification", "budget_before", "budget_consumed", "budget_after",
        "artifact_exists", "artifact_hash_available", "artifact_sha256",
        "artifact_persistence_status",
    }
    return {key: row.get(key) for key in sorted(allowed)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a Stage B receipt without payloads")
    parser.add_argument("evaluation_id")
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()
    database = Database(args.database or _database_path())
    print(json.dumps(inspect_receipt(database, args.evaluation_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
