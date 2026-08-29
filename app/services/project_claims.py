from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any

from app.db import Database, utc_now
from app.services.ai_runtime import StructuredAIRuntime, build_ai_trace_payload
from app.services.retrieval_service import ProjectRetrievalService


ADMISSIBILITY: dict[str, set[str]] = {
    "real_user_research": {"target_user", "user_problem", "behavior", "value", "feasibility"},
    "public_source": {"target_user", "user_problem", "behavior", "value", "feasibility"},
    "user_input": set(),
    "model_hypothesis": set(),
    "implementation_evidence": {"feasibility"},
    "simulated_research": set(),
}

RELATIONS = {"supports", "contradicts", "contextualizes"}
DIRECTNESS = {"direct", "indirect"}
SCOPE_FIT = {"fit", "limited"}
RECENCY = {"current", "unknown", "stale"}


class ProjectClaimService:
    CRITICALITY_WEIGHT = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    STATUS_WEIGHT = {
        "contradicted": 6,
        "conflict": 5,
        "stale": 4,
        "unverified": 3,
        "limited_support": 2,
        "supported": 0,
    }
    ANALYZER_VERSION = "evidence-analyzer-v1"

    def __init__(
        self,
        db: Database | None = None,
        retrieval: ProjectRetrievalService | None = None,
        runtime: StructuredAIRuntime | None = None,
        impact_resolver: Any | None = None,
    ):
        self.db = db
        self.retrieval = retrieval
        self.runtime = runtime
        self.impact_resolver = impact_resolver

    def _require_db(self) -> Database:
        if self.db is None:
            raise RuntimeError("ProjectClaimService database is not configured")
        return self.db

    @staticmethod
    def _normalize_span(value: str) -> str:
        # Evidence matching is intentionally exact after only CRLF/CR normalization and outer trim.
        return value.replace("\r\n", "\n").replace("\r", "\n").strip()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        return dict(row)

    def _insert_claim_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        claim_type: str,
        statement: str,
        provenance: str,
        criticality: str,
        scope_note: str,
    ) -> dict[str, Any]:
        claim_id = f"claim_{uuid.uuid4().hex}"
        now = utc_now()
        connection.execute(
            """
            INSERT INTO project_claims(
                id, project_id, claim_type, statement, provenance, verification_status,
                criticality, scope_note, status, created_at, updated_at, supersedes_claim_id
            ) VALUES (?, ?, ?, ?, ?, 'unverified', ?, ?, 'active', ?, ?, NULL)
            """,
            (
                claim_id,
                project_id,
                claim_type,
                statement.strip(),
                provenance,
                criticality,
                scope_note,
                now,
                now,
            ),
        )
        row = connection.execute("SELECT * FROM project_claims WHERE id = ?", (claim_id,)).fetchone()
        return dict(row)

    def create_initial_claims_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        decision_id: str,
        brief: dict[str, Any],
        selected_candidate: dict[str, Any],
    ) -> list[dict[str, Any]]:
        claims: list[dict[str, Any]] = []
        provenance = dict(brief.get("provenance") or {})
        base_scope = "用户确认 IdeaBrief 仅确认系统理解准确，不构成市场事实验证。"
        claims.append(
            self._insert_claim_tx(
                connection,
                project_id=project_id,
                claim_type="target_user",
                statement=brief["target_user"],
                provenance=provenance.get("target_user", "model_hypothesis"),
                criticality="high",
                scope_note=base_scope,
            )
        )
        claims.append(
            self._insert_claim_tx(
                connection,
                project_id=project_id,
                claim_type="user_problem",
                statement=brief["problem"],
                provenance=provenance.get("problem", "model_hypothesis"),
                criticality="critical",
                scope_note=base_scope,
            )
        )
        claims.append(
            self._insert_claim_tx(
                connection,
                project_id=project_id,
                claim_type="value",
                statement=f"方案“{selected_candidate['title']}”能够产生预期价值：{selected_candidate['why_fit']}",
                provenance=selected_candidate.get("provenance", "model_hypothesis"),
                criticality="high",
                scope_note="这是方案设计假设，需要通过真实用户任务验证。",
            )
        )

        feasibility_statements: list[str] = []
        for item in selected_candidate.get("data_requirements", []):
            feasibility_statements.append(f"可以获得并可靠使用所需数据：{item}")
        if selected_candidate.get("major_dependency"):
            feasibility_statements.append(
                f"关键实现依赖可满足：{selected_candidate['major_dependency']}"
            )
        seen: set[str] = set()
        for statement in feasibility_statements:
            if statement in seen:
                continue
            seen.add(statement)
            claims.append(
                self._insert_claim_tx(
                    connection,
                    project_id=project_id,
                    claim_type="feasibility",
                    statement=statement,
                    provenance=selected_candidate.get("provenance", "model_hypothesis"),
                    criticality="critical",
                    scope_note="技术/数据可行性需由实际数据或实现证据验证。",
                )
            )

        for claim in claims:
            role = "assumption" if claim["claim_type"] == "feasibility" else "supports"
            connection.execute(
                "INSERT INTO decision_claim_links(decision_id, claim_id, role, created_at) VALUES (?, ?, ?, ?)",
                (decision_id, claim["id"], role, utc_now()),
            )
        return claims

    def next_best_action_tx(
        self,
        connection: sqlite3.Connection,
        claims: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not claims:
            return {
                "claim_id": None,
                "action": "继续完善方案",
                "reason": "当前没有可优先排序的关键判断。",
            }

        def score(claim: dict[str, Any]) -> tuple[int, int, int, str]:
            dep_count = int(
                connection.execute(
                    "SELECT COUNT(DISTINCT decision_id) FROM decision_claim_links WHERE claim_id = ?",
                    (claim["id"],),
                ).fetchone()[0]
            )
            feasibility_bonus = 2 if claim["claim_type"] == "feasibility" else 0
            return (
                self.CRITICALITY_WEIGHT.get(claim["criticality"], 0) + feasibility_bonus,
                self.STATUS_WEIGHT.get(claim["verification_status"], 0),
                dep_count,
                claim["id"],
            )

        target = max(claims, key=score)
        return {
            "claim_id": target["id"],
            "claim_type": target["claim_type"],
            "action": f"验证：{target['statement']}",
            "reason": "这是当前高关键度、尚未验证且影响已确认方案的判断。",
            "verification_status": target["verification_status"],
        }

    def list_claims(self, project_id: str) -> list[dict[str, Any]]:
        db = self._require_db()
        if db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise KeyError("project not found")
        return db.fetch_all(
            "SELECT * FROM project_claims WHERE project_id=? AND status='active' ORDER BY criticality DESC, created_at, id",
            (project_id,),
        )

    def get_claim(self, project_id: str, claim_id: str) -> dict[str, Any]:
        db = self._require_db()
        row = db.fetch_one(
            "SELECT * FROM project_claims WHERE id=? AND project_id=? AND status='active'",
            (claim_id, project_id),
        )
        if row is None:
            raise KeyError("project claim not found")
        row["evidence"] = db.fetch_all(
            """
            SELECT l.*, s.title AS source_title, s.source_type, s.status AS source_status
            FROM project_claim_evidence_links l
            JOIN sources s ON s.id=l.source_id
            WHERE l.claim_id=? ORDER BY l.created_at, l.source_id, l.chunk_id
            """,
            (claim_id,),
        )
        return row

    def _validate_relation_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        claim_id: str,
        source_id: str,
        chunk_id: str,
        relation: str,
        directness: str,
        scope_fit: str,
        recency_state: str,
        retrieval_run_id: str | None,
        analysis_version: str,
        evidence_span: str,
        reason: str,
    ) -> dict[str, Any]:
        if relation not in RELATIONS:
            raise ValueError("INVALID_EVIDENCE_RELATION")
        if directness not in DIRECTNESS:
            raise ValueError("INVALID_EVIDENCE_DIRECTNESS")
        if scope_fit not in SCOPE_FIT:
            raise ValueError("INVALID_EVIDENCE_SCOPE_FIT")
        if recency_state not in RECENCY:
            raise ValueError("INVALID_EVIDENCE_RECENCY")
        claim = connection.execute(
            "SELECT * FROM project_claims WHERE id=? AND project_id=? AND status='active'",
            (claim_id, project_id),
        ).fetchone()
        if claim is None:
            raise ValueError("EVIDENCE_SCOPE_MISMATCH: claim is not active in project")
        row = connection.execute(
            """
            SELECT s.*, c.id AS chunk_id, c.project_id AS chunk_project_id, c.source_id AS chunk_source_id,
                   c.content AS chunk_content
            FROM sources s JOIN source_chunks c ON c.source_id=s.id
            WHERE s.id=? AND c.id=?
            """,
            (source_id, chunk_id),
        ).fetchone()
        if row is None:
            raise ValueError("EVIDENCE_SCOPE_MISMATCH: source/chunk pair not found")
        if row["project_id"] != project_id or row["chunk_project_id"] != project_id or row["chunk_source_id"] != source_id:
            raise ValueError("EVIDENCE_SCOPE_MISMATCH: source or chunk belongs to another project")
        if row["status"] != "active":
            raise ValueError("SOURCE_NOT_ACTIVE")
        if claim["claim_type"] not in ADMISSIBILITY.get(row["source_type"], set()):
            raise ValueError(
                f"SOURCE_TYPE_NOT_ADMISSIBLE: {row['source_type']} cannot validate {claim['claim_type']}"
            )
        if recency_state == "stale":
            raise ValueError("STALE_EVIDENCE_NOT_ADMISSIBLE")
        normalized_span = self._normalize_span(evidence_span)
        normalized_chunk = self._normalize_span(row["chunk_content"])
        if not normalized_span or normalized_span not in normalized_chunk:
            raise ValueError("EVIDENCE_SPAN_NOT_FOUND")
        if retrieval_run_id:
            hit = connection.execute(
                """
                SELECT 1 FROM retrieval_hits h JOIN retrieval_runs r ON r.id=h.run_id
                WHERE h.run_id=? AND h.chunk_id=? AND h.source_id=? AND h.project_id=?
                  AND r.project_id=?
                """,
                (retrieval_run_id, chunk_id, source_id, project_id, project_id),
            ).fetchone()
            if hit is None:
                raise ValueError("RETRIEVAL_TRACE_SCOPE_MISMATCH")
        return {
            "project_id": project_id,
            "claim_id": claim_id,
            "claim_type": claim["claim_type"],
            "source_id": source_id,
            "source_type": row["source_type"],
            "source_sha256": row["sha256"],
            "chunk_id": chunk_id,
            "relation": relation,
            "directness": directness,
            "scope_fit": scope_fit,
            "recency_state": recency_state,
            "retrieval_run_id": retrieval_run_id,
            "analysis_version": analysis_version.strip() or self.ANALYZER_VERSION,
            "evidence_span": normalized_span,
            "reason": reason.strip(),
        }

    def revalidate_existing_relation_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        link: dict[str, Any],
    ) -> dict[str, Any]:
        return self._validate_relation_tx(
            connection,
            project_id=project_id,
            claim_id=link["claim_id"],
            source_id=link["source_id"],
            chunk_id=link["chunk_id"],
            relation=link["relation"],
            directness=link["directness"],
            scope_fit=link["scope_fit"],
            recency_state=link["recency_state"],
            retrieval_run_id=link.get("retrieval_run_id"),
            analysis_version=link["analysis_version"],
            evidence_span=link["evidence_span"],
            reason=link.get("reason", ""),
        )

    def validate_relation_proposal(self, **proposal: Any) -> dict[str, Any]:
        db = self._require_db()
        with db.connect() as connection:
            return self._validate_relation_tx(connection, **proposal)

    def persist_relation(self, **proposal: Any) -> dict[str, Any]:
        db = self._require_db()
        with db.connect() as connection:
            validated = self._validate_relation_tx(connection, **proposal)
            now = utc_now()
            connection.execute(
                """
                INSERT INTO project_claim_evidence_links(
                    claim_id, source_id, chunk_id, relation, directness, scope_fit,
                    recency_state, retrieval_run_id, analysis_version, evidence_span,
                    reason, source_sha256_at_link, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(claim_id, chunk_id, relation) DO UPDATE SET
                    source_id=excluded.source_id,
                    directness=excluded.directness,
                    scope_fit=excluded.scope_fit,
                    recency_state=excluded.recency_state,
                    retrieval_run_id=excluded.retrieval_run_id,
                    analysis_version=excluded.analysis_version,
                    evidence_span=excluded.evidence_span,
                    reason=excluded.reason,
                    source_sha256_at_link=excluded.source_sha256_at_link,
                    active=1
                """,
                (
                    validated["claim_id"], validated["source_id"], validated["chunk_id"],
                    validated["relation"], validated["directness"], validated["scope_fit"],
                    validated["recency_state"], validated["retrieval_run_id"],
                    validated["analysis_version"], validated["evidence_span"], validated["reason"],
                    validated["source_sha256"], now,
                ),
            )
            claim_status = self.recompute_status_tx(connection, validated["claim_id"])
            link = connection.execute(
                """
                SELECT * FROM project_claim_evidence_links
                WHERE claim_id=? AND chunk_id=? AND relation=?
                """,
                (validated["claim_id"], validated["chunk_id"], validated["relation"]),
            ).fetchone()
            return {"link": dict(link), "claim_status": claim_status}

    def recompute_status_tx(self, connection: sqlite3.Connection, claim_id: str) -> str:
        claim = connection.execute(
            "SELECT * FROM project_claims WHERE id=? AND status='active'", (claim_id,)
        ).fetchone()
        if claim is None:
            raise KeyError("project claim not found")
        rows = connection.execute(
            """
            SELECT l.*, s.status AS source_status
            FROM project_claim_evidence_links l JOIN sources s ON s.id=l.source_id
            WHERE l.claim_id=?
            """,
            (claim_id,),
        ).fetchall()
        active = [
            row for row in rows
            if int(row["active"]) == 1 and row["source_status"] == "active" and row["recency_state"] != "stale"
        ]
        direct_support = {row["source_id"] for row in active if row["relation"] == "supports" and row["directness"] == "direct"}
        any_support = {row["source_id"] for row in active if row["relation"] == "supports"}
        direct_contradiction = {row["source_id"] for row in active if row["relation"] == "contradicts" and row["directness"] == "direct"}
        cross_conflict = any(left != right for left in direct_support for right in direct_contradiction)
        if cross_conflict:
            status = "conflict"
        elif direct_contradiction and not direct_support:
            status = "contradicted"
        elif len(direct_support) >= 2 and claim["scope_note"].strip() and not direct_contradiction:
            status = "supported"
        elif any_support and not direct_contradiction:
            status = "limited_support"
        else:
            previously_supported = any(row["relation"] == "supports" and int(row["active"]) == 0 for row in rows)
            status = "stale" if previously_supported and not direct_contradiction else "unverified"
        connection.execute(
            "UPDATE project_claims SET verification_status=?, updated_at=? WHERE id=?",
            (status, utc_now(), claim_id),
        )
        return status

    def analyze_project_evidence(
        self,
        project_id: str,
        *,
        claim_ids: list[str] | None = None,
        actor: str,
    ) -> dict[str, Any]:
        db = self._require_db()
        if self.retrieval is None or self.runtime is None:
            raise RuntimeError("Evidence analyzer runtime is not configured")
        claims = self.list_claims(project_id)
        if claim_ids:
            wanted = set(claim_ids)
            claims = [claim for claim in claims if claim["id"] in wanted]
            if len(claims) != len(wanted):
                raise KeyError("one or more project claims were not found")
        changes: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        resolver = getattr(self.runtime, "for_project", None)
        for claim in claims:
            runtime = resolver(project_id) if callable(resolver) else self.runtime
            admissible_types = [source_type for source_type, types in ADMISSIBILITY.items() if claim["claim_type"] in types]
            run = self.retrieval.execute_retrieval(
                project_id,
                claim["statement"],
                profile_id="balanced_traceable_v1",
                top_k=8,
                source_types=admissible_types,
                purpose="evidence_analysis",
                actor=actor,
            )
            started = time.perf_counter()
            output: list[dict[str, Any]] | None = None
            status = "completed"
            try:
                output = runtime.analyze_evidence(claim=claim, chunks=run["items"])
            except Exception:
                status = "failed"
                trace = build_ai_trace_payload(
                    runtime=runtime,
                    input_payload={"claim": claim, "chunks": run["items"]},
                    output_payload=None,
                    started_at=started,
                    status=status,
                    component_version=self.ANALYZER_VERSION,
                )
                db.insert_audit(
                    actor=actor,
                    action="project_evidence_analyzed",
                    entity_type="project_claim",
                    entity_id=claim["id"],
                    payload={**trace, "project_id": project_id, "retrieval_run_id": run["run_id"]},
                )
                raise
            trace = build_ai_trace_payload(
                runtime=runtime,
                input_payload={"claim": claim, "chunks": run["items"]},
                output_payload=output,
                started_at=started,
                status=status,
                component_version=self.ANALYZER_VERSION,
            )
            db.insert_audit(
                actor=actor,
                action="project_evidence_analyzed",
                entity_type="project_claim",
                entity_id=claim["id"],
                payload={**trace, "project_id": project_id, "retrieval_run_id": run["run_id"]},
            )
            before = claim["verification_status"]
            for raw in output:
                proposal = {
                    "project_id": project_id,
                    "claim_id": claim["id"],
                    "source_id": raw["source_id"],
                    "chunk_id": raw["chunk_id"],
                    "relation": raw["relation"],
                    "directness": raw.get("directness", "direct"),
                    "scope_fit": raw.get("scope_fit", "fit"),
                    "recency_state": raw.get("recency_state", "current"),
                    "retrieval_run_id": run["run_id"],
                    "analysis_version": self.ANALYZER_VERSION,
                    "evidence_span": raw["evidence_span"],
                    "reason": raw.get("reason", ""),
                }
                try:
                    persisted = self.persist_relation(**proposal)
                except ValueError as exc:
                    rejected.append({"claim_id": claim["id"], "proposal": raw, "reason": str(exc)})
                    continue
                after = persisted["claim_status"]
                impact = None
                if before != after and self.impact_resolver is not None:
                    impact = self.impact_resolver.resolve_claim_change(
                        project_id=project_id,
                        claim_id=claim["id"],
                        before_status=before,
                        after_status=after,
                        trigger_source_id=raw["source_id"],
                        actor=actor,
                    )
                changes.append({
                    "claim_id": claim["id"],
                    "before": before,
                    "after": after,
                    "link": persisted["link"],
                    "impact": impact,
                })
                before = after
        return {"project_id": project_id, "changes": changes, "rejected": rejected}

    def impact_summary(self, project_id: str) -> dict[str, Any]:
        claims = self.list_claims(project_id)
        return {
            "project_id": project_id,
            "claims": [
                {
                    "claim_id": claim["id"],
                    "statement": claim["statement"],
                    "claim_type": claim["claim_type"],
                    "criticality": claim["criticality"],
                    "verification_status": claim["verification_status"],
                    "scope_note": claim["scope_note"],
                }
                for claim in claims
            ],
        }
