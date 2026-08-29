from __future__ import annotations

import json
import re
import uuid
from typing import Any

from app.db import Database, utc_now
from app.services.projects import ProjectService


_STEP_ORDER = [
    "audience",
    "problem",
    "constraints",
    "evidence",
    "success",
    "solution",
    "canvas_ready",
    "complete",
]


class GuidedProjectService:
    """Bounded, transparent PM coaching state machine.

    The service keeps user-confirmed input separate from system suggestions and
    only writes a normal versioned Canvas after an explicit apply action.
    """

    def __init__(self, db: Database, projects: ProjectService | None = None):
        self.db = db
        self.projects = projects or ProjectService(db)

    def get_state(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)
        session = self.db.fetch_one(
            "SELECT * FROM guided_sessions WHERE project_id = ?", (project_id,)
        )
        if session is None:
            raise KeyError("legacy guided session not found")
        return self._serialize_session(session)

    def solution_proposals(self, project_id: str) -> dict[str, Any]:
        """Return three comparable suggestions and a bounded plan for the current idea.

        These are system suggestions based on the current Canvas, never an
        automatic project decision or a claim of implementation readiness.
        """
        project = self.projects.get_project(project_id)
        canvas = self.db.get_canvas(project_id)
        if canvas is None:
            state = {
                "idea": project["summary"],
                "target_users": "尚未确认",
                "user_problem": project["summary"],
                "constraints": [],
                "success_definition": "尚未确认",
            }
        else:
            state = {
                "idea": project["summary"],
                "target_users": canvas["target_users"],
                "user_problem": canvas["problem"],
                "constraints": canvas["constraints"],
                "success_definition": "；".join(canvas["success_metrics"]),
            }
        return {
            "project_id": project_id,
            "canvas_version": canvas["version"] if canvas else None,
            "options": self._build_solution_options(state),
            "idea_plan": self._build_idea_plan(state),
        }

    def respond(
        self,
        project_id: str,
        *,
        answer: str,
        choice_id: str | None,
        actor: str,
    ) -> dict[str, Any]:
        if not actor.strip():
            raise ValueError("actor is required")
        payload = self.get_state(project_id)
        session_id = payload["session_id"]
        current_step = payload["current_step"]
        state = dict(payload["state"])

        if current_step in {"canvas_ready", "complete"}:
            raise ValueError(f"guided session cannot accept an answer in step {current_step}")

        trace: dict[str, Any] = {
            "step": current_step,
            "source": "user_confirmed",
            "written_fields": [],
            "choice_id": choice_id,
        }

        if current_step == "solution":
            option = self._resolve_solution_choice(state, choice_id, answer)
            user_content = answer.strip() if option["id"] == "custom_solution" else option["title"]
            if option["id"] == "custom_solution":
                state["solution_options"] = [
                    *state.get("solution_options", []),
                    option,
                ]
            state["selected_solution_id"] = option["id"]
            state["proposed_canvas_patch"] = self._build_canvas_patch(state, option)
            next_step = "canvas_ready"
            trace["written_fields"] = ["selected_solution_id", "proposed_canvas_patch"]
            self._record_decision(project_id, state, option)
        else:
            normalized_answer = answer.strip()
            if not normalized_answer:
                raise ValueError("answer is required")
            user_content = normalized_answer
            next_step, fields = self._apply_answer(current_step, normalized_answer, state)
            trace["written_fields"] = fields

        state["last_trace"] = trace
        now = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                """
                UPDATE guided_sessions
                SET current_step = ?, state_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (next_step, json.dumps(state, ensure_ascii=False), now, session_id),
            )
            self._insert_message(
                connection,
                session_id=session_id,
                project_id=project_id,
                role="user",
                message_type="answer",
                content=user_content,
                metadata={"step": current_step, "trace": trace},
                created_at=now,
            )
            coach = self._coach_for(next_step, state)
            self._insert_message(
                connection,
                session_id=session_id,
                project_id=project_id,
                role="assistant",
                message_type="question" if coach.get("question") else "status",
                content=coach["message"],
                metadata={"step": next_step, "coach": coach},
                created_at=utc_now(),
            )
        self.db.insert_audit(
            actor=actor,
            action="guided_answer_recorded",
            entity_type="guided_session",
            entity_id=session_id,
            payload={
                "project_id": project_id,
                "from_step": current_step,
                "to_step": next_step,
                "written_fields": trace["written_fields"],
                "source": "user_confirmed",
            },
        )
        result = self.get_state(project_id)
        result["trace"] = trace
        return result

    def apply_canvas(self, project_id: str, *, actor: str) -> dict[str, Any]:
        payload = self.get_state(project_id)
        if payload["current_step"] != "canvas_ready":
            raise ValueError("guided session is not ready to apply a Canvas")
        patch = payload.get("proposed_canvas_patch") or {}
        required = {"problem", "target_users", "goals", "success_metrics"}
        if not required <= patch.keys():
            raise ValueError("guided session is not ready: Canvas proposal is incomplete")

        canvas = self.projects.update_canvas(
            project_id,
            problem=patch["problem"],
            target_users=patch["target_users"],
            goals=list(patch["goals"]),
            non_goals=list(patch.get("non_goals", [])),
            success_metrics=list(patch["success_metrics"]),
            constraints=list(patch.get("constraints", [])),
            actor=actor,
        )
        state = dict(payload["state"])
        state["confirmed_canvas_version"] = int(canvas["version"])
        state["canvas_confirmation_source"] = "explicit_user_apply"
        now = utc_now()
        self.db.execute(
            """
            UPDATE guided_sessions
            SET current_step = 'complete', status = 'completed', state_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (json.dumps(state, ensure_ascii=False), now, payload["session_id"]),
        )
        self.db.execute(
            """
            UPDATE project_decisions
            SET status = 'confirmed', confirmed_at = ?
            WHERE id = (
                SELECT id FROM project_decisions
                WHERE project_id = ? AND decision_type = 'guided_solution'
                  AND status = 'proposed'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            """,
            (now, project_id),
        )
        coach = self._coach_for("complete", state)
        with self.db.connect() as connection:
            self._insert_message(
                connection,
                session_id=payload["session_id"],
                project_id=project_id,
                role="assistant",
                message_type="status",
                content=coach["message"],
                metadata={"step": "complete", "coach": coach, "canvas_version": canvas["version"]},
                created_at=utc_now(),
            )
        self.db.insert_audit(
            actor=actor,
            action="guided_canvas_applied",
            entity_type="project_canvas",
            entity_id=project_id,
            payload={"canvas_version": canvas["version"], "session_id": payload["session_id"]},
        )
        result = self.get_state(project_id)
        result["canvas"] = canvas
        return result

    def reset(self, project_id: str, *, actor: str) -> dict[str, Any]:
        project = self.projects.get_project(project_id)
        existing = self.db.fetch_one(
            "SELECT id FROM guided_sessions WHERE project_id = ?", (project_id,)
        )
        if existing is None:
            raise KeyError("legacy guided session not found")
        with self.db.connect() as connection:
            connection.execute(
                "DELETE FROM guided_messages WHERE session_id = ?", (existing["id"],)
            )
            connection.execute(
                "DELETE FROM guided_sessions WHERE id = ?", (existing["id"],)
            )
        session = self._create_session(project, ignore_existing_canvas=True)
        self.db.insert_audit(
            actor=actor,
            action="guided_session_reset",
            entity_type="guided_session",
            entity_id=project_id,
            payload={"session_id": session["id"]},
        )
        return self._serialize_session(session)

    def go_back(self, project_id: str, *, actor: str) -> dict[str, Any]:
        payload = self.get_state(project_id)
        current_step = payload["current_step"]
        state = dict(payload["state"])
        previous = {
            "problem": ("audience", ["target_users"]),
            "constraints": ("problem", ["user_problem"]),
            "evidence": ("constraints", ["constraints"]),
            "success": ("evidence", ["evidence_status"]),
            "solution": ("success", ["success_definition", "solution_options"]),
            "canvas_ready": ("solution", ["selected_solution_id", "proposed_canvas_patch"]),
        }
        if current_step not in previous:
            raise ValueError("guided session cannot go back from the current step")
        next_step, fields = previous[current_step]
        for field in fields:
            if field in {"constraints", "solution_options"}:
                state[field] = []
            else:
                state[field] = None if field == "proposed_canvas_patch" else ""
            if field in state.get("confirmed_fields", []):
                state["confirmed_fields"].remove(field)
        if current_step == "canvas_ready":
            self.db.execute(
                """
                UPDATE project_decisions SET status = 'superseded'
                WHERE id = (
                    SELECT id FROM project_decisions
                    WHERE project_id = ? AND decision_type = 'guided_solution' AND status = 'proposed'
                    ORDER BY created_at DESC, id DESC LIMIT 1
                )
                """,
                (project_id,),
            )
        state["last_trace"] = {"step": current_step, "source": "user_edit", "written_fields": fields}
        self.db.execute(
            """
            UPDATE guided_sessions SET current_step = ?, state_json = ?, updated_at = ? WHERE id = ?
            """,
            (next_step, json.dumps(state, ensure_ascii=False), utc_now(), payload["session_id"]),
        )
        self.db.insert_audit(
            actor=actor,
            action="guided_step_reopened",
            entity_type="guided_session",
            entity_id=payload["session_id"],
            payload={"project_id": project_id, "from_step": current_step, "to_step": next_step},
        )
        return self.get_state(project_id)

    def _create_session(
        self,
        project: dict[str, Any],
        *,
        ignore_existing_canvas: bool = False,
    ) -> dict[str, Any]:
        canvas = None if ignore_existing_canvas else self.db.get_canvas(project["id"])
        if canvas is None:
            current_step = "audience"
            status = "active"
            state: dict[str, Any] = {
                "idea": project["summary"].strip(),
                "target_users": "",
                "user_problem": "",
                "constraints": [],
                "evidence_status": "",
                "success_definition": "",
                "solution_options": [],
                "selected_solution_id": None,
                "proposed_canvas_patch": None,
                "confirmed_canvas_version": None,
                "confirmed_fields": ["idea"],
                "suggested_fields": {},
            }
        else:
            current_step = "complete"
            status = "completed"
            state = {
                "idea": project["summary"].strip(),
                "target_users": canvas["target_users"],
                "user_problem": canvas["problem"],
                "constraints": canvas["constraints"],
                "evidence_status": "已有版本化项目合同",
                "success_definition": "；".join(canvas["success_metrics"]),
                "solution_options": [],
                "selected_solution_id": None,
                "proposed_canvas_patch": {
                    "problem": canvas["problem"],
                    "target_users": canvas["target_users"],
                    "goals": canvas["goals"],
                    "non_goals": canvas["non_goals"],
                    "success_metrics": canvas["success_metrics"],
                    "constraints": canvas["constraints"],
                },
                "confirmed_canvas_version": canvas["version"],
                "confirmed_fields": [
                    "idea",
                    "target_users",
                    "user_problem",
                    "constraints",
                    "success_definition",
                ],
                "suggested_fields": {},
            }

        session_id = f"guided_{uuid.uuid4().hex}"
        now = utc_now()
        coach = self._coach_for(current_step, state)
        with self.db.connect() as connection:
            connection.execute(
                """
                INSERT INTO guided_sessions(
                    id, project_id, current_step, state_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    project["id"],
                    current_step,
                    json.dumps(state, ensure_ascii=False),
                    status,
                    now,
                    now,
                ),
            )
            self._insert_message(
                connection,
                session_id=session_id,
                project_id=project["id"],
                role="assistant",
                message_type="question" if coach.get("question") else "status",
                content=coach["message"],
                metadata={"step": current_step, "coach": coach},
                created_at=now,
            )
        session = self.db.fetch_one("SELECT * FROM guided_sessions WHERE id = ?", (session_id,))
        assert session is not None
        return session

    def _serialize_session(self, session: dict[str, Any]) -> dict[str, Any]:
        state = json.loads(session["state_json"])
        coach = self._coach_for(session["current_step"], state)
        messages = self.db.fetch_all(
            """
            SELECT id, role, message_type, content, metadata_json, created_at
            FROM guided_messages WHERE session_id = ?
            ORDER BY created_at, id
            """,
            (session["id"],),
        )
        for message in messages:
            message["metadata"] = json.loads(message.pop("metadata_json") or "{}")
        return {
            "session_id": session["id"],
            "project_id": session["project_id"],
            "current_step": session["current_step"],
            "status": session["status"],
            "progress": self._progress(session["current_step"]),
            "state": state,
            "coach": coach,
            "proposed_canvas_patch": state.get("proposed_canvas_patch"),
            "evidence_requirements": self._evidence_requirements(state),
            "messages": messages,
            "trace": state.get("last_trace"),
            "created_at": session["created_at"],
            "updated_at": session["updated_at"],
        }

    @staticmethod
    def _insert_message(
        connection,
        *,
        session_id: str,
        project_id: str,
        role: str,
        message_type: str,
        content: str,
        metadata: dict[str, Any],
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO guided_messages(
                id, session_id, project_id, role, message_type,
                content, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"message_{uuid.uuid4().hex}",
                session_id,
                project_id,
                role,
                message_type,
                content,
                json.dumps(metadata, ensure_ascii=False),
                created_at,
            ),
        )

    def _apply_answer(
        self,
        step: str,
        answer: str,
        state: dict[str, Any],
    ) -> tuple[str, list[str]]:
        if step == "audience":
            state["target_users"] = answer
            self._confirm_field(state, "target_users")
            return "problem", ["target_users"]
        if step == "problem":
            state["user_problem"] = answer
            self._confirm_field(state, "user_problem")
            return "constraints", ["user_problem"]
        if step == "constraints":
            state["constraints"] = self._split_items(answer)
            self._confirm_field(state, "constraints")
            return "evidence", ["constraints"]
        if step == "evidence":
            state["evidence_status"] = answer
            self._confirm_field(state, "evidence_status")
            return "success", ["evidence_status"]
        if step == "success":
            state["success_definition"] = answer
            state["solution_options"] = self._build_solution_options(state)
            self._confirm_field(state, "success_definition")
            state.setdefault("suggested_fields", {})["solution_options"] = {
                "source": "system_suggestion",
                "reason": "根据用户已确认的受众、问题、约束和成功标准生成三个可比较方向。",
            }
            return "solution", ["success_definition", "solution_options"]
        raise ValueError(f"unsupported guided step: {step}")

    @staticmethod
    def _confirm_field(state: dict[str, Any], field: str) -> None:
        confirmed = state.setdefault("confirmed_fields", [])
        if field not in confirmed:
            confirmed.append(field)

    @staticmethod
    def _split_items(value: str) -> list[str]:
        items = [item.strip() for item in re.split(r"[；;\n、]+", value) if item.strip()]
        return items or [value.strip()]

    def _resolve_solution_choice(
        self,
        state: dict[str, Any],
        choice_id: str | None,
        answer: str,
    ) -> dict[str, Any]:
        options = state.get("solution_options") or []
        if not options:
            raise ValueError("solution options are missing")
        normalized = (choice_id or answer).strip()
        if normalized == "custom_solution":
            custom_summary = answer.strip()
            if not custom_summary:
                raise ValueError("a custom solution description is required")
            return {
                "id": "custom_solution",
                "title": "自定义/组合方案",
                "summary": custom_summary,
                "benefits": ["由项目创建者明确描述", "可组合已有方向"],
                "costs": ["需要后续补充验证依据"],
                "risks": ["范围或依赖尚未完全明确"],
                "unknowns": ["需要人工复核具体取舍"],
                "constraint_fit": "；".join(state.get("constraints") or []),
                "source": "user_confirmed",
            }
        for option in options:
            if normalized in {option["id"], option["title"]}:
                return option
        raise ValueError("a valid solution choice is required")

    @staticmethod
    def _build_solution_options(state: dict[str, Any]) -> list[dict[str, Any]]:
        audience = state.get("target_users") or "目标用户"
        problem = state.get("user_problem") or "当前问题"
        constraints = "、".join(state.get("constraints") or ["当前约束"])
        return [
            {
                "id": "guided_workflow",
                "title": "分步产品教练",
                "summary": f"围绕{audience}，通过一次一个问题的引导解决“{problem}”。",
                "benefits": ["新手认知负担低", "每一步都有解释和示例", "确认后再写入项目合同"],
                "costs": ["需要设计稳定的状态流", "对开放式复杂项目的覆盖有限"],
                "risks": ["引导过长会增加中途退出", "固定问题可能不适合所有场景"],
                "unknowns": ["用户愿意完成多少步", "哪些问题最需要跳过或改写"],
                "constraint_fit": constraints,
            },
            {
                "id": "evidence_first_workspace",
                "title": "证据优先工作台",
                "summary": f"先帮助{audience}整理来源、主张和可追溯依据，再生成产品方案。",
                "benefits": ["降低无来源强结论", "适合需要面试解释和复盘的项目", "来源边界清晰"],
                "costs": ["资料整理成本更高", "没有来源时产出会更保守"],
                "risks": ["新手仍可能不理解来源等级", "过度治理可能拖慢早期探索"],
                "unknowns": ["证据追溯是否显著提高完成质量", "用户是否愿意补充原始来源"],
                "constraint_fit": constraints,
            },
            {
                "id": "focused_mvp",
                "title": "单任务轻量 MVP",
                "summary": f"只解决{audience}最关键的一项任务，先验证“{problem}”是否高频。",
                "benefits": ["开发范围最小", "验证速度快", "失败退出成本低"],
                "costs": ["项目完整度较低", "后续可能需要重构为完整工作流"],
                "risks": ["过度收窄会弱化差异化", "不能覆盖端到端项目交付"],
                "unknowns": ["最关键单任务到底是哪一个", "轻量功能能否形成持续使用"],
                "constraint_fit": constraints,
            },
        ]

    @staticmethod
    def _build_canvas_patch(
        state: dict[str, Any],
        option: dict[str, Any],
    ) -> dict[str, Any]:
        problem = (
            f"项目想法：{state.get('idea', '').strip()}\n"
            f"目标用户当前问题：{state.get('user_problem', '').strip()}"
        ).strip()
        return {
            "problem": problem,
            "target_users": state.get("target_users", "").strip(),
            "goals": [
                option["summary"],
                "让项目关键假设、依据和待验证项可以回看。",
            ],
            "non_goals": [
                "不将未经确认的信息表述为已验证事实。",
                "不以当前草案替代人工审批或业务决策。",
            ],
            "success_metrics": [
                state.get("success_definition", "").strip(),
                "关键事实性主张可追溯率达到 100%。",
                "无依据事实性主张率为 0。",
            ],
            "constraints": list(state.get("constraints") or []),
        }

    @staticmethod
    def _build_idea_plan(state: dict[str, Any]) -> dict[str, Any]:
        idea = state.get("idea") or "当前产品想法"
        audience = state.get("target_users") or "目标用户"
        problem = state.get("user_problem") or "待确认的问题"
        constraints = list(state.get("constraints") or ["尚未补充现实约束"])
        success = state.get("success_definition") or "尚未定义成功标准"
        return {
            "title": "具体 Idea 的实施路径",
            "summary": f"围绕“{idea}”，先为{audience}解决“{problem}”。",
            "steps": [
                {"title": "第 1 步：缩小首个使用场景", "detail": f"只选择一个高频场景，并把不做的内容写清楚。当前约束：{'；'.join(constraints)}。"},
                {"title": "第 2 步：做可点击的最小流程", "detail": "先实现输入、核心判断/生成、人工确认和结果回看四个必要环节；不要先堆叠扩展功能。"},
                {"title": "第 3 步：用真实或明确标注的模拟材料试跑", "detail": "记录输入、输出、人工修改和失败原因；模拟材料不能作为真实用户验证。"},
                {"title": "第 4 步：按成功标准复盘", "detail": f"检查是否达到：{success}。未达到时优先修正首个场景，而不是扩大范围。"},
            ],
            "acceptance_checks": [
                "用户能独立完成一次核心流程。",
                "每个关键结论都能说明来自用户输入、来源材料还是系统建议。",
                "未确认的假设明确显示为待验证，而不是写成事实。",
            ],
            "boundary": "这是基于当前 Canvas 的建议实施路径；需要你结合真实用户反馈、成本和技术条件确认。",
        }

    def _record_decision(
        self,
        project_id: str,
        state: dict[str, Any],
        selected: dict[str, Any],
    ) -> None:
        self.db.execute(
            """
            INSERT INTO project_decisions(
                id, project_id, decision_type, options_json,
                selected_option_id, rationale, status, created_at, confirmed_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'proposed', ?, NULL)
            """,
            (
                f"decision_{uuid.uuid4().hex}",
                project_id,
                "guided_solution",
                json.dumps(state.get("solution_options", []), ensure_ascii=False),
                selected["id"],
                "由用户显式选择或描述；尚未写入 Canvas。",
                utc_now(),
            ),
        )

    @staticmethod
    def _coach_for(step: str, state: dict[str, Any]) -> dict[str, Any]:
        prompts: dict[str, dict[str, Any]] = {
            "audience": {
                "message": "先不填专业表格。我们先确定第一版最想帮助的人。",
                "question": "这个产品最想先帮助哪一类人？",
                "why": "不同用户的场景、能力和成功标准不同；先选一个核心人群能避免方案过宽。",
                "examples": ["准备转岗产品经理的人", "第一次做 AI 项目的学生", "产品能力较弱的独立开发者"],
                "choices": [
                    {"id": "career_switcher", "label": "转岗产品经理"},
                    {"id": "student", "label": "第一次做项目的学生"},
                    {"id": "indie_builder", "label": "独立开发者"},
                    {"id": "unsure", "label": "我不确定，继续帮我判断"},
                ],
            },
            "problem": {
                "message": f"已确认核心用户：{state.get('target_users', '')}。下一步只聚焦他们最卡的一件事。",
                "question": "他们在什么具体场景下最容易卡住？",
                "why": "“需要一个更好的工具”过于宽泛；具体场景才能转成可验证需求。",
                "examples": ["面对空白 PRD 不知道先写什么", "找到资料但无法判断是否可信", "把文档交给 AI Coding 时版本混乱"],
                "choices": [],
            },
            "constraints": {
                "message": "问题已经明确。现在补充现实边界，避免生成无法落地的方案。",
                "question": "第一版必须遵守哪些时间、预算、人员或技术限制？",
                "why": "约束不是专业术语考试，而是帮助系统排除不现实方案。",
                "examples": ["两周内完成", "单人开发", "默认不依赖付费模型", "只做本地 MVP"],
                "choices": [
                    {"id": "two_weeks", "label": "两周内"},
                    {"id": "solo", "label": "单人开发"},
                    {"id": "local_first", "label": "本地优先"},
                    {"id": "no_paid_model", "label": "不依赖付费模型"},
                ],
            },
            "evidence": {
                "message": "约束已记录。接下来只确认你手上已有的依据，不要求现在就补齐。",
                "question": "你现在已经有哪些可以核对的资料？",
                "why": "系统需要区分真实来源、公开资料、个人输入和待验证假设，避免把猜测写成事实。",
                "examples": ["产品经理反馈", "公开竞品页面", "课程作业", "代码与测试", "目前没有"],
                "choices": [],
            },
            "success": {
                "message": "已有证据情况已记录。现在定义一个新手也能判断的第一版成功标准。",
                "question": "第一版做到什么程度，你会认为它真的有用？",
                "why": "成功标准决定后续优先级和验收，不能只写“体验更好”。",
                "examples": ["30 分钟内完成项目框架", "生成 PRD 的关键结论都能回到来源", "可以直接交给 Codex 执行"],
                "choices": [],
            },
            "solution": {
                "message": "根据已确认的信息，系统生成了三个方向。它们只是建议，不会自动写入项目合同。",
                "question": "你希望先采用哪一个方向？",
                "why": "比较收益、成本、风险和未知项，比直接接受一个模型答案更可审计。",
                "examples": ["选择后仍可在高级工作台修改"],
                "choices": [
                    {
                        "id": option["id"],
                        "label": option["title"],
                        "description": option["summary"],
                    }
                    for option in state.get("solution_options", [])
                ] + [{"id": "custom_solution", "label": "自定义/组合方案", "description": "用自己的话说明要组合或替换的方向。"}],
            },
            "canvas_ready": {
                "message": "方案已形成 Canvas 草案，但尚未写入。请先检查右侧的已确认内容、系统建议和未验证项。",
                "question": "确认后是否将这份草案保存为新的 Canvas 版本？",
                "why": "显式确认可以阻止系统建议在用户不知情时变成正式需求。",
                "examples": ["点击“确认并保存 Canvas”后才会创建版本"],
                "choices": [],
            },
            "complete": {
                "message": "项目合同已保存。下一步应补充证据、运行可追溯检索，再生成并审查 PRD/TechDoc。",
                "question": "",
                "why": "",
                "examples": [],
                "choices": [],
            },
        }
        if step not in prompts:
            raise ValueError(f"unknown guided step: {step}")
        return prompts[step]

    @staticmethod
    def _progress(step: str) -> dict[str, Any]:
        index = _STEP_ORDER.index(step)
        return {
            "step_index": index,
            "step_count": len(_STEP_ORDER) - 1,
            "percent": round(min(index, len(_STEP_ORDER) - 2) / (len(_STEP_ORDER) - 2) * 100),
            "steps": [
                {
                    "id": item,
                    "status": "complete" if position < index else "current" if position == index else "upcoming",
                }
                for position, item in enumerate(_STEP_ORDER[:-1])
            ],
        }

    @staticmethod
    def _evidence_requirements(state: dict[str, Any]) -> list[dict[str, str]]:
        requirements = [
            {
                "id": "user_problem_evidence",
                "label": "用户问题依据",
                "status": "described" if state.get("evidence_status") else "missing",
                "guidance": "至少说明来源是实际反馈、公开资料、模拟场景还是个人判断。",
            },
            {
                "id": "solution_evidence",
                "label": "方案可行性依据",
                "status": "pending" if not state.get("selected_solution_id") else "needs_review",
                "guidance": "选择方向后，再用竞品、实现证据或测试补充可行性。",
            },
        ]
        return requirements
