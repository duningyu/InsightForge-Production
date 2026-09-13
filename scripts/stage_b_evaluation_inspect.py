"""Sanitized Stage B operator for receipt inspection and diagnostics.

Inspection and dry-check commands expose metadata only and never perform a
provider operation.  The explicit AI Reference shape command is the sole
operator entry point that invokes the existing product runtime; it still
prints only sanitized receipt metadata.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from app.db import Database
from app.services.document_versions import DocumentVersionService
from app.services.generation import LocalDocumentGenerator
from app.services.loop import DocumentLoop
from app.services.stage_b_evaluation import (
    DEFAULT_STAGE_B_TRANSPORT_BUDGET,
    CONTEXT_VERSION,
    INSIGHTFORGE_PROMPT_VERSION,
    STAGE_B_MODEL,
    STAGE_B_PARTICIPANT,
    STAGE_B_PROVIDER,
    StageBEvaluationContext,
    StageBEvaluationReceiptStore,
    StageBExecutionPolicy,
    StageBGuardError,
    evaluate_stage_b_guard,
)
from app.services.stage_b_synthetic_seed import (
    STAGE_B_PHASE1A_PARTICIPANT,
    StageBPhase1ASyntheticProjectSeedService,
)


PHASE2_PRD_CONFIRM = "PHASE2_PRD_CONFIRM"
PHASE2_TECHDOC_GENERATE = "PHASE2_TECHDOC_GENERATE"
PHASE2_TECHDOC_CONFIRM = "PHASE2_TECHDOC_CONFIRM"
PHASE2_HANDOFF = "PHASE2_HANDOFF"
PHASE2_OPERATIONS = (
    PHASE2_PRD_CONFIRM,
    PHASE2_TECHDOC_GENERATE,
    PHASE2_TECHDOC_CONFIRM,
    PHASE2_HANDOFF,
)


@dataclass(frozen=True)
class Phase2OperatorContext:
    """Typed identity passed between the future Phase 2 operator stages."""

    operation: Literal[
        "PHASE2_PRD_CONFIRM",
        "PHASE2_TECHDOC_GENERATE",
        "PHASE2_TECHDOC_CONFIRM",
        "PHASE2_HANDOFF",
    ]
    project_id: str
    actor: str
    idempotency_key: str


@dataclass(frozen=True)
class Phase2SafeReceiptMetadata:
    """Allowlisted Phase 2 receipt fields; never carries document content."""

    operation: str
    evaluation_id: str | None = None
    project_id: str | None = None
    selected_solution_id: str | None = None
    document_id: str | None = None
    version_id: str | None = None
    snapshot_id: str | None = None
    acknowledgement_id: str | None = None
    acknowledgement_content_sha256: str | None = None
    handoff_run_id: str | None = None
    package_sha256: str | None = None
    status: str | None = None
    counts: dict[str, int] | None = None
    terminal_stage: str | None = None


def sanitize_phase2_receipt_metadata(metadata: Phase2SafeReceiptMetadata) -> dict[str, object]:
    """Serialize only the typed, non-content Phase 2 receipt metadata."""
    return {key: value for key, value in asdict(metadata).items() if value is not None}


def _phase2_unimplemented(context: Phase2OperatorContext) -> Phase2SafeReceiptMetadata:
    raise StageBGuardError(f"{context.operation}_NOT_IMPLEMENTED")


def _phase2_prd_preflight(database: Database, project_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    project = database.fetch_one(
        "SELECT id, project_origin, exclude_from_beta_metrics, current_snapshot_id FROM projects WHERE id=?",
        (project_id,),
    )
    if project is None:
        raise KeyError("project not found")
    if project["project_origin"] not in {"demo", "qa"} or not bool(project["exclude_from_beta_metrics"]):
        raise StageBGuardError("STAGE_B_SYNTHETIC_PROJECT_REQUIRED")
    snapshot_id = project.get("current_snapshot_id")
    snapshot = database.fetch_one(
        "SELECT id, project_id, confirmed_at FROM project_snapshots WHERE id=? AND project_id=?",
        (snapshot_id, project_id),
    ) if snapshot_id else None
    if snapshot is None or not snapshot["confirmed_at"]:
        raise StageBGuardError("PHASE2_PRD_CURRENT_SNAPSHOT_REQUIRED")
    snapshot_health = database.fetch_one(
        "SELECT health_status FROM artifact_health WHERE artifact_type='project_snapshot' AND artifact_id=?",
        (snapshot_id,),
    )
    if snapshot_health is None or snapshot_health["health_status"] != "current":
        raise StageBGuardError("PHASE2_PRD_SNAPSHOT_NOT_CURRENT")
    selected = database.fetch_all(
        """
        SELECT candidate.id AS selected_solution_id
        FROM snapshot_decision_links AS link
        JOIN project_decisions AS decision ON decision.id=link.decision_id
        JOIN solution_candidates AS candidate ON candidate.id=decision.selected_option_id
        WHERE link.snapshot_id=? AND link.role='current_solution'
          AND decision.project_id=? AND decision.status='confirmed'
          AND candidate.project_id=?
        """,
        (snapshot_id, project_id, project_id),
    )
    if len(selected) != 1:
        raise StageBGuardError("PHASE2_PRD_SELECTED_SOLUTION_AMBIGUOUS")
    solution = selected[0]
    prds = database.fetch_all(
        """
        SELECT version.*
        FROM document_versions AS version
        JOIN artifact_dependencies AS dependency
          ON dependency.artifact_type='document_version'
         AND dependency.artifact_id=version.id
         AND dependency.dependency_type='project_snapshot'
         AND dependency.dependency_id=?
        WHERE version.project_id=? AND version.doc_type='prd'
          AND version.lifecycle_status='active' AND version.validation_status='passed'
        ORDER BY version.version DESC, version.id
        """,
        (snapshot_id, project_id),
    )
    if len(prds) != 1:
        raise StageBGuardError("PHASE2_PRD_CURRENT_VERSION_AMBIGUOUS")
    prd = prds[0]
    health = database.fetch_one(
        "SELECT health_status FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
        (prd["id"],),
    )
    if health is None or health["health_status"] != "current":
        raise StageBGuardError("PHASE2_PRD_VERSION_NOT_CURRENT")
    return project, snapshot, solution, prd


def _phase2_prd_result(
    *, evaluation_id: str, project_id: str, solution_id: str, snapshot_id: str, version: dict[str, Any]
) -> Phase2SafeReceiptMetadata:
    return Phase2SafeReceiptMetadata(
        operation=PHASE2_PRD_CONFIRM,
        evaluation_id=evaluation_id,
        project_id=project_id,
        selected_solution_id=solution_id,
        document_id=version["document_id"],
        version_id=version["id"],
        snapshot_id=snapshot_id,
        status=version["status"],
        counts={"confirmed": 1 if version["status"] == "approved" else 0},
        terminal_stage="PRD_CONFIRMED" if version["status"] == "approved" else "PRD_CONFIRMATION_INCOMPLETE",
    )


def run_confirm_prd_canary(*, database: Database, project_id: str, actor: str) -> Phase2SafeReceiptMetadata:
    project, snapshot, solution, prd = _phase2_prd_preflight(database, project_id)
    idempotency_key = "stage-b-phase2:prd-confirm:" + hashlib.sha256(
        f"{project_id}:{snapshot['id']}:{prd['id']}".encode("utf-8")
    ).hexdigest()
    context = Phase2OperatorContext(PHASE2_PRD_CONFIRM, project_id, actor, idempotency_key)
    evaluation_id = "phase2-prd-confirm-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    store = StageBEvaluationReceiptStore(database=database)
    existing_rows = database.fetch_all(
        "SELECT evaluation_id, status FROM stage_b_evaluation_receipts WHERE operation=? AND idea_id=?",
        (context.operation, project_id),
    )
    if len(existing_rows) > 1 or (
        existing_rows and existing_rows[0]["evaluation_id"] != evaluation_id
    ):
        raise StageBGuardError("PHASE2_PRD_CONFIRMATION_RECEIPT_AMBIGUOUS")
    existing = existing_rows[0] if existing_rows else None
    if existing is not None:
        if existing["status"] != "SUCCEEDED":
            raise StageBGuardError("PHASE2_PRD_CONFIRMATION_PREVIOUSLY_FAILED")
        confirmed = DocumentVersionService(database)._get(prd["id"])
        if confirmed["status"] != "approved":
            raise StageBGuardError("PHASE2_PRD_CONFIRMATION_RESULT_MISMATCH")
        return _phase2_prd_result(
            evaluation_id=evaluation_id, project_id=project_id,
            solution_id=solution["selected_solution_id"], snapshot_id=snapshot["id"], version=confirmed,
        )
    store.create(
        evaluation_id=evaluation_id, execution_id=evaluation_id, idea_id=project_id,
        evaluation_type=PHASE2_PRD_CONFIRM, execution_mode="INSIGHTFORGE",
        participant=STAGE_B_PARTICIPANT, provider=STAGE_B_PROVIDER, model=STAGE_B_MODEL,
        operation=PHASE2_PRD_CONFIRM, prompt_version=INSIGHTFORGE_PROMPT_VERSION,
        context_version=CONTEXT_VERSION, retry_ordinal=0,
        budget_before=DEFAULT_STAGE_B_TRANSPORT_BUDGET, prompt=None,
    )
    readback = StageBEvaluationReceiptStore(database=Database(database.path)).inspect(evaluation_id)
    if not (
        readback["status"] == "CREATED"
        and readback["idea_id"] == context.project_id
        and readback["operation"] == context.operation
        and readback["dispatch_count"] == 0
        and readback["transport_count"] == 0
        and not readback["transport_attempted"]
    ):
        raise StageBGuardError("PHASE2_PRD_CONFIRM_PRE_MUTATION_READBACK_FAILED")
    started_at = time.monotonic()
    try:
        confirmed = DocumentVersionService(database).confirm(
            prd["id"], actor=context.actor,
            note="Phase 2 PRD confirmation canary", human_confirmed=True,
        )
        store.mark_success(
            evaluation_id,
            response={
                "content": True, "kind": PHASE2_PRD_CONFIRM,
                "project_id": project_id, "snapshot_id": snapshot["id"],
                "version_id": confirmed["id"], "status": confirmed["status"],
            },
            started_at=started_at, response_timestamp=time.monotonic(),
        )
        store.write_artifact(
            evaluation_id, prompt=None,
            response={
                "kind": PHASE2_PRD_CONFIRM, "project_id": project_id,
                "snapshot_id": snapshot["id"], "version_id": confirmed["id"],
                "status": confirmed["status"],
            },
        )
        return _phase2_prd_result(
            evaluation_id=evaluation_id, project_id=project_id,
            solution_id=solution["selected_solution_id"], snapshot_id=snapshot["id"], version=confirmed,
        )
    except Exception as exc:
        safe_failure = StageBGuardError("PHASE2_PRD_CONFIRMATION_FAILED")
        try:
            store.mark_failure(
                evaluation_id, error=safe_failure,
                started_at=started_at, response_timestamp=time.monotonic(),
            )
            store.write_artifact(
                evaluation_id, prompt=None,
                response={"kind": PHASE2_PRD_CONFIRM, "failure": "CONFIRMATION_FAILED"},
            )
        except Exception:
            store.mark_artifact_failure(evaluation_id)
        raise safe_failure from exc


def run_local_techdoc_canary(*, database: Database, project_id: str, actor: str) -> Phase2SafeReceiptMetadata:
    project, snapshot, solution, prd = _phase2_prd_preflight(database, project_id)
    if prd["status"] != "approved":
        raise StageBGuardError("PHASE2_TECHDOC_CONFIRMED_PRD_REQUIRED")

    idempotency_key = "stage-b-phase2:techdoc-generate:" + hashlib.sha256(
        f"{project_id}:{snapshot['id']}:{solution['selected_solution_id']}:{prd['id']}".encode("utf-8")
    ).hexdigest()
    context = Phase2OperatorContext(PHASE2_TECHDOC_GENERATE, project_id, actor, idempotency_key)
    evaluation_id = "phase2-techdoc-generate-" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    store = StageBEvaluationReceiptStore(database=database)
    existing_rows = database.fetch_all(
        "SELECT evaluation_id, status FROM stage_b_evaluation_receipts WHERE operation=? AND idea_id=?",
        (context.operation, project_id),
    )
    if len(existing_rows) > 1 or (existing_rows and existing_rows[0]["evaluation_id"] != evaluation_id):
        raise StageBGuardError("PHASE2_TECHDOC_GENERATION_RECEIPT_AMBIGUOUS")
    existing = existing_rows[0] if existing_rows else None
    if existing is not None:
        if existing["status"] != "SUCCEEDED":
            raise StageBGuardError("PHASE2_TECHDOC_GENERATION_PREVIOUSLY_FAILED")
        version = database.fetch_one(
            "SELECT * FROM document_versions WHERE idempotency_key=? AND project_id=? AND doc_type='techdoc'",
            (idempotency_key, project_id),
        )
        if version is None:
            raise StageBGuardError("PHASE2_TECHDOC_GENERATION_RESULT_MISMATCH")
        return _phase2_techdoc_result(
            evaluation_id=evaluation_id, project_id=project_id,
            solution_id=solution["selected_solution_id"], snapshot_id=snapshot["id"], version=version,
        )

    store.create(
        evaluation_id=evaluation_id, execution_id=evaluation_id, idea_id=project_id,
        evaluation_type=PHASE2_TECHDOC_GENERATE, execution_mode="INSIGHTFORGE",
        participant=STAGE_B_PARTICIPANT, provider=STAGE_B_PROVIDER, model=STAGE_B_MODEL,
        operation=PHASE2_TECHDOC_GENERATE, prompt_version=INSIGHTFORGE_PROMPT_VERSION,
        context_version=CONTEXT_VERSION, retry_ordinal=0,
        budget_before=DEFAULT_STAGE_B_TRANSPORT_BUDGET,
        prompt=None,
    )
    readback = StageBEvaluationReceiptStore(database=Database(database.path)).inspect(evaluation_id)
    if not (
        readback["status"] == "CREATED"
        and readback["idea_id"] == context.project_id
        and readback["operation"] == context.operation
        and readback["dispatch_count"] == 0
        and readback["transport_count"] == 0
        and not readback["transport_attempted"]
    ):
        raise StageBGuardError("PHASE2_TECHDOC_PRE_MUTATION_READBACK_FAILED")
    # Keep the explicit evaluation context local to this operation.  The
    # DocumentLoop contract carries the same identity through its idempotency
    # key and snapshot binding; it has no provider context parameter.
    _ = StageBEvaluationContext(
        evaluation_id=evaluation_id, evaluation_type=PHASE2_TECHDOC_GENERATE,
        surface="TECHDOC", participant=STAGE_B_PARTICIPANT,
        execution_mode="INSIGHTFORGE", retry_ordinal=0, receipt_store=store,
    )
    started_at = time.monotonic()
    try:
        result = DocumentLoop(database, generator=LocalDocumentGenerator()).run(
            project_id, "techdoc", idempotency_key=idempotency_key,
            require_snapshot=True, competitor_snapshot_id=None,
            use_competitor_snapshot=False,
        )
        version = database.fetch_one(
            "SELECT * FROM document_versions WHERE id=? AND project_id=? AND doc_type='techdoc'",
            (result["version_id"], project_id),
        )
        if version is None or version["validation_status"] != "passed":
            raise StageBGuardError("PHASE2_TECHDOC_GENERATION_RESULT_INVALID")
        database.execute(
            """INSERT OR IGNORE INTO artifact_dependencies(
                   artifact_type, artifact_id, dependency_type, dependency_id,
                   dependency_version, created_at
               ) VALUES ('document_version', ?, 'prd_version', ?, ?, ?)""",
            (version["id"], prd["id"], prd["version"], version["created_at"]),
        )
        safe_response = {
            "content": True, "kind": PHASE2_TECHDOC_GENERATE,
            "project_id": project_id, "document_id": version["document_id"],
            "version_id": version["id"], "snapshot_id": snapshot["id"],
            "status": version["status"],
        }
        store.mark_success(
            evaluation_id, response=safe_response,
            started_at=started_at, response_timestamp=time.monotonic(),
        )
        store.write_artifact(evaluation_id, prompt=None, response=safe_response)
        return _phase2_techdoc_result(
            evaluation_id=evaluation_id, project_id=project_id,
            solution_id=solution["selected_solution_id"], snapshot_id=snapshot["id"], version=version,
        )
    except Exception as exc:
        safe_failure = StageBGuardError("PHASE2_TECHDOC_GENERATION_FAILED")
        try:
            store.mark_failure(
                evaluation_id, error=safe_failure,
                started_at=started_at, response_timestamp=time.monotonic(),
            )
            store.write_artifact(
                evaluation_id, prompt=None,
                response={"kind": PHASE2_TECHDOC_GENERATE, "failure": "GENERATION_FAILED"},
            )
        except Exception:
            store.mark_artifact_failure(evaluation_id)
        raise safe_failure from exc


def _phase2_techdoc_result(
    *, evaluation_id: str, project_id: str, solution_id: str, snapshot_id: str,
    version: dict[str, Any],
) -> Phase2SafeReceiptMetadata:
    return Phase2SafeReceiptMetadata(
        operation=PHASE2_TECHDOC_GENERATE, evaluation_id=evaluation_id,
        project_id=project_id, selected_solution_id=solution_id,
        document_id=version["document_id"], version_id=version["id"],
        snapshot_id=snapshot_id, status="completed",
        counts={"generated": 1}, terminal_stage="TECHDOC_GENERATED",
    )


def run_confirm_techdoc_canary(*, database: Database, project_id: str, actor: str) -> Phase2SafeReceiptMetadata:
    return _phase2_unimplemented(Phase2OperatorContext(PHASE2_TECHDOC_CONFIRM, project_id, actor, ""))


def run_handoff_canary(*, database: Database, project_id: str, actor: str) -> Phase2SafeReceiptMetadata:
    return _phase2_unimplemented(Phase2OperatorContext(PHASE2_HANDOFF, project_id, actor, ""))


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
        "dispatch_permit_id", "dispatch_evaluation_id", "failure_stage",
        "output_contract_attempted", "decode_status", "schema_validation",
        "application_postprocess",
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


def run_ai_reference_shape_canary(
    *,
    database: Database,
    project_id: str,
    actor: str,
    runtime: object,
    ai_reference_service: object | None = None,
    participant: str = STAGE_B_PARTICIPANT,
    real_provider_stage_b: bool = True,
    safe_fixture_mode: bool = False,
    accounts_enabled: bool = False,
    receipt_store_factory: Callable[[Database], StageBEvaluationReceiptStore] | None = None,
) -> dict[str, object]:
    """Run the internal Stage-B AI Reference path with durable preflight.

    This function is intentionally an operator primitive, not an HTTP handler.
    The runtime and service are injected so tests can exercise the exact
    coordination boundary without ever contacting a provider.
    """
    evaluate_stage_b_guard(
        real_provider_stage_b=real_provider_stage_b,
        safe_fixture_mode=safe_fixture_mode,
        accounts_enabled=accounts_enabled,
        participant_id=participant,
    )
    database.init_schema()
    store_factory = receipt_store_factory or (lambda db: StageBEvaluationReceiptStore(database=db))
    store = store_factory(database)
    budget_before = DEFAULT_STAGE_B_TRANSPORT_BUDGET - store.consumed_count()
    if budget_before < 0:
        raise StageBGuardError("STAGE_B_TRANSPORT_BUDGET_EXHAUSTED")
    evaluation_id = f"ai-reference-shape-{uuid.uuid4().hex}"
    store.create(
        evaluation_id=evaluation_id,
        execution_id=evaluation_id,
        idea_id=project_id,
        evaluation_type="AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY",
        execution_mode="INSIGHTFORGE",
        participant=participant,
        provider=STAGE_B_PROVIDER,
        model=STAGE_B_MODEL,
        operation="ai_reference",
        prompt_version=INSIGHTFORGE_PROMPT_VERSION,
        context_version=CONTEXT_VERSION,
        retry_ordinal=0,
        budget_before=budget_before,
        prompt=None,
    )

    # A separate connection is deliberately used before any product call.
    readback = store_factory(Database(database.path)).inspect(evaluation_id)
    if not (
        readback["status"] == "CREATED"
        and readback["dispatch_count"] == 0
        and readback["transport_count"] == 0
        and not readback["transport_attempted"]
    ):
        raise StageBGuardError("AI_REFERENCE_EVALUATION_PRE_TRANSPORT_READBACK_FAILED")

    store.artifact_root.mkdir(parents=True, exist_ok=True)
    if not os.access(store.artifact_root, os.W_OK):
        raise StageBGuardError("PRIVATE_ARTIFACT_TARGET_NOT_WRITABLE")
    context = StageBEvaluationContext(
        evaluation_id=evaluation_id,
        evaluation_type="AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY",
        surface="AI_REFERENCE",
        participant=participant,
        execution_mode="INSIGHTFORGE",
        retry_ordinal=0,
        receipt_store=store,
    )
    service = ai_reference_service
    if service is None:
        from app.services.ai_reference import AIReferenceService
        service = AIReferenceService(database)
    started_at = time.monotonic()
    try:
        service.generate(
            project_id,
            actor=actor,
            runtime=runtime,
            idempotency_key=None,
            evaluation_context=context,
        )
        safe_shape = dict(getattr(runtime, "last_provider_diagnostic", {}) or {})
        store.mark_success(
            evaluation_id,
            response={"content": True, "safe_shape": safe_shape},
            started_at=started_at,
            response_timestamp=time.monotonic(),
        )
        store.write_artifact(
            evaluation_id,
            prompt=None,
            response={"kind": "AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY", "safe_shape": safe_shape},
        )
        return inspect_receipt(database, evaluation_id)
    except Exception as exc:
        try:
            store.mark_failure(
                evaluation_id,
                error=exc,
                started_at=started_at,
                response_timestamp=time.monotonic(),
            )
            store.write_artifact(
                evaluation_id,
                prompt=None,
                response={
                    "kind": "AI_REFERENCE_SHAPE_DIAGNOSTIC_CANARY",
                    "safe_shape": dict(getattr(runtime, "last_provider_diagnostic", {}) or {}),
                },
            )
        except Exception:
            store.mark_artifact_failure(evaluation_id)
        raise


def _run_ai_reference_shape_canary_cli(args: argparse.Namespace) -> int:
    from app.main import create_app

    async def run() -> dict[str, object]:
        application = create_app(database_path=args.database, seed=False)
        async with application.router.lifespan_context(application):
            return run_ai_reference_shape_canary(
                database=application.state.db,
                project_id=args.project_id,
                actor=args.actor,
                runtime=application.state.structured_runtime,
                ai_reference_service=application.state.ai_reference,
                participant=os.environ.get("BETA_PARTICIPANT_ID", ""),
                real_provider_stage_b=_env_bool("REAL_PROVIDER_STAGE_B"),
                safe_fixture_mode=_env_bool("INSIGHTFORGE_SAFE_FIXTURE_MODE"),
                accounts_enabled=_env_bool("INSIGHTFORGE_ACCOUNTS_ENABLED"),
            )

    output = asyncio.run(run())
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def _create_product_flow_evaluation(
    *, database: Database, project_id: str, participant: str, evaluation_type: str,
    operation: str, surface: str,
    real_provider_stage_b: bool = True, safe_fixture_mode: bool = False,
    accounts_enabled: bool = False,
    receipt_store_factory: Callable[[Database], StageBEvaluationReceiptStore] | None = None,
) -> tuple[str, StageBEvaluationReceiptStore, StageBEvaluationContext]:
    """Create and independently read back a product-flow receipt before dispatch."""
    evaluate_stage_b_guard(
        real_provider_stage_b=real_provider_stage_b,
        safe_fixture_mode=safe_fixture_mode,
        accounts_enabled=accounts_enabled,
        participant_id=participant,
    )
    database.init_schema()
    project = database.fetch_one(
        "SELECT id, project_origin, exclude_from_beta_metrics FROM projects WHERE id = ?",
        (project_id,),
    )
    if project is None:
        raise KeyError("project not found")
    if project.get("project_origin") not in {"demo", "qa"} or not bool(project.get("exclude_from_beta_metrics")):
        raise StageBGuardError("STAGE_B_SYNTHETIC_PROJECT_REQUIRED")
    factory = receipt_store_factory or (lambda db: StageBEvaluationReceiptStore(database=db))
    store = factory(database)
    budget_before = DEFAULT_STAGE_B_TRANSPORT_BUDGET - store.consumed_count()
    if budget_before < 0:
        raise StageBGuardError("STAGE_B_TRANSPORT_BUDGET_EXHAUSTED")
    evaluation_id = f"{operation}-{uuid.uuid4().hex}"
    store.create(
        evaluation_id=evaluation_id, execution_id=evaluation_id, idea_id=project_id,
        evaluation_type=evaluation_type, execution_mode="INSIGHTFORGE",
        participant=participant, provider=STAGE_B_PROVIDER, model=STAGE_B_MODEL,
        operation=operation, prompt_version=INSIGHTFORGE_PROMPT_VERSION,
        context_version=CONTEXT_VERSION, retry_ordinal=0,
        budget_before=budget_before, prompt=None,
    )
    readback = factory(Database(database.path)).inspect(evaluation_id)
    if not (
        readback["status"] == "CREATED"
        and readback["dispatch_count"] == 0
        and readback["transport_count"] == 0
        and not readback["transport_attempted"]
    ):
        raise StageBGuardError("PRODUCT_FLOW_EVALUATION_PRE_TRANSPORT_READBACK_FAILED")
    store.artifact_root.mkdir(parents=True, exist_ok=True)
    if not os.access(store.artifact_root, os.W_OK):
        raise StageBGuardError("PRIVATE_ARTIFACT_TARGET_NOT_WRITABLE")
    context = StageBEvaluationContext(
        evaluation_id=evaluation_id, evaluation_type=evaluation_type,
        surface=surface, participant=participant,
        execution_mode="INSIGHTFORGE", retry_ordinal=0, receipt_store=store,
    )
    return evaluation_id, store, context


def run_solutions_canary(
    *, database: Database, project_id: str, actor: str, solution_service: object,
    participant: str = STAGE_B_PARTICIPANT, receipt_store_factory: Callable[[Database], StageBEvaluationReceiptStore] | None = None,
    real_provider_stage_b: bool = True, safe_fixture_mode: bool = False,
    accounts_enabled: bool = False,
) -> dict[str, object]:
    """Coordinate one Stage-B Solutions execution through the existing service."""
    evaluation_id, store, context = _create_product_flow_evaluation(
        database=database, project_id=project_id, participant=participant,
        evaluation_type="SOLUTIONS_CANARY", operation="solutions_generation",
        surface="SOLUTIONS",
        real_provider_stage_b=real_provider_stage_b, safe_fixture_mode=safe_fixture_mode,
        accounts_enabled=accounts_enabled,
        receipt_store_factory=receipt_store_factory,
    )
    started_at = time.monotonic()
    try:
        result = solution_service.generate(
            project_id, actor=actor, evaluation_context=context,
            execution_policy=StageBExecutionPolicy(
                validation_regeneration_allowed=False, max_provider_transports=1,
            ), use_competitor_snapshot=False,
        )
        store.mark_success(
            evaluation_id, response={"content": bool(result), "kind": "SOLUTIONS_CANARY"},
            started_at=started_at, response_timestamp=time.monotonic(),
        )
        store.write_artifact(
            evaluation_id, prompt=None,
            response={"kind": "SOLUTIONS_CANARY", "project_id": project_id, "result_present": bool(result)},
        )
        return inspect_receipt(database, evaluation_id)
    except Exception as exc:
        store.mark_failure(evaluation_id, error=exc, started_at=started_at, response_timestamp=time.monotonic())
        store.write_artifact(evaluation_id, prompt=None, response={"kind": "SOLUTIONS_CANARY", "failure": type(exc).__name__})
        raise


def run_local_prd_canary(
    *, database: Database, project_id: str, actor: str, document_loop: object,
    participant: str = STAGE_B_PARTICIPANT, receipt_store_factory: Callable[[Database], StageBEvaluationReceiptStore] | None = None,
    real_provider_stage_b: bool = True, safe_fixture_mode: bool = False,
    accounts_enabled: bool = False,
) -> dict[str, object]:
    """Run the provider-free local PRD path with a durable Stage-B receipt."""
    evaluate_stage_b_guard(
        real_provider_stage_b=real_provider_stage_b, safe_fixture_mode=safe_fixture_mode,
        accounts_enabled=accounts_enabled, participant_id=participant,
    )
    project = database.fetch_one("SELECT current_snapshot_id FROM projects WHERE id = ?", (project_id,))
    if project is None:
        raise KeyError("project not found")
    if not project.get("current_snapshot_id"):
        raise StageBGuardError("SELECTED_SOLUTION_SNAPSHOT_REQUIRED")
    evaluation_id, store, _context = _create_product_flow_evaluation(
        database=database, project_id=project_id, participant=participant,
        evaluation_type="LOCAL_PRD_CANARY", operation="local_prd_generation",
        surface="PRD",
        real_provider_stage_b=real_provider_stage_b, safe_fixture_mode=safe_fixture_mode,
        accounts_enabled=accounts_enabled,
        receipt_store_factory=receipt_store_factory,
    )
    started_at = time.monotonic()
    try:
        result = document_loop.run(
            project_id, "prd",
            idempotency_key=f"stage-b-local-prd:{evaluation_id}",
            require_snapshot=True, use_competitor_snapshot=False,
        )
        store.mark_success(
            evaluation_id, response={"content": bool(result), "kind": "LOCAL_PRD_CANARY"},
            started_at=started_at, response_timestamp=time.monotonic(),
        )
        store.write_artifact(
            evaluation_id, prompt=None,
            response={"kind": "LOCAL_PRD_CANARY", "project_id": project_id, "result_present": bool(result)},
        )
        return inspect_receipt(database, evaluation_id)
    except Exception as exc:
        store.mark_failure(evaluation_id, error=exc, started_at=started_at, response_timestamp=time.monotonic())
        store.write_artifact(evaluation_id, prompt=None, response={"kind": "LOCAL_PRD_CANARY", "failure": type(exc).__name__})
        raise


def _run_solutions_canary_cli(args: argparse.Namespace) -> int:
    from app.main import create_app

    async def run() -> dict[str, object]:
        application = create_app(database_path=args.database, seed=False)
        async with application.router.lifespan_context(application):
            return run_solutions_canary(
                database=application.state.db, project_id=args.project_id,
                actor=args.actor, solution_service=application.state.solution_design,
                participant=os.environ.get("BETA_PARTICIPANT_ID", ""),
                real_provider_stage_b=_env_bool("REAL_PROVIDER_STAGE_B"),
                safe_fixture_mode=_env_bool("INSIGHTFORGE_SAFE_FIXTURE_MODE"),
                accounts_enabled=_env_bool("INSIGHTFORGE_ACCOUNTS_ENABLED"),
            )

    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
    return 0


def _run_local_prd_canary_cli(args: argparse.Namespace) -> int:
    from app.main import create_app

    async def run() -> dict[str, object]:
        application = create_app(database_path=args.database, seed=False)
        async with application.router.lifespan_context(application):
            return run_local_prd_canary(
                database=application.state.db, project_id=args.project_id,
                actor=args.actor, document_loop=application.state.document_loop,
                participant=os.environ.get("BETA_PARTICIPANT_ID", ""),
                real_provider_stage_b=_env_bool("REAL_PROVIDER_STAGE_B"),
                safe_fixture_mode=_env_bool("INSIGHTFORGE_SAFE_FIXTURE_MODE"),
                accounts_enabled=_env_bool("INSIGHTFORGE_ACCOUNTS_ENABLED"),
            )

    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
    return 0


_PHASE2_COMMANDS = {
    "confirm-prd-canary": (PHASE2_PRD_CONFIRM, run_confirm_prd_canary),
    "local-techdoc-canary": (PHASE2_TECHDOC_GENERATE, run_local_techdoc_canary),
    "confirm-techdoc-canary": (PHASE2_TECHDOC_CONFIRM, run_confirm_techdoc_canary),
    "handoff-canary": (PHASE2_HANDOFF, run_handoff_canary),
}


def _phase2_parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"Run the internal Stage-B {command} operator")
    parser.add_argument(command, nargs="?")
    parser.add_argument("--database", type=Path, default=_database_path())
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--actor", default="stage-b-operator")
    return parser


def _run_phase2_canary_cli(args: argparse.Namespace, command: str) -> int:
    _operation, runner = _PHASE2_COMMANDS[command]
    result = runner(database=Database(args.database), project_id=args.project_id, actor=args.actor)
    print(json.dumps(sanitize_phase2_receipt_metadata(result), ensure_ascii=False, indent=2))
    return 0


def _run_seed_phase1a_project_cli(args: argparse.Namespace) -> int:
    database = Database(args.database)
    database.init_schema()
    result = StageBPhase1ASyntheticProjectSeedService(database).seed(
        participant=args.participant,
        actor=args.actor,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--help"]:
        parser = argparse.ArgumentParser(description="Inspect Stage-B evaluation metadata or run an internal diagnostic")
        parser.add_argument(
            "command",
            nargs="?",
            choices=("inspect", "inspect-provider-attempt", "dry-create", "ai-reference-shape-canary", "solutions-canary", "local-prd-canary", "seed-phase1a-project", *_PHASE2_COMMANDS),
            help="operator command (the diagnostic command requires its own arguments)",
        )
        parser.print_help()
        return 0
    command = argv[0] if argv and argv[0] in {"inspect", "inspect-provider-attempt", "dry-create", "ai-reference-shape-canary", "solutions-canary", "local-prd-canary", "seed-phase1a-project", *_PHASE2_COMMANDS} else "inspect"
    if command == "seed-phase1a-project":
        parser = argparse.ArgumentParser(description="Create the internal Stage-B Phase1A synthetic canary project")
        parser.add_argument("seed-phase1a-project", nargs="?")
        parser.add_argument("--database", type=Path, default=_database_path())
        parser.add_argument("--participant", default=STAGE_B_PHASE1A_PARTICIPANT)
        parser.add_argument("--actor", default="stage-b-operator")
        if "--help" in argv[1:]:
            parser.print_help()
            return 0
        return _run_seed_phase1a_project_cli(parser.parse_args(argv[1:]))
    if command in {"solutions-canary", "local-prd-canary"}:
        parser = argparse.ArgumentParser(description=f"Run the internal Stage-B {command} operator")
        parser.add_argument(command, nargs="?")
        parser.add_argument("--database", type=Path, default=_database_path())
        parser.add_argument("--project-id", required=True)
        parser.add_argument("--actor", default="stage-b-operator")
        if "--help" in argv[1:]:
            parser.print_help()
            return 0
        args = parser.parse_args(argv[1:])
        return _run_solutions_canary_cli(args) if command == "solutions-canary" else _run_local_prd_canary_cli(args)
    if command in _PHASE2_COMMANDS:
        parser = _phase2_parser(command)
        if "--help" in argv[1:]:
            parser.print_help()
            return 0
        try:
            args = parser.parse_args(argv[1:])
        except SystemExit as exc:
            return int(exc.code)
        return _run_phase2_canary_cli(args, command)
    if command == "ai-reference-shape-canary":
        parser = argparse.ArgumentParser(description="Run the internal Stage-B AI Reference shape diagnostic")
        parser.add_argument("ai-reference-shape-canary", nargs="?")
        parser.add_argument("--database", type=Path, default=_database_path())
        parser.add_argument("--project-id", required=True)
        parser.add_argument("--actor", default="stage-b-operator")
        return _run_ai_reference_shape_canary_cli(parser.parse_args(argv[1:]))
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
