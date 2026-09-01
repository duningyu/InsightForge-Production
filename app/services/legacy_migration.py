from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from app.db import Database, utc_now
from app.services.ai_runtime import sha256_payload
from app.services.artifact_health import ArtifactHealthService


class LegacyMigrationService:
    """Add a 3.0 Snapshot projection over traceable 2.x project state.

    Migration is deliberately conservative: Canvas fields can become unverified
    project Claims because they are traceable project-owner inputs, while old
    generated document prose and old citations never become project evidence.
    """

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

    @staticmethod
    def _has_migratable_canvas(canvas: dict[str, Any]) -> bool:
        return bool(
            str(canvas.get("problem") or "").strip()
            and str(canvas.get("target_users") or "").strip()
            and any(str(goal).strip() for goal in (canvas.get("goals") or []))
        )

    def __init__(self, db: Database):
        self.db = db
        self.health = ArtifactHealthService(db)

    @classmethod
    def _serialize_snapshot(cls, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        for field in cls.JSON_FIELDS:
            payload[field] = json.loads(payload.pop(f"{field}_json"))
        return payload

    @staticmethod
    def _selected_option(decision: dict[str, Any] | None) -> dict[str, Any] | None:
        if not decision or not decision.get("selected_option_id"):
            return None
        try:
            options = json.loads(decision.get("options_json") or "[]")
        except json.JSONDecodeError:
            return None
        for option in options if isinstance(options, list) else []:
            if isinstance(option, dict) and option.get("id") == decision["selected_option_id"]:
                return option
        return None

    def _existing_snapshot_tx(
        self, connection: sqlite3.Connection, project_id: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT * FROM project_snapshots
            WHERE project_id=? AND snapshot_origin='legacy_migration'
            ORDER BY version DESC,id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        return self._serialize_snapshot(row) if row else None

    def _ensure_idea_brief_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project: dict[str, Any],
        canvas: dict[str, Any],
        now: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1",
            (project["id"],),
        ).fetchone()
        if row is not None:
            return dict(row)
        brief_id = f"brief_legacy_{uuid.uuid4().hex}"
        desired = (canvas.get("goals") or [project["summary"]])[0]
        provenance = {
            "target_user": "user_input",
            "problem": "user_input",
            "desired_outcome": "user_input",
            "known_resources": "model_hypothesis",
            "constraints": "user_input",
            "unknowns": "model_hypothesis",
        }
        unknowns = ["历史项目没有 3.0 项目级证据状态；迁移后的关键判断需要重新验证。"]
        connection.execute(
            """
            INSERT INTO idea_briefs(
                id,project_id,version,original_idea,target_user,problem,desired_outcome,
                known_resources_json,constraints_json,unknowns_json,provenance_json,
                clarification_required,clarification_question,confirmation_status,
                created_at,confirmed_at,supersedes_id
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,0,NULL,'inferred',?,NULL,NULL)
            """,
            (
                brief_id,
                project["id"],
                1,
                project["summary"],
                canvas["target_users"],
                canvas["problem"],
                desired,
                "[]",
                json.dumps(canvas.get("constraints") or [], ensure_ascii=False),
                json.dumps(unknowns, ensure_ascii=False),
                json.dumps(provenance, ensure_ascii=False, sort_keys=True),
                now,
            ),
        )
        return dict(connection.execute("SELECT * FROM idea_briefs WHERE id=?", (brief_id,)).fetchone())

    def _ensure_decision_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        now: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT * FROM project_decisions
            WHERE project_id=? AND status='confirmed'
            ORDER BY confirmed_at DESC,created_at DESC,id DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
        if row is not None:
            decision = dict(row)
            if not decision.get("decision_key"):
                connection.execute(
                    """
                    UPDATE project_decisions
                    SET decision_key='legacy_solution',decision_version=COALESCE(decision_version,1),
                        decision_payload_json=CASE WHEN decision_payload_json='{}' THEN ? ELSE decision_payload_json END,
                        confirmed_by=COALESCE(confirmed_by,'legacy_user')
                    WHERE id=?
                    """,
                    (json.dumps({"origin": "legacy_migration"}, ensure_ascii=False), decision["id"]),
                )
                decision = dict(connection.execute("SELECT * FROM project_decisions WHERE id=?", (decision["id"],)).fetchone())
            return decision

        decision_id = f"decision_legacy_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO project_decisions(
                id,project_id,decision_type,options_json,selected_option_id,rationale,status,
                decision_key,decision_version,decision_payload_json,supersedes_decision_id,
                confirmed_by,created_at,confirmed_at
            ) VALUES (?,?, 'legacy_canvas_migration','[]',NULL,?,'confirmed',
                      'legacy_canvas_contract',1,?,NULL,'legacy_user',?,?)
            """,
            (
                decision_id,
                project_id,
                "迁移记录：仅保留旧版 Canvas 已确认的项目合同，不推断新的方案选择。",
                json.dumps({"origin": "legacy_canvas", "market_validation": False}, ensure_ascii=False),
                now,
                now,
            ),
        )
        return dict(connection.execute("SELECT * FROM project_decisions WHERE id=?", (decision_id,)).fetchone())

    def _create_claim_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        claim_type: str,
        statement: str,
        criticality: str,
        scope_note: str,
        now: str,
    ) -> dict[str, Any]:
        claim_id = f"claim_legacy_{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO project_claims(
                id,project_id,claim_type,statement,provenance,verification_status,
                criticality,scope_note,status,created_at,updated_at,supersedes_claim_id
            ) VALUES (?,?,?,?, 'user_input','unverified',?,?, 'active',?,?,NULL)
            """,
            (claim_id, project_id, claim_type, statement, criticality, scope_note, now, now),
        )
        return dict(connection.execute("SELECT * FROM project_claims WHERE id=?", (claim_id,)).fetchone())

    def _ensure_claims_tx(
        self,
        connection: sqlite3.Connection,
        *,
        project_id: str,
        decision_id: str,
        canvas: dict[str, Any],
        now: str,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT * FROM project_claims WHERE project_id=? AND status='active' ORDER BY created_at,id",
            (project_id,),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
        scope = "来自旧版 Canvas 的项目所有者输入；迁移不代表真实市场验证。"
        claims = [
            self._create_claim_tx(
                connection,
                project_id=project_id,
                claim_type="target_user",
                statement=canvas["target_users"],
                criticality="high",
                scope_note=scope,
                now=now,
            ),
            self._create_claim_tx(
                connection,
                project_id=project_id,
                claim_type="user_problem",
                statement=canvas["problem"],
                criticality="critical",
                scope_note=scope,
                now=now,
            ),
        ]
        goals = canvas.get("goals") or []
        if goals:
            claims.append(
                self._create_claim_tx(
                    connection,
                    project_id=project_id,
                    claim_type="value",
                    statement=f"项目目标能够产生预期价值：{goals[0]}",
                    criticality="high",
                    scope_note="旧版 Canvas 中的目标仅作为待验证产品假设迁移。",
                    now=now,
                )
            )
        for claim in claims:
            connection.execute(
                "INSERT OR IGNORE INTO decision_claim_links(decision_id,claim_id,role,created_at) VALUES (?,?,'supports',?)",
                (decision_id, claim["id"], now),
            )
        return claims

    def migrate_project(self, project_id: str) -> dict[str, Any] | None:
        with self.db.connect() as connection:
            project_row = connection.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
            if project_row is None:
                raise KeyError("project not found")
            existing = self._existing_snapshot_tx(connection, project_id)
            if existing is not None:
                if not project_row["current_snapshot_id"]:
                    connection.execute(
                        "UPDATE projects SET current_snapshot_id=? WHERE id=?",
                        (existing["id"], project_id),
                    )
                return existing
            if project_row["current_snapshot_id"]:
                return None
            canvas_row = connection.execute("SELECT * FROM project_canvas WHERE project_id=?", (project_id,)).fetchone()
            if canvas_row is None:
                return None

            project = dict(project_row)
            canvas = dict(canvas_row)
            for field in ("goals", "non_goals", "success_metrics", "constraints"):
                canvas[field] = json.loads(canvas.pop(f"{field}_json"))
            if not self._has_migratable_canvas(canvas):
                return None
            now = utc_now()
            brief = self._ensure_idea_brief_tx(connection, project=project, canvas=canvas, now=now)
            decision = self._ensure_decision_tx(connection, project_id=project_id, now=now)
            claims = self._ensure_claims_tx(
                connection,
                project_id=project_id,
                decision_id=decision["id"],
                canvas=canvas,
                now=now,
            )
            selected = self._selected_option(decision)
            solution_title = (selected or {}).get("title") or project["title"]
            solution = {
                "candidate_id": decision.get("selected_option_id"),
                "title": solution_title,
                "mechanism": "other",
                "why_fit": (selected or {}).get("summary") or "从旧版 Canvas/Decision 迁移；未重新生成方案。",
                "rationale": decision.get("rationale") or "旧版项目合同迁移。",
                "core_decision_logic": "legacy_migration_only",
                "decision_logic": [],
                "explicit_non_goals": canvas.get("non_goals") or [],
                "evolution_path": [],
            }
            payload = {
                "title": project["title"],
                "one_liner": f"旧版项目迁移：为{canvas['target_users']}处理“{canvas['problem']}”。",
                "target_user": {
                    "primary": canvas["target_users"],
                    "provenance": "user_input",
                    "verification_status": "unverified",
                },
                "problem": {
                    "statement": canvas["problem"],
                    "provenance": "user_input",
                    "verification_status": "unverified",
                },
                "solution": solution,
                "mvp": {
                    "pages": [],
                    "features": canvas.get("goals") or [],
                    "outcomes": canvas.get("goals") or [],
                    "implementation_plan": [],
                    "acceptance_criteria": canvas.get("success_metrics") or [],
                    "risks": [],
                },
                "user_flow": [],
                "inputs": [],
                "outputs": [],
                "technical_plan": {
                    "components": [],
                    "data_requirements": [],
                    "constraints": canvas.get("constraints") or [],
                    "complexity": "unknown",
                    "major_dependency": "",
                },
                "unknowns": ["迁移后的关键判断尚未通过 3.0 Evidence Impact 重新验证。"],
                "next_action": {
                    "claim_id": next((item["id"] for item in claims if item["claim_type"] == "user_problem"), claims[0]["id"]),
                    "action": "验证迁移后的核心问题判断",
                    "reason": "旧版 Canvas 证明项目当时这样定义，不证明真实用户需求已经成立。",
                },
            }
            snapshot_id = f"snapshot_legacy_{uuid.uuid4().hex}"
            content_sha = sha256_payload(payload)
            connection.execute(
                """
                INSERT INTO project_snapshots(
                    id,project_id,version,idea_brief_id,decision_id,title,one_liner,
                    target_user_json,problem_json,solution_json,mvp_json,user_flow_json,
                    inputs_json,outputs_json,technical_plan_json,unknowns_json,next_action_json,
                    snapshot_origin,created_at,confirmed_at,created_by,supersedes_snapshot_id,content_sha256
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'legacy_migration',?,?,?,NULL,?)
                """,
                (
                    snapshot_id,
                    project_id,
                    1,
                    brief["id"],
                    decision["id"],
                    payload["title"],
                    payload["one_liner"],
                    json.dumps(payload["target_user"], ensure_ascii=False),
                    json.dumps(payload["problem"], ensure_ascii=False),
                    json.dumps(payload["solution"], ensure_ascii=False),
                    json.dumps(payload["mvp"], ensure_ascii=False),
                    "[]",
                    "[]",
                    "[]",
                    json.dumps(payload["technical_plan"], ensure_ascii=False),
                    json.dumps(payload["unknowns"], ensure_ascii=False),
                    json.dumps(payload["next_action"], ensure_ascii=False),
                    now,
                    canvas.get("updated_at") or now,
                    "legacy_migration",
                    content_sha,
                ),
            )
            for claim in claims:
                connection.execute(
                    "INSERT OR IGNORE INTO snapshot_claim_links(snapshot_id,claim_id,role) VALUES (?,?,'basis')",
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
            connection.execute(
                "INSERT OR IGNORE INTO snapshot_decision_links(snapshot_id,decision_id,role) VALUES (?,?,'current_solution')",
                (snapshot_id, decision["id"]),
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
                reason="legacy Canvas/Decision migrated without inventing evidence or validation",
            )
            connection.execute(
                "UPDATE projects SET current_snapshot_id=?,updated_at=? WHERE id=? AND current_snapshot_id IS NULL",
                (snapshot_id, now, project_id),
            )
            self.db.insert_audit_tx(
                connection,
                actor="legacy_migration",
                action="legacy_project_snapshot_migrated",
                entity_type="project_snapshot",
                entity_id=snapshot_id,
                payload={
                    "project_id": project_id,
                    "snapshot_origin": "legacy_migration",
                    "market_validation": False,
                    "evidence_links_created": 0,
                },
            )
            row = connection.execute("SELECT * FROM project_snapshots WHERE id=?", (snapshot_id,)).fetchone()
            return self._serialize_snapshot(row)

    def migrate_all(self) -> dict[str, Any]:
        projects = self.db.fetch_all("SELECT id FROM projects ORDER BY created_at,id")
        migrated = 0
        skipped = 0
        for project in projects:
            before = self.db.fetch_one(
                "SELECT id FROM project_snapshots WHERE project_id=? AND snapshot_origin='legacy_migration' LIMIT 1",
                (project["id"],),
            )
            result = self.migrate_project(project["id"])
            if result is not None and before is None and result["snapshot_origin"] == "legacy_migration":
                migrated += 1
            else:
                skipped += 1
        return {"projects": len(projects), "migrated": migrated, "skipped": skipped}
