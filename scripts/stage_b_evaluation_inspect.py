"""Read-only, sanitized Stage B evaluation receipt inspector.

This operator tool intentionally exposes metadata only.  It never prints the
private prompt/response artifact and never performs a provider operation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

from app.db import Database
from app.services.stage_b_evaluation import (
    DEFAULT_STAGE_B_TRANSPORT_BUDGET,
    StageBEvaluationReceiptStore,
    StageBGuardError,
    evaluate_stage_b_guard,
)


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
        "artifact_bytes", "artifact_persistence_status",
    }
    return {key: row.get(key) for key in sorted(allowed)}


def inspect_provider_attempt(database: Database, attempt_id: str) -> dict[str, object]:
    """Return provider-attempt metadata, including shape only, never bodies."""
    with database.connect() as connection:
        row = connection.execute(
            """
            SELECT provider_attempt_id, model_id, elapsed_ms, response_headers_observed,
                   exception_class, failure_stage, safe_response_shape_json
            FROM provider_attempts
            WHERE provider_attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
    if row is None:
        raise KeyError(f"provider attempt not found: {attempt_id}")
    return {
        "provider_attempt_id": row["provider_attempt_id"],
        "model_id": row["model_id"],
        "elapsed_ms": row["elapsed_ms"],
        "response_headers_observed": bool(row["response_headers_observed"]),
        "exception_class": row["exception_class"],
        "failure_stage": row["failure_stage"],
        "safe_response_shape": json.loads(row["safe_response_shape_json"] or "{}"),
    }


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_dry_scope() -> str:
    participant = os.environ.get("BETA_PARTICIPANT_ID")
    evaluate_stage_b_guard(
        real_provider_stage_b=_env_bool("REAL_PROVIDER_STAGE_B"),
        safe_fixture_mode=_env_bool("INSIGHTFORGE_SAFE_FIXTURE_MODE"),
        accounts_enabled=_env_bool("INSIGHTFORGE_ACCOUNTS_ENABLED"),
        participant_id=participant,
    )
    return participant or ""


def _dry_create(database: Database, *, as_json: bool) -> int:
    participant = _require_dry_scope()
    evaluation_id = f"dry-{uuid.uuid4().hex}"
    store = StageBEvaluationReceiptStore(database=database)
    row = store.create_dry_check(
        evaluation_id=evaluation_id,
        idea_id="OBSERVABILITY_CLOUD_DRY_CHECK",
        participant=participant,
        max_transports=DEFAULT_STAGE_B_TRANSPORT_BUDGET,
    )
    output = inspect_receipt(database, evaluation_id)
    if as_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for key in (
            "evaluation_id", "status", "evaluation_type", "execution_mode",
            "artifact_sha256", "artifact_bytes", "budget_before", "budget_after",
            "dispatch_count", "transport_count", "transport_attempted",
        ):
            print(f"{key}={output.get(key)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv and argv[0] in {"inspect", "inspect-provider-attempt", "dry-create"} else "inspect"
    if command == "dry-create":
        parser = argparse.ArgumentParser(description="Create a Stage-B dry observability receipt")
        parser.add_argument("dry-create", nargs="?")
        parser.add_argument("--database", type=Path, default=None)
        parser.add_argument("--json", action="store_true")
        args = parser.parse_args(argv[1:])
        database = Database(args.database or _database_path())
        database.init_schema()
        return _dry_create(database, as_json=args.json)

    if command == "inspect-provider-attempt":
        parser = argparse.ArgumentParser(description="Inspect a provider attempt without payloads")
        parser.add_argument("attempt_id")
        parser.add_argument("--database", type=Path, default=None)
        args = parser.parse_args(argv[1:])
        database = Database(args.database or _database_path())
        print(json.dumps(inspect_provider_attempt(database, args.attempt_id), ensure_ascii=False, indent=2))
        return 0

    parser = argparse.ArgumentParser(description="Inspect a Stage B receipt without payloads")
    if command == "inspect":
        argv = argv[1:]
    parser.add_argument("evaluation_id")
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args(argv)
    database = Database(args.database or _database_path())
    print(json.dumps(inspect_receipt(database, args.evaluation_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
