from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable

from app.db import Database, utc_now
from app.services.ai_runtime import sha256_payload


_DIRECT_ID_TABLES = (
    "sources",
    "source_chunks",
    "retrieval_runs",
    "idea_briefs",
    "solution_runs",
    "solution_candidates",
    "project_decisions",
    "project_claims",
    "project_snapshots",
    "documents",
    "document_versions",
    "generation_runs",
    "document_claims",
    "guided_sessions",
    "guided_messages",
    "change_proposals",
)


class ExampleCopyService:
    """Create an editable, independently keyed copy of a canonical example."""

    def __init__(self, db: Database):
        self.db = db

    def list_examples(self) -> list[dict[str, Any]]:
        return self.db.fetch_all(
            """SELECT id,title,summary,status,current_snapshot_id,created_at,updated_at
               FROM projects WHERE status='example' ORDER BY created_at,id"""
        )

    @staticmethod
    def _new_id(old_id: str) -> str:
        prefix = old_id.split("_", 1)[0] or "copy"
        return f"{prefix}_{uuid.uuid4().hex}"

    @staticmethod
    def _rows(
        connection: sqlite3.Connection,
        table: str,
        where: str,
        params: Iterable[Any],
    ) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM {table} WHERE {where} ORDER BY rowid",  # fixed internal tables
                tuple(params),
            ).fetchall()
        ]

    @staticmethod
    def _insert(
        connection: sqlite3.Connection,
        table: str,
        row: dict[str, Any],
        **overrides: Any,
    ) -> None:
        payload = {**row, **overrides}
        columns = list(payload)
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",  # fixed internal tables
            tuple(payload[column] for column in columns),
        )

    @staticmethod
    def _replace_ids(value: Any, id_map: dict[str, str]) -> Any:
        if value is None or not isinstance(value, str):
            return value
        rewritten = value
        for old_id in sorted(id_map, key=len, reverse=True):
            rewritten = rewritten.replace(old_id, id_map[old_id])
        return rewritten

    @classmethod
    def _rewrite_json(cls, value: str, id_map: dict[str, str]) -> str:
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return cls._replace_ids(value, id_map)

        def rewrite(item: Any) -> Any:
            if isinstance(item, dict):
                return {key: rewrite(child) for key, child in item.items()}
            if isinstance(item, list):
                return [rewrite(child) for child in item]
            if isinstance(item, str):
                return cls._replace_ids(item, id_map)
            return item

        return json.dumps(rewrite(payload), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _snapshot_hash(row: dict[str, Any]) -> str:
        payload: dict[str, Any] = {"title": row["title"], "one_liner": row["one_liner"]}
        for field in (
            "target_user", "problem", "solution", "mvp", "user_flow", "inputs",
            "outputs", "technical_plan", "unknowns", "next_action",
        ):
            payload[field] = json.loads(row[f"{field}_json"])
        return sha256_payload(payload)

    def copy(
        self,
        example_id: str,
        actor: str,
        *,
        source_status: str = "example",
        relation_type: str = "example_copy",
        title_suffix: str = "",
    ) -> dict[str, Any]:
        if source_status not in {"example", "active"}:
            raise ValueError("unsupported project copy source status")
        if relation_type not in {"example_copy", "project_copy"}:
            raise ValueError("unsupported project relation type")
        clean_actor = actor.strip()
        if not clean_actor:
            raise ValueError("actor is required")
        if len(clean_actor) > 80:
            raise ValueError("actor must be at most 80 characters")

        child_id = f"project_{uuid.uuid4().hex}"
        now = utc_now()
        with self.db.connect() as connection:
            parent_row = connection.execute(
                "SELECT * FROM projects WHERE id=? AND status=?", (example_id, source_status)
            ).fetchone()
            if parent_row is None:
                raise KeyError("canonical example not found" if source_status == "example" else "active project not found")
            parent = dict(parent_row)

            direct_rows = {
                table: self._rows(connection, table, "project_id=?", (example_id,))
                for table in _DIRECT_ID_TABLES
            }
            id_map: dict[str, str] = {example_id: child_id}
            for table in _DIRECT_ID_TABLES:
                for row in direct_rows[table]:
                    id_map[row["id"]] = self._new_id(row["id"])

            generation_ids = [row["id"] for row in direct_rows["generation_runs"]]
            validation_rows = self._indirect_rows(
                connection, "validation_issues", "generation_run_id", generation_ids
            )
            for row in validation_rows:
                id_map[row["id"]] = self._new_id(row["id"])

            document_claim_ids = [row["id"] for row in direct_rows["document_claims"]]
            document_evidence_rows = self._indirect_rows(
                connection, "claim_evidence_links", "claim_id", document_claim_ids
            )
            project_claim_ids = [row["id"] for row in direct_rows["project_claims"]]
            project_evidence_rows = self._indirect_rows(
                connection, "project_claim_evidence_links", "claim_id", project_claim_ids
            )
            decision_ids = [row["id"] for row in direct_rows["project_decisions"]]
            decision_claim_rows = self._indirect_rows(
                connection, "decision_claim_links", "decision_id", decision_ids
            )
            snapshot_ids = [row["id"] for row in direct_rows["project_snapshots"]]
            snapshot_claim_rows = self._indirect_rows(
                connection, "snapshot_claim_links", "snapshot_id", snapshot_ids
            )
            snapshot_decision_rows = self._indirect_rows(
                connection, "snapshot_decision_links", "snapshot_id", snapshot_ids
            )

            artifact_ids = list(id_map)
            artifact_dependency_rows = self._indirect_rows(
                connection, "artifact_dependencies", "artifact_id", artifact_ids
            )
            artifact_health_rows = self._indirect_rows(
                connection, "artifact_health", "artifact_id", artifact_ids
            )

            self._insert(
                connection,
                "projects",
                parent,
                id=child_id,
                title=f"{parent['title']}{title_suffix}",
                status="active",
                current_snapshot_id=None,
                created_at=now,
                updated_at=now,
            )
            for table in ("project_canvas", "project_canvas_versions"):
                for row in self._rows(connection, table, "project_id=?", (example_id,)):
                    self._insert(connection, table, row, project_id=child_id)

            for row in direct_rows["sources"]:
                metadata = self._rewrite_json(row["metadata_json"], id_map)
                self._insert(
                    connection, "sources", row, id=id_map[row["id"]],
                    project_id=child_id, metadata_json=metadata,
                )
            for row in direct_rows["source_chunks"]:
                self._insert(
                    connection, "source_chunks", row, id=id_map[row["id"]],
                    source_id=id_map[row["source_id"]], project_id=child_id,
                )

            for row in direct_rows["retrieval_runs"]:
                self._insert(
                    connection, "retrieval_runs", row,
                    id=id_map[row["id"]], project_id=child_id,
                    source_types_json=self._rewrite_json(row["source_types_json"], id_map),
                )
            for row in self._rows(connection, "retrieval_hits", "project_id=?", (example_id,)):
                self._insert(
                    connection, "retrieval_hits", row,
                    run_id=id_map[row["run_id"]], chunk_id=id_map[row["chunk_id"]],
                    source_id=id_map[row["source_id"]], project_id=child_id,
                )

            for row in direct_rows["idea_briefs"]:
                self._insert(
                    connection, "idea_briefs", row, id=id_map[row["id"]],
                    project_id=child_id,
                    supersedes_id=id_map.get(row["supersedes_id"]),
                    known_resources_json=self._rewrite_json(row["known_resources_json"], id_map),
                    constraints_json=self._rewrite_json(row["constraints_json"], id_map),
                    unknowns_json=self._rewrite_json(row["unknowns_json"], id_map),
                    provenance_json=self._rewrite_json(row["provenance_json"], id_map),
                )
            for row in direct_rows["solution_runs"]:
                self._insert(
                    connection, "solution_runs", row, id=id_map[row["id"]],
                    project_id=child_id, idea_brief_id=id_map[row["idea_brief_id"]],
                )
            for row in direct_rows["solution_candidates"]:
                rewritten = {
                    column: self._rewrite_json(value, id_map)
                    for column, value in row.items()
                    if column.endswith("_json")
                }
                self._insert(
                    connection, "solution_candidates", row, **rewritten,
                    id=id_map[row["id"]], run_id=id_map[row["run_id"]], project_id=child_id,
                )

            for row in direct_rows["project_decisions"]:
                self._insert(
                    connection, "project_decisions", row, id=id_map[row["id"]],
                    project_id=child_id,
                    options_json=self._rewrite_json(row["options_json"], id_map),
                    selected_option_id=id_map.get(row["selected_option_id"], row["selected_option_id"]),
                    decision_payload_json=self._rewrite_json(row["decision_payload_json"], id_map),
                    supersedes_decision_id=id_map.get(row["supersedes_decision_id"]),
                )
            for row in direct_rows["project_claims"]:
                self._insert(
                    connection, "project_claims", row, id=id_map[row["id"]],
                    project_id=child_id,
                    supersedes_claim_id=id_map.get(row["supersedes_claim_id"]),
                )
            for row in project_evidence_rows:
                self._insert(
                    connection, "project_claim_evidence_links", row,
                    claim_id=id_map[row["claim_id"]], source_id=id_map[row["source_id"]],
                    chunk_id=id_map[row["chunk_id"]],
                    retrieval_run_id=id_map.get(row["retrieval_run_id"]),
                )
            for row in decision_claim_rows:
                self._insert(
                    connection, "decision_claim_links", row,
                    decision_id=id_map[row["decision_id"]], claim_id=id_map[row["claim_id"]],
                )

            for row in direct_rows["project_snapshots"]:
                rewritten = dict(row)
                for column in tuple(rewritten):
                    if column.endswith("_json"):
                        rewritten[column] = self._rewrite_json(rewritten[column], id_map)
                rewritten.update(
                    id=id_map[row["id"]], project_id=child_id,
                    idea_brief_id=id_map[row["idea_brief_id"]],
                    decision_id=id_map[row["decision_id"]],
                    supersedes_snapshot_id=id_map.get(row["supersedes_snapshot_id"]),
                )
                rewritten["content_sha256"] = self._snapshot_hash(rewritten)
                self._insert(connection, "project_snapshots", rewritten)
            for row in snapshot_claim_rows:
                self._insert(
                    connection, "snapshot_claim_links", row,
                    snapshot_id=id_map[row["snapshot_id"]], claim_id=id_map[row["claim_id"]],
                )
            for row in snapshot_decision_rows:
                self._insert(
                    connection, "snapshot_decision_links", row,
                    snapshot_id=id_map[row["snapshot_id"]], decision_id=id_map[row["decision_id"]],
                )

            for row in direct_rows["documents"]:
                self._insert(
                    connection, "documents", row, id=id_map[row["id"]], project_id=child_id
                )
            for row in direct_rows["document_versions"]:
                self._insert(
                    connection, "document_versions", row, id=id_map[row["id"]],
                    document_id=id_map[row["document_id"]], project_id=child_id,
                    content=self._replace_ids(row["content"], id_map),
                    citations_json=self._rewrite_json(row["citations_json"], id_map),
                    idempotency_key=f"example-copy:{child_id}:{uuid.uuid4().hex}",
                )
            for row in direct_rows["generation_runs"]:
                self._insert(
                    connection, "generation_runs", row, id=id_map[row["id"]],
                    project_id=child_id,
                    version_id=id_map.get(row["version_id"]),
                    retrieval_run_ids_json=self._rewrite_json(
                        row["retrieval_run_ids_json"], id_map
                    ),
                )
            for row in validation_rows:
                self._insert(
                    connection, "validation_issues", row, id=id_map[row["id"]],
                    generation_run_id=id_map[row["generation_run_id"]],
                    version_id=id_map.get(row["version_id"]),
                )
            for row in direct_rows["document_claims"]:
                self._insert(
                    connection, "document_claims", row, id=id_map[row["id"]],
                    version_id=id_map[row["version_id"]], project_id=child_id,
                    metadata_json=self._rewrite_json(row["metadata_json"], id_map),
                )
            for row in document_evidence_rows:
                self._insert(
                    connection, "claim_evidence_links", row,
                    claim_id=id_map[row["claim_id"]], source_id=id_map[row["source_id"]],
                    chunk_id=id_map[row["chunk_id"]],
                    retrieval_run_id=id_map.get(row["retrieval_run_id"]),
                )

            for row in direct_rows["guided_sessions"]:
                self._insert(
                    connection, "guided_sessions", row, id=id_map[row["id"]],
                    project_id=child_id,
                    state_json=self._rewrite_json(row["state_json"], id_map),
                )
            for row in direct_rows["guided_messages"]:
                self._insert(
                    connection, "guided_messages", row, id=id_map[row["id"]],
                    session_id=id_map[row["session_id"]], project_id=child_id,
                    metadata_json=self._rewrite_json(row["metadata_json"], id_map),
                )
            for row in direct_rows["change_proposals"]:
                rewritten_json = {
                    column: self._rewrite_json(row[column], id_map)
                    for column in (
                        "affected_claims_json", "affected_decisions_json", "suggested_changes_json"
                    )
                }
                self._insert(
                    connection, "change_proposals", row, **rewritten_json,
                    id=id_map[row["id"]], project_id=child_id,
                    trigger_source_id=id_map.get(row["trigger_source_id"]),
                    from_snapshot_id=id_map[row["from_snapshot_id"]],
                )

            model_override = connection.execute(
                "SELECT * FROM project_model_profiles WHERE project_id=?", (example_id,)
            ).fetchone()
            if model_override is not None:
                self._insert(
                    connection, "project_model_profiles", dict(model_override),
                    project_id=child_id, created_at=now, updated_at=now,
                )

            for row in artifact_dependency_rows:
                self._insert(
                    connection, "artifact_dependencies", row,
                    artifact_id=id_map[row["artifact_id"]],
                    dependency_id=id_map.get(row["dependency_id"], row["dependency_id"]),
                )
            for row in artifact_health_rows:
                self._insert(
                    connection, "artifact_health", row,
                    artifact_id=id_map[row["artifact_id"]],
                    trigger_source_id=id_map.get(row["trigger_source_id"]),
                )

            current_snapshot_id = id_map.get(parent["current_snapshot_id"])
            connection.execute(
                "UPDATE projects SET current_snapshot_id=? WHERE id=?",
                (current_snapshot_id, child_id),
            )
            connection.execute(
                """INSERT INTO project_relations(
                       parent_project_id,child_project_id,relation_type,created_at
                   ) VALUES (?,?,?,?)""",
                (example_id, child_id, relation_type, now),
            )
            self.db.insert_audit_tx(
                connection,
                actor=clean_actor,
                action="canonical_example_copied" if relation_type == "example_copy" else "project_copied",
                entity_type="project",
                entity_id=child_id,
                payload={
                    "parent_project_id": example_id,
                    "relation_type": relation_type,
                },
            )

        return {
            "id": child_id,
            "title": f"{parent['title']}{title_suffix}",
            "summary": parent["summary"],
            "status": "active",
            "current_snapshot_id": id_map.get(parent["current_snapshot_id"]),
            "created_at": now,
            "updated_at": now,
            "parent_project_id": example_id,
            "relation_type": relation_type,
        }

    def copy_project(self, project_id: str, actor: str) -> dict[str, Any]:
        return self.copy(
            project_id,
            actor,
            source_status="active",
            relation_type="project_copy",
            title_suffix="（副本）",
        )

    @staticmethod
    def _indirect_rows(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        ids: list[str],
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM {table} WHERE {column} IN ({placeholders}) ORDER BY rowid",  # fixed internal tables
                tuple(ids),
            ).fetchall()
        ]
