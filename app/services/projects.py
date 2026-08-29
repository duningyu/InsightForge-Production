from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import Database, utc_now


class ProjectService:
    """Own project and canvas lifecycle without mixing retrieval or generation."""

    def __init__(self, db: Database):
        self.db = db

    def list_projects(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            """
            SELECT * FROM projects
            WHERE status IN ('active', 'example')
            ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, updated_at DESC, id
            """
        )

    def list_trashed_projects(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM projects WHERE status = 'trashed' ORDER BY updated_at DESC, id"
        )

    def history(
        self,
        *,
        query: str = "",
        status: str = "all",
        sort: str = "updated_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        if status not in {"all", "active", "example", "trashed"}:
            raise ValueError("unsupported history status filter")
        sort_columns = {
            "updated_at": "p.updated_at",
            "created_at": "p.created_at",
            "title": "p.title COLLATE NOCASE",
        }
        if sort not in sort_columns:
            raise ValueError("unsupported history sort")
        if order not in {"asc", "desc"}:
            raise ValueError("unsupported history order")
        if page < 1 or page_size < 1 or page_size > 100:
            raise ValueError("invalid history pagination")

        where: list[str] = []
        params: list[Any] = []
        if status != "all":
            where.append("p.status=?")
            params.append(status)
        clean_query = query.strip()
        if clean_query:
            where.append("(LOWER(p.title) LIKE LOWER(?) OR LOWER(p.summary) LIKE LOWER(?))")
            pattern = f"%{clean_query}%"
            params.extend([pattern, pattern])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""

        total_row = self.db.fetch_one(
            f"SELECT COUNT(*) AS total FROM projects AS p {where_sql}", tuple(params)
        )
        total = int(total_row["total"] if total_row else 0)
        offset = (page - 1) * page_size
        rows = self.db.fetch_all(
            f"""
            SELECT p.*, r.parent_project_id, r.relation_type
            FROM projects AS p
            LEFT JOIN project_relations AS r ON r.child_project_id=p.id
            {where_sql}
            ORDER BY {sort_columns[sort]} {order.upper()}, p.id ASC
            LIMIT ? OFFSET ?
            """,
            (*params, page_size, offset),
        )
        pages = max(1, (total + page_size - 1) // page_size) if total else 1
        return {
            "items": rows,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    def get_project(self, project_id: str) -> dict[str, Any]:
        project = self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        return project

    def get_project_detail(self, project_id: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        project["canvas"] = self.db.get_canvas(project_id)
        project["sources"] = self.db.fetch_all(
            """
            SELECT id, project_id, title, filename, source_type, authority, sha256,
                   source_url, publisher, published_at, captured_at, authority_label,
                   authority_basis, status, metadata_json, created_at
            FROM sources WHERE project_id = ? ORDER BY created_at, id
            """,
            (project_id,),
        )
        for source in project["sources"]:
            source["metadata"] = json.loads(source.pop("metadata_json", "{}") or "{}")
        project["document_versions"] = self.db.fetch_all(
            """
            SELECT id, document_id, project_id, doc_type, version, canvas_version,
                   status, lifecycle_status, validation_status, created_at, approved_at
            FROM document_versions WHERE project_id = ? AND lifecycle_status = 'active'
            ORDER BY doc_type, version DESC
            """,
            (project_id,),
        )
        return project

    def create_project(self, *, title: str, summary: str, actor: str) -> dict[str, Any]:
        project_id = f"project_{uuid.uuid4().hex}"
        now = utc_now()
        self.db.execute(
            "INSERT INTO projects(id, title, summary, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, title.strip(), summary.strip(), "active", now, now),
        )
        self.db.insert_audit(
            actor=actor,
            action="project_created",
            entity_type="project",
            entity_id=project_id,
            payload={"title": title, "summary": summary},
        )
        return self.get_project(project_id)

    def move_to_trash(self, project_id: str, *, actor: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project["status"] == "trashed":
            return project
        now = utc_now()
        self.db.execute(
            "UPDATE projects SET status = 'trashed', updated_at = ? WHERE id = ?",
            (now, project_id),
        )
        self.db.insert_audit(
            actor=actor,
            action="project_moved_to_trash",
            entity_type="project",
            entity_id=project_id,
            payload={"title": project["title"]},
        )
        return self.get_project(project_id)

    def restore_from_trash(self, project_id: str, *, actor: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project["status"] != "trashed":
            raise ValueError("only trashed projects can be restored")
        now = utc_now()
        self.db.execute(
            "UPDATE projects SET status = 'active', updated_at = ? WHERE id = ?",
            (now, project_id),
        )
        self.db.insert_audit(
            actor=actor,
            action="project_restored_from_trash",
            entity_type="project",
            entity_id=project_id,
            payload={"title": project["title"]},
        )
        return self.get_project(project_id)

    def purge_from_trash(self, project_id: str, *, actor: str) -> dict[str, Any]:
        project = self.get_project(project_id)
        if project["status"] != "trashed":
            raise ValueError("project must be in trash before permanent deletion")

        # Delete the complete project graph in dependency order. The schema intentionally
        # uses restrictive foreign keys rather than broad ON DELETE CASCADE, so a purge
        # must be explicit and auditable whenever a new project-scoped table is added.
        with self.db.connect() as connection:
            connection.execute("DELETE FROM document_edit_drafts WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_tour_progress WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_model_profiles WHERE project_id = ?", (project_id,))
            connection.execute(
                "DELETE FROM project_relations WHERE child_project_id = ? OR parent_project_id = ?",
                (project_id, project_id),
            )

            connection.execute("DELETE FROM change_proposals WHERE project_id = ?", (project_id,))
            connection.execute(
                """
                DELETE FROM artifact_health
                WHERE (artifact_type='project_snapshot' AND artifact_id IN (
                           SELECT id FROM project_snapshots WHERE project_id=?
                       ))
                   OR (artifact_type='document_version' AND artifact_id IN (
                           SELECT id FROM document_versions WHERE project_id=?
                       ))
                   OR trigger_source_id IN (SELECT id FROM sources WHERE project_id=?)
                """,
                (project_id, project_id, project_id),
            )
            connection.execute(
                """
                DELETE FROM artifact_dependencies
                WHERE (artifact_type='project_snapshot' AND artifact_id IN (
                           SELECT id FROM project_snapshots WHERE project_id=?
                       ))
                   OR (artifact_type='document_version' AND artifact_id IN (
                           SELECT id FROM document_versions WHERE project_id=?
                       ))
                   OR dependency_id IN (
                       SELECT id FROM project_snapshots WHERE project_id=?
                       UNION SELECT id FROM project_claims WHERE project_id=?
                       UNION SELECT id FROM project_decisions WHERE project_id=?
                       UNION SELECT id FROM sources WHERE project_id=?
                   )
                """,
                (project_id, project_id, project_id, project_id, project_id, project_id),
            )

            connection.execute(
                "DELETE FROM snapshot_claim_links WHERE snapshot_id IN (SELECT id FROM project_snapshots WHERE project_id=?)",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM snapshot_decision_links WHERE snapshot_id IN (SELECT id FROM project_snapshots WHERE project_id=?)",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM decision_claim_links WHERE decision_id IN (SELECT id FROM project_decisions WHERE project_id=?) OR claim_id IN (SELECT id FROM project_claims WHERE project_id=?)",
                (project_id, project_id),
            )
            connection.execute(
                "DELETE FROM project_claim_evidence_links WHERE claim_id IN (SELECT id FROM project_claims WHERE project_id=?)",
                (project_id,),
            )
            connection.execute(
                "DELETE FROM claim_evidence_links WHERE claim_id IN (SELECT id FROM document_claims WHERE project_id = ?)",
                (project_id,),
            )
            connection.execute("DELETE FROM document_claims WHERE project_id = ?", (project_id,))

            connection.execute(
                "DELETE FROM validation_issues WHERE generation_run_id IN (SELECT id FROM generation_runs WHERE project_id = ?)",
                (project_id,),
            )
            connection.execute("DELETE FROM generation_runs WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM retrieval_hits WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM retrieval_runs WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM handoff_runs WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM guided_messages WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM guided_sessions WHERE project_id = ?", (project_id,))

            connection.execute("DELETE FROM solution_candidates WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM solution_runs WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_snapshots WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_decisions WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_claims WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM idea_briefs WHERE project_id = ?", (project_id,))

            connection.execute("DELETE FROM document_versions WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM documents WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM source_chunks WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM sources WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_canvas_versions WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM project_canvas WHERE project_id = ?", (project_id,))
            connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))

        self.db.insert_audit(
            actor=actor,
            action="project_permanently_deleted",
            entity_type="project",
            entity_id=project_id,
            payload={"title": project["title"]},
        )
        return {"id": project_id, "status": "permanently_deleted"}

    def get_canvas(self, project_id: str) -> dict[str, Any]:
        self.get_project(project_id)
        canvas = self.db.get_canvas(project_id)
        if canvas is None:
            raise KeyError("project canvas not found")
        return canvas

    def write_canvas_tx(
        self,
        connection: sqlite3.Connection,
        project_id: str,
        *,
        problem: str,
        target_users: str,
        goals: list[str],
        non_goals: list[str],
        success_metrics: list[str],
        constraints: list[str],
        now: str,
    ) -> dict[str, Any]:
        existing = connection.execute(
            "SELECT version, created_at FROM project_canvas WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        version = int(existing["version"]) + 1 if existing else 1
        created_at = existing["created_at"] if existing else now
        payload = (
            project_id,
            version,
            problem.strip(),
            target_users.strip(),
            json.dumps(goals, ensure_ascii=False),
            json.dumps(non_goals, ensure_ascii=False),
            json.dumps(success_metrics, ensure_ascii=False),
            json.dumps(constraints, ensure_ascii=False),
            created_at,
            now,
        )
        connection.execute(
            """
            INSERT INTO project_canvas(
                project_id, version, problem, target_users, goals_json,
                non_goals_json, success_metrics_json, constraints_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                version = excluded.version,
                problem = excluded.problem,
                target_users = excluded.target_users,
                goals_json = excluded.goals_json,
                non_goals_json = excluded.non_goals_json,
                success_metrics_json = excluded.success_metrics_json,
                constraints_json = excluded.constraints_json,
                updated_at = excluded.updated_at
            """,
            payload,
        )
        connection.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (now, project_id),
        )
        connection.execute(
            """
            INSERT INTO project_canvas_versions(
                project_id, version, problem, target_users, goals_json,
                non_goals_json, success_metrics_json, constraints_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                version,
                problem.strip(),
                target_users.strip(),
                json.dumps(goals, ensure_ascii=False),
                json.dumps(non_goals, ensure_ascii=False),
                json.dumps(success_metrics, ensure_ascii=False),
                json.dumps(constraints, ensure_ascii=False),
                now,
            ),
        )
        return {
            "project_id": project_id,
            "version": version,
            "problem": problem.strip(),
            "target_users": target_users.strip(),
            "goals": list(goals),
            "non_goals": list(non_goals),
            "success_metrics": list(success_metrics),
            "constraints": list(constraints),
            "created_at": created_at,
            "updated_at": now,
        }

    def update_canvas(
        self,
        project_id: str,
        *,
        problem: str,
        target_users: str,
        goals: list[str],
        non_goals: list[str],
        success_metrics: list[str],
        constraints: list[str],
        actor: str,
    ) -> dict[str, Any]:
        project = self.get_project(project_id)
        now = utc_now()
        with self.db.connect() as connection:
            canvas = self.write_canvas_tx(
                connection,
                project_id,
                problem=problem,
                target_users=target_users,
                goals=goals,
                non_goals=non_goals,
                success_metrics=success_metrics,
                constraints=constraints,
                now=now,
            )
            current_project = connection.execute(
                "SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            current_snapshot_id = current_project["current_snapshot_id"] if current_project else None
            if current_snapshot_id:
                connection.execute(
                    """
                    INSERT INTO artifact_health(
                        artifact_type,artifact_id,health_status,reason,trigger_source_id,updated_at
                    ) VALUES ('project_snapshot',?,'needs_review',?,NULL,?)
                    ON CONFLICT(artifact_type,artifact_id) DO UPDATE SET
                        health_status='needs_review',reason=excluded.reason,
                        trigger_source_id=NULL,updated_at=excluded.updated_at
                    """,
                    (current_snapshot_id, f"direct Canvas edit v{canvas['version']} requires Snapshot reconciliation", now),
                )
                reason = f"canvas_version:{canvas['version']}"
                existing = connection.execute(
                    """
                    SELECT id FROM change_proposals
                    WHERE project_id=? AND from_snapshot_id=?
                      AND proposal_type='snapshot_canvas_reconciliation'
                      AND reason=? AND status='open'
                    LIMIT 1
                    """,
                    (project_id, current_snapshot_id, reason),
                ).fetchone()
                if existing is None:
                    proposal_id = f"proposal_{uuid.uuid4().hex}"
                    current_claims = connection.execute(
                        """
                        SELECT * FROM project_claims
                        WHERE project_id=? AND status='active' AND claim_type IN ('target_user','user_problem')
                        ORDER BY created_at,id
                        """,
                        (project_id,),
                    ).fetchall()
                    by_type = {row["claim_type"]: row for row in current_claims}
                    claim_replacements = []
                    target_claim = by_type.get("target_user")
                    if target_claim is not None and target_claim["statement"] != target_users.strip():
                        claim_replacements.append({
                            "old_claim_id": target_claim["id"],
                            "claim_type": "target_user",
                            "statement": target_users.strip(),
                            "provenance": "user_input",
                        })
                    problem_claim = by_type.get("user_problem")
                    if problem_claim is not None and problem_claim["statement"] != problem.strip():
                        claim_replacements.append({
                            "old_claim_id": problem_claim["id"],
                            "claim_type": "user_problem",
                            "statement": problem.strip(),
                            "provenance": "user_input",
                        })
                    suggested_changes = {
                        "canvas_version": canvas["version"],
                        "claim_replacements": claim_replacements,
                        "snapshot_patch": {
                            "problem": {
                                "statement": problem.strip(),
                                "provenance": "user_input",
                                "verification_status": "unverified",
                            },
                            "target_user": {
                                "primary": target_users.strip(),
                                "provenance": "user_input",
                                "verification_status": "unverified",
                            },
                            "mvp": {
                                "outcomes": list(goals),
                                "acceptance_criteria": list(success_metrics),
                            },
                            "solution": {"explicit_non_goals": list(non_goals)},
                            "unknowns": list(constraints),
                            "technical_plan": {"constraints": list(constraints)},
                        },
                    }
                    connection.execute(
                        """
                        INSERT INTO change_proposals(
                            id,project_id,trigger_source_id,from_snapshot_id,proposal_type,
                            summary,reason,affected_claims_json,affected_decisions_json,
                            suggested_changes_json,status,created_at,decided_at,decided_by
                        ) VALUES (?,?,NULL,?,'snapshot_canvas_reconciliation',?,?,?,?,?,'open',?,NULL,NULL)
                        """,
                        (
                            proposal_id, project_id, current_snapshot_id,
                            "Canvas 与当前 Project Snapshot 存在待确认差异", reason,
                            json.dumps([item["old_claim_id"] for item in claim_replacements], ensure_ascii=False),
                            '[]',
                            json.dumps(suggested_changes, ensure_ascii=False, sort_keys=True), now,
                        ),
                    )
                    self.db.insert_audit_tx(
                        connection, actor=actor, action="snapshot_canvas_reconciliation_proposed",
                        entity_type="change_proposal", entity_id=proposal_id,
                        payload={
                            "project_id": project_id,
                            "snapshot_id": current_snapshot_id,
                            "canvas_version": canvas["version"],
                        },
                    )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action="canvas_updated",
                entity_type="project_canvas",
                entity_id=project_id,
                payload={"version": canvas["version"], "snapshot_managed": bool(current_snapshot_id)},
            )
        return self.get_canvas(project_id)

