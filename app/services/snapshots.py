from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import Database, utc_now
from app.errors import ConflictError
from app.services.ai_runtime import sha256_payload
from app.services.artifact_health import ArtifactHealthService
from app.services.canvas_projection import CanvasProjectionService
from app.services.decisions import DecisionService
from app.services.project_claims import ProjectClaimService
from app.services.projects import ProjectService


class SnapshotService:
    JSON_FIELDS = (
        "target_user",
        "problem",
        "solution",
        "mvp",
        "user_flow",
        "inputs",
        "outputs",
        "technical_plan",
        "unknowns",
        "next_action",
    )

    def __init__(
        self,
        db: Database,
        projects: ProjectService,
        decisions: DecisionService,
        claims: ProjectClaimService,
        projection: CanvasProjectionService,
        health: ArtifactHealthService | None = None,
    ):
        self.db = db
        self.projects = projects
        self.decisions = decisions
        self.claims = claims
        self.projection = projection
        self.health = health or ArtifactHealthService(db)

    @staticmethod
    def _deserialize_brief(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for field in ("known_resources", "constraints", "unknowns", "provenance"):
            data[field] = json.loads(data.pop(f"{field}_json"))
        data["clarification_required"] = bool(data.get("clarification_required", 0))
        return data

    @staticmethod
    def _deserialize_candidate(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        data = dict(row)
        for field in (
            "user_flow", "mvp_pages", "features", "inputs", "outputs", "decision_logic",
            "data_requirements", "technical_components", "implementation_plan",
            "acceptance_cases", "risks", "unknowns",
        ):
            data[field] = json.loads(data.pop(f"{field}_json"))
        for field in ("requires_llm_runtime", "requires_rag_runtime", "requires_agent_runtime"):
            data[field] = bool(data[field])
        return data

    def _latest_solution_candidates_tx(
        self, connection: sqlite3.Connection, project_id: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        run = connection.execute(
            """
            SELECT * FROM solution_runs
            WHERE project_id = ? AND status IN ('completed','completed_two_candidates')
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if run is None:
            raise ConflictError("VALID_SOLUTION_RUN_REQUIRED")
        rows = connection.execute(
            "SELECT * FROM solution_candidates WHERE run_id = ? ORDER BY created_at, id",
            (run["id"],),
        ).fetchall()
        return dict(run), [self._deserialize_candidate(row) for row in rows]

    @staticmethod
    def _unique(items: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            clean = str(item).strip()
            if clean and clean not in seen:
                seen.add(clean)
                result.append(clean)
        return result

    @staticmethod
    def _candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate_id": candidate["id"],
            "title": candidate["title"],
            "mechanism": candidate["mechanism"],
            "why_fit": candidate["why_fit"],
        }

    def _build_snapshot_payload(
        self,
        *,
        project: dict[str, Any],
        brief: dict[str, Any],
        selected: dict[str, Any],
        evolution: list[dict[str, Any]],
        rationale: str,
        next_action: dict[str, Any],
    ) -> dict[str, Any]:
        unknowns = self._unique([*brief["unknowns"], *selected["unknowns"]])
        target_user = {
            "primary": brief["target_user"],
            "provenance": brief["provenance"].get("target_user", "model_hypothesis"),
            "verification_status": "unverified",
        }
        problem = {
            "statement": brief["problem"],
            "provenance": brief["provenance"].get("problem", "model_hypothesis"),
            "verification_status": "unverified",
        }
        solution = {
            "candidate_id": selected["id"],
            "title": selected["title"],
            "mechanism": selected["mechanism"],
            "why_fit": selected["why_fit"],
            "rationale": rationale,
            "core_decision_logic": selected["core_decision_logic"],
            "decision_logic": selected["decision_logic"],
            "explicit_non_goals": [],
            "evolution_path": [self._candidate_summary(item) for item in evolution],
        }
        mvp = {
            "pages": selected["mvp_pages"],
            "features": selected["features"],
            "outcomes": self._unique([brief["desired_outcome"]]),
            "implementation_plan": selected["implementation_plan"],
            "acceptance_criteria": selected["acceptance_cases"],
            "risks": selected["risks"],
        }
        technical = {
            "components": selected["technical_components"],
            "data_requirements": selected["data_requirements"],
            "constraints": list(brief["constraints"]),
            "complexity": selected["complexity"],
            "major_dependency": selected["major_dependency"],
        }
        return {
            "title": selected["title"],
            "one_liner": f"为{brief['target_user']}解决“{brief['problem']}”，首个 MVP 采用“{selected['title']}”。",
            "target_user": target_user,
            "problem": problem,
            "solution": solution,
            "mvp": mvp,
            "user_flow": selected["user_flow"],
            "inputs": selected["inputs"],
            "outputs": selected["outputs"],
            "technical_plan": technical,
            "unknowns": unknowns,
            "next_action": next_action,
        }

    def confirm_initial_solution(
        self,
        project_id: str,
        *,
        strategy: str,
        candidate_ids: list[str],
        rationale: str,
        human_confirmed: bool,
        actor: str,
    ) -> dict[str, Any]:
        if not human_confirmed:
            raise PermissionError("explicit human confirmation is required")
        if strategy == "single" and len(candidate_ids) != 1:
            raise ValueError("single strategy requires exactly one candidate")
        if strategy == "staged" and len(candidate_ids) < 2:
            raise ValueError("staged strategy requires at least two ordered candidates")
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError("candidate_ids must be unique")

        now = utc_now()
        with self.db.connect() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if project_row is None:
                raise KeyError("project not found")
            project = dict(project_row)
            if project.get("current_snapshot_id"):
                raise ConflictError("INITIAL_SNAPSHOT_ALREADY_CONFIRMED")

            brief_row = connection.execute(
                "SELECT * FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1",
                (project_id,),
            ).fetchone()
            if brief_row is None or brief_row["confirmation_status"] != "confirmed":
                raise ConflictError("CONFIRMED_IDEA_BRIEF_REQUIRED")
            brief = self._deserialize_brief(brief_row)
            if brief["clarification_required"]:
                raise ConflictError("IDEA_BRIEF_CLARIFICATION_REQUIRED")

            _run, candidates = self._latest_solution_candidates_tx(connection, project_id)
            by_id = {item["id"]: item for item in candidates}
            if any(candidate_id not in by_id for candidate_id in candidate_ids):
                raise ConflictError("SOLUTION_CANDIDATE_SCOPE_MISMATCH")
            selected = by_id[candidate_ids[0]]
            evolution = [by_id[item] for item in candidate_ids[1:]]
            option_ids = [item["id"] for item in candidates]

            decision = self.decisions.propose_solution_selection(
                connection=connection,
                project_id=project_id,
                option_ids=option_ids,
                selected_option_id=selected["id"],
                rationale=rationale,
                decision_payload={"strategy": strategy, "candidate_ids": candidate_ids},
                actor=actor,
            )
            connection.execute(
                """
                UPDATE project_decisions
                SET status='confirmed', decision_version=1, confirmed_by=?, confirmed_at=?
                WHERE id=?
                """,
                (actor, now, decision["id"]),
            )
            decision["status"] = "confirmed"
            decision["decision_version"] = 1
            decision["confirmed_by"] = actor
            decision["confirmed_at"] = now

            claims = self.claims.create_initial_claims_tx(
                connection,
                project_id=project_id,
                decision_id=decision["id"],
                brief=brief,
                selected_candidate=selected,
            )
            next_action = self.claims.next_best_action_tx(connection, claims)
            payload = self._build_snapshot_payload(
                project=project,
                brief=brief,
                selected=selected,
                evolution=evolution,
                rationale=rationale,
                next_action=next_action,
            )
            snapshot_id = f"snapshot_{uuid.uuid4().hex}"
            content_sha = sha256_payload(payload)
            connection.execute(
                """
                INSERT INTO project_snapshots(
                    id, project_id, version, idea_brief_id, decision_id, title, one_liner,
                    target_user_json, problem_json, solution_json, mvp_json, user_flow_json,
                    inputs_json, outputs_json, technical_plan_json, unknowns_json,
                    next_action_json, snapshot_origin, created_at, confirmed_at, created_by,
                    supersedes_snapshot_id, content_sha256
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          'quick_value_flow', ?, ?, ?, NULL, ?)
                """,
                (
                    snapshot_id,
                    project_id,
                    brief["id"],
                    decision["id"],
                    payload["title"],
                    payload["one_liner"],
                    json.dumps(payload["target_user"], ensure_ascii=False),
                    json.dumps(payload["problem"], ensure_ascii=False),
                    json.dumps(payload["solution"], ensure_ascii=False),
                    json.dumps(payload["mvp"], ensure_ascii=False),
                    json.dumps(payload["user_flow"], ensure_ascii=False),
                    json.dumps(payload["inputs"], ensure_ascii=False),
                    json.dumps(payload["outputs"], ensure_ascii=False),
                    json.dumps(payload["technical_plan"], ensure_ascii=False),
                    json.dumps(payload["unknowns"], ensure_ascii=False),
                    json.dumps(payload["next_action"], ensure_ascii=False),
                    now,
                    now,
                    actor,
                    content_sha,
                ),
            )
            for claim in claims:
                connection.execute(
                    "INSERT INTO snapshot_claim_links(snapshot_id, claim_id, role) VALUES (?, ?, 'basis')",
                    (snapshot_id, claim["id"]),
                )
            connection.execute(
                "INSERT INTO snapshot_decision_links(snapshot_id, decision_id, role) VALUES (?, ?, 'current_solution')",
                (snapshot_id, decision["id"]),
            )
            for claim in claims:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO artifact_dependencies(
                        artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at
                    ) VALUES ('project_snapshot',?,'project_claim',?,NULL,?)
                    """,
                    (snapshot_id, claim["id"], now),
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO artifact_dependencies(
                    artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at
                ) VALUES ('project_snapshot',?,'project_decision',?,NULL,?)
                """,
                (snapshot_id, decision["id"], now),
            )
            self.health.set_tx(
                connection,
                artifact_type="project_snapshot",
                artifact_id=snapshot_id,
                health_status="current",
                reason="initial confirmed project snapshot",
            )
            connection.execute(
                "UPDATE projects SET current_snapshot_id=?, updated_at=? WHERE id=?",
                (snapshot_id, now, project_id),
            )
            projection = self.projection.project(payload)
            canvas = self.projects.write_canvas_tx(
                connection,
                project_id,
                problem=projection.problem,
                target_users=projection.target_users,
                goals=projection.goals,
                non_goals=projection.non_goals,
                success_metrics=projection.success_metrics,
                constraints=projection.constraints,
                now=now,
            )
            self.db.insert_audit_tx(
                connection,
                actor=actor,
                action="project_snapshot_confirmed",
                entity_type="project_snapshot",
                entity_id=snapshot_id,
                payload={
                    "project_id": project_id,
                    "version": 1,
                    "decision_id": decision["id"],
                    "canvas_version": canvas["version"],
                    "strategy": strategy,
                    "candidate_ids": candidate_ids,
                    "human_confirmed": True,
                    "market_validation": False,
                },
            )
        return self.get(snapshot_id)

    @classmethod
    def _serialize_snapshot_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        for field in cls.JSON_FIELDS:
            payload[field] = json.loads(payload.pop(f"{field}_json"))
        return payload

    @staticmethod
    def _deep_merge(base: Any, patch: Any) -> Any:
        if isinstance(base, dict) and isinstance(patch, dict):
            merged = dict(base)
            for key, value in patch.items():
                merged[key] = SnapshotService._deep_merge(merged.get(key), value)
            return merged
        return patch

    @classmethod
    def _snapshot_content_payload(cls, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": snapshot["title"],
            "one_liner": snapshot["one_liner"],
            **{field: snapshot[field] for field in cls.JSON_FIELDS},
        }

    def derive_project_state(self, project_id: str) -> str:
        project = self.projects.get_project(project_id)
        current_snapshot_id = project.get("current_snapshot_id")
        if not current_snapshot_id:
            return "exploring"
        health = self.db.fetch_one(
            "SELECT health_status FROM artifact_health WHERE artifact_type='project_snapshot' AND artifact_id=?",
            (current_snapshot_id,),
        )
        if health is None or health["health_status"] != "current":
            return "reconfirm_required"
        open_proposal = self.db.fetch_one(
            """
            SELECT id FROM change_proposals
            WHERE project_id=? AND from_snapshot_id=? AND status='open'
            LIMIT 1
            """,
            (project_id, current_snapshot_id),
        )
        if open_proposal is not None:
            return "reconfirm_required"
        return "executable"

    def reconfirm_current_health(
        self,
        project_id: str,
        *,
        human_confirmed: bool,
        note: str,
        actor: str,
    ) -> dict[str, Any]:
        """Restore health for an unchanged current Snapshot after an explicit human review."""
        if not human_confirmed:
            raise PermissionError("explicit human confirmation is required")
        with self.db.connect() as connection:
            project = connection.execute(
                "SELECT current_snapshot_id FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if project is None:
                raise KeyError("project not found")
            snapshot_id = project["current_snapshot_id"]
            if not snapshot_id:
                raise ConflictError("CURRENT_SNAPSHOT_REQUIRED")
            snapshot = connection.execute(
                "SELECT id FROM project_snapshots WHERE id=? AND project_id=?",
                (snapshot_id, project_id),
            ).fetchone()
            if snapshot is None:
                raise ConflictError("CURRENT_SNAPSHOT_REQUIRED")
            proposal = connection.execute(
                """
                SELECT id FROM change_proposals
                WHERE project_id=? AND from_snapshot_id=? AND status='open'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (project_id, snapshot_id),
            ).fetchone()
            if proposal is not None:
                raise ConflictError("OPEN_CHANGE_PROPOSAL_REQUIRES_DECISION")
            health = connection.execute(
                """
                SELECT health_status FROM artifact_health
                WHERE artifact_type='project_snapshot' AND artifact_id=?
                """,
                (snapshot_id,),
            ).fetchone()
            if health is None or health["health_status"] != "current":
                self.health.set_tx(
                    connection,
                    artifact_type="project_snapshot",
                    artifact_id=snapshot_id,
                    health_status="current",
                    reason="human reconfirmed unchanged current Snapshot",
                )
                self.db.insert_audit_tx(
                    connection,
                    actor=actor,
                    action="project_snapshot_health_reconfirmed",
                    entity_type="project_snapshot",
                    entity_id=snapshot_id,
                    payload={"project_id": project_id, "human_confirmed": True, "note": note},
                )
        return self.get(snapshot_id)

    def create_from_change_proposal_tx(
        self,
        connection: sqlite3.Connection,
        *,
        proposal: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        old_row = connection.execute(
            "SELECT * FROM project_snapshots WHERE id=? AND project_id=?",
            (proposal["from_snapshot_id"], proposal["project_id"]),
        ).fetchone()
        if old_row is None:
            raise ConflictError("CHANGE_PROPOSAL_SNAPSHOT_SCOPE_MISMATCH")
        old_snapshot = self._serialize_snapshot_row(dict(old_row))
        project = connection.execute(
            "SELECT current_snapshot_id FROM projects WHERE id=?",
            (proposal["project_id"],),
        ).fetchone()
        if project is None:
            raise KeyError("project not found")
        if project["current_snapshot_id"] != old_snapshot["id"]:
            raise ConflictError("STALE_CHANGE_PROPOSAL: from_snapshot is no longer current")

        suggested_changes = proposal.get("suggested_changes") or {}
        snapshot_patch = dict(suggested_changes.get("snapshot_patch") or {})
        content = self._snapshot_content_payload(old_snapshot)
        content = self._deep_merge(content, snapshot_patch)

        replacement_claims: list[dict[str, Any]] = []
        for replacement in list(suggested_changes.get("claim_replacements") or []):
            old_claim = connection.execute(
                "SELECT * FROM project_claims WHERE id=? AND project_id=? AND status='active'",
                (replacement["old_claim_id"], old_snapshot["project_id"]),
            ).fetchone()
            if old_claim is None:
                raise ConflictError("CHANGE_PROPOSAL_CLAIM_SCOPE_MISMATCH")
            if old_claim["claim_type"] != replacement["claim_type"]:
                raise ConflictError("CHANGE_PROPOSAL_CLAIM_TYPE_MISMATCH")
            new_claim_id = f"claim_{uuid.uuid4().hex}"
            now_claim = utc_now()
            connection.execute(
                "UPDATE project_claims SET status='superseded',updated_at=? WHERE id=?",
                (now_claim, old_claim["id"]),
            )
            connection.execute(
                """
                INSERT INTO project_claims(
                    id,project_id,claim_type,statement,provenance,verification_status,
                    criticality,scope_note,status,created_at,updated_at,supersedes_claim_id
                ) VALUES (?,?,?,?,?,'unverified',?,?,'active',?,?,?)
                """,
                (
                    new_claim_id, old_snapshot["project_id"], old_claim["claim_type"],
                    str(replacement["statement"]).strip(), replacement.get("provenance", "user_input"),
                    old_claim["criticality"],
                    "用户确认的 Canvas 兼容编辑；该确认只表示项目意图变化，不构成市场验证。",
                    now_claim, now_claim, old_claim["id"],
                ),
            )
            decision_links = connection.execute(
                "SELECT decision_id,role FROM decision_claim_links WHERE claim_id=?",
                (old_claim["id"],),
            ).fetchall()
            for link in decision_links:
                connection.execute(
                    "INSERT INTO decision_claim_links(decision_id,claim_id,role,created_at) VALUES (?,?,?,?)",
                    (link["decision_id"], new_claim_id, link["role"], now_claim),
                )
            replacement_claim = connection.execute(
                "SELECT * FROM project_claims WHERE id=?", (new_claim_id,)
            ).fetchone()
            replacement_claims.append(dict(replacement_claim))

        claim_rows = connection.execute(
            """
            SELECT pc.* FROM project_claims pc
            JOIN snapshot_claim_links scl ON scl.claim_id=pc.id
            WHERE scl.snapshot_id=? AND pc.status='active'
            ORDER BY pc.created_at,pc.id
            """,
            (old_snapshot["id"],),
        ).fetchall()
        claims = [dict(row) for row in claim_rows]
        existing_claim_ids = {claim["id"] for claim in claims}
        claims.extend(claim for claim in replacement_claims if claim["id"] not in existing_claim_ids)
        for claim in claims:
            if claim["claim_type"] == "target_user":
                content["target_user"] = self._deep_merge(
                    content.get("target_user", {}),
                    {"verification_status": claim["verification_status"]},
                )
            elif claim["claim_type"] == "user_problem":
                content["problem"] = self._deep_merge(
                    content.get("problem", {}),
                    {"verification_status": claim["verification_status"]},
                )
        content["next_action"] = self.claims.next_best_action_tx(connection, claims)

        now = utc_now()
        snapshot_id = f"snapshot_{uuid.uuid4().hex}"
        version = int(old_snapshot["version"]) + 1
        content_sha = sha256_payload(content)
        connection.execute(
            """
            INSERT INTO project_snapshots(
                id,project_id,version,idea_brief_id,decision_id,title,one_liner,
                target_user_json,problem_json,solution_json,mvp_json,user_flow_json,
                inputs_json,outputs_json,technical_plan_json,unknowns_json,next_action_json,
                snapshot_origin,created_at,confirmed_at,created_by,supersedes_snapshot_id,content_sha256
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'change_proposal',?,?,?,?,?)
            """,
            (
                snapshot_id, old_snapshot["project_id"], version, old_snapshot["idea_brief_id"],
                old_snapshot["decision_id"], content["title"], content["one_liner"],
                json.dumps(content["target_user"], ensure_ascii=False),
                json.dumps(content["problem"], ensure_ascii=False),
                json.dumps(content["solution"], ensure_ascii=False),
                json.dumps(content["mvp"], ensure_ascii=False),
                json.dumps(content["user_flow"], ensure_ascii=False),
                json.dumps(content["inputs"], ensure_ascii=False),
                json.dumps(content["outputs"], ensure_ascii=False),
                json.dumps(content["technical_plan"], ensure_ascii=False),
                json.dumps(content["unknowns"], ensure_ascii=False),
                json.dumps(content["next_action"], ensure_ascii=False),
                now, now, actor, old_snapshot["id"], content_sha,
            ),
        )
        for claim in claims:
            connection.execute(
                "INSERT INTO snapshot_claim_links(snapshot_id,claim_id,role) VALUES (?,?,'basis')",
                (snapshot_id, claim["id"]),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO artifact_dependencies(
                    artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at
                ) VALUES ('project_snapshot',?,'project_claim',?,NULL,?)
                """,
                (snapshot_id, claim["id"], now),
            )
        decision_rows = connection.execute(
            "SELECT decision_id,role FROM snapshot_decision_links WHERE snapshot_id=?",
            (old_snapshot["id"],),
        ).fetchall()
        for row in decision_rows:
            connection.execute(
                "INSERT INTO snapshot_decision_links(snapshot_id,decision_id,role) VALUES (?,?,?)",
                (snapshot_id, row["decision_id"], row["role"]),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO artifact_dependencies(
                    artifact_type,artifact_id,dependency_type,dependency_id,dependency_version,created_at
                ) VALUES ('project_snapshot',?,'project_decision',?,NULL,?)
                """,
                (snapshot_id, row["decision_id"], now),
            )
        connection.execute(
            "UPDATE projects SET current_snapshot_id=?,updated_at=? WHERE id=?",
            (snapshot_id, now, old_snapshot["project_id"]),
        )
        self.health.set_tx(
            connection, artifact_type="project_snapshot", artifact_id=old_snapshot["id"],
            health_status="superseded", reason=f"superseded by {snapshot_id}"
        )
        self.health.set_tx(
            connection, artifact_type="project_snapshot", artifact_id=snapshot_id,
            health_status="current", reason=f"accepted change proposal {proposal['id']}"
        )
        projection = self.projection.project(content)
        canvas = self.projects.write_canvas_tx(
            connection, old_snapshot["project_id"],
            problem=projection.problem, target_users=projection.target_users, goals=projection.goals,
            non_goals=projection.non_goals, success_metrics=projection.success_metrics,
            constraints=projection.constraints, now=now,
        )
        self.db.insert_audit_tx(
            connection, actor=actor, action="project_snapshot_superseded",
            entity_type="project_snapshot", entity_id=snapshot_id,
            payload={
                "project_id": old_snapshot["project_id"],
                "version": version,
                "supersedes_snapshot_id": old_snapshot["id"],
                "proposal_id": proposal["id"],
                "canvas_version": canvas["version"],
                "human_confirmed": True,
            },
        )
        row = connection.execute("SELECT * FROM project_snapshots WHERE id=?", (snapshot_id,)).fetchone()
        return self._serialize_snapshot_row(dict(row))

    def get(self, snapshot_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM project_snapshots WHERE id=?", (snapshot_id,))
        if row is None:
            raise KeyError("project snapshot not found")
        payload = self._serialize_snapshot_row(row)
        health = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='project_snapshot' AND artifact_id=?",
            (snapshot_id,),
        )
        payload["health"] = health or {
            "artifact_type": "project_snapshot",
            "artifact_id": snapshot_id,
            "health_status": "current",
            "reason": "legacy snapshot health not materialized",
            "trigger_source_id": None,
            "updated_at": payload["created_at"],
        }
        project = self.projects.get_project(payload["project_id"])
        payload["has_open_proposal"] = bool(
            project.get("current_snapshot_id") == snapshot_id
            and self.db.fetch_one(
                """
                SELECT id FROM change_proposals
                WHERE project_id=? AND from_snapshot_id=? AND status='open'
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (payload["project_id"], snapshot_id),
            )
        )
        payload["ux_state"] = (
            self.derive_project_state(payload["project_id"])
            if project.get("current_snapshot_id") == snapshot_id
            else "historical"
        )
        return payload

    def get_current(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)
        snapshot_id = project.get("current_snapshot_id")
        if not snapshot_id:
            raise KeyError("current project snapshot not found")
        return self.get(snapshot_id)

    def list_versions(self, project_id: str) -> list[dict[str, Any]]:
        self.projects.get_project(project_id)
        rows = self.db.fetch_all(
            "SELECT * FROM project_snapshots WHERE project_id=? ORDER BY version DESC",
            (project_id,),
        )
        return [self._serialize_snapshot_row(row) for row in rows]
