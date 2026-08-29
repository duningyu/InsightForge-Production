from __future__ import annotations

import json
from typing import Any

from app.db import Database
from app.services.handoff import HandoffService
from app.services.project_claims import ProjectClaimService


class GuidanceService:
    """Select one workflow action from persisted project state only."""

    _TOUR_STEPS = {"idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"}

    def __init__(self, db: Database):
        self.db = db
        self.handoff = HandoffService(db)

    @staticmethod
    def _action(
        code: str, title: str, reason: str, view: str, control_id: str
    ) -> dict[str, str]:
        return {
            "code": code,
            "title": title,
            "reason": reason,
            "view": view,
            "control_id": control_id,
        }

    def project_next_action(self, project_id: str) -> dict[str, str]:
        project = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if project is None:
            raise KeyError("project not found")

        brief = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1",
            (project_id,),
        )
        if (
            brief is None
            or brief["confirmation_status"] != "confirmed"
            or bool(brief["clarification_required"])
        ):
            return self._action(
                "confirm_idea_brief",
                "确认或修改 Idea 理解",
                "在生成方案前，先确认系统对目标用户、问题和约束的理解。",
                "solutions",
                "idea-brief-confirm",
            )

        if not self._has_completed_solution_run(project_id, brief["id"]):
            return self._action(
                "generate_solutions",
                "生成候选方案",
                "已确认 Idea 理解；现在需要比较不同的实现路径。",
                "solutions",
                "generate-solutions-button",
            )

        if not project.get("current_snapshot_id"):
            return self._action(
                "select_solution",
                "选择 MVP 方案",
                "候选方案已经生成，选择一个方案后才能形成可追踪的项目快照。",
                "solutions",
                "solutions-content",
            )

        snapshot_id = str(project["current_snapshot_id"])
        proposal = self._highest_priority_open_snapshot_proposal(project_id, snapshot_id)
        if proposal is not None:
            return self._action(
                "review_project_snapshot",
                "检查并确认项目快照",
                "当前 Snapshot 有待处理的变更建议；请先决定是否接受、延后或拒绝它。",
                "evidence",
                f"proposal-actions:{proposal['id']}",
            )

        if not self._snapshot_health_is_current(snapshot_id):
            return self._action(
                "reconfirm_project_snapshot",
                "重新确认当前项目快照",
                "当前 Snapshot 的健康状态需要人工复核；确认后会恢复为当前可执行版本。",
                "snapshot",
                "snapshot-health-reconfirm",
            )

        claim = self._highest_priority_unverified_claim(project_id)
        if claim is not None:
            return self._action(
                "verify_project_claim",
                "验证关键项目主张",
                f"“{claim['statement']}”是当前优先级最高、尚未充分验证的主张。",
                "evidence",
                "evidence-claims-panel",
            )

        if not self._has_current_healthy_document(project_id, "prd", snapshot_id):
            return self._action(
                "generate_or_update_prd",
                "生成或更新 PRD",
                "当前 Snapshot 尚无可确认的健康 PRD。",
                "documents",
                "documents-content",
            )

        if not self._has_current_healthy_document(project_id, "techdoc", snapshot_id):
            return self._action(
                "generate_or_update_techdoc",
                "生成或更新 TechDoc",
                "当前 Snapshot 尚无可确认的健康 TechDoc。",
                "documents",
                "documents-content",
            )

        if not self._has_confirmed_current_document(project_id, "prd", snapshot_id) or not self._has_confirmed_current_document(
            project_id, "techdoc", snapshot_id
        ):
            return self._action(
                "confirm_document_versions",
                "确认当前文档版本",
                "PRD 和 TechDoc 已通过校验；需要人工确认当前健康版本。",
                "documents",
                "documents-content",
            )

        readiness = self.handoff.readiness(project_id)
        if not readiness["ready"]:
            return self._readiness_recovery_action(readiness)

        if not self._has_current_handoff_export(project, readiness):
            return self._action(
                "export_handoff",
                "导出开发交接包",
                "当前 Snapshot 和确认文档已经就绪，可以导出可执行的开发交接包。",
                "handoff",
                "export-handoff-button",
            )

        return self._action(
            "ready",
            "项目已就绪",
            "当前项目已完成交接；没有需要虚构的新任务。",
            "handoff",
            "handoff-content",
        )

    def home_next_action(self) -> dict[str, str]:
        projects = self.db.fetch_all(
            """
            SELECT id, title FROM projects
            WHERE status='active' AND id != 'project_insightforge_demo'
            ORDER BY updated_at DESC, id DESC
            """
        )
        for project in projects:
            if self.project_next_action(project["id"])["code"] != "ready":
                return self._action(
                    "continue_project",
                    "继续当前项目",
                    f"“{project['title']}”是最近更新且尚未完成的项目。",
                    f"project:{project['id']}",
                    f"project-select:{project['id']}",
                )

        if not self._has_completed_example_tour():
            return self._action(
                "start_example_tour",
                "开始完整示例导览",
                "当前没有未完成项目；通过一个完整示例熟悉从 Idea 到交接的流程。",
                "home",
                "example-list",
            )

        return self._action(
            "create_new_idea",
            "创建新 Idea",
            "当前没有未完成项目，且已完成示例导览。",
            "home",
            "quick-start-idea",
        )

    def _has_completed_solution_run(self, project_id: str, idea_brief_id: str) -> bool:
        row = self.db.fetch_one(
            """
            SELECT runs.id FROM solution_runs AS runs
            WHERE runs.project_id=? AND runs.idea_brief_id=?
              AND runs.status IN ('completed', 'completed_two_candidates')
              AND EXISTS (SELECT 1 FROM solution_candidates WHERE run_id=runs.id)
            ORDER BY runs.created_at DESC, runs.id DESC LIMIT 1
            """,
            (project_id, idea_brief_id),
        )
        return row is not None

    def _snapshot_health_is_current(self, snapshot_id: str) -> bool:
        health = self.db.fetch_one(
            """
            SELECT health_status FROM artifact_health
            WHERE artifact_type='project_snapshot' AND artifact_id=?
            """,
            (snapshot_id,),
        )
        return health is not None and health["health_status"] == "current"

    def _highest_priority_open_snapshot_proposal(
        self, project_id: str, snapshot_id: str
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            """
            SELECT id FROM change_proposals
            WHERE project_id=? AND from_snapshot_id=? AND status='open'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (project_id, snapshot_id),
        )

    def _highest_priority_unverified_claim(self, project_id: str) -> dict[str, Any] | None:
        claims = self.db.fetch_all(
            """
            SELECT * FROM project_claims
            WHERE project_id=? AND status='active' AND verification_status != 'supported'
            """,
            (project_id,),
        )
        if not claims:
            return None
        with self.db.connect() as connection:
            target = ProjectClaimService(self.db).next_best_action_tx(connection, claims)
        return self.db.fetch_one(
            "SELECT * FROM project_claims WHERE id=?", (target["claim_id"],)
        )

    def _has_current_healthy_document(
        self, project_id: str, doc_type: str, snapshot_id: str
    ) -> bool:
        row = self.db.fetch_one(
            """
            SELECT versions.id
            FROM document_versions AS versions
            JOIN artifact_dependencies AS dependencies
              ON dependencies.artifact_type='document_version'
             AND dependencies.artifact_id=versions.id
             AND dependencies.dependency_type='project_snapshot'
             AND dependencies.dependency_id=?
            JOIN artifact_health AS health
              ON health.artifact_type='document_version' AND health.artifact_id=versions.id
            WHERE versions.project_id=? AND versions.doc_type=?
              AND versions.lifecycle_status='active'
              AND versions.validation_status='passed'
              AND health.health_status='current'
            ORDER BY versions.version DESC, versions.id DESC
            LIMIT 1
            """,
            (snapshot_id, project_id, doc_type),
        )
        return row is not None

    def _has_confirmed_current_document(
        self, project_id: str, doc_type: str, snapshot_id: str
    ) -> bool:
        row = self.db.fetch_one(
            """
            SELECT versions.id
            FROM document_versions AS versions
            JOIN artifact_dependencies AS dependencies
              ON dependencies.artifact_type='document_version'
             AND dependencies.artifact_id=versions.id
             AND dependencies.dependency_type='project_snapshot'
             AND dependencies.dependency_id=?
            JOIN artifact_health AS health
              ON health.artifact_type='document_version' AND health.artifact_id=versions.id
            WHERE versions.project_id=? AND versions.doc_type=?
              AND versions.lifecycle_status='active'
              AND versions.validation_status='passed'
              AND versions.status='approved'
              AND health.health_status='current'
            ORDER BY versions.version DESC, versions.approved_at DESC, versions.id DESC
            LIMIT 1
            """,
            (snapshot_id, project_id, doc_type),
        )
        return row is not None

    def _readiness_recovery_action(self, readiness: dict[str, Any]) -> dict[str, str]:
        codes = {str(item.get("code")) for item in readiness.get("missing", [])}
        if "current_snapshot_unhealthy" in codes:
            return self._action(
                "reconfirm_project_snapshot",
                "重新确认当前项目快照",
                "当前 Snapshot 的健康状态需要人工复核，文档不能替代该确认。",
                "snapshot",
                "snapshot-health-reconfirm",
            )
        if {"confirmed_prd_missing", "confirmed_prd_unhealthy", "approved_prd_missing"} & codes:
            return self._action(
                "generate_or_update_prd",
                "生成或更新 PRD",
                "交接前需要一份当前健康的已确认 PRD。",
                "documents",
                "documents-content",
            )
        if {"confirmed_techdoc_missing", "confirmed_techdoc_unhealthy", "approved_techdoc_missing"} & codes:
            return self._action(
                "generate_or_update_techdoc",
                "生成或更新 TechDoc",
                "交接前需要一份当前健康的已确认 TechDoc。",
                "documents",
                "documents-content",
            )
        return self._action(
            "export_handoff",
            "重新检查并导出交接包",
            "当前交接准备度仍有待处理项；请在导出前复核当前状态。",
            "handoff",
            "export-handoff-button",
        )

    def _has_current_handoff_export(
        self, project: dict[str, Any], readiness: dict[str, Any]
    ) -> bool:
        snapshot_id = str(project["current_snapshot_id"])
        snapshot = self.db.fetch_one(
            "SELECT id, version, content_sha256 FROM project_snapshots WHERE id=?",
            (snapshot_id,),
        )
        documents = readiness.get("documents") or {}
        prd = documents.get("prd") or {}
        techdoc = documents.get("techdoc") or {}
        if snapshot is None or not prd.get("version_id") or not techdoc.get("version_id"):
            return False
        runs = self.db.fetch_all(
            """
            SELECT manifest_json FROM handoff_runs
            WHERE project_id=? AND status='completed'
            ORDER BY created_at DESC, id DESC
            """,
            (project["id"],),
        )
        for run in runs:
            try:
                manifest = json.loads(run["manifest_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            manifest_snapshot = manifest.get("snapshot") or {}
            manifest_documents = manifest.get("confirmed_documents") or {}
            manifest_prd = manifest_documents.get("prd") or {}
            manifest_techdoc = manifest_documents.get("techdoc") or {}
            if (
                manifest.get("project_id") == project["id"]
                and manifest.get("canvas_version") == readiness.get("canvas_version")
                and manifest.get("unresolved_claim_count") == readiness.get("unresolved_claim_count")
                and manifest_snapshot.get("id") == snapshot["id"]
                and manifest_snapshot.get("version") == snapshot["version"]
                and manifest_snapshot.get("content_sha256") == snapshot["content_sha256"]
                and manifest_prd.get("version_id") == prd["version_id"]
                and manifest_techdoc.get("version_id") == techdoc["version_id"]
            ):
                return True
        return False

    def _has_completed_example_tour(self) -> bool:
        table = self.db.fetch_one(
            "SELECT 1 AS present FROM sqlite_master WHERE type='table' AND name='project_tour_progress'"
        )
        if table is None:
            return False
        rows = self.db.fetch_all(
            "SELECT current_step, completed_steps_json FROM project_tour_progress"
        )
        for row in rows:
            if row["current_step"] in {"complete", "completed", "skipped"}:
                return True
            try:
                completed_steps = set(json.loads(row["completed_steps_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            if self._TOUR_STEPS <= completed_steps:
                return True
        return False
