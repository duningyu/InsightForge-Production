from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import Database, stable_id, utc_now
from app.services.claims import ClaimService
from app.services.generation import LocalDocumentGenerator, build_generator
from app.services.retrieval_service import ProjectRetrievalService
from app.services.validation import DocumentValidator
from app.services.artifact_health import ArtifactHealthService


class DocumentLoop:
    def __init__(
        self,
        db: Database,
        *,
        generator: LocalDocumentGenerator | None = None,
        validator: DocumentValidator | None = None,
        retrieval: ProjectRetrievalService | None = None,
        max_rounds: int = 2,
    ):
        if max_rounds < 1 or max_rounds > 5:
            raise ValueError("max_rounds must be in [1, 5]")
        self.db = db
        self.generator = generator or build_generator()
        self.validator = validator or DocumentValidator()
        self.retrieval = retrieval or ProjectRetrievalService(db)
        self.claims = ClaimService(db)
        self.health = ArtifactHealthService(db)
        self.max_rounds = max_rounds

    def run(
        self,
        project_id: str,
        doc_type: str,
        *,
        idempotency_key: str | None = None,
        require_snapshot: bool = False,
    ) -> dict[str, Any]:
        if doc_type not in {"prd", "techdoc"}:
            raise ValueError("doc_type must be prd or techdoc")
        project = self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        current_snapshot_id = project.get("current_snapshot_id")
        if require_snapshot and not current_snapshot_id:
            raise ValueError("current confirmed Snapshot is required for 3.0 document generation")
        canvas = self.db.get_canvas(project_id)
        if canvas is None:
            raise ValueError("project canvas is missing")

        if idempotency_key:
            existing = self.db.fetch_one(
                "SELECT * FROM document_versions WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            if existing is not None:
                if existing["project_id"] != project_id or existing["doc_type"] != doc_type:
                    raise ValueError("idempotency key is already bound to another request")
                terminal_state = (
                    "completed"
                    if existing["validation_status"] == "passed"
                    else "needs_human_review"
                )
                return self._version_result(
                    existing,
                    reused=True,
                    rounds=0,
                    terminal_state=terminal_state,
                )
        effective_key = idempotency_key or f"{project_id}:{doc_type}:{uuid.uuid4().hex}"

        run_id = f"generation_{uuid.uuid4().hex}"
        now = utc_now()
        self.db.execute(
            """
            INSERT INTO generation_runs(
                id, project_id, doc_type, status, terminal_state, rounds,
                version_id, retrieval_run_ids_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                doc_type,
                "running",
                "running",
                0,
                None,
                "[]",
                now,
                now,
            ),
        )

        evidence, retrieval_run_ids = self._collect_evidence(project_id, canvas)
        self.db.execute(
            "UPDATE generation_runs SET retrieval_run_ids_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(retrieval_run_ids, ensure_ascii=False), utc_now(), run_id),
        )
        generated = self.generator.generate(
            doc_type,
            canvas,
            evidence,
            project_title=project["title"],
        )
        content = generated["content"]
        citations = generated["citations"]
        structured_claims = list(generated.get("claims") or [])
        valid_citations = self.retrieval.valid_citations(project_id)
        terminal_state = "needs_human_review"
        final_issues: list[dict[str, Any]] = []
        rounds = 0

        for round_no in range(1, self.max_rounds + 1):
            rounds = round_no
            issues = self.validator.validate(
                content=content,
                valid_citations=valid_citations,
                canvas=canvas,
                doc_type=doc_type,
                claims=structured_claims,
            )
            final_issues = issues
            for issue in issues:
                self.db.execute(
                    """
                    INSERT INTO validation_issues(
                        id, generation_run_id, version_id, round_no, code,
                        severity, message, section, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"issue_{uuid.uuid4().hex}",
                        run_id,
                        None,
                        round_no,
                        issue["code"],
                        issue["severity"],
                        issue["message"],
                        issue.get("section"),
                        utc_now(),
                    ),
                )
            if not issues:
                terminal_state = "completed"
                break
            if round_no < self.max_rounds:
                content = self.generator.repair(content, issues, evidence)

        document_id = stable_id("document", f"{project_id}:{doc_type}")
        title = f"{project['title']} {'PRD' if doc_type == 'prd' else 'TechDoc'}"
        self.db.execute(
            "INSERT OR IGNORE INTO documents(id, project_id, doc_type, title, created_at) VALUES (?, ?, ?, ?, ?)",
            (document_id, project_id, doc_type, title, utc_now()),
        )
        version_row = self.db.fetch_one(
            "SELECT COALESCE(MAX(version), 0) AS max_version FROM document_versions WHERE document_id = ?",
            (document_id,),
        )
        assert version_row is not None
        version = int(version_row["max_version"]) + 1
        version_id = f"version_{uuid.uuid4().hex}"
        validation_status = "passed" if terminal_state == "completed" else "needs_human_review"
        self.db.execute(
            """
            INSERT INTO document_versions(
                id, document_id, project_id, doc_type, version, canvas_version,
                status, content, citations_json, validation_status,
                idempotency_key, created_at, approved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                document_id,
                project_id,
                doc_type,
                version,
                int(canvas["version"]),
                "draft",
                content,
                json.dumps(citations, ensure_ascii=False),
                validation_status,
                effective_key,
                utc_now(),
                None,
            ),
        )
        if structured_claims:
            self.claims.persist(
                version_id=version_id,
                project_id=project_id,
                claims=structured_claims,
            )
        if current_snapshot_id:
            self._persist_v3_dependencies(
                version_id=version_id,
                project_id=project_id,
                snapshot_id=current_snapshot_id,
                citations=citations,
                evidence=evidence,
            )
        self.db.execute(
            "UPDATE validation_issues SET version_id = ? WHERE generation_run_id = ?",
            (version_id, run_id),
        )
        status = "completed" if terminal_state == "completed" else "needs_human_review"
        self.db.execute(
            """
            UPDATE generation_runs
            SET status = ?, terminal_state = ?, rounds = ?, version_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, terminal_state, rounds, version_id, utc_now(), run_id),
        )
        self.db.insert_audit(
            actor="system",
            action="document_loop_completed",
            entity_type="document_version",
            entity_id=version_id,
            payload={
                "project_id": project_id,
                "doc_type": doc_type,
                "terminal_state": terminal_state,
                "rounds": rounds,
                "issue_codes": [issue["code"] for issue in final_issues],
                "retrieval_run_ids": retrieval_run_ids,
                "claim_count": len(structured_claims),
            },
        )
        row = self.db.fetch_one("SELECT * FROM document_versions WHERE id = ?", (version_id,))
        assert row is not None
        result = self._version_result(
            row,
            reused=False,
            rounds=rounds,
            terminal_state=terminal_state,
        )
        result.update(
            {
                "run_id": run_id,
                "issues": final_issues,
                "retrieval_run_ids": retrieval_run_ids,
            }
        )
        return result

    def _collect_evidence(
        self,
        project_id: str,
        canvas: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        queries = [
            ("problem", str(canvas.get("problem", ""))),
            ("target_users", str(canvas.get("target_users", ""))),
            ("public_context", "竞品 差异 公开资料 引用 版本"),
            ("implementation", "MVP 实现 技术 架构 API 测试"),
            ("simulated_context", "模拟 人工构造 用户痛点 来源真实性"),
        ]
        collected: dict[str, dict[str, Any]] = {}
        run_ids: list[str] = []
        for label, query in queries:
            if not query.strip():
                continue
            result = self.retrieval.execute_retrieval(
                project_id,
                query,
                profile_id="document_generation_v1",
                source_types=None,
                purpose=f"document_generation:{label}",
                actor="system",
            )
            run_ids.append(result["run_id"])
            for item in result["items"]:
                previous = collected.get(item["chunk_id"])
                if previous is None or float(item["hybrid_score"]) > float(
                    previous["hybrid_score"]
                ):
                    collected[item["chunk_id"]] = item

        source_rows = self.db.fetch_all(
            """
            SELECT id, title, source_type, content
            FROM sources
            WHERE project_id = ? AND COALESCE(status, 'active') = 'active'
            ORDER BY source_type, id
            """,
            (project_id,),
        )
        seen_types = {item["source_type"] for item in collected.values()}
        for source in source_rows:
            if source["source_type"] in seen_types:
                continue
            query = f"{source['title']} {source['content'][:160]}"
            result = self.retrieval.execute_retrieval(
                project_id,
                query,
                profile_id="document_generation_v1",
                top_k=1,
                source_types=[source["source_type"]],
                purpose=f"document_generation:source_type_fallback:{source['source_type']}",
                actor="system",
            )
            run_ids.append(result["run_id"])
            if result["items"]:
                item = result["items"][0]
                collected[item["chunk_id"]] = item
                seen_types.add(source["source_type"])

        ordered = sorted(
            collected.values(),
            key=lambda item: (
                -float(item.get("hybrid_score", 0.0)),
                str(item.get("source_type", "")),
                str(item.get("chunk_id", "")),
            ),
        )[:16]
        return ordered, list(dict.fromkeys(run_ids))

    def _persist_v3_dependencies(
        self,
        *,
        version_id: str,
        project_id: str,
        snapshot_id: str,
        citations: list[str],
        evidence: list[dict[str, Any]],
    ) -> None:
        now = utc_now()
        citation_set = set(citations)
        source_ids = sorted({
            str(item["source_id"])
            for item in evidence
            if item.get("citation") in citation_set and item.get("source_id")
        })
        claims = self.db.fetch_all(
            "SELECT id FROM project_claims WHERE project_id=? AND status='active' ORDER BY id",
            (project_id,),
        )
        with self.db.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO artifact_dependencies(artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at) VALUES ('document_version',?,?,?,?,?)",
                (version_id, "project_snapshot", snapshot_id, None, now),
            )
            for claim in claims:
                connection.execute(
                    "INSERT OR IGNORE INTO artifact_dependencies(artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at) VALUES ('document_version',?,?,?,?,?)",
                    (version_id, "project_claim", claim["id"], None, now),
                )
            for source_id in source_ids:
                connection.execute(
                    "INSERT OR IGNORE INTO artifact_dependencies(artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at) VALUES ('document_version',?,?,?,?,?)",
                    (version_id, "source", source_id, None, now),
                )
            self.health.set_tx(
                connection, artifact_type="document_version", artifact_id=version_id,
                health_status="current", reason="generated from current confirmed Snapshot and active dependencies",
            )

    def _version_result(
        self,
        row: dict[str, Any],
        *,
        reused: bool,
        rounds: int,
        terminal_state: str,
    ) -> dict[str, Any]:
        claim_payload = self.claims.list_for_version(row["id"])
        generation = self.db.fetch_one(
            """
            SELECT id, retrieval_run_ids_json
            FROM generation_runs WHERE version_id = ?
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (row["id"],),
        )
        retrieval_run_ids = (
            json.loads(generation["retrieval_run_ids_json"])
            if generation is not None
            else []
        )
        health = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (row["id"],),
        )
        return {
            "version_id": row["id"],
            "document_id": row["document_id"],
            "project_id": row["project_id"],
            "doc_type": row["doc_type"],
            "version": row["version"],
            "canvas_version": row["canvas_version"],
            "status": row["status"],
            "validation_status": row["validation_status"],
            "content": row["content"],
            "citations": json.loads(row["citations_json"]),
            "claims": claim_payload["items"],
            "retrieval_run_ids": retrieval_run_ids,
            "rounds": rounds,
            "terminal_state": terminal_state,
            "reused": reused,
            "artifact_health": health,
        }
