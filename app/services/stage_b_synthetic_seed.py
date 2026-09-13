from __future__ import annotations

from typing import Any

from app.db import Database
from app.errors import ConflictError
from app.schemas import IdeaBriefDraft
from app.services.projects import ProjectService
from app.services.quick_start import QuickStartService
from app.services.solution_design import SolutionDesignService


STAGE_B_PHASE1A_PARTICIPANT = "railway_stage_b"
PHASE1A_SYNTHETIC_PROJECT_TITLE = "Stage B Phase1A Synthetic Canary — 实习求职进度管理"
PHASE1A_SYNTHETIC_PROJECT_SUMMARY = "轻量求职进度管理工具"
PHASE1A_SYNTHETIC_PROJECT_ID = "project_seed_phase1a_synthetic"


class StageBPhase1ASyntheticProjectSeedService:
    """Create the single provider-free, confirmed Phase1A demo project."""

    def __init__(self, db: Database):
        self.db = db
        self.projects = ProjectService(db)
        self.briefs = QuickStartService(db, self.projects, runtime=None)  # type: ignore[arg-type]

    @staticmethod
    def _draft() -> IdeaBriefDraft:
        return IdeaBriefDraft(
            original_idea="轻量求职进度管理工具",
            target_user="正在准备实习或校招求职的学生",
            problem="投递、笔试、面试、结果和待跟进事项分散在多个平台或个人记录中，用户容易遗漏当前阶段、结果和后续跟进动作。",
            desired_outcome="让用户能够集中记录求职流程状态，并清楚知道当前进度和下一步待办。",
            known_resources=[],
            constraints=["内容为合成测试上下文，不代表真实用户研究或市场事实。"],
            unknowns=["需要通过后续用户验证确认实际求职流程和提醒需求。"],
            provenance={
                "original_idea": "user_input",
                "target_user": "user_input",
                "problem": "user_input",
                "desired_outcome": "user_input",
            },
            clarification_required=False,
            clarification_question=None,
        )

    def _existing(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM projects WHERE title=? ORDER BY created_at, id",
            (PHASE1A_SYNTHETIC_PROJECT_TITLE,),
        )

    def _validate_clean_state(self, project: dict[str, Any]) -> dict[str, int]:
        project_id = project["id"]
        table_counts = {
            "solutions": "solution_runs",
            "solution_candidates": "solution_candidates",
            "documents": "documents",
            "document_versions": "document_versions",
            "sources": "sources",
            "source_chunks": "source_chunks",
            "snapshots": "project_snapshots",
            "competitor_snapshots": "competitor_decision_snapshots",
            "handoffs": "handoff_runs",
            "handoff_acknowledgements": "handoff_unresolved_acknowledgements",
            "feedback": "beta_feedback",
            "guided_sessions": "guided_sessions",
            "guided_messages": "guided_messages",
            "decisions": "project_decisions",
            "retrieval_runs": "retrieval_runs",
            "claims": "project_claims",
            "ai_reference_results": "ai_reference_results",
            "ai_reference_adoptions": "ai_reference_adoptions",
            "canvas": "project_canvas",
            "canvas_versions": "project_canvas_versions",
        }
        counts = {
            name: int(self.db.fetch_one(f"SELECT COUNT(*) AS count FROM {table} WHERE project_id=?", (project_id,))["count"])
            for name, table in table_counts.items()
        }
        if project.get("current_snapshot_id") or project.get("current_competitor_snapshot_id") or any(counts.values()):
            raise ConflictError("SYNTHETIC_PROJECT_STATE_NOT_CLEAN")
        return counts

    def _validate(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)
        if project["project_origin"] != "demo" or not bool(project["exclude_from_beta_metrics"]):
            raise ConflictError("SYNTHETIC_PROJECT_IDENTITY_INVALID")
        brief_row = self.db.fetch_one(
            "SELECT * FROM idea_briefs WHERE project_id=? ORDER BY version DESC LIMIT 1",
            (project_id,),
        )
        if not brief_row or brief_row["confirmation_status"] != "confirmed" or brief_row["clarification_required"]:
            raise ConflictError("SYNTHETIC_PROJECT_BRIEF_NOT_CONFIRMED")
        solution_service = SolutionDesignService(self.db, runtime=None)  # type: ignore[arg-type]
        confirmed = solution_service._confirmed_brief_row(project_id)
        solution_service._brief_for_project(project_id, confirmed, use_competitor_snapshot=False)
        clean_counts = self._validate_clean_state(project)
        return {
            "project_id": project_id,
            "participant": STAGE_B_PHASE1A_PARTICIPANT,
            "project_origin": project["project_origin"],
            "exclude_from_beta_metrics": bool(project["exclude_from_beta_metrics"]),
            "solutions_context_preflight": "PASS",
            "state": "clean",
            "state_counts": clean_counts,
        }

    def seed(self, *, participant: str, actor: str) -> dict[str, Any]:
        if participant != STAGE_B_PHASE1A_PARTICIPANT:
            raise ValueError("STAGE_B_PARTICIPANT_REQUIRED")
        existing = self._existing()
        seeded = self.db.fetch_one("SELECT * FROM projects WHERE id=?", (PHASE1A_SYNTHETIC_PROJECT_ID,))
        if len(existing) > 1:
            raise ConflictError("AMBIGUOUS_SYNTHETIC_PROJECT_IDENTITY")
        if existing and existing[0]["id"] != PHASE1A_SYNTHETIC_PROJECT_ID:
            raise ConflictError("SYNTHETIC_PROJECT_TITLE_COLLISION")
        if seeded:
            if not existing or seeded["title"] != PHASE1A_SYNTHETIC_PROJECT_TITLE:
                raise ConflictError("SYNTHETIC_PROJECT_ID_COLLISION")
            return self._validate(PHASE1A_SYNTHETIC_PROJECT_ID)

        project_id = PHASE1A_SYNTHETIC_PROJECT_ID
        draft = self._draft()
        with self.db.connect() as connection:
            self.projects.create_project_tx(
                connection,
                project_id=project_id,
                title=PHASE1A_SYNTHETIC_PROJECT_TITLE,
                summary=PHASE1A_SYNTHETIC_PROJECT_SUMMARY,
                actor=actor,
                project_origin="demo",
                exclude_from_beta_metrics=True,
                audit_action="stage_b_phase1a_synthetic_project_seeded",
                audit_payload={"participant": participant, "synthetic_input": True},
            )
            brief_id = self._insert_confirmed_brief_tx(connection, project_id, draft, actor)
        return self._validate(project_id) | {"brief_id": brief_id}

    def _insert_confirmed_brief_tx(self, connection, project_id: str, draft: IdeaBriefDraft, actor: str) -> str:
        brief_id = self.briefs._insert_brief_tx(
            connection,
            project_id=project_id,
            version=1,
            draft=draft,
            confirmation_status="inferred",
        )
        self.briefs._confirm_brief_tx(
            connection,
            brief_id=brief_id,
            project_id=project_id,
            actor=actor,
            note="Stage B synthetic seed; no market validation claimed.",
        )
        return brief_id
