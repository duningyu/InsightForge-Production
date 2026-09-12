from __future__ import annotations

import json
import uuid
from typing import Any

from app.db import Database, stable_id, utc_now
from app.services.claims import ClaimService
from app.services.generation import LocalDocumentGenerator, build_generator
from app.services.retrieval_service import ProjectRetrievalService
from app.services.validation import DocumentValidator, PRD_HEADINGS, TECHDOC_HEADINGS
from app.services.artifact_health import ArtifactHealthService
from app.services.generation_contracts import (
    GenerationContractError, validate_document_sections, validate_document_draft, call_generation,
    reject_raw_generation_values,
)


_UNSET_COMPETITOR_BINDING = object()


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
        competitor_snapshot_id: str | None | object = _UNSET_COMPETITOR_BINDING,
        use_competitor_snapshot: bool = True,
    ) -> dict[str, Any]:
        if doc_type not in {"prd", "techdoc"}:
            raise ValueError("doc_type must be prd or techdoc")
        project = self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        current_snapshot_id = project.get("current_snapshot_id")
        current_competitor_snapshot_id = project.get("current_competitor_snapshot_id")
        explicit_competitor_binding = competitor_snapshot_id is not _UNSET_COMPETITOR_BINDING
        bound_competitor_snapshot_id = None if not explicit_competitor_binding else competitor_snapshot_id
        effective_competitor_snapshot_id = bound_competitor_snapshot_id
        if use_competitor_snapshot and explicit_competitor_binding and bound_competitor_snapshot_id is None:
            raise ValueError("current confirmed competitor snapshot is required for this document generation")
        if use_competitor_snapshot and bound_competitor_snapshot_id is not None:
            competitor_snapshot = self.db.fetch_one(
                "SELECT project_id FROM competitor_decision_snapshots WHERE id = ?",
                (bound_competitor_snapshot_id,),
            )
            if competitor_snapshot is None or competitor_snapshot["project_id"] != project_id:
                raise ValueError("competitor snapshot is not part of this project")
        if require_snapshot and not current_snapshot_id:
            raise ValueError("current confirmed Snapshot is required for 3.0 document generation")
        snapshot = None
        if current_snapshot_id:
            snapshot = self.db.fetch_one(
                "SELECT * FROM project_snapshots WHERE id=?", (current_snapshot_id,)
            )
            if not snapshot or snapshot["project_id"] != project_id or not snapshot["confirmed_at"]:
                raise GenerationContractError("DOCUMENT_SNAPSHOT_BINDING_FAILED")
        if use_competitor_snapshot and not explicit_competitor_binding:
            effective_competitor_snapshot_id = current_competitor_snapshot_id
            if effective_competitor_snapshot_id:
                competitor = self.db.fetch_one(
                    "SELECT project_id FROM competitor_decision_snapshots WHERE id=?", (effective_competitor_snapshot_id,)
                )
                if not competitor or competitor["project_id"] != project_id:
                    raise GenerationContractError("DOCUMENT_SNAPSHOT_BINDING_FAILED")
        if require_snapshot and use_competitor_snapshot and not (
            current_competitor_snapshot_id or bound_competitor_snapshot_id
        ):
            raise ValueError("current confirmed competitor snapshot is required for this document generation")
        canvas = self.db.get_canvas(project_id)
        if canvas is None:
            raise ValueError("project canvas is missing")
        generation_canvas = self._canvas_with_snapshot_context(canvas, snapshot)

        if idempotency_key:
            existing = self.db.fetch_one(
                "SELECT * FROM document_versions WHERE idempotency_key = ?",
                (idempotency_key,),
            )
            if existing is not None:
                if existing["project_id"] != project_id or existing["doc_type"] != doc_type:
                    raise ValueError("idempotency key is already bound to another request")
                validate_document_sections(existing["content"], PRD_HEADINGS if doc_type == "prd" else TECHDOC_HEADINGS)
                if current_snapshot_id:
                    binding = self.db.fetch_one(
                        "SELECT dependency_id FROM artifact_dependencies WHERE artifact_type='document_version' AND artifact_id=? AND dependency_type='project_snapshot'",
                        (existing["id"],),
                    )
                    if not binding or binding["dependency_id"] != current_snapshot_id:
                        raise GenerationContractError("DOCUMENT_SNAPSHOT_BINDING_FAILED")
                if existing.get("competitor_snapshot_id") != effective_competitor_snapshot_id:
                    raise GenerationContractError("DOCUMENT_SNAPSHOT_BINDING_FAILED")
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
        terminal_state = "needs_human_review"
        final_issues: list[dict[str, Any]] = []
        rounds = 0
        try:
            generated = validate_document_draft(call_generation(lambda: self.generator.generate(
                doc_type, generation_canvas, evidence, project_title=project["title"],
            )))
            content = generated["content"]
            citations = generated["citations"]
            structured_claims = generated["claims"]
            valid_citations = self.retrieval.valid_citations(project_id)

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
                blocking_issues = [issue for issue in issues if issue.get("severity") != "warning"]
                if not blocking_issues:
                    terminal_state = "completed"
                    break
                if round_no < self.max_rounds:
                    content = call_generation(lambda: self.generator.repair(content, issues, evidence))
                    validate_document_draft({"content": content, "citations": citations, "claims": structured_claims})

            validate_document_sections(content, PRD_HEADINGS if doc_type == "prd" else TECHDOC_HEADINGS)
            latest_project = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
            if not latest_project or latest_project.get("current_snapshot_id") != current_snapshot_id:
                raise GenerationContractError("DOCUMENT_SNAPSHOT_BINDING_CHANGED")
            if use_competitor_snapshot and not explicit_competitor_binding and latest_project.get("current_competitor_snapshot_id") != current_competitor_snapshot_id:
                raise GenerationContractError("DOCUMENT_SNAPSHOT_BINDING_CHANGED")
        except GenerationContractError:
            self.db.execute(
                "UPDATE generation_runs SET status='failed', terminal_state='failed', rounds=?, updated_at=? WHERE id=?",
                (rounds, utc_now(), run_id),
            )
            raise

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
                idempotency_key, created_at, approved_at, competitor_snapshot_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                effective_competitor_snapshot_id,
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

    @staticmethod
    def _canvas_with_snapshot_context(
        canvas: dict[str, Any], snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if snapshot is None:
            return canvas
        inherited = dict(canvas)
        context: dict[str, Any] = {}
        for field in (
            "target_user", "problem", "solution", "mvp", "user_flow", "inputs",
            "outputs", "technical_plan", "unknowns", "next_action",
        ):
            raw = snapshot.get(f"{field}_json")
            if raw is not None:
                context[field] = json.loads(raw)
        inherited["selected_solution_context"] = context
        inherited["selected_snapshot_id"] = snapshot.get("id")
        return inherited

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
        citations = json.loads(row["citations_json"])
        reject_raw_generation_values([row["content"], citations, claim_payload["items"]])
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
            "citations": citations,
            "claims": claim_payload["items"],
            "retrieval_run_ids": retrieval_run_ids,
            "rounds": rounds,
            "terminal_state": terminal_state,
            "reused": reused,
            "artifact_health": health,
        }
