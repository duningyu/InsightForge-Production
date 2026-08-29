from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import Database, SOURCE_TYPES, utc_now
from app.retrieval import HybridRetriever
from app.retrieval_profiles import get_retrieval_profile


class ProjectRetrievalService:
    """Project-scoped retrieval with persisted, replayable run metadata."""

    def __init__(self, db: Database, retriever: HybridRetriever | None = None):
        self.db = db
        self._legacy_retriever = retriever

    def execute_retrieval(
        self,
        project_id: str,
        query: str,
        *,
        profile_id: str = "balanced_traceable_v1",
        top_k: int | None = None,
        source_types: list[str] | None = None,
        purpose: str = "manual_search",
        actor: str = "system",
    ) -> dict[str, Any]:
        if self.db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,)) is None:
            raise KeyError("project not found")
        if not query.strip():
            raise ValueError("query is required")
        if not actor.strip():
            raise ValueError("actor is required")

        profile = get_retrieval_profile(profile_id)
        effective_top_k = profile.top_k if top_k is None else top_k
        if not 1 <= effective_top_k <= 30:
            raise ValueError("top_k must be in [1, 30]")

        normalized_types = list(dict.fromkeys(source_types or []))
        invalid = sorted(set(normalized_types) - SOURCE_TYPES)
        if invalid:
            raise ValueError(f"invalid source types: {invalid}")

        params: list[Any] = [project_id]
        where = "c.project_id = ? AND COALESCE(s.status, 'active') = 'active'"
        if normalized_types:
            placeholders = ",".join("?" for _ in normalized_types)
            where += f" AND s.source_type IN ({placeholders})"
            params.extend(normalized_types)

        rows = self.db.fetch_all(
            f"""
            SELECT c.id AS chunk_id, c.source_id, c.project_id, c.chunk_index,
                   c.content, s.title AS source_title, s.filename,
                   s.source_type, s.authority, s.sha256, s.source_url,
                   s.publisher, s.published_at, s.captured_at,
                   s.authority_label, s.authority_basis
            FROM source_chunks c
            JOIN sources s ON s.id = c.source_id
            WHERE {where}
            ORDER BY c.source_id, c.chunk_index
            """,
            tuple(params),
        )

        retriever = self._legacy_retriever or HybridRetriever(
            bm25_weight=profile.bm25_weight,
            cosine_weight=profile.cosine_weight,
            authority_weight=profile.authority_weight,
        )
        ranked = retriever.search(query, rows, top_k=effective_top_k)
        for item in ranked:
            item["citation"] = f"[source:{item['source_id']}#chunk:{item['chunk_id']}]"

        run_id = f"retrieval_{uuid.uuid4().hex}"
        for item in ranked:
            item["retrieval_run_id"] = run_id
        created_at = utc_now()
        self.db.execute(
            """
            INSERT INTO retrieval_runs(
                id, project_id, query, purpose, profile_id, top_k,
                bm25_weight, cosine_weight, authority_weight,
                source_types_json, candidate_count, returned_count,
                actor, selection_basis, validation_status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                query.strip(),
                purpose,
                profile.id,
                effective_top_k,
                profile.bm25_weight,
                profile.cosine_weight,
                profile.authority_weight,
                json.dumps(normalized_types, ensure_ascii=False),
                len(rows),
                len(ranked),
                actor,
                profile.selection_basis,
                profile.validation_status,
                created_at,
            ),
        )
        for item in ranked:
            self.db.execute(
                """
                INSERT INTO retrieval_hits(
                    run_id, rank, chunk_id, source_id, project_id,
                    bm25_score, cosine_score, authority_score, hybrid_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(item["rank"]),
                    item["chunk_id"],
                    item["source_id"],
                    project_id,
                    float(item["bm25_score"]),
                    float(item["cosine_score"]),
                    float(item["authority_score"]),
                    float(item["hybrid_score"]),
                ),
            )

        config = {
            "profile_id": profile.id,
            "profile_label": profile.label,
            "profile_description": profile.description,
            "effective_top_k": effective_top_k,
            "top_k_source": "profile_default" if top_k is None else "explicit_override",
            "weights": profile.weights,
            "selection_basis": profile.selection_basis,
            "validation_status": profile.validation_status,
            "tradeoff": profile.tradeoff,
            "purpose": purpose,
        }
        return {
            "run_id": run_id,
            "project_id": project_id,
            "query": query.strip(),
            "config": config,
            "candidate_count": len(rows),
            "returned_count": len(ranked),
            "items": ranked,
            "created_at": created_at,
        }

    def retrieve_project_sources(
        self,
        project_id: str,
        query: str,
        top_k: int = 8,
        source_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Backward-compatible list-returning API used by existing code/tests."""
        return self.execute_retrieval(
            project_id,
            query,
            profile_id="balanced_traceable_v1",
            top_k=top_k,
            source_types=source_types,
            purpose="legacy_service_call",
            actor="system",
        )["items"]

    def list_runs(self, project_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        if self.db.fetch_one("SELECT id FROM projects WHERE id = ?", (project_id,)) is None:
            raise KeyError("project not found")
        rows = self.db.fetch_all(
            """
            SELECT * FROM retrieval_runs
            WHERE project_id = ?
            ORDER BY created_at DESC, id DESC LIMIT ?
            """,
            (project_id, limit),
        )
        for row in rows:
            row["source_types"] = json.loads(row.pop("source_types_json"))
            row["weights"] = {
                "bm25": row["bm25_weight"],
                "cosine": row["cosine_weight"],
                "authority": row["authority_weight"],
            }
        return rows

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self.db.fetch_one("SELECT * FROM retrieval_runs WHERE id = ?", (run_id,))
        if run is None:
            raise KeyError("retrieval run not found")
        run["source_types"] = json.loads(run.pop("source_types_json"))
        run["weights"] = {
            "bm25": run["bm25_weight"],
            "cosine": run["cosine_weight"],
            "authority": run["authority_weight"],
        }
        run["items"] = self.db.fetch_all(
            """
            SELECT h.rank, h.bm25_score, h.cosine_score, h.authority_score,
                   h.hybrid_score, h.chunk_id, h.source_id, h.project_id,
                   c.chunk_index, c.content, s.title AS source_title,
                   s.filename, s.source_type, s.authority, s.sha256,
                   s.source_url, s.publisher, s.published_at, s.captured_at,
                   s.authority_label, s.authority_basis
            FROM retrieval_hits h
            JOIN source_chunks c ON c.id = h.chunk_id
            JOIN sources s ON s.id = h.source_id
            WHERE h.run_id = ?
            ORDER BY h.rank
            """,
            (run_id,),
        )
        for item in run["items"]:
            item["citation"] = f"[source:{item['source_id']}#chunk:{item['chunk_id']}]"
        return run

    def valid_citations(self, project_id: str) -> dict[str, dict[str, Any]]:
        rows = self.db.fetch_all(
            """
            SELECT c.id AS chunk_id, c.source_id, c.project_id, c.chunk_index,
                   c.content, s.title AS source_title, s.source_type, s.authority,
                   s.source_url, s.publisher, s.authority_label, s.authority_basis
            FROM source_chunks c JOIN sources s ON s.id = c.source_id
            WHERE c.project_id = ? AND COALESCE(s.status, 'active') = 'active'
            """,
            (project_id,),
        )
        return {
            f"[source:{row['source_id']}#chunk:{row['chunk_id']}]": row
            for row in rows
        }
