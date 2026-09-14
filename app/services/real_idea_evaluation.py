from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

from app.db import Database, utc_now
from app.services.projects import ProjectService
from app.services.real_idea_budget import (
    BATCH_EARMARK,
    EXTENSION_CREDITS,
    EXTENSION_ID,
    RealIdeaBudgetService,
)


BATCH_STATES = frozenset({"CREATED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "STOPPED", "FINALIZED"})
SAMPLE_STATES = frozenset({
    "QUICKSTART_PENDING", "AWAITING_BRIEF_REVIEW", "OPERATIONAL_INCOMPLETE",
    "AWAITING_SOLUTION_REVIEW", "COMPLETED", "PARTIAL", "FAILED", "STOPPED",
    "WITHDRAWN", "FINALIZED",
})
SAMPLE_KEYS = ("REAL_IDEA_01", "REAL_IDEA_02", "REAL_IDEA_03")


class ExpectedSeedFailure(RuntimeError):
    """Testable failure point proving sample creation is atomic."""


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


class RealIdeaEvaluationService:
    """Internal, isolated lifecycle for a real-idea evaluation sample.

    This service owns only evaluation state and project birth.  It does not expose an
    HTTP route and it never creates briefs, solutions, documents, or Provider calls.
    """

    def __init__(self, database: Database, *, durable_budget: int, actor: str = "real_idea_evaluation"):
        self.database = database
        self.actor = actor
        self.projects = ProjectService(database)
        self.budget = RealIdeaBudgetService(database, durable_budget=durable_budget)

    def start_batch(self, batch_id: str | Any, actor: str | None = None) -> BatchRecord:
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("batch_id is required")
        batch_id = batch_id.strip()
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
                "SELECT sample_key FROM real_idea_samples WHERE batch_id = ? ORDER BY sample_key",
                (batch_id,),
            ).fetchall()
            used_keys = {row["sample_key"] for row in used}
            available = [key for key in SAMPLE_KEYS if key not in used_keys]
            if not available:
                raise ValueError("all three batch sample slots are already used")
            sample_key = available[0]
            sample_id = f"sample_{uuid.uuid4().hex}"
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

    @staticmethod
    def _sample(row: Any) -> SampleRecord:
        return SampleRecord(
            row["sample_id"], row["batch_id"], row["sample_key"], row["project_id"],
            row["raw_idea_sha256"], row["state"], row["budget_allocation_id"],
        )
