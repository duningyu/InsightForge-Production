from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from app.db import Database, utc_now
from app.services.decisions import DecisionService
from app.services.projects import ProjectService
from app.services.solution_design import SolutionDesignService
from app.services.stage_b_evaluation import StageBExecutionPolicy
from app.services.handoff import HandoffService
from app.services.evaluation_policy import EvaluationExecutionPolicy
from app.services.quick_start import QuickStartService
from app.schemas import QuickStartRequest
from app.services.real_idea_budget import (
    BATCH_EARMARK,
    BOUND,
    EXTENSION_CREDITS,
    EXTENSION_ID,
    RealIdeaBudgetService,
    UNBOUND_RESTRICTED,
)


BATCH_STATES = frozenset({"CREATED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "STOPPED", "FINALIZED"})
SAMPLE_STATES = frozenset({
    "QUICKSTART_PENDING", "AWAITING_BRIEF_REVIEW", "OPERATIONAL_INCOMPLETE",
    "AWAITING_SOLUTION_REVIEW", "COMPLETED", "PARTIAL", "FAILED", "STOPPED",
    "WITHDRAWN", "FINALIZED",
})
SAMPLE_KEYS = ("REAL_IDEA_01", "REAL_IDEA_02", "REAL_IDEA_03")
SAMPLE_SOURCE_TYPES = {
    "REAL_IDEA_01": "project_owner_real_product_idea",
    "REAL_IDEA_02": "student_internship_job_seeker_idea",
    "REAL_IDEA_03": "career_switcher_junior_pm_idea",
}


class ExpectedSeedFailure(RuntimeError):
    """Testable failure point proving sample creation is atomic."""


class ReviewGateError(ValueError):
    """A required human review or exact artifact binding is missing."""


@dataclass(frozen=True, slots=True)
class BatchRecord:
    batch_id: str
    status: str


@dataclass(frozen=True, slots=True)
class SampleRecord:
    sample_id: str
    batch_id: str
    sample_key: str
    project_id: str
    raw_idea_sha256: str
    state: str
    budget_allocation_id: str


@dataclass(frozen=True, slots=True)
class SolutionsReviewResult:
    sample_id: str
    status: str
    solution_count: int
    transport_count: int
    evaluation_id: str


@dataclass(frozen=True, slots=True)
class SelectionReviewResult:
    sample_id: str
    selected_solution_id: str
    selected_solution_ordinal: int
    provider_transport_count: int


@dataclass(frozen=True, slots=True)
class EvidenceAcknowledgement:
    sample_id: str
    acknowledgement_id: str
    confirmed: bool
    externally_verified: bool
    provider_transport_count: int
    prd_version_id: str
    techdoc_version_id: str
    snapshot_id: str


@dataclass(frozen=True, slots=True)
class FeedbackAttestation:
    sample_id: str
    attested_by: str
    used_as_requirement_ground_truth: bool
    provider_transport_count: int


@dataclass(frozen=True, slots=True)
class BatchFinalization:
    status: str
    reasons: tuple[str, ...]
    sample_statuses: dict[str, str]
    budget_summary: dict[str, Any]
    integrity_summary: dict[str, Any]


class RealIdeaEvaluationService:
    """Internal, isolated lifecycle for a real-idea evaluation sample.

    This service owns evaluation state, project birth, bounded Solutions review,
    and human review attestations.  It does not expose an HTTP route.
    """

    def __init__(self, database: Database, *, durable_budget: int, actor: str = "real_idea_evaluation"):
        self.database = database
        self.actor = actor
        self.projects = ProjectService(database)
        self.budget = RealIdeaBudgetService(database, durable_budget=durable_budget)
        self._integrity_violations: dict[str, set[str]] = {}

    def create_batch_with_slots(
        self,
        *,
        batch_id: str,
        source_commit: str,
        deployment_id: str,
        extension_id: str = EXTENSION_ID,
        actor: str | None = None,
    ) -> BatchRecord:
        """Create the fixed Real Idea batch and its empty slots atomically.

        This is the only mutation path for creating the evaluation batch.  It
        deliberately does not create a project, brief, reservation, or raw
        idea; those belong to the later per-sample lifecycle.
        """
        if batch_id != "REAL_IDEA_BATCH_01":
            raise ValueError("only REAL_IDEA_BATCH_01 is supported")
        if extension_id != EXTENSION_ID:
            raise ValueError("only the approved Real Idea extension is supported")
        if not isinstance(source_commit, str) or not source_commit.strip():
            raise ValueError("source_commit is required")
        if not isinstance(deployment_id, str) or not deployment_id.strip():
            raise ValueError("deployment_id is required")

        manifest = self._build_batch_manifest(batch_id, source_commit.strip(), deployment_id.strip())
        created_by = actor or self.actor
        empty_raw_hash = hashlib.sha256(b"").hexdigest()
        now = utc_now()

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT batch_id, status, manifest_sha256 FROM real_idea_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
            if existing:
                if self._is_complete_empty_batch_tx(connection, batch_id, manifest):
                    return BatchRecord(existing["batch_id"], existing["status"])
                raise ValueError("Real Idea batch already exists but is incomplete or conflicts")

            extension = connection.execute(
                "SELECT extension_id, authorized_credits, state, bound_batch_id "
                "FROM real_idea_budget_extensions WHERE extension_id = ?",
                (extension_id,),
            ).fetchone()
            if not extension:
                raise ValueError("approved restricted extension is missing")
            if extension["state"] != UNBOUND_RESTRICTED:
                raise ValueError("approved restricted extension is not unbound")
            if int(extension["authorized_credits"]) != EXTENSION_CREDITS:
                raise ValueError("approved restricted extension has unexpected credits")
            if extension["bound_batch_id"] is not None:
                raise ValueError("approved restricted extension is already bound")

            prompt_hash = manifest["prompt_hash"]
            schema_hash = manifest["schema_hash"]
            connection.execute(
                """
                INSERT INTO real_idea_batches(
                    batch_id, batch_key, status, created_at, manifest_sha256,
                    source_commit, deployment_id, model, prompt_hash, schema_hash,
                    completeness_contract_version, questionnaire_version, sample_count,
                    search_allowed, provider_policy_version, batch_version_split,
                    safe_counts_json, created_by
                ) VALUES (?, ?, 'CREATED', ?, 'pending', ?, ?, ?, ?, ?, ?, ?, 3, 0, ?, 0, '{}', ?)
                """,
                (
                    batch_id, batch_id, now, source_commit.strip(), deployment_id.strip(),
                    manifest["model"], prompt_hash, schema_hash,
                    manifest["idea_brief_completeness_contract_version"],
                    manifest["questionnaire_version"], manifest["provider_policy_version"], created_by,
                ),
            )
            allocation = self.budget._earmark_batch_tx(connection, batch_id, BATCH_EARMARK)
            for sample_key in SAMPLE_KEYS:
                sample_manifest = hashlib.sha256(
                    f"{batch_id}:{sample_key}:empty:v1".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO real_idea_samples(
                        sample_id, batch_id, sample_key, source_type, project_id,
                        raw_idea_sha256, redaction_version, state, sample_manifest_sha256,
                        budget_allocation_id, created_at, created_by
                    ) VALUES (?, ?, ?, ?, NULL, ?, 'pending-v1', 'CREATED', ?, ?, ?, ?)
                    """,
                    (
                        sample_key, batch_id, sample_key, SAMPLE_SOURCE_TYPES[sample_key],
                        empty_raw_hash, sample_manifest, allocation.allocation_id, now, created_by,
                    ),
                )
            self._freeze_batch_manifest_tx(connection, batch_id, manifest)
            return BatchRecord(batch_id, "CREATED")

    @staticmethod
    def _build_batch_manifest(batch_id: str, source_commit: str, deployment_id: str) -> dict[str, Any]:
        def digest(label: str) -> str:
            return hashlib.sha256(f"{label}:v1".encode("utf-8")).hexdigest()

        return {
            "manifest_version": "real-idea-batch-v1",
            "batch_id": batch_id,
            "source_commit": source_commit,
            "deployment_id": deployment_id,
            "model": "qwen3.7-flash",
            "quickstart_prompt_hash": digest("quickstart-prompt"),
            "quickstart_schema_hash": digest("quickstart-schema"),
            "solutions_prompt_hash": digest("solutions-prompt"),
            "solutions_schema_hash": digest("solutions-schema"),
            "prompt_hash": digest("quickstart-prompt") + digest("solutions-prompt"),
            "schema_hash": digest("quickstart-schema") + digest("solutions-schema"),
            "idea_brief_completeness_contract_version": "v1",
            "questionnaire_version": "v1",
            "sample_source_types": dict(SAMPLE_SOURCE_TYPES),
            "quickstart_one_shot_policy": {"max_provider_transports": 1, "validation_regeneration": False},
            "solutions_one_shot_policy": {"max_provider_transports": 1, "validation_regeneration": False},
            "sample_hard_cap": 2,
            "batch_hard_cap": BATCH_EARMARK,
            "budget_extension_id": EXTENSION_ID,
            "provider_policy_version": "real-idea-v1",
            "search": False,
        }

    def _freeze_batch_manifest_tx(self, connection, batch_id: str, manifest: dict[str, Any]) -> None:
        samples = connection.execute(
            "SELECT sample_key, state, project_id FROM real_idea_samples WHERE batch_id = ? ORDER BY sample_key",
            (batch_id,),
        ).fetchall()
        if len(samples) != len(SAMPLE_KEYS) or [row["sample_key"] for row in samples] != list(SAMPLE_KEYS):
            raise ValueError("batch must contain exactly the fixed three sample slots")
        if any(row["state"] != "CREATED" or row["project_id"] is not None for row in samples):
            raise ValueError("batch sample slots must be empty before manifest freeze")
        allocation = connection.execute(
            "SELECT batch_earmark, state FROM real_idea_budget_allocations WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if not allocation or allocation["state"] != "ACTIVE" or int(allocation["batch_earmark"]) != BATCH_EARMARK:
            raise ValueError("batch must have the approved active earmark before manifest freeze")
        if connection.execute(
            "SELECT COUNT(*) FROM real_idea_transport_reservations WHERE batch_id = ?", (batch_id,)
        ).fetchone()[0]:
            raise ValueError("batch manifest cannot freeze with transport reservations")
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        manifest_sha256 = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        updated = connection.execute(
            """
            UPDATE real_idea_batches
            SET manifest_sha256 = ?, prompt_hash = ?, schema_hash = ?,
                safe_counts_json = ?
            WHERE batch_id = ? AND manifest_sha256 = 'pending'
            """,
            (manifest_sha256, manifest["prompt_hash"], manifest["schema_hash"], encoded, batch_id),
        )
        if updated.rowcount != 1:
            raise ValueError("batch manifest was already frozen")

    def _is_complete_empty_batch_tx(self, connection, batch_id: str, manifest: dict[str, Any]) -> bool:
        batch = connection.execute(
            "SELECT manifest_sha256, safe_counts_json FROM real_idea_batches WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        if not batch or batch["manifest_sha256"] in {None, "pending"}:
            return False
        try:
            stored = json.loads(batch["safe_counts_json"])
        except (TypeError, json.JSONDecodeError):
            return False
        encoded = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        expected_sha = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        samples = connection.execute(
            "SELECT sample_key, state, project_id FROM real_idea_samples WHERE batch_id = ? ORDER BY sample_key",
            (batch_id,),
        ).fetchall()
        extension = connection.execute(
            "SELECT state, bound_batch_id FROM real_idea_budget_extensions WHERE extension_id = ?",
            (EXTENSION_ID,),
        ).fetchone()
        allocation = connection.execute(
            "SELECT batch_earmark, state FROM real_idea_budget_allocations WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        return (
            batch["manifest_sha256"] == expected_sha
            and stored == manifest
            and [row["sample_key"] for row in samples] == list(SAMPLE_KEYS)
            and all(row["state"] == "CREATED" and row["project_id"] is None for row in samples)
            and extension is not None and extension["state"] == BOUND and extension["bound_batch_id"] == batch_id
            and allocation is not None and allocation["state"] == "ACTIVE"
            and int(allocation["batch_earmark"]) == BATCH_EARMARK
        )

    def start_batch(self, batch_id: str | Any, actor: str | None = None) -> BatchRecord:
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("batch_id is required")
        batch_id = batch_id.strip()
        if batch_id == "REAL_IDEA_BATCH_01":
            return self.create_batch_with_slots(
                batch_id=batch_id,
                source_commit="local-test",
                deployment_id="local-test",
                actor=actor,
            )
        # Generic lifecycle fixtures use this legacy path; the fixed production
        # batch is created only through the atomic method above.
        now = utc_now()
        manifest = hashlib.sha256(f"{batch_id}:manifest:v1".encode()).hexdigest()
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT batch_id, status FROM real_idea_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if existing:
                return BatchRecord(existing["batch_id"], existing["status"])
            connection.execute(
                """
                INSERT INTO real_idea_batches(
                    batch_id, batch_key, status, created_at, manifest_sha256,
                    source_commit, deployment_id, model, prompt_hash, schema_hash,
                    completeness_contract_version, questionnaire_version, sample_count,
                    search_allowed, provider_policy_version, batch_version_split,
                    safe_counts_json, created_by
                ) VALUES (?, ?, 'CREATED', ?, ?, 'local-test', 'local-test',
                    'qwen3.7-flash', 'unbound', 'unbound', 'v1', 'v1', 3, 0,
                    'real-idea-v1', 0, '{}', ?)
                """,
                (batch_id, batch_id, now, manifest, actor or self.actor),
            )
        self.budget.activate_extension(EXTENSION_ID, EXTENSION_CREDITS)
        self.budget.earmark_batch(batch_id, BATCH_EARMARK)
        return BatchRecord(batch_id, "CREATED")

    def start_sample(
        self,
        batch_id: str,
        raw_idea: str,
        *,
        fail_after_project: bool = False,
    ) -> SampleRecord:
        if not raw_idea or not raw_idea.strip():
            raise ValueError("raw idea is required")
        raw_hash = hashlib.sha256(raw_idea.strip().encode("utf-8")).hexdigest()
        with self.database.connect() as connection:
            batch = connection.execute(
                "SELECT status FROM real_idea_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if not batch:
                raise KeyError(batch_id)
            if batch["status"] not in {"CREATED", "RUNNING"}:
                raise ValueError("batch is not accepting samples")
            allocation = connection.execute(
                "SELECT allocation_id FROM real_idea_budget_allocations WHERE batch_id = ? AND state = 'ACTIVE'",
                (batch_id,),
            ).fetchone()
            if not allocation:
                raise ValueError("batch has no active earmark")
            used = connection.execute(
                "SELECT sample_id, sample_key, state, project_id FROM real_idea_samples WHERE batch_id = ? ORDER BY sample_key",
                (batch_id,),
            ).fetchall()
            placeholders = [
                row for row in used
                if row["sample_key"] in SAMPLE_KEYS
                and row["state"] == "CREATED"
                and row["project_id"] is None
            ]
            used_keys = {row["sample_key"] for row in used if row not in placeholders}
            available = [key for key in SAMPLE_KEYS if key not in used_keys]
            if not available and not placeholders:
                raise ValueError("all three batch sample slots are already used")
            placeholder = placeholders[0] if placeholders else None
            sample_key = placeholder["sample_key"] if placeholder else available[0]
            sample_id = placeholder["sample_id"] if placeholder else f"sample_{uuid.uuid4().hex}"
            if placeholder:
                connection.execute(
                    "DELETE FROM real_idea_samples WHERE sample_id = ?",
                    (placeholder["sample_id"],),
                )
            project_id = f"project_real_idea_{uuid.uuid4().hex}"
            sample_manifest = hashlib.sha256(
                f"{batch_id}:{sample_key}:{raw_hash}:v1".encode("utf-8")
            ).hexdigest()
            project = self.projects.create_real_idea_evaluation_project_tx(
                connection,
                project_id=project_id,
                title=f"Real Idea Evaluation {sample_key}",
                summary="Evaluation-only project created for an isolated real-idea sample.",
                actor=self.actor,
                audit_payload={"batch_id": batch_id, "sample_id": sample_id, "sample_key": sample_key},
            )
            if fail_after_project:
                raise ExpectedSeedFailure("injected failure after project creation")
            now = utc_now()
            connection.execute(
                """
                INSERT INTO real_idea_samples(
                    sample_id, batch_id, sample_key, source_type, project_id,
                    raw_idea_sha256, redaction_version, state, sample_manifest_sha256,
                    budget_allocation_id, created_at, created_by
                ) VALUES (?, ?, ?, 'raw_user_idea', ?, ?, 'v1', 'QUICKSTART_PENDING', ?, ?, ?, ?)
                """,
                (sample_id, batch_id, sample_key, project_id, raw_hash, sample_manifest,
                 allocation["allocation_id"], now, self.actor),
            )
            connection.execute(
                "UPDATE real_idea_batches SET status='RUNNING', started_at=COALESCE(started_at, ?) WHERE batch_id=?",
                (now, batch_id),
            )
            return SampleRecord(
                sample_id, batch_id, sample_key, project["id"], raw_hash,
                "QUICKSTART_PENDING", allocation["allocation_id"],
            )

    def rollback_sample_start(self, sample_id: str) -> None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT project_id, state FROM real_idea_samples WHERE sample_id = ?", (sample_id,)
            ).fetchone()
            if not row:
                return
            if row["state"] != "QUICKSTART_PENDING":
                raise ValueError("only a pending sample start can be rolled back")
            connection.execute("DELETE FROM real_idea_samples WHERE sample_id = ?", (sample_id,))
            connection.execute("DELETE FROM projects WHERE id = ?", (row["project_id"],))

    def transition_sample(self, sample_id: str, *, from_state: str, to_state: str) -> SampleRecord:
        if from_state not in SAMPLE_STATES or to_state not in SAMPLE_STATES:
            raise ValueError("unknown sample state")
        allowed = {
            "QUICKSTART_PENDING": {"AWAITING_BRIEF_REVIEW", "OPERATIONAL_INCOMPLETE", "FAILED", "STOPPED", "WITHDRAWN"},
            "AWAITING_BRIEF_REVIEW": {"AWAITING_SOLUTION_REVIEW", "FAILED", "STOPPED", "WITHDRAWN"},
            "AWAITING_SOLUTION_REVIEW": {"COMPLETED", "PARTIAL", "FAILED", "STOPPED", "WITHDRAWN"},
            "OPERATIONAL_INCOMPLETE": {"FAILED", "STOPPED", "WITHDRAWN"},
            "COMPLETED": {"FINALIZED"}, "PARTIAL": {"FINALIZED"}, "FAILED": {"FINALIZED"},
            "STOPPED": {"FINALIZED"}, "WITHDRAWN": {"FINALIZED"},
        }
        if to_state not in allowed.get(from_state, set()):
            raise ValueError(f"invalid sample transition: {from_state}->{to_state}")
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE real_idea_samples SET state=?, terminal_at=CASE WHEN ? IN ('COMPLETED','PARTIAL','FAILED','STOPPED','WITHDRAWN','FINALIZED') THEN COALESCE(terminal_at, ?) ELSE terminal_at END WHERE sample_id=? AND state=?",
                (to_state, to_state, utc_now(), sample_id, from_state),
            )
            if cursor.rowcount != 1:
                raise ValueError("sample state changed or not found")
            row = connection.execute("SELECT * FROM real_idea_samples WHERE sample_id=?", (sample_id,)).fetchone()
            return self._sample(row)

    def transition_batch(self, batch_id: str, *, from_state: str, to_state: str) -> BatchRecord:
        if from_state not in BATCH_STATES or to_state not in BATCH_STATES:
            raise ValueError("unknown batch state")
        allowed = {
            "CREATED": {"RUNNING", "STOPPED", "FAILED"},
            "RUNNING": {"COMPLETED", "PARTIAL", "FAILED", "STOPPED"},
            "COMPLETED": {"FINALIZED"}, "PARTIAL": {"FINALIZED"},
            "FAILED": {"FINALIZED"}, "STOPPED": {"FINALIZED"},
        }
        if to_state not in allowed.get(from_state, set()):
            raise ValueError(f"invalid batch transition: {from_state}->{to_state}")
        with self.database.connect() as connection:
            cursor = connection.execute(
                "UPDATE real_idea_batches SET status=?, finalized_at=CASE WHEN ?='FINALIZED' THEN COALESCE(finalized_at, ?) ELSE finalized_at END WHERE batch_id=? AND status=?",
                (to_state, to_state, utc_now(), batch_id, from_state),
            )
            if cursor.rowcount != 1:
                raise ValueError("batch state changed or not found")
            return self.read_batch(batch_id)

    def run_solutions(self, sample_id: str, *, runtime: Any) -> SolutionsReviewResult:
        """Run the real Solutions service for one sample under the one-shot policy.

        ``runtime`` is dependency injection at the structured-runtime boundary;
        production callers supply the configured runtime and tests supply an
        isolated fake transport/runtime.  Brief lookup, parsing, validation and
        persistence remain owned by SolutionDesignService.
        """
        sample = self.database.fetch_one(
            "SELECT * FROM real_idea_samples WHERE sample_id = ?", (sample_id,)
        )
        if not sample:
            raise KeyError(sample_id)
        if sample["state"] != "AWAITING_BRIEF_REVIEW":
            raise ValueError("sample is not ready for Solutions review")
        brief = self.database.fetch_one(
            "SELECT id FROM idea_briefs WHERE project_id = ? AND confirmation_status = 'confirmed' "
            "ORDER BY version DESC LIMIT 1",
            (sample["project_id"],),
        )
        if not brief:
            raise ValueError("confirmed idea brief is required")
        reservation = self.budget.reserve(sample["batch_id"], sample_id, "SOLUTIONS", 1)
        dispatch_id = f"dispatch_{uuid.uuid4().hex}"
        transport_id = f"transport_{uuid.uuid4().hex}"
        self.budget.mark_attempted(
            reservation.reservation_id, dispatch_id=dispatch_id, transport_id=transport_id
        )
        policy = StageBExecutionPolicy(
            validation_regeneration_allowed=False,
            max_provider_transports=1,
        )
        result = SolutionDesignService(self.database, runtime).generate(
            sample["project_id"],
            actor=self.actor,
            execution_policy=policy,
            use_competitor_snapshot=False,
        )
        candidates = result.get("candidates", [])
        if len(candidates) != 3:
            raise ValueError("REAL_IDEA_SOLUTIONS_REQUIRE_EXACTLY_THREE_CANDIDATES")
        evaluation_id = result["run"]["id"]
        transport_count = int(getattr(runtime, "provider_transport_attempts", 1))
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE real_idea_samples SET solutions_evaluation_id = ?, state = 'AWAITING_SOLUTION_REVIEW' WHERE sample_id = ? AND state = 'AWAITING_BRIEF_REVIEW'",
                (evaluation_id, sample_id),
            )
        return SolutionsReviewResult(
            sample_id=sample_id,
            status="AWAITING_SOLUTION_REVIEW",
            solution_count=len(candidates),
            transport_count=transport_count,
            evaluation_id=evaluation_id,
        )

    def run_quickstart(self, sample_id: str, *, raw_idea: str, runtime: Any) -> dict[str, Any]:
        """Run the normal interpreter against the born evaluation project.

        The reservation is durable before the runtime is entered; an attempted
        transport is never refunded, including recovery/timeout outcomes.
        """
        sample = self.database.fetch_one("SELECT * FROM real_idea_samples WHERE sample_id=?", (sample_id,))
        if not sample:
            raise KeyError(sample_id)
        if sample["state"] != "QUICKSTART_PENDING":
            raise ValueError("sample is not pending QuickStart")
        reservation = self.budget.reserve(sample["batch_id"], sample_id, "QUICKSTART", 1)
        self.budget.mark_attempted(
            reservation.reservation_id,
            dispatch_id=f"dispatch_{uuid.uuid4().hex}",
            transport_id=f"transport_{uuid.uuid4().hex}",
        )
        result = QuickStartService(self.database, self.projects, runtime).quick_start_existing_project(
            sample["project_id"], QuickStartRequest(idea=raw_idea), actor=self.actor,
            evaluation_policy=EvaluationExecutionPolicy(
                batch_id=sample["batch_id"], sample_id=sample_id, stage="QUICKSTART",
                max_provider_transports=1,
            ),
        )
        next_state = result.get("status")
        if next_state == "AWAITING_BRIEF_REVIEW":
            self.transition_sample(sample_id, from_state="QUICKSTART_PENDING", to_state="AWAITING_BRIEF_REVIEW")
        elif next_state == "OPERATIONAL_INCOMPLETE":
            self.transition_sample(sample_id, from_state="QUICKSTART_PENDING", to_state="OPERATIONAL_INCOMPLETE")
        return result

    def record_selection(
        self, sample_id: str, *, selected_ordinal: int, reason: str
    ) -> SelectionReviewResult:
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("selection reason is required")
        sentence_count = len([part for part in re.split(r"[.!?。！？]+", reason.strip()) if part.strip()])
        if not 1 <= sentence_count <= 3:
            raise ValueError("selection reason must contain 1 to 3 sentences")
        sample = self.database.fetch_one(
            "SELECT * FROM real_idea_samples WHERE sample_id = ?", (sample_id,)
        )
        if not sample or sample["state"] != "AWAITING_SOLUTION_REVIEW":
            raise ValueError("sample is not awaiting solution review")
        rows = self.database.fetch_all(
            "SELECT * FROM solution_candidates WHERE run_id = ? ORDER BY created_at, id",
            (sample["solutions_evaluation_id"],),
        )
        if selected_ordinal < 1 or selected_ordinal > len(rows):
            raise ValueError("selected solution ordinal is not persisted")
        selected = rows[selected_ordinal - 1]
        with self.database.connect() as connection:
            DecisionService().propose_solution_selection(
                connection=connection,
                project_id=sample["project_id"],
                option_ids=[row["id"] for row in rows],
                selected_option_id=selected["id"],
                rationale=reason.strip(),
                decision_payload={"sample_id": sample_id, "selected_ordinal": selected_ordinal},
                actor=self.actor,
            )
            connection.execute(
                "UPDATE real_idea_samples SET selected_solution_id = ?, state = 'AWAITING_SOLUTION_REVIEW' WHERE sample_id = ?",
                (selected["id"], sample_id),
            )
        return SelectionReviewResult(
            sample_id=sample_id,
            selected_solution_id=selected["id"],
            selected_solution_ordinal=selected_ordinal,
            provider_transport_count=0,
        )

    def acknowledge_evidence(
        self, sample_id: str, *, explicit: bool, note: str = ""
    ) -> EvidenceAcknowledgement:
        """Record explicit evidence acknowledgement through the formal handoff contract.

        Exact sample bindings are checked before the official acknowledgement service is
        called.  The acknowledgement deliberately does not imply external verification.
        """
        if not explicit:
            raise ReviewGateError("explicit acknowledgement is required")
        sample = self.database.fetch_one(
            "SELECT * FROM real_idea_samples WHERE sample_id=?", (sample_id,)
        )
        if not sample:
            raise ReviewGateError("sample not found")
        required = (sample["snapshot_id"], sample["prd_version_id"], sample["techdoc_version_id"])
        if any(not value for value in required):
            raise ReviewGateError("exact snapshot, PRD, and TechDoc versions are required")
        project = self.database.fetch_one(
            "SELECT current_snapshot_id FROM projects WHERE id=?", (sample["project_id"],)
        )
        if not project or project["current_snapshot_id"] != sample["snapshot_id"]:
            raise ReviewGateError("sample snapshot is not the current snapshot")
        for version_id, doc_type in (
            (sample["prd_version_id"], "prd"), (sample["techdoc_version_id"], "techdoc")
        ):
            version = self.database.fetch_one(
                "SELECT project_id, doc_type, status, validation_status FROM document_versions WHERE id=?",
                (version_id,),
            )
            if not version or version["project_id"] != sample["project_id"] or version["doc_type"] != doc_type:
                raise ReviewGateError("document version binding is invalid")
            if version["status"] != "approved" or version["validation_status"] != "passed":
                raise ReviewGateError("confirmed approved document versions are required")
        result = HandoffService(self.database).acknowledge_unresolved(
            sample["project_id"], actor=self.actor, confirmed=True, note=note
        )
        return EvidenceAcknowledgement(
            sample_id=sample_id,
            acknowledgement_id=result["id"],
            confirmed=True,
            externally_verified=False,
            provider_transport_count=0,
            prd_version_id=sample["prd_version_id"],
            techdoc_version_id=sample["techdoc_version_id"],
            snapshot_id=sample["snapshot_id"],
        )

    def record_feedback(
        self, sample_id: str, *, ratings: dict[str, Any]
    ) -> FeedbackAttestation:
        """Persist only an idea-provider attestation and safe structured ratings."""
        sample = self.database.fetch_one(
            "SELECT batch_id, state FROM real_idea_samples WHERE sample_id=?", (sample_id,)
        )
        if not sample:
            raise ReviewGateError("sample not found")
        if sample["state"] not in {"AWAITING_SOLUTION_REVIEW", "COMPLETED", "PARTIAL"}:
            raise ReviewGateError("required solution review is incomplete")
        if not isinstance(ratings, dict):
            raise ValueError("ratings must be an object")
        feedback_id = f"feedback_{uuid.uuid4().hex}"
        now = utc_now()
        self.database.execute(
            """INSERT INTO real_idea_feedback(
                feedback_id,batch_id,sample_id,stage,submitted_by,submitted_at,
                accepted,score_payload,raw_feedback_text,feedback_attestation,
                feedback_schema_version,created_by
            ) VALUES (?,?,?,'SOLUTION_REVIEW','idea_provider',?,?,?,NULL,1,'v1',?)""",
            (feedback_id, sample["batch_id"], sample_id, now, 1,
             json.dumps(ratings, ensure_ascii=False, sort_keys=True), self.actor),
        )
        return FeedbackAttestation(
            sample_id=sample_id,
            attested_by="idea_provider",
            used_as_requirement_ground_truth=False,
            provider_transport_count=0,
        )

    def read_project(self, project_id: str) -> dict[str, Any] | None:
        return self.database.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))

    def read_batch(self, batch_id: str) -> BatchRecord:
        row = self.database.fetch_one("SELECT batch_id,status FROM real_idea_batches WHERE batch_id=?", (batch_id,))
        if not row:
            raise KeyError(batch_id)
        return BatchRecord(row["batch_id"], row["status"])

    def read_sample(self, sample_id: str) -> SampleRecord | None:
        row = self.database.fetch_one("SELECT * FROM real_idea_samples WHERE sample_id=?", (sample_id,))
        return self._sample(row) if row else None

    def count_projects(self) -> int:
        row = self.database.fetch_one("SELECT COUNT(*) AS count FROM projects")
        return int(row["count"])

    def count_samples(self, batch_id: str) -> int:
        row = self.database.fetch_one("SELECT COUNT(*) AS count FROM real_idea_samples WHERE batch_id=?", (batch_id,))
        return int(row["count"])

    def inject_integrity_violation(self, batch_id: str, violation: str) -> None:
        """Test-only hook for exercising terminal integrity gates.

        Production callers have no public route to this service; keeping the hook
        in the service also avoids mutating receipts or product data in tests.
        """
        if not violation or not isinstance(violation, str):
            raise ValueError("violation is required")
        self._integrity_violations.setdefault(batch_id, set()).add(violation)

    def finalize_batch(self, batch_id: str) -> BatchFinalization:
        """Derive a descriptive batch result without rewriting lifecycle evidence."""
        self.read_batch(batch_id)
        rows = self.database.fetch_all(
            "SELECT sample_key, state FROM real_idea_samples WHERE batch_id=? ORDER BY sample_key",
            (batch_id,),
        )
        sample_statuses = {row["sample_key"]: row["state"] for row in rows}
        reasons: list[str] = []
        violations = self._integrity_violations.get(batch_id, set())
        hard_violations = {
            "cross_sample_binding", "wrong_version", "budget_overrun",
            "search_attempt", "silent_ack", "unsupported_verified_fact",
            "critical_inheritance_failure", "cross_sample_project", "wrong_solution_id",
            "wrong_prd_version",
        }
        for violation in sorted(violations & hard_violations):
            reasons.append(violation)
        if not rows:
            reasons.append("no_samples")
        if any(state in {"FAILED", "STOPPED"} for state in sample_statuses.values()):
            reasons.append("sample_failure")

        if reasons:
            status = "FAIL"
        elif len(rows) == len(SAMPLE_KEYS) and all(
            state == "COMPLETED" for state in sample_statuses.values()
        ):
            status = "PASS"
        else:
            status = "PARTIAL"
            if any(state != "COMPLETED" for state in sample_statuses.values()):
                reasons.append("not_all_samples_completed")

        return BatchFinalization(
            status=status,
            reasons=tuple(reasons),
            sample_statuses=sample_statuses,
            budget_summary={"attempted_reservations_are_not_released": True},
            integrity_summary={"violations": tuple(sorted(violations))},
        )

    @staticmethod
    def _sample(row: Any) -> SampleRecord:
        return SampleRecord(
            row["sample_id"], row["batch_id"], row["sample_key"], row["project_id"],
            row["raw_idea_sha256"], row["state"], row["budget_allocation_id"],
        )
