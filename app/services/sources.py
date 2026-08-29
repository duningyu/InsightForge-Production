from __future__ import annotations

import hashlib
import json
from typing import Any

from app.db import Database
from app.ingestion import extract_text
from app.services.source_guidance import SourceGuidanceService


class SourceService:
    def __init__(self, db: Database, project_claims: Any | None = None, impact_resolver: Any | None = None):
        self.db = db
        self.guidance = SourceGuidanceService()
        self.project_claims = project_claims
        self.impact_resolver = impact_resolver

    def _require_lifecycle_services(self) -> tuple[Any, Any]:
        if self.project_claims is None or self.impact_resolver is None:
            raise RuntimeError("source lifecycle propagation services are not configured")
        return self.project_claims, self.impact_resolver

    @staticmethod
    def _normalize(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        normalized = dict(row)
        raw_metadata = normalized.pop("metadata_json", "{}") or "{}"
        try:
            normalized["metadata"] = json.loads(raw_metadata)
        except json.JSONDecodeError:
            normalized["metadata"] = {"parse_error": True}
        return normalized

    def add_source(
        self,
        *,
        project_id: str,
        title: str,
        source_type: str,
        authority: float,
        content: str,
        filename: str,
        source_url: str | None = None,
        publisher: str | None = None,
        published_at: str | None = None,
        captured_at: str | None = None,
        authority_label: str | None = None,
        authority_basis: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_id = self.db.add_source(
            project_id=project_id,
            title=title,
            source_type=source_type,
            authority=authority,
            content=content,
            filename=filename,
            source_url=source_url,
            publisher=publisher,
            published_at=published_at,
            captured_at=captured_at,
            authority_label=authority_label,
            authority_basis=authority_basis,
            status=status,
            metadata=metadata,
        )
        source = self.get_source(source_id)
        if source is None:
            raise RuntimeError("source insertion did not persist")
        self.db.insert_audit(
            actor="web_user",
            action="source_added",
            entity_type="source",
            entity_id=source_id,
            payload={
                "project_id": project_id,
                "source_type": source_type,
                "authority": authority,
                "authority_label": source.get("authority_label"),
                "filename": filename,
                "source_url": source_url,
            },
        )
        return source

    def add_guided_source(
        self,
        *,
        project_id: str,
        title: str,
        origin_kind: str,
        content: str,
        filename: str,
        source_url: str | None = None,
        publisher: str | None = None,
        published_at: str | None = None,
    ) -> dict[str, Any]:
        proposal = self.guidance.classify(
            origin_kind=origin_kind,
            title=title,
            source_url=source_url,
            publisher=publisher,
            published_at=published_at,
            filename=filename,
            content=content,
        )
        source = self.add_source(
            project_id=project_id,
            title=title,
            source_type=proposal["source_type"],
            authority=float(proposal["authority"]),
            content=content,
            filename=filename,
            source_url=source_url,
            publisher=publisher,
            published_at=published_at,
            authority_label=proposal["authority_label"],
            authority_basis=proposal["authority_basis"],
            metadata={
                "origin_kind": origin_kind,
                "classification_reason": proposal["classification_reason"],
                "needs_confirmation": proposal["needs_confirmation"],
                "allowed_claims": proposal["allowed_claims"],
                "limitations": proposal["limitations"],
            },
        )
        source["guidance"] = proposal
        return source

    def add_uploaded_source(
        self,
        *,
        project_id: str,
        title: str,
        source_type: str,
        authority: float,
        filename: str,
        data: bytes,
    ) -> dict[str, Any]:
        return self.add_source(
            project_id=project_id,
            title=title,
            source_type=source_type,
            authority=authority,
            content=extract_text(filename, data),
            filename=filename,
        )

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        return self._normalize(self.db.fetch_one("SELECT * FROM sources WHERE id = ?", (source_id,)))

    def list_sources(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            """
            SELECT id, project_id, title, filename, source_type, authority, sha256,
                   source_url, publisher, published_at, captured_at, authority_label,
                   authority_basis, status, metadata_json, created_at
            FROM sources WHERE project_id = ? ORDER BY created_at, id
            """,
            (project_id,),
        )
        return [self._normalize(row) for row in rows if row is not None]
    def archive(self, project_id: str, source_id: str, *, actor: str) -> dict[str, Any]:
        claims_service, impact = self._require_lifecycle_services()
        affected_claims: list[dict[str, Any]] = []
        proposal_ids: list[str] = []
        artifact_health_changes: list[dict[str, Any]] = []
        with self.db.connect() as connection:
            source = connection.execute(
                "SELECT * FROM sources WHERE id=? AND project_id=?", (source_id, project_id)
            ).fetchone()
            if source is None:
                raise ValueError("SOURCE_SCOPE_MISMATCH")
            if source["status"] == "archived":
                return {
                    "source": self._normalize(dict(source)),
                    "affected_claims": [],
                    "proposal_ids": [],
                    "artifact_health_changes": [],
                    "invalid_links": [],
                }
            claim_rows = connection.execute(
                """
                SELECT DISTINCT pc.id,pc.verification_status
                FROM project_claim_evidence_links l
                JOIN project_claims pc ON pc.id=l.claim_id
                WHERE l.source_id=? AND l.active=1 AND pc.project_id=? AND pc.status='active'
                ORDER BY pc.id
                """,
                (source_id, project_id),
            ).fetchall()
            before_by_claim = {row["id"]: row["verification_status"] for row in claim_rows}
            connection.execute("UPDATE sources SET status='archived' WHERE id=?", (source_id,))
            connection.execute(
                "UPDATE project_claim_evidence_links SET active=0 WHERE source_id=? AND active=1",
                (source_id,),
            )
            direct_artifacts = connection.execute(
                "SELECT artifact_type,artifact_id FROM artifact_dependencies WHERE dependency_type='source' AND dependency_id=?",
                (source_id,),
            ).fetchall()
            for artifact in direct_artifacts:
                impact.health.set_tx(
                    connection, artifact_type=artifact["artifact_type"], artifact_id=artifact["artifact_id"],
                    health_status="stale_evidence", reason=f"source {source_id} archived", trigger_source_id=source_id,
                )
                payload = dict(artifact)
                if payload not in artifact_health_changes:
                    artifact_health_changes.append(payload)
            for claim_id, before in before_by_claim.items():
                after = claims_service.recompute_status_tx(connection, claim_id)
                impact_result = None
                if before != after:
                    impact_result = impact.resolve_claim_change_tx(
                        connection,
                        project_id=project_id,
                        claim_id=claim_id,
                        before_status=before,
                        after_status=after,
                        trigger_source_id=source_id,
                        actor=actor,
                        stale_evidence=(after == "stale"),
                    )
                    if impact_result.get("proposal_id") and impact_result["proposal_id"] not in proposal_ids:
                        proposal_ids.append(impact_result["proposal_id"])
                    for artifact in impact_result.get("affected_artifacts", []):
                        if artifact not in artifact_health_changes:
                            artifact_health_changes.append(artifact)
                affected_claims.append({
                    "claim_id": claim_id,
                    "before": before,
                    "after": after,
                    "impact": impact_result,
                })
            self.db.insert_audit_tx(
                connection, actor=actor, action="source_archived", entity_type="source", entity_id=source_id,
                payload={
                    "project_id": project_id,
                    "affected_claim_ids": list(before_by_claim),
                    "proposal_ids": proposal_ids,
                },
            )
        source_after = self.get_source(source_id)
        return {
            "source": source_after,
            "affected_claims": affected_claims,
            "proposal_ids": proposal_ids,
            "artifact_health_changes": artifact_health_changes,
            "invalid_links": [],
        }

    def restore(self, project_id: str, source_id: str, *, actor: str) -> dict[str, Any]:
        claims_service, impact = self._require_lifecycle_services()
        affected_claims: list[dict[str, Any]] = []
        proposal_ids: list[str] = []
        artifact_health_changes: list[dict[str, Any]] = []
        invalid_links: list[dict[str, Any]] = []
        with self.db.connect() as connection:
            source = connection.execute(
                "SELECT * FROM sources WHERE id=? AND project_id=?", (source_id, project_id)
            ).fetchone()
            if source is None:
                raise ValueError("SOURCE_SCOPE_MISMATCH")
            computed_sha = hashlib.sha256(source["content"].encode("utf-8")).hexdigest()
            if computed_sha != source["sha256"]:
                raise ValueError("SOURCE_CONTENT_SHA_MISMATCH")

            link_rows = connection.execute(
                """
                SELECT l.*,pc.project_id AS claim_project_id,pc.verification_status
                FROM project_claim_evidence_links l
                JOIN project_claims pc ON pc.id=l.claim_id
                WHERE l.source_id=? AND l.active=0 AND pc.project_id=? AND pc.status='active'
                ORDER BY l.claim_id,l.chunk_id,l.relation
                """,
                (source_id, project_id),
            ).fetchall()
            before_by_claim = {row["claim_id"]: row["verification_status"] for row in link_rows}
            connection.execute("UPDATE sources SET status='active' WHERE id=?", (source_id,))

            for row in link_rows:
                if row["source_sha256_at_link"] != source["sha256"]:
                    invalid_links.append({
                        "claim_id": row["claim_id"],
                        "chunk_id": row["chunk_id"],
                        "relation": row["relation"],
                        "reason": "SOURCE_VERSION_CHANGED",
                    })
                    continue
                try:
                    claims_service.revalidate_existing_relation_tx(
                        connection, project_id=project_id, link=dict(row)
                    )
                except ValueError as exc:
                    invalid_links.append({
                        "claim_id": row["claim_id"],
                        "chunk_id": row["chunk_id"],
                        "relation": row["relation"],
                        "reason": str(exc),
                    })
                    continue
                connection.execute(
                    """
                    UPDATE project_claim_evidence_links SET active=1
                    WHERE claim_id=? AND chunk_id=? AND relation=?
                    """,
                    (row["claim_id"], row["chunk_id"], row["relation"]),
                )

            for claim_id, before in before_by_claim.items():
                after = claims_service.recompute_status_tx(connection, claim_id)
                impact_result = None
                if before != after:
                    impact_result = impact.resolve_claim_change_tx(
                        connection,
                        project_id=project_id,
                        claim_id=claim_id,
                        before_status=before,
                        after_status=after,
                        trigger_source_id=source_id,
                        actor=actor,
                        stale_evidence=False,
                    )
                    if impact_result.get("proposal_id") and impact_result["proposal_id"] not in proposal_ids:
                        proposal_ids.append(impact_result["proposal_id"])
                    for artifact in impact_result.get("affected_artifacts", []):
                        if artifact not in artifact_health_changes:
                            artifact_health_changes.append(artifact)
                affected_claims.append({
                    "claim_id": claim_id,
                    "before": before,
                    "after": after,
                    "impact": impact_result,
                })
            self.db.insert_audit_tx(
                connection, actor=actor, action="source_restored", entity_type="source", entity_id=source_id,
                payload={
                    "project_id": project_id,
                    "affected_claim_ids": list(before_by_claim),
                    "invalid_link_count": len(invalid_links),
                    "proposal_ids": proposal_ids,
                },
            )
        return {
            "source": self.get_source(source_id),
            "affected_claims": affected_claims,
            "proposal_ids": proposal_ids,
            "artifact_health_changes": artifact_health_changes,
            "invalid_links": invalid_links,
        }
