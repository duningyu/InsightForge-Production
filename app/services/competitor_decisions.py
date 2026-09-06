"""Project-scoped competitor comparison and immutable decision snapshots."""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from app.db import Database, utc_now
from app.errors import ConflictError
from app.services.ai_runtime import sha256_payload
from app.services.projects import ProjectService


class CompetitorDecisionService:
    def __init__(self, db: Database, projects: ProjectService):
        self.db = db
        self.projects = projects

    def _candidates(self, project_id: str, candidate_ids: list[str]) -> list[dict[str, Any]]:
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ConflictError("候选产品不能重复")
        rows = self.db.fetch_all(
            "SELECT * FROM competitor_candidates WHERE project_id=? AND id IN ({}) ORDER BY created_at, id".format(
                ",".join("?" for _ in candidate_ids)
            ),
            (project_id, *candidate_ids),
        )
        by_id = {row["id"]: row for row in rows}
        if len(rows) != len(candidate_ids):
            raise KeyError("候选产品不存在或不可访问")
        if any(not bool(by_id[item]["selected"]) for item in candidate_ids):
            raise ConflictError("只能比较当前项目中已加入比较的候选产品")
        return [by_id[item] for item in candidate_ids]

    def create_comparison(self, project_id: str, candidate_ids: list[str], *, actor: str, runtime: Any) -> dict[str, Any]:
        self.projects.get_project(project_id)
        rows = self._candidates(project_id, candidate_ids)
        inputs = [
            {
                "candidate_id": row["id"],
                "name": row["name"],
                "url": row["url"],
                "description": row["description"],
                "source_status": "用户输入，尚未核实",
            }
            for row in rows
        ]
        result = runtime.compare_competitors(inputs)
        result_json = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
        comparison_id = f"competitor_comparison_{uuid4().hex}"
        now = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO competitor_comparisons(id,project_id,created_by,candidate_ids_json,result_json,created_at) VALUES (?,?,?,?,?,?)",
                (comparison_id, project_id, actor, json.dumps(candidate_ids), json.dumps(result_json, ensure_ascii=False), now),
            )
            self.db.insert_audit_tx(connection, actor=actor, action="competitor_comparison_created",
                                    entity_type="competitor_comparison", entity_id=comparison_id,
                                    payload={"project_id": project_id, "candidate_count": len(candidate_ids)})
        return {"id": comparison_id, "project_id": project_id, "candidate_ids": candidate_ids,
                "comparison": result_json, "created_at": now}

    def get_comparison(self, project_id: str, comparison_id: str) -> dict[str, Any]:
        self.projects.get_project(project_id)
        row = self.db.fetch_one("SELECT * FROM competitor_comparisons WHERE project_id=? AND id=?", (project_id, comparison_id))
        if row is None:
            raise KeyError("比较结果不存在或不可访问")
        return {"id": row["id"], "project_id": row["project_id"],
                "candidate_ids": json.loads(row["candidate_ids_json"]),
                "comparison": json.loads(row["result_json"]), "created_at": row["created_at"]}

    def create_snapshot(self, project_id: str, comparison_id: str, decisions: list[dict[str, Any]], *, actor: str) -> dict[str, Any]:
        comparison = self.get_comparison(project_id, comparison_id)
        candidate_ids = list(comparison["candidate_ids"])
        decision_ids = [item["candidate_id"] for item in decisions]
        if len(set(decision_ids)) != len(decision_ids) or any(item_id not in candidate_ids for item_id in decision_ids):
            raise ConflictError("决策必须属于本次比较")
        normalized_decisions = [
            {**item, "rationale": item.get("rationale") or item.get("reason") or ""}
            for item in decisions
        ]
        self._candidates(project_id, candidate_ids)
        content = {
            "project_id": project_id,
            "comparison_id": comparison_id,
            "candidate_ids": candidate_ids,
            "sources": [
                {"candidate_id": row["id"], "name": row["name"], "url": row["url"], "source_status": "用户输入，尚未核实"}
                for row in self._candidates(project_id, candidate_ids)
            ],
            "comparison": comparison["comparison"],
            "decisions": normalized_decisions,
            "boundary": "AI分析参考，建议结合实际产品页面核对。",
        }
        snapshot_id = f"competitor_snapshot_{uuid4().hex}"
        now = utc_now()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO competitor_decision_snapshots(id,project_id,created_by,comparison_id,candidate_ids_json,content_json,content_sha256,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (snapshot_id, project_id, actor, comparison_id, json.dumps(candidate_ids),
                 json.dumps(content, ensure_ascii=False), sha256_payload(content), now),
            )
            connection.execute("UPDATE projects SET current_competitor_snapshot_id=?, updated_at=? WHERE id=?",
                               (snapshot_id, now, project_id))
            self.db.insert_audit_tx(connection, actor=actor, action="competitor_snapshot_created",
                                    entity_type="competitor_snapshot", entity_id=snapshot_id,
                                    payload={"project_id": project_id, "comparison_id": comparison_id})
        return {"id": snapshot_id, "project_id": project_id, "content": content,
                "decision_snapshot": {**content, "id": snapshot_id, "content_sha256": sha256_payload(content)},
                "content_sha256": sha256_payload(content), "created_at": now}

    def get_snapshot(self, project_id: str, snapshot_id: str) -> dict[str, Any]:
        self.projects.get_project(project_id)
        row = self.db.fetch_one("SELECT * FROM competitor_decision_snapshots WHERE project_id=? AND id=?", (project_id, snapshot_id))
        if row is None:
            raise KeyError("竞品决策快照不存在或不可访问")
        return {"id": row["id"], "project_id": row["project_id"], "comparison_id": row["comparison_id"],
                "content": json.loads(row["content_json"]), "content_sha256": row["content_sha256"], "created_at": row["created_at"]}

    def context_for_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.fetch_one("SELECT current_competitor_snapshot_id FROM projects WHERE id=?", (project_id,))
        if not row or not row.get("current_competitor_snapshot_id"):
            return None
        snapshot = self.get_snapshot(project_id, row["current_competitor_snapshot_id"])
        content = snapshot["content"]
        grouped = {"adopt": [], "avoid": [], "defer": []}
        for decision in content.get("decisions", []):
            grouped.setdefault(decision["decision"], []).append({
                "candidate_id": decision["candidate_id"], "rationale": decision.get("rationale", "")
            })
        return {"snapshot_id": snapshot["id"], "boundary": content["boundary"],
                "adopt": grouped["adopt"], "avoid": grouped["avoid"], "defer": grouped["defer"]}
