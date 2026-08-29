from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import Database, utc_now


class ClaimService:
    """Persist and read version-scoped claim/evidence ledgers."""

    def __init__(self, db: Database):
        self.db = db

    def persist(
        self,
        *,
        version_id: str,
        project_id: str,
        claims: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if self.db.fetch_one("SELECT id FROM document_versions WHERE id = ?", (version_id,)) is None:
            raise KeyError("document version not found")
        for claim in claims:
            claim_id = f"claim_{uuid.uuid4().hex}"
            metadata = dict(claim.get("metadata") or {})
            self.db.execute(
                """
                INSERT INTO document_claims(
                    id, version_id, project_id, section, claim_text, claim_type,
                    support_status, explanation, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    version_id,
                    project_id,
                    str(claim.get("section") or "未分组"),
                    str(claim.get("claim_text") or "").strip(),
                    str(claim.get("claim_type") or "unresolved"),
                    str(claim.get("support_status") or "unresolved"),
                    str(claim.get("explanation") or ""),
                    json.dumps(metadata, ensure_ascii=False),
                    utc_now(),
                ),
            )
            for evidence in claim.get("evidence") or []:
                source_id = evidence.get("source_id")
                chunk_id = evidence.get("chunk_id")
                if not source_id or not chunk_id:
                    citation = str(evidence.get("citation") or "")
                    resolved = self._resolve_citation(project_id, citation)
                    source_id = resolved["source_id"]
                    chunk_id = resolved["chunk_id"]
                self.db.execute(
                    """
                    INSERT OR IGNORE INTO claim_evidence_links(
                        claim_id, source_id, chunk_id, relation,
                        retrieval_run_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        source_id,
                        chunk_id,
                        str(evidence.get("relation") or "supports"),
                        evidence.get("retrieval_run_id"),
                        utc_now(),
                    ),
                )
        return self.list_for_version(version_id)["items"]

    def list_for_version(self, version_id: str) -> dict[str, Any]:
        version = self.db.fetch_one(
            "SELECT id, project_id, doc_type, version FROM document_versions WHERE id = ? AND lifecycle_status = 'active'",
            (version_id,),
        )
        if version is None:
            raise KeyError("document version not found")
        claims = self.db.fetch_all(
            """
            SELECT id, version_id, project_id, section, claim_text, claim_type,
                   support_status, explanation, metadata_json, created_at
            FROM document_claims WHERE version_id = ?
            ORDER BY created_at, id
            """,
            (version_id,),
        )
        for claim in claims:
            claim["metadata"] = json.loads(claim.pop("metadata_json") or "{}")
            claim["evidence"] = self.db.fetch_all(
                """
                SELECT l.relation, l.retrieval_run_id, l.source_id, l.chunk_id,
                       s.title AS source_title, s.filename, s.source_type,
                       s.authority, s.authority_label, s.authority_basis,
                       s.source_url, s.publisher, s.published_at, s.captured_at,
                       c.chunk_index, c.content
                FROM claim_evidence_links l
                JOIN sources s ON s.id = l.source_id
                JOIN source_chunks c ON c.id = l.chunk_id
                WHERE l.claim_id = ?
                ORDER BY l.relation, l.chunk_id
                """,
                (claim["id"],),
            )
            for evidence in claim["evidence"]:
                evidence["citation"] = (
                    f"[source:{evidence['source_id']}#chunk:{evidence['chunk_id']}]"
                )
        return {
            "version_id": version_id,
            "project_id": version["project_id"],
            "doc_type": version["doc_type"],
            "document_version": version["version"],
            "items": claims,
        }

    def _resolve_citation(self, project_id: str, citation: str) -> dict[str, Any]:
        prefix = "[source:"
        middle = "#chunk:"
        if not citation.startswith(prefix) or middle not in citation or not citation.endswith("]"):
            raise ValueError(f"invalid citation: {citation}")
        body = citation[len(prefix) : -1]
        source_id, chunk_id = body.split(middle, 1)
        row = self.db.fetch_one(
            """
            SELECT c.source_id, c.id AS chunk_id
            FROM source_chunks c
            WHERE c.project_id = ? AND c.source_id = ? AND c.id = ?
            """,
            (project_id, source_id, chunk_id),
        )
        if row is None:
            raise ValueError(f"citation is outside project scope: {citation}")
        return row
