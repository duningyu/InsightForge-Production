from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.db import Database
from app.services.artifact_health import ArtifactHealthService
from app.services.change_proposals import ChangeProposalService


class ImpactResolver:
    def __init__(
        self,
        db: Database,
        health: ArtifactHealthService,
        proposals: ChangeProposalService,
    ):
        self.db = db
        self.health = health
        self.proposals = proposals

    @staticmethod
    def _is_material(
        *,
        claim: sqlite3.Row,
        roles: set[str],
        before_status: str,
        after_status: str,
        has_artifact_dependency: bool,
    ) -> bool:
        if claim["criticality"] == "critical" and "assumption" in roles and after_status in {"conflict", "contradicted", "stale"}:
            return True
        if (
            claim["criticality"] == "critical"
            and claim["claim_type"] == "feasibility"
            and before_status == "unverified"
            and after_status in {"supported", "contradicted"}
        ):
            return True
        if claim["claim_type"] in {"user_problem", "value"} and (
            (before_status in {"supported", "limited_support"} and after_status in {"conflict", "contradicted", "stale"})
            or (before_status == "unverified" and after_status == "contradicted")
        ):
            return True
        if has_artifact_dependency and before_status in {"supported", "limited_support"} and after_status in {"conflict", "contradicted", "stale"}:
            return True
        return False

    def resolve_claim_change_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        claim_id: str,
        before_status: str,
        after_status: str,
        trigger_source_id: str | None,
        actor: str,
        stale_evidence: bool = False,
    ) -> dict[str, Any]:
        claim = connection.execute(
            "SELECT * FROM project_claims WHERE id=? AND project_id=? AND status='active'",
            (claim_id, project_id),
        ).fetchone()
        if claim is None:
            raise KeyError("project claim not found")
        decisions = connection.execute(
            """
            SELECT pd.id, dcl.role FROM decision_claim_links dcl
            JOIN project_decisions pd ON pd.id=dcl.decision_id
            WHERE dcl.claim_id=? AND pd.project_id=? AND pd.status='confirmed'
            """,
            (claim_id, project_id),
        ).fetchall()
        decision_ids = sorted({row["id"] for row in decisions})
        roles = {row["role"] for row in decisions}
        project = connection.execute(
            "SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if project is None:
            raise KeyError("project not found")
        current_snapshot_id = project["current_snapshot_id"]
        dependency = connection.execute(
            "SELECT 1 FROM artifact_dependencies WHERE dependency_type='project_claim' AND dependency_id=? LIMIT 1",
            (claim_id,),
        ).fetchone()
        has_snapshot_link = False
        if current_snapshot_id:
            has_snapshot_link = connection.execute(
                "SELECT 1 FROM snapshot_claim_links WHERE snapshot_id=? AND claim_id=? LIMIT 1",
                (current_snapshot_id, claim_id),
            ).fetchone() is not None
        material = self._is_material(
            claim=claim,
            roles=roles,
            before_status=before_status,
            after_status=after_status,
            has_artifact_dependency=bool(dependency or has_snapshot_link),
        )
        if not material or not current_snapshot_id:
            return {
                "material": False,
                "proposal_id": None,
                "affected_decision_ids": decision_ids,
                "affected_artifacts": [],
            }

        health_status = "stale_evidence" if stale_evidence else "needs_review"
        self.health.set_tx(
            connection,
            artifact_type="project_snapshot",
            artifact_id=current_snapshot_id,
            health_status=health_status,
            reason=f"claim {claim_id} changed {before_status} -> {after_status}",
            trigger_source_id=trigger_source_id,
        )
        dependency_rows = connection.execute(
            """
            SELECT artifact_type,artifact_id FROM artifact_dependencies
            WHERE dependency_type='project_claim' AND dependency_id=?
            """,
            (claim_id,),
        ).fetchall()
        affected_artifacts: list[dict[str, str]] = [
            {"artifact_type": "project_snapshot", "artifact_id": current_snapshot_id}
        ]
        for row in dependency_rows:
            if row["artifact_type"] == "project_snapshot" and row["artifact_id"] == current_snapshot_id:
                continue
            self.health.set_tx(
                connection,
                artifact_type=row["artifact_type"],
                artifact_id=row["artifact_id"],
                health_status=health_status,
                reason=f"dependent claim {claim_id} changed {before_status} -> {after_status}",
                trigger_source_id=trigger_source_id,
            )
            affected_artifacts.append(dict(row))

        existing_rows = connection.execute(
            """
            SELECT * FROM change_proposals
            WHERE project_id=? AND from_snapshot_id=? AND proposal_type='evidence_material_change'
              AND status='open'
            ORDER BY created_at DESC
            """,
            (project_id, current_snapshot_id),
        ).fetchall()
        for existing in existing_rows:
            affected_claims = json.loads(existing["affected_claims_json"])
            if claim_id in affected_claims:
                return {
                    "material": True,
                    "proposal_id": existing["id"],
                    "affected_decision_ids": decision_ids,
                    "affected_artifacts": affected_artifacts,
                }

        suggested_changes: dict[str, Any] = {
            "claim_status_updates": {claim_id: after_status},
            "snapshot_patch": {},
        }
        if claim["claim_type"] == "target_user":
            suggested_changes["snapshot_patch"] = {"target_user": {"verification_status": after_status}}
        elif claim["claim_type"] == "user_problem":
            suggested_changes["snapshot_patch"] = {"problem": {"verification_status": after_status}}
        proposal = self.proposals.create_tx(
            connection,
            project_id=project_id,
            from_snapshot_id=current_snapshot_id,
            proposal_type="evidence_material_change",
            summary="关键产品判断的证据状态发生变化",
            reason=f"{claim['statement']}：{before_status} → {after_status}",
            affected_claim_ids=[claim_id],
            affected_decision_ids=decision_ids,
            suggested_changes=suggested_changes,
            trigger_source_id=trigger_source_id,
        )
        self.db.insert_audit_tx(
            connection,
            actor=actor,
            action="evidence_impact_resolved",
            entity_type="project_claim",
            entity_id=claim_id,
            payload={
                "project_id": project_id,
                "before_status": before_status,
                "after_status": after_status,
                "material": True,
                "proposal_id": proposal["id"],
                "affected_decision_ids": decision_ids,
            },
        )
        return {
            "material": True,
            "proposal_id": proposal["id"],
            "affected_decision_ids": decision_ids,
            "affected_artifacts": affected_artifacts,
        }

    def resolve_claim_change(self, **kwargs: Any) -> dict[str, Any]:
        with self.db.connect() as connection:
            return self.resolve_claim_change_tx(connection, **kwargs)
