"""Provider-free P0/P1 quality evaluation for the M3 action lifecycle."""

from __future__ import annotations

import json
from typing import Any

from app.services.real_idea_metrics import ArtifactBinding, QualityEvaluationService


_CLAIM_CLASSES = {
    "SUPPORTED_FACT",
    "USER_INPUT",
    "MODEL_HYPOTHESIS",
    "UNVERIFIED_CLAIM",
    "UNSUPPORTED_FACTUAL_ASSERTION",
}


class IFGuideM3QualityService:
    """Compute recoverable M3 quality evidence without creating another ledger."""

    def __init__(self, db):
        self.db = db
        self.ledger = QualityEvaluationService(db)

    def _owner(self, project_id: str, actor: str) -> None:
        row = self.db.fetch_one(
            "SELECT owner_actor FROM project_intents WHERE project_id = ? "
            "ORDER BY revision DESC LIMIT 1",
            (project_id,),
        )
        if not row:
            raise KeyError("project intent not found")
        if row["owner_actor"] != actor:
            raise PermissionError("M3 quality belongs to another actor")

    def _load_binding_rows(
        self, *, project_id: str, task_id: str, task_revision: int,
        submission_id: str, submission_revision: int, review_id: str, review_revision: int,
    ) -> tuple[Any, Any, Any]:
        task = self.db.fetch_one(
            "SELECT task_id, project_id, kind, card_revision FROM first_action_cards "
            "WHERE task_id = ? AND project_id = ?",
            (task_id, project_id),
        )
        submission = self.db.fetch_one(
            "SELECT * FROM action_submissions WHERE submission_id = ?",
            (submission_id,),
        )
        review = self.db.fetch_one(
            "SELECT * FROM action_reviews WHERE review_id = ?",
            (review_id,),
        )
        if not task or task["kind"] != "FIRST_ACTION" or task["card_revision"] != task_revision:
            raise ValueError("M3_TASK_BINDING_REQUIRED")
        if not submission or (
            submission["project_id"] != project_id
            or submission["task_id"] != task_id
            or submission["task_revision"] != task_revision
            or submission["revision"] != submission_revision
        ):
            raise ValueError("M3_SUBMISSION_BINDING_REQUIRED")
        if not review or (
            review["project_id"] != project_id
            or review["submission_id"] != submission_id
            or review["submission_revision"] != submission_revision
            or review["task_id"] != task_id
            or review["task_revision"] != task_revision
            or review["revision"] != review_revision
        ):
            raise ValueError("M3_REVIEW_BINDING_REQUIRED")
        return task, submission, review

    @staticmethod
    def _json(value: str, default: Any) -> Any:
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _review_accuracy(status: str, items: list[dict[str, Any]], recommendation: str) -> float:
        outcomes = [item.get("outcome") for item in items]
        if status == "PASS":
            return 1.0 if outcomes and all(outcome == "PASS" for outcome in outcomes) else 0.0
        if status == "FAIL":
            return 1.0 if "FAIL" in outcomes else 0.0
        if status == "UNKNOWN":
            return 1.0 if "UNKNOWN" in outcomes or bool(recommendation.strip()) else 0.0
        if status == "NOT_APPLICABLE":
            return 1.0 if bool(recommendation.strip()) else 0.0
        return 0.0

    def _p1_metrics(self, submission: Any, review: Any) -> dict[str, Any]:
        items = self._json(review["check_items_json"], [])
        if not isinstance(items, list):
            items = []
        critical_pass = [
            item for item in items
            if isinstance(item, dict) and item.get("critical") and item.get("outcome") == "PASS"
        ]
        evidenced_critical_pass = [
            item for item in critical_pass
            if isinstance(item.get("evidence_refs"), list) and item["evidence_refs"]
        ]
        decisions = self.db.fetch_all(
            "SELECT source_submission_id, source_review_id FROM decision_records "
            "WHERE project_id = ? AND source_submission_id = ?",
            (submission["project_id"], submission["submission_id"]),
        )
        traceable = sum(
            row["source_submission_id"] == submission["submission_id"]
            and row["source_review_id"] == review["review_id"]
            for row in decisions
        )

        factual_assertions = 0
        unsupported_assertions = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            claim_class = item.get("claim_class")
            if claim_class in _CLAIM_CLASSES and claim_class in {
                "SUPPORTED_FACT", "UNSUPPORTED_FACTUAL_ASSERTION"
            }:
                factual_assertions += 1
                unsupported_assertions += claim_class == "UNSUPPORTED_FACTUAL_ASSERTION"

        unknown_rows = self.db.fetch_all(
            "SELECT overall_status, COUNT(*) AS count FROM action_reviews "
            "WHERE submission_id = ? GROUP BY overall_status ORDER BY overall_status",
            (submission["submission_id"],),
        )
        unknown_distribution = {row["overall_status"]: row["count"] for row in unknown_rows}
        review_status = review["overall_status"]
        recovery = self.db.fetch_one(
            "SELECT goal, checks_json, source_review_id FROM first_action_cards "
            "WHERE project_id = ? AND kind = 'RECOVERY' AND source_review_id = ?",
            (submission["project_id"], review["review_id"]),
        )
        recovery_specific = 1.0 if review_status == "PASS" else 0.0
        if review_status != "PASS" and recovery:
            checks = self._json(recovery["checks_json"], [])
            recovery_specific = 1.0 if recovery["goal"].strip() and isinstance(checks, list) and checks else 0.0

        return {
            "evidence_sufficiency": (
                len(evidenced_critical_pass) / len(critical_pass) if critical_pass else 1.0
            ),
            "review_accuracy": self._review_accuracy(
                review_status, items, review["recommendation"] or ""
            ),
            "result_decision_traceability": traceable / len(decisions) if decisions else 1.0,
            "unsupported_conclusion_rate": (
                unsupported_assertions / factual_assertions if factual_assertions else 0.0
            ),
            "recovery_specificity": recovery_specific,
            "unknown_status_distribution": unknown_distribution,
        }

    def evaluate(
        self, *, actor: str, project_id: str, task_id: str, task_revision: int,
        submission_id: str, submission_revision: int, review_id: str, review_revision: int,
    ) -> dict[str, Any]:
        self._owner(project_id, actor)
        task, submission, review = self._load_binding_rows(
            project_id=project_id, task_id=task_id, task_revision=task_revision,
            submission_id=submission_id, submission_revision=submission_revision,
            review_id=review_id, review_revision=review_revision,
        )
        p1_metrics = self._p1_metrics(submission, review)
        p0_payload = {
            **p1_metrics,
            "p0_violations": [],
            "p1_gaps": [],
        }
        binding = ArtifactBinding(
            batch_id=None,
            sample_id=None,
            project_id=project_id,
            artifact_type="M3_ACTION",
            artifact_version_id=f"{task_id}:{task_revision}",
            selected_solution_id=None,
            snapshot_id=None,
            upstream_version_ids=(),
            quality_layer="P0",
            evaluator_role="system",
            metric_payload=p0_payload,
            input_manifest={
                "task_id": task_id,
                "task_revision": task_revision,
                "submission_id": submission_id,
                "submission_revision": submission_revision,
                "review_id": review_id,
                "review_revision": review_revision,
            },
            evidence_manifest={
                "submission_kind": submission["submission_kind"],
                "review_status": review["overall_status"],
                "evidence_level": review["evidence_level"],
            },
            policy_version="if-guide-m3-quality-v1",
            owner_actor=actor,
            artifact_id=task["task_id"],
            artifact_revision=task["card_revision"],
            evaluation_scope="IF_GUIDE_M3",
        )
        p0 = self.ledger.evaluate_p0(binding)
        p1_id = self.ledger.enqueue_p1(p0.quality_evaluation_id)
        p1 = self.ledger.get(p1_id)
        return {
            "p0": {"quality_evaluation_id": p0.quality_evaluation_id, "status": p0.status},
            "p1": {
                "quality_evaluation_id": p1.quality_evaluation_id,
                "status": p1.status,
                "metric_payload": dict(p1.metric_payload),
            },
            "p2_status": "NOT_REVIEWED",
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
        }
