"""Provider-free M1 purpose confirmation and first-action planning."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.errors import ConflictError


PURPOSES = {"LEARNING", "PERSONAL_USE", "FOR_OTHERS", "UNSPECIFIED"}
TEMPLATE_VERSION = "m1-first-action-v1"
ACTION_FIELDS = (
    "goal",
    "why_now",
    "inputs",
    "steps",
    "expected_artifact",
    "checks",
    "branches",
    "stop_condition",
    "prohibited_actions",
)


_TEMPLATES: dict[str, dict[str, Any]] = {
    "LEARNING": {
        "goal": "把一个具体问题拆成一次可观察的学习练习。",
        "why_now": "现在先用低成本练习验证自己是否理解了关键步骤。",
        "inputs": ["一个明确的问题", "可访问的学习材料"],
        "steps": ["写下已知与未知", "完成一次小练习", "记录卡住的位置"],
        "expected_artifact": "一份带有结果和疑问的练习记录。",
        "checks": ["结果能被自己复盘", "疑问被单独列出"],
        "branches": ["如果无法完成，缩小练习范围"],
        "stop_condition": "练习完成且下一条疑问已被记录。",
        "prohibited_actions": ["不得把一次练习结果当作市场需求"],
    },
    "PERSONAL_USE": {
        "goal": "用自己的真实输入完成一次可复盘的小流程。",
        "why_now": "现在先验证它是否改善你自己的当前做法。",
        "inputs": ["自己的真实材料", "当前使用的方法"],
        "steps": ["记录当前做法", "完成一次小范围尝试", "比较尝试前后差异"],
        "expected_artifact": "一份个人使用前后对比记录。",
        "checks": ["输入确实来自自己", "差异可以具体描述"],
        "branches": ["如果没有改善，保留原因并停止扩大范围"],
        "stop_condition": "完成一次前后对比并记录是否继续。",
        "prohibited_actions": ["不得外推为普遍市场需求"],
    },
    "FOR_OTHERS": {
        "goal": "围绕一个具体观察对象完成一次可核验的手动验证。",
        "why_now": "现在先观察具体使用者是否遇到这个问题。",
        "inputs": ["一个具体观察对象", "一组中性的观察问题"],
        "steps": ["说明要观察的问题", "进行一次手动观察或访谈", "记录原话和不确定性"],
        "expected_artifact": "一份去除身份信息的观察记录。",
        "checks": ["观察与目标问题相关", "事实和推测分开记录"],
        "branches": ["如果无法观察，记录阻碍而不补造结果"],
        "stop_condition": "完成一次观察并标记仍未验证的部分。",
        "prohibited_actions": ["不得把一次观察当作市场验证结论"],
    },
    "UNSPECIFIED": {
        "goal": "把模糊想法缩小为一个低风险、可撤销的小尝试。",
        "why_now": "现在先获得一个具体反馈，而不是扩大承诺。",
        "inputs": ["当前模糊想法", "可用的少量时间或材料"],
        "steps": ["选择最小尝试", "执行一次可撤销步骤", "记录结果与新问题"],
        "expected_artifact": "一份小尝试结果和下一步判断记录。",
        "checks": ["尝试可撤销", "没有把假设写成事实"],
        "branches": ["如果风险或成本上升，立即缩小或停止"],
        "stop_condition": "结果已记录，且下一步仍可由用户决定。",
        "prohibited_actions": ["不得自动商业化"],
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode(value: str) -> Any:
    return json.loads(value)


def _substantive(value: str) -> bool:
    return bool(value.strip()) and value.strip() not in {"待定", "暂未确认", "TODO", "TBD"}


class ProjectIntentService:
    def __init__(self, db):
        self.db = db

    def _project(self, connection, project_id: str) -> Any:
        project = connection.execute(
            "SELECT id, status FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            raise KeyError("project not found")
        if project["status"] != "active":
            raise ValueError("project is not active")
        return project

    def _check_owner(self, row: Any, actor: str) -> None:
        if row is not None and row["owner_actor"] != actor:
            raise PermissionError("project intent belongs to another actor")

    def _latest_intent(self, connection, project_id: str) -> Any:
        return connection.execute(
            "SELECT * FROM project_intents WHERE project_id = ? ORDER BY revision DESC LIMIT 1",
            (project_id,),
        ).fetchone()

    def _action_row(self, connection, project_id: str, intent_revision: int) -> Any:
        return connection.execute(
            """SELECT * FROM first_action_cards
               WHERE project_id = ? AND intent_revision = ? AND template_version = ?""",
            (project_id, intent_revision, TEMPLATE_VERSION),
        ).fetchone()

    def _public_intent(self, row: Any) -> dict[str, Any]:
        return {
            "intent_id": row["intent_id"],
            "project_id": row["project_id"],
            "purpose": row["purpose"],
            "raw_idea": row["raw_idea"],
            "revision": row["revision"],
            "confirmed_at": row["confirmed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _public_action(self, row: Any) -> dict[str, Any]:
        return {
            "task_id": row["task_id"],
            "project_id": row["project_id"],
            "intent_revision": row["intent_revision"],
            "template_version": row["template_version"],
            "status": row["status"],
            "goal": row["goal"],
            "why_now": row["why_now"],
            "inputs": _decode(row["inputs_json"]),
            "steps": _decode(row["steps_json"]),
            "expected_artifact": row["expected_artifact"],
            "checks": _decode(row["checks_json"]),
            "branches": _decode(row["branches_json"]),
            "stop_condition": row["stop_condition"],
            "prohibited_actions": _decode(row["prohibited_actions_json"]),
            "revision": row["card_revision"],
            "confirmed": bool(row["confirmed"]),
            "confirmed_at": row["confirmed_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _quality(self, intent: Any, action: Any) -> dict[str, Any]:
        covered = sum(bool(action[field] if field not in {
            "inputs", "steps", "checks", "branches", "prohibited_actions"
        } else _decode(action[f"{field}_json"])) for field in ACTION_FIELDS)
        return {
            "structural_coverage": {"covered": covered, "required": len(ACTION_FIELDS)},
            "provider_dispatches": 0,
            "provider_transports": 0,
            "search_requests": 0,
            "source_identity": "user",
            "purpose_alignment": "PASS" if intent["purpose"] in PURPOSES else "FAIL",
            "guard": True,
        }

    def _response(self, intent: Any, action: Any) -> dict[str, Any]:
        return {
            "intent": self._public_intent(intent),
            "first_action": self._public_action(action),
            "quality": self._quality(intent, action),
        }

    def set_intent(
        self, project_id: str, *, purpose: str, raw_idea: str,
        actor: str, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if purpose not in PURPOSES or not _substantive(raw_idea):
            raise ValueError("purpose and raw_idea must be substantive")
        now = _now()
        with self.db.connect() as connection:
            self._project(connection, project_id)
            current = self._latest_intent(connection, project_id)
            self._check_owner(current, actor)
            current_revision = int(current["revision"]) if current else 0
            if expected_revision != current_revision:
                if current is None and expected_revision is not None:
                    raise ConflictError("INTENT_REVISION_CONFLICT")
                if current is not None:
                    raise ConflictError("INTENT_REVISION_CONFLICT")
            revision = current_revision + 1
            connection.execute(
                """INSERT INTO project_intents(
                    intent_id, project_id, owner_actor, revision, purpose, raw_idea,
                    confirmed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), project_id, actor, revision, purpose, raw_idea.strip(), now, now, now),
            )
            template = _TEMPLATES[purpose]
            task_id = str(uuid.uuid4())
            connection.execute(
                """INSERT INTO first_action_cards(
                    task_id, project_id, intent_revision, template_version, status,
                    goal, why_now, inputs_json, steps_json, expected_artifact,
                    checks_json, branches_json, stop_condition, prohibited_actions_json,
                    card_revision, confirmed, confirmed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'READY', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, NULL, ?, ?)""",
                (
                    task_id, project_id, revision, TEMPLATE_VERSION,
                    template["goal"], template["why_now"], _json(template["inputs"]),
                    _json(template["steps"]), template["expected_artifact"],
                    _json(template["checks"]), _json(template["branches"]),
                    template["stop_condition"], _json(template["prohibited_actions"]),
                    now, now,
                ),
            )
            intent = self._latest_intent(connection, project_id)
            action = self._action_row(connection, project_id, revision)
            return self._response(intent, action)

    def get_intent(self, project_id: str, *, actor: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            intent = self._latest_intent(connection, project_id)
            if intent is None:
                return {"intent": None, "first_action": None, "quality": None}
            self._check_owner(intent, actor)
            return self._response(intent, self._action_row(connection, project_id, intent["revision"]))

    def ensure_first_action(self, project_id: str, *, actor: str) -> dict[str, Any]:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            intent = self._latest_intent(connection, project_id)
            if intent is None:
                raise ConflictError("INTENT_REQUIRED")
            self._check_owner(intent, actor)
            return self._response(intent, self._action_row(connection, project_id, intent["revision"]))

    def update_action(self, project_id: str, task_id: str, *, actor: str,
                      expected_revision: int, updates: dict[str, Any]) -> dict[str, Any]:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            intent = self._latest_intent(connection, project_id)
            if intent is None:
                raise ConflictError("INTENT_REQUIRED")
            self._check_owner(intent, actor)
            action = connection.execute(
                "SELECT * FROM first_action_cards WHERE task_id = ? AND project_id = ?",
                (task_id, project_id),
            ).fetchone()
            if action is None:
                raise KeyError("first action not found")
            if int(action["intent_revision"]) != int(intent["revision"]):
                raise ConflictError("ACTION_NOT_CURRENT")
            if int(action["card_revision"]) != expected_revision:
                raise ConflictError("ACTION_REVISION_CONFLICT")
            values: dict[str, Any] = {
                "goal": action["goal"], "why_now": action["why_now"],
                "inputs_json": action["inputs_json"], "steps_json": action["steps_json"],
                "expected_artifact": action["expected_artifact"], "checks_json": action["checks_json"],
                "branches_json": action["branches_json"], "stop_condition": action["stop_condition"],
                "prohibited_actions_json": action["prohibited_actions_json"],
            }
            for field, value in updates.items():
                if value is None:
                    continue
                if field in {"inputs", "steps", "checks", "branches", "prohibited_actions"}:
                    if not value or any(not isinstance(item, str) or not _substantive(item) for item in value):
                        raise ValueError("action fields must be substantive")
                    values[f"{field}_json"] = _json(value)
                elif not _substantive(value):
                    raise ValueError("action fields must be substantive")
                else:
                    values[field] = value
            if any(not values[key] for key in values):
                raise ValueError("first action must be complete")
            new_revision = expected_revision + 1
            now = _now()
            connection.execute(
                """UPDATE first_action_cards SET
                    status = 'READY', goal = ?, why_now = ?, inputs_json = ?, steps_json = ?,
                    expected_artifact = ?, checks_json = ?, branches_json = ?, stop_condition = ?,
                    prohibited_actions_json = ?, card_revision = ?, confirmed = 0,
                    confirmed_at = NULL, updated_at = ?
                   WHERE task_id = ? AND project_id = ?""",
                (
                    values["goal"], values["why_now"], values["inputs_json"], values["steps_json"],
                    values["expected_artifact"], values["checks_json"], values["branches_json"],
                    values["stop_condition"], values["prohibited_actions_json"], new_revision, now,
                    task_id, project_id,
                ),
            )
            return self._response(intent, connection.execute(
                "SELECT * FROM first_action_cards WHERE task_id = ?", (task_id,)
            ).fetchone())

    def confirm_action(self, project_id: str, task_id: str, *, actor: str,
                       expected_revision: int) -> dict[str, Any]:
        with self.db.connect() as connection:
            self._project(connection, project_id)
            intent = self._latest_intent(connection, project_id)
            if intent is None:
                raise ConflictError("INTENT_REQUIRED")
            self._check_owner(intent, actor)
            action = connection.execute(
                "SELECT * FROM first_action_cards WHERE task_id = ? AND project_id = ?",
                (task_id, project_id),
            ).fetchone()
            if action is None:
                raise KeyError("first action not found")
            if int(action["intent_revision"]) != int(intent["revision"]):
                raise ConflictError("ACTION_NOT_CURRENT")
            if int(action["card_revision"]) != expected_revision:
                raise ConflictError("ACTION_REVISION_CONFLICT")
            if action["status"] != "READY":
                raise ConflictError("ACTION_NOT_READY")
            now = _now()
            connection.execute(
                "UPDATE first_action_cards SET confirmed = 1, confirmed_at = ?, updated_at = ? WHERE task_id = ?",
                (now, now, task_id),
            )
            return self._response(intent, connection.execute(
                "SELECT * FROM first_action_cards WHERE task_id = ?", (task_id,)
            ).fetchone())
