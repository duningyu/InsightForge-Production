from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from typing import Any

from app.config import Settings
from app.db import Database, utc_now
from app.services.claims import ClaimService
from app.services.retrieval_service import ProjectRetrievalService


_ALLOWED_CLIENTS = {"codex", "claude_code", "cursor", "generic"}
_CLIENT_LABELS = {
    "codex": "Codex",
    "claude_code": "Claude Code",
    "cursor": "Cursor",
    "generic": "通用 AI Coding 客户端",
}
_EXPECTED_FILES = [
    "README_FIRST.md",
    "APPROVED_CONTEXT.md",
    "PRD_APPROVED.md",
    "TECHDOC_APPROVED.md",
    "CLAIM_LEDGER.json",
    "SOURCE_MANIFEST.json",
    "RETRIEVAL_TRACE.json",
    "ACCEPTANCE_TESTS.md",
    "IMPLEMENTATION_TASKS.json",
    "AGENTS.md",
    "HANDOFF_MANIFEST.json",
]


class HandoffService:
    """Create a concrete, versioned AI coding handoff package.

    The service fails closed until a validation-passed approved PRD and TechDoc
    exist. Unresolved claims are preserved as warnings and included in the ZIP;
    they are never silently promoted to requirements.
    """

    def __init__(self, db: Database):
        self.db = db
        self.claims = ClaimService(db)
        self.retrieval = ProjectRetrievalService(db)

    def readiness(self, project_id: str) -> dict[str, Any]:
        project = self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise KeyError("project not found")
        if project.get("current_snapshot_id"):
            return self._v3_readiness(project)
        return self._legacy_readiness(project)

    def _legacy_readiness(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = project["id"]
        canvas = self.db.get_canvas(project_id)
        prd = self._latest_approved(project_id, "prd")
        techdoc = self._latest_approved(project_id, "techdoc")
        missing: list[dict[str, str]] = []
        if canvas is None:
            missing.append({"code": "canvas_missing", "message": "需要先确认并保存项目 Canvas。"})
        if prd is None:
            missing.append({"code": "approved_prd_missing", "message": "需要一份 validation_status=passed 的人工批准 PRD。"})
        if techdoc is None:
            missing.append({"code": "approved_techdoc_missing", "message": "需要一份 validation_status=passed 的人工批准 TechDoc。"})
        selected_ids = [item["id"] for item in (prd, techdoc) if item is not None]
        unresolved_count = self._unresolved_count(selected_ids)
        draft_unresolved_count = self._latest_draft_unresolved_count(project_id)
        warnings: list[dict[str, str]] = []
        if unresolved_count:
            warnings.append({"code": "unresolved_claims_preserved", "message": f"存在 {unresolved_count} 条未解决主张；交接包会保留并禁止当作已确认需求。"})
        return {
            "project_id": project_id, "ready": not missing, "missing": missing, "warnings": warnings,
            "canvas_version": canvas["version"] if canvas else None, "snapshot": None,
            "documents": {"prd": self._document_metadata(prd), "techdoc": self._document_metadata(techdoc)},
            "unresolved_claim_count": unresolved_count, "draft_unresolved_claim_count": draft_unresolved_count,
            "expected_files": list(_EXPECTED_FILES), "claim_boundary": self._claim_boundary(),
        }

    def _v3_readiness(self, project: dict[str, Any]) -> dict[str, Any]:
        project_id = project["id"]
        snapshot_id = project["current_snapshot_id"]
        snapshot_row = self.db.fetch_one(
            "SELECT * FROM project_snapshots WHERE id=? AND project_id=?", (snapshot_id, project_id)
        )
        snapshot_health = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='project_snapshot' AND artifact_id=?", (snapshot_id,)
        )
        missing: list[dict[str, str]] = []
        if snapshot_row is None or snapshot_health is None or snapshot_health["health_status"] != "current":
            missing.append({"code": "current_snapshot_unhealthy", "message": "当前 Project Snapshot 缺失或需要重新确认。"})
        prd, prd_health = self._latest_confirmed_for_snapshot(project_id, "prd", snapshot_id)
        techdoc, techdoc_health = self._latest_confirmed_for_snapshot(project_id, "techdoc", snapshot_id)
        if prd is None:
            missing.append({"code": "confirmed_prd_missing", "message": "需要确认一份基于当前 Snapshot 的 PRD。"})
        elif prd_health is None or prd_health["health_status"] != "current":
            missing.append({"code": "confirmed_prd_unhealthy", "message": "当前确认 PRD 的证据或依赖已经失效。"})
        if techdoc is None:
            missing.append({"code": "confirmed_techdoc_missing", "message": "需要确认一份基于当前 Snapshot 的 TechDoc。"})
        elif techdoc_health is None or techdoc_health["health_status"] != "current":
            missing.append({"code": "confirmed_techdoc_unhealthy", "message": "当前确认 TechDoc 的证据或依赖已经失效。"})
        selected_ids = [item["id"] for item in (prd, techdoc) if item is not None]
        unresolved_count = self._unresolved_count(selected_ids)
        warnings: list[dict[str, str]] = []
        if unresolved_count:
            warnings.append({"code": "unresolved_claims_preserved", "message": f"存在 {unresolved_count} 条未解决主张；交接包会保留并禁止当作已确认需求。"})
        return {
            "project_id": project_id, "ready": not missing, "missing": missing, "warnings": warnings,
            "canvas_version": (self.db.get_canvas(project_id) or {}).get("version"),
            "snapshot": {"id": snapshot_id, "version": snapshot_row["version"] if snapshot_row else None,
                         "health_status": snapshot_health["health_status"] if snapshot_health else None},
            "documents": {"prd": self._v3_document_metadata(prd, prd_health), "techdoc": self._v3_document_metadata(techdoc, techdoc_health)},
            "unresolved_claim_count": unresolved_count,
            "draft_unresolved_claim_count": self._latest_draft_unresolved_count(project_id),
            "expected_files": self._v3_expected_files(), "claim_boundary": self._claim_boundary(),
        }

    def preview_manifest(
        self,
        project_id: str,
        *,
        target_client: str,
    ) -> dict[str, Any]:
        self._validate_client(target_client)
        readiness = self.readiness(project_id)
        return {
            "project_id": project_id,
            "target_client": target_client,
            "target_client_label": _CLIENT_LABELS[target_client],
            "ready": readiness["ready"],
            "missing": readiness["missing"],
            "warnings": readiness["warnings"],
            "expected_files": list(_EXPECTED_FILES),
            "claim_boundary": readiness["claim_boundary"],
        }

    def build_zip(
        self,
        project_id: str,
        *,
        target_client: str,
        actor: str,
    ) -> tuple[bytes, dict[str, Any]]:
        if not actor.strip():
            raise ValueError("actor is required")
        self._validate_client(target_client)
        readiness = self.readiness(project_id)
        if not readiness["ready"]:
            codes = ", ".join(item["code"] for item in readiness["missing"])
            raise ValueError(f"handoff is not ready: {codes}")
        project_probe = self.db.fetch_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project_probe is not None and project_probe.get("current_snapshot_id"):
            return self._build_v3_zip(project_probe, readiness=readiness, target_client=target_client, actor=actor)

        project = project_probe
        canvas = self.db.get_canvas(project_id)
        prd = self._latest_approved(project_id, "prd")
        techdoc = self._latest_approved(project_id, "techdoc")
        assert project is not None and canvas is not None and prd is not None and techdoc is not None

        handoff_run_id = f"handoff_{uuid.uuid4().hex}"
        created_at = utc_now()
        claim_documents = [
            self.claims.list_for_version(prd["id"]),
            self.claims.list_for_version(techdoc["id"]),
        ]
        sources = self._source_manifest(project_id)
        retrieval_trace = self._retrieval_trace([prd["id"], techdoc["id"]])

        files: dict[str, bytes] = {
            "README_FIRST.md": self._readme(
                project=project,
                canvas=canvas,
                readiness=readiness,
                target_client=target_client,
            ).encode("utf-8"),
            "APPROVED_CONTEXT.md": self._approved_context(project, canvas).encode("utf-8"),
            "PRD_APPROVED.md": (str(prd["content"]).strip() + "\n").encode("utf-8"),
            "TECHDOC_APPROVED.md": (str(techdoc["content"]).strip() + "\n").encode("utf-8"),
            "CLAIM_LEDGER.json": self._json_bytes(
                {
                    "project_id": project_id,
                    "documents": claim_documents,
                    "unresolved_claim_count": readiness["unresolved_claim_count"],
                }
            ),
            "SOURCE_MANIFEST.json": self._json_bytes(
                {"project_id": project_id, "sources": sources}
            ),
            "RETRIEVAL_TRACE.json": self._json_bytes(
                {"project_id": project_id, "runs": retrieval_trace}
            ),
            "ACCEPTANCE_TESTS.md": self._acceptance_tests(canvas).encode("utf-8"),
            "IMPLEMENTATION_TASKS.json": self._json_bytes(
                self._implementation_tasks(project_id, canvas)
            ),
            "AGENTS.md": self._agents_md(target_client).encode("utf-8"),
        }

        file_manifest = {
            filename: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
            for filename, payload in sorted(files.items())
        }
        manifest: dict[str, Any] = {
            "handoff_run_id": handoff_run_id,
            "app_version": Settings().app_version,
            "project_id": project_id,
            "project_title": project["title"],
            "target_client": target_client,
            "target_client_label": _CLIENT_LABELS[target_client],
            "created_at": created_at,
            "canvas_version": canvas["version"],
            "approved_documents": {
                "prd": self._document_metadata(prd),
                "techdoc": self._document_metadata(techdoc),
            },
            "unresolved_claim_count": readiness["unresolved_claim_count"],
            "warnings": readiness["warnings"],
            "claim_boundary": self._claim_boundary(),
            "files": file_manifest,
        }
        files["HANDOFF_MANIFEST.json"] = self._json_bytes(manifest)
        zip_bytes = self._zip_bytes(files)
        package_sha256 = hashlib.sha256(zip_bytes).hexdigest()
        manifest["package_sha256"] = package_sha256

        self.db.execute(
            """
            INSERT INTO handoff_runs(
                id, project_id, target_client, status, manifest_json, sha256, created_at
            ) VALUES (?, ?, ?, 'completed', ?, ?, ?)
            """,
            (
                handoff_run_id,
                project_id,
                target_client,
                json.dumps(manifest, ensure_ascii=False),
                package_sha256,
                created_at,
            ),
        )
        self.db.insert_audit(
            actor=actor,
            action="handoff_package_exported",
            entity_type="handoff_run",
            entity_id=handoff_run_id,
            payload={
                "project_id": project_id,
                "target_client": target_client,
                "package_sha256": package_sha256,
                "unresolved_claim_count": readiness["unresolved_claim_count"],
            },
        )
        return zip_bytes, manifest

    def _latest_confirmed_for_snapshot(
        self, project_id: str, doc_type: str, snapshot_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        row = self.db.fetch_one(
            """
            SELECT dv.* FROM document_versions dv
            JOIN artifact_dependencies dep
              ON dep.artifact_type='document_version' AND dep.artifact_id=dv.id
             AND dep.dependency_type='project_snapshot' AND dep.dependency_id=?
            WHERE dv.project_id=? AND dv.doc_type=? AND dv.status='approved'
              AND dv.validation_status='passed' AND dv.lifecycle_status='active'
            ORDER BY dv.version DESC,dv.approved_at DESC,dv.id DESC LIMIT 1
            """,
            (snapshot_id, project_id, doc_type),
        )
        if row is None:
            return None, None
        health = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (row["id"],),
        )
        return row, health

    @staticmethod
    def _v3_document_metadata(row: dict[str, Any] | None, health: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "version_id": row["id"], "document_id": row["document_id"], "doc_type": row["doc_type"],
            "version": row["version"], "canvas_version": row["canvas_version"],
            "validation_status": row["validation_status"], "status": row["status"],
            "confirmed_at": row["approved_at"],
            "health_status": health["health_status"] if health else None,
        }

    @staticmethod
    def _v3_expected_files() -> list[str]:
        return [
            "README_FIRST.md", "PROJECT_SNAPSHOT.json", "MVP_SCOPE.md", "UNRESOLVED_RISKS.md",
            "CONFIRMED_CONTEXT.md", "PRD_APPROVED.md", "TECHDOC_APPROVED.md", "CLAIM_LEDGER.json",
            "SOURCE_MANIFEST.json", "RETRIEVAL_TRACE.json", "ACCEPTANCE_TESTS.md",
            "IMPLEMENTATION_TASKS.json", "AGENTS.md", "HANDOFF_MANIFEST.json",
        ]

    def _snapshot_payload(self, snapshot_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM project_snapshots WHERE id=?", (snapshot_id,))
        if row is None:
            raise KeyError("project snapshot not found")
        payload = dict(row)
        for field in ("target_user","problem","solution","mvp","user_flow","inputs","outputs","technical_plan","unknowns","next_action"):
            payload[field] = json.loads(payload.pop(f"{field}_json"))
        return payload

    @staticmethod
    def _mvp_scope(snapshot: dict[str, Any]) -> str:
        mvp = snapshot.get("mvp") or {}
        solution = snapshot.get("solution") or {}
        lines = ["# MVP Scope", "", f"当前方案：{solution.get('title','')}", "", "## In scope"]
        lines.extend(f"- {item}" for item in (mvp.get("features") or []))
        lines.extend(["", "## Explicit non-scope"])
        non_goals = solution.get("explicit_non_goals") or []
        lines.extend(f"- {item}" for item in non_goals)
        if not non_goals:
            lines.append("- 当前 Snapshot 未声明额外非目标。")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _unresolved_risks(snapshot: dict[str, Any]) -> str:
        lines = ["# Unresolved Risks", ""]
        unknowns = snapshot.get("unknowns") or []
        lines.extend(f"- {item}" for item in unknowns)
        if not unknowns:
            lines.append("- 当前 Snapshot 未记录关键未知项。")
        return "\n".join(lines) + "\n"

    def _build_v3_zip(
        self, project: dict[str, Any], *, readiness: dict[str, Any], target_client: str, actor: str
    ) -> tuple[bytes, dict[str, Any]]:
        project_id = project["id"]
        snapshot = self._snapshot_payload(project["current_snapshot_id"])
        canvas = self.db.get_canvas(project_id)
        prd, _prd_health = self._latest_confirmed_for_snapshot(project_id, "prd", snapshot["id"])
        techdoc, _tech_health = self._latest_confirmed_for_snapshot(project_id, "techdoc", snapshot["id"])
        assert canvas is not None and prd is not None and techdoc is not None
        handoff_run_id = f"handoff_{uuid.uuid4().hex}"
        created_at = utc_now()
        claim_documents = [self.claims.list_for_version(prd["id"]), self.claims.list_for_version(techdoc["id"])]
        sources = self._source_manifest(project_id)
        retrieval_trace = self._retrieval_trace([prd["id"], techdoc["id"]])
        confirmed_context = self._approved_context(project, canvas).replace("批准", "确认")
        files: dict[str, bytes] = {
            "README_FIRST.md": self._readme(project=project, canvas=canvas, readiness=readiness, target_client=target_client).replace("批准", "确认").encode("utf-8"),
            "PROJECT_SNAPSHOT.json": self._json_bytes(snapshot),
            "MVP_SCOPE.md": self._mvp_scope(snapshot).encode("utf-8"),
            "UNRESOLVED_RISKS.md": self._unresolved_risks(snapshot).encode("utf-8"),
            "CONFIRMED_CONTEXT.md": confirmed_context.encode("utf-8"),
            "PRD_APPROVED.md": (str(prd["content"]).strip()+"\n").encode("utf-8"),
            "TECHDOC_APPROVED.md": (str(techdoc["content"]).strip()+"\n").encode("utf-8"),
            "CLAIM_LEDGER.json": self._json_bytes({"project_id":project_id,"documents":claim_documents,"unresolved_claim_count":readiness["unresolved_claim_count"]}),
            "SOURCE_MANIFEST.json": self._json_bytes({"project_id":project_id,"sources":sources}),
            "RETRIEVAL_TRACE.json": self._json_bytes({"project_id":project_id,"runs":retrieval_trace}),
            "ACCEPTANCE_TESTS.md": self._acceptance_tests(canvas).encode("utf-8"),
            "IMPLEMENTATION_TASKS.json": self._json_bytes(self._implementation_tasks(project_id,canvas)),
            "AGENTS.md": self._agents_md(target_client).replace("批准", "确认").encode("utf-8"),
        }
        file_manifest={name:{"sha256":hashlib.sha256(payload).hexdigest(),"bytes":len(payload)} for name,payload in sorted(files.items())}
        manifest={
            "handoff_run_id":handoff_run_id,"app_version":Settings().app_version,"project_id":project_id,
            "project_title":project["title"],"target_client":target_client,"target_client_label":_CLIENT_LABELS[target_client],
            "created_at":created_at,"canvas_version":canvas["version"],
            "snapshot":{"id":snapshot["id"],"version":snapshot["version"],"content_sha256":snapshot["content_sha256"]},
            "confirmed_documents":{"prd":self._document_metadata(prd),"techdoc":self._document_metadata(techdoc)},
            "unresolved_claim_count":readiness["unresolved_claim_count"],"warnings":readiness["warnings"],
            "claim_boundary":self._claim_boundary(),"files":file_manifest,
        }
        files["HANDOFF_MANIFEST.json"]=self._json_bytes(manifest)
        zip_bytes=self._zip_bytes(files)
        package_sha256=hashlib.sha256(zip_bytes).hexdigest()
        manifest["package_sha256"]=package_sha256
        self.db.execute(
            "INSERT INTO handoff_runs(id,project_id,target_client,status,manifest_json,sha256,created_at) VALUES (?,?,?,'completed',?,?,?)",
            (handoff_run_id,project_id,target_client,json.dumps(manifest,ensure_ascii=False),package_sha256,created_at),
        )
        self.db.insert_audit(actor=actor,action="handoff_package_exported",entity_type="handoff_run",entity_id=handoff_run_id,payload={"project_id":project_id,"target_client":target_client,"package_sha256":package_sha256,"snapshot_id":snapshot["id"]})
        return zip_bytes, manifest

    def _latest_approved(self, project_id: str, doc_type: str) -> dict[str, Any] | None:
        return self.db.fetch_one(
            """
            SELECT * FROM document_versions
            WHERE project_id = ? AND doc_type = ?
              AND status = 'approved' AND validation_status = 'passed'
              AND lifecycle_status = 'active'
            ORDER BY version DESC, approved_at DESC, id DESC LIMIT 1
            """,
            (project_id, doc_type),
        )

    def _unresolved_count(self, version_ids: list[str]) -> int:
        if not version_ids:
            return 0
        placeholders = ",".join("?" for _ in version_ids)
        row = self.db.fetch_one(
            f"""
            SELECT COUNT(*) AS count FROM document_claims
            WHERE version_id IN ({placeholders}) AND claim_type = 'unresolved'
            """,
            tuple(version_ids),
        )
        return int(row["count"]) if row else 0

    def _latest_draft_unresolved_count(self, project_id: str) -> int:
        row = self.db.fetch_one(
            """
            SELECT COUNT(*) AS count
            FROM document_claims AS claims
            JOIN document_versions AS versions ON versions.id = claims.version_id
            WHERE versions.project_id = ?
              AND versions.status != 'approved'
              AND versions.lifecycle_status = 'active'
              AND claims.claim_type = 'unresolved'
              AND versions.version = (
                  SELECT MAX(candidate.version)
                  FROM document_versions AS candidate
                  WHERE candidate.project_id = versions.project_id
                    AND candidate.doc_type = versions.doc_type
                    AND candidate.status != 'approved'
                    AND candidate.lifecycle_status = 'active'
              )
            """,
            (project_id,),
        )
        return int(row["count"]) if row else 0

    @staticmethod
    def _document_metadata(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "version_id": row["id"],
            "document_id": row["document_id"],
            "doc_type": row["doc_type"],
            "version": row["version"],
            "canvas_version": row["canvas_version"],
            "validation_status": row["validation_status"],
            "status": row["status"],
            "approved_at": row["approved_at"],
        }

    def _source_manifest(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.fetch_all(
            """
            SELECT id, title, filename, source_type, authority, authority_label,
                   authority_basis, source_url, publisher, published_at,
                   captured_at, status, sha256, metadata_json, created_at
            FROM sources WHERE project_id = ? ORDER BY created_at, id
            """,
            (project_id,),
        )
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        return rows

    def _retrieval_trace(self, version_ids: list[str]) -> list[dict[str, Any]]:
        if not version_ids:
            return []
        placeholders = ",".join("?" for _ in version_ids)
        generations = self.db.fetch_all(
            f"""
            SELECT version_id, retrieval_run_ids_json
            FROM generation_runs WHERE version_id IN ({placeholders})
            ORDER BY created_at, id
            """,
            tuple(version_ids),
        )
        run_ids: list[str] = []
        for generation in generations:
            run_ids.extend(json.loads(generation["retrieval_run_ids_json"] or "[]"))
        return [self.retrieval.get_run(run_id) for run_id in dict.fromkeys(run_ids)]

    @staticmethod
    def _readme(
        *,
        project: dict[str, Any],
        canvas: dict[str, Any],
        readiness: dict[str, Any],
        target_client: str,
    ) -> str:
        warning_lines = "\n".join(
            f"- {item['message']}" for item in readiness["warnings"]
        ) or "- 当前批准版本没有未解决主张。"
        return f"""# {project['title']} — AI Coding 交接包

目标客户端：{_CLIENT_LABELS[target_client]}
Canvas 版本：v{canvas['version']}

## 使用顺序

1. 先阅读 `HANDOFF_MANIFEST.json`，核对版本和 SHA-256。
2. 阅读 `APPROVED_CONTEXT.md`、`PRD_APPROVED.md` 与 `TECHDOC_APPROVED.md`。
3. 阅读 `CLAIM_LEDGER.json`，不得把 unresolved 或 model_suggestion 当作批准需求。
4. 按 `IMPLEMENTATION_TASKS.json` 执行，并用 `ACCEPTANCE_TESTS.md` 验收。
5. 遵守 `AGENTS.md` 中的修改、测试和回报规则。

## 当前边界与警告

{warning_lines}

本包证明批准上下文已经被版本化导出，不证明代码已实现或上线。
"""

    @staticmethod
    def _approved_context(project: dict[str, Any], canvas: dict[str, Any]) -> str:
        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items) or "- 无"

        return f"""# Approved Context

## Project

- Project ID: `{project['id']}`
- Title: {project['title']}
- Summary: {project['summary']}
- Canvas Version: {canvas['version']}

## Problem

{canvas['problem']}

## Target Users

{canvas['target_users']}

## Goals

{bullets(canvas['goals'])}

## Non-goals

{bullets(canvas['non_goals'])}

## Success Metrics

{bullets(canvas['success_metrics'])}

## Constraints

{bullets(canvas['constraints'])}
"""

    @staticmethod
    def _acceptance_tests(canvas: dict[str, Any]) -> str:
        lines = ["# Acceptance Tests", "", "以下验收项直接来自批准 Canvas，不代表已经通过。", ""]
        for index, metric in enumerate(canvas.get("success_metrics", []), start=1):
            lines.extend(
                [
                    f"## AT-{index:02d}",
                    "",
                    f"- 验收目标：{metric}",
                    "- Given：使用批准 Canvas 与固定输入。",
                    "- When：执行对应功能或评测流程。",
                    "- Then：保存可复核输出、日志和失败原因；未达标不得标记完成。",
                    "",
                ]
            )
        if not canvas.get("success_metrics"):
            lines.append("- 当前 Canvas 没有成功指标，交接前必须补充。")
        lines.extend(["", "## Constraints", ""])
        lines.extend(f"- {item}" for item in canvas.get("constraints", []))
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _implementation_tasks(project_id: str, canvas: dict[str, Any]) -> dict[str, Any]:
        metrics = list(canvas.get("success_metrics", []))
        tasks = []
        for index, goal in enumerate(canvas.get("goals", []), start=1):
            tasks.append(
                {
                    "id": f"TASK-{index:02d}",
                    "title": goal,
                    "status": "not_started",
                    "requirement_source": {
                        "project_id": project_id,
                        "canvas_version": canvas["version"],
                        "field": "goals",
                        "index": index - 1,
                    },
                    "acceptance_criteria": metrics,
                    "must_not": [
                        "静默改变批准需求",
                        "把 unresolved 主张当作事实",
                        "跳过测试后声称完成",
                    ],
                }
            )
        return {
            "project_id": project_id,
            "canvas_version": canvas["version"],
            "tasks": tasks,
        }

    @staticmethod
    def _agents_md(target_client: str) -> str:
        client = _CLIENT_LABELS[target_client]
        return f"""# AGENTS.md — {client} Execution Contract

## Authority

- 批准 PRD、批准 TechDoc 与 Canvas 版本是本次实现的需求边界。
- `CLAIM_LEDGER.json` 中的 `unresolved` 与 `model_suggestion` 不得当作已批准需求。
- 不得静默修改已批准需求；发现冲突时先记录 change request，再等待人工确认。

## Required workflow

1. 在修改代码前读取 `HANDOFF_MANIFEST.json` 并校验文件 SHA-256。
2. 按 `IMPLEMENTATION_TASKS.json` 分任务执行，保持可追踪提交。
3. 先写失败测试，再实现最小修改。
4. 执行全部相关测试、静态检查和运行烟雾测试。
5. 回报修改文件、测试命令、真实输出、失败项和剩余风险。

## Prohibited claims

- 未运行测试不得声称“已通过”。
- 未接入真实外部系统不得声称“已上线”或“形成在线闭环”。
- 不得把模拟研究、单次反馈或模型建议改写成市场验证。
"""

    @staticmethod
    def _claim_boundary() -> dict[str, Any]:
        return {
            "auto_approval": False,
            "auto_publish": False,
            "overwrite_approved_versions": False,
            "unresolved_claims_are_requirements": False,
            "simulated_research_is_real_research": False,
            "package_proves_implementation_complete": False,
        }

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    @staticmethod
    def _zip_bytes(files: dict[str, bytes]) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for filename in sorted(files):
                info = zipfile.ZipInfo(filename)
                info.date_time = (1980, 1, 1, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, files[filename])
        return output.getvalue()

    @staticmethod
    def _validate_client(target_client: str) -> None:
        if target_client not in _ALLOWED_CLIENTS:
            raise ValueError(f"invalid target_client: {target_client}")
