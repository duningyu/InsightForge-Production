from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Callable, Literal

from app.db import Database, utc_now
from app.services.generation import LocalDocumentGenerator
from app.services.claims import ClaimService
from app.services.handoff import HandoffService
from app.services.document_versions import DocumentVersionService
from app.services.loop import DocumentLoop
from app.services.projects import ProjectService
from app.services.retrieval_service import ProjectRetrievalService
from app.services.validation import DocumentValidator
from app.services.ai_runtime import build_structured_runtime
from app.services.artifact_health import ArtifactHealthService
from app.services.canvas_projection import CanvasProjectionService
from app.services.change_proposals import ChangeProposalService
from app.services.decisions import DecisionService
from app.services.project_claims import ProjectClaimService
from app.services.snapshots import SnapshotService
from app.services.solution_design import SolutionDesignService
from app.services.hybrid_runtime import HybridStructuredRuntime
from app.services.model_profiles import ModelProfileService


ToolPermissionClass = Literal[
    "local_read", "network_read", "local_write", "delete", "export"
]
_PERMISSION_CLASSES = {"local_read", "network_read", "local_write", "delete", "export"}


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    risk_level: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], str], Any]
    permission_class: ToolPermissionClass | None = None

    def __post_init__(self) -> None:
        if self.risk_level not in {"L0", "L1", "L2"}:
            raise ValueError("risk_level must be L0, L1, or L2")
        permission_class = self.permission_class
        if permission_class is None:
            permission_class = "local_read" if self.risk_level == "L0" else "local_write"
            if self.name == "export_artifact":
                permission_class = "export"
            object.__setattr__(self, "permission_class", permission_class)
        if permission_class not in _PERMISSION_CLASSES:
            raise ValueError("unknown tool permission class")

    def as_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
                "strict": True,
                "x-risk-level": self.risk_level,
                "x-permission-class": self.permission_class,
            },
        }


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "null":
        return value is None
    if expected == "object":
        return isinstance(value, dict)
    return True


def _validate_json_type(name: str, value: Any, schema: dict[str, Any]) -> None:
    expected = schema.get("type")
    expected_types = expected if isinstance(expected, list) else [expected]
    if expected and not any(_matches_type(value, item) for item in expected_types):
        raise ValueError(f"argument {name} has an invalid type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"argument {name} must be one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"argument {name} is too short")
        if len(value) > schema.get("maxLength", 10**9):
            raise ValueError(f"argument {name} is too long")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"argument {name} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"argument {name} is above maximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"argument {name} has too few items")
        if len(value) > schema.get("maxItems", 10**9):
            raise ValueError(f"argument {name} has too many items")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_json_type(f"{name}[{index}]", item, item_schema)


class ToolRegistry:
    """Application-owned Function Calling registry with explicit risk gates."""

    def __init__(
        self,
        db: Database,
        *,
        generator: LocalDocumentGenerator | None = None,
        max_loop_rounds: int = 2,
        structured_runtime: Any | None = None,
    ):
        self.db = db
        self.projects = ProjectService(db)
        self.retrieval = ProjectRetrievalService(db)
        self.claims = ClaimService(db)
        self.handoff = HandoffService(db)
        self.document_versions = DocumentVersionService(db)
        self.loop = DocumentLoop(db, generator=generator, max_rounds=max_loop_rounds)
        self.validator = DocumentValidator()
        self.structured_runtime = structured_runtime or HybridStructuredRuntime(
            ModelProfileService(db),
            local_runtime=build_structured_runtime(mode="deterministic_demo"),
        )
        self.project_claims = ProjectClaimService(db=db, retrieval=self.retrieval, runtime=self.structured_runtime)
        self.artifact_health = ArtifactHealthService(db)
        self.snapshots = SnapshotService(
            db, self.projects, DecisionService(), self.project_claims, CanvasProjectionService(), self.artifact_health
        )
        self.change_proposals = ChangeProposalService(db, self.snapshots)
        self.solution_design = SolutionDesignService(db, self.structured_runtime)
        string_id = {"type": "string", "minLength": 1, "maxLength": 200}
        source_enum = [
            "real_user_research",
            "simulated_research",
            "public_source",
            "user_input",
            "model_hypothesis",
            "implementation_evidence",
        ]
        self._tools: dict[str, ToolSpec] = {}
        self._register(
            ToolSpec(
                "retrieve_project_sources",
                "Retrieve evidence only within one project and preserve source labels.",
                "L0",
                _object_schema(
                    {
                        "project_id": string_id,
                        "query": {"type": "string", "minLength": 1, "maxLength": 2000},
                        "top_k": {"type": "integer", "minimum": 1, "maximum": 30},
                        "profile_id": {"type": "string", "minLength": 1, "maxLength": 80},
                        "source_types": {
                            "type": "array",
                            "items": {"type": "string", "enum": source_enum},
                            "maxItems": 6,
                        },
                    },
                    ["project_id", "query", "top_k", "source_types"],
                ),
                self._retrieve_project_sources,
            )
        )
        self._register(
            ToolSpec(
                "get_project_canvas",
                "Read the current canvas for one project.",
                "L0",
                _object_schema({"project_id": string_id}, ["project_id"]),
                self._get_project_canvas,
            )
        )
        self._register(
            ToolSpec(
                "get_document_version",
                "Read one immutable document version.",
                "L0",
                _object_schema({"version_id": string_id}, ["version_id"]),
                self._get_document_version,
            )
        )
        self._register(
            ToolSpec(
                "get_document_claims",
                "Read the structured claim/evidence ledger for one document version.",
                "L0",
                _object_schema({"version_id": string_id}, ["version_id"]),
                self._get_document_claims,
            )
        )
        self._register(
            ToolSpec(
                "get_handoff_readiness",
                "Read fail-closed AI coding handoff readiness for one project.",
                "L0",
                _object_schema({"project_id": string_id}, ["project_id"]),
                self._get_handoff_readiness,
            )
        )
        self._register(
            ToolSpec(
                "prepare_handoff_manifest",
                "Prepare a non-binary handoff manifest preview; this does not export, approve, or publish.",
                "L1",
                _object_schema(
                    {
                        "project_id": string_id,
                        "target_client": {
                            "type": "string",
                            "enum": ["codex", "claude_code", "cursor", "generic"],
                        },
                    },
                    ["project_id", "target_client"],
                ),
                self._prepare_handoff_manifest,
            )
        )
        self._register(
            ToolSpec(
                "create_document_draft",
                "Create a cited PRD or TechDoc draft through the bounded quality loop.",
                "L1",
                _object_schema(
                    {
                        "project_id": string_id,
                        "doc_type": {"type": "string", "enum": ["prd", "techdoc"]},
                        "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 200},
                    },
                    ["project_id", "doc_type", "idempotency_key"],
                ),
                self._create_document_draft,
            )
        )
        self._register(
            ToolSpec(
                "run_document_validator",
                "Re-run deterministic citation and claim-boundary validation.",
                "L1",
                _object_schema({"version_id": string_id}, ["version_id"]),
                self._run_document_validator,
            )
        )
        self._register(
            ToolSpec(
                "export_artifact",
                "Export one version as Markdown, JSON, or base64-encoded DOCX.",
                "L1",
                _object_schema(
                    {
                        "version_id": string_id,
                        "format": {"type": "string", "enum": ["md", "json", "docx"]},
                    },
                    ["version_id", "format"],
                ),
                self._export_artifact,
            )
        )
        self._register(
            ToolSpec(
                "approve_document_version",
                "Approve one validated version. The host must explicitly confirm a human action.",
                "L2",
                _object_schema(
                    {
                        "version_id": string_id,
                        "note": {"type": "string", "minLength": 0, "maxLength": 1000},
                    },
                    ["version_id", "note"],
                ),
                self._approve_document_version,
            )
        )
        # InsightForge 3.0 task-oriented surface. Legacy tools above remain readable
        # until legacy migration is completed; destructive/publish operations stay absent.
        self._register(ToolSpec("get_current_snapshot", "Read the current confirmed Project Snapshot.", "L0", _object_schema({"project_id": string_id}, ["project_id"]), self._get_current_snapshot))
        self._register(ToolSpec("get_project_claims", "Read active project-level claims and evidence state.", "L0", _object_schema({"project_id": string_id}, ["project_id"]), self._get_project_claims_v3))
        self._register(ToolSpec("retrieve_project_evidence", "Retrieve evidence inside one project for a product judgment.", "L0", _object_schema({"project_id": string_id, "query": {"type":"string","minLength":1,"maxLength":2000}, "top_k": {"type":"integer","minimum":1,"maximum":30}}, ["project_id","query","top_k"]), self._retrieve_project_evidence))
        self._register(ToolSpec("get_solution_candidates", "Read the latest domain-specific candidate solutions.", "L0", _object_schema({"project_id": string_id}, ["project_id"]), self._get_solution_candidates))
        self._register(ToolSpec("create_solution_proposal", "Generate a bounded set of solution candidates; this does not confirm a decision.", "L1", _object_schema({"project_id": string_id}, ["project_id"]), self._create_solution_proposal))
        self._register(ToolSpec("create_evidence_relation_proposal", "Validate an evidence relation proposal without persisting it as formal evidence.", "L1", _object_schema({
            "project_id": string_id, "claim_id": string_id, "source_id": string_id, "chunk_id": string_id,
            "relation": {"type":"string","enum":["supports","contradicts","contextualizes"]},
            "directness": {"type":"string","enum":["direct","indirect"]}, "scope_fit": {"type":"string","enum":["fit","limited"]},
            "recency_state": {"type":"string","enum":["current","unknown","stale"]}, "evidence_span": {"type":"string","minLength":1,"maxLength":8000},
            "reason": {"type":"string","minLength":1,"maxLength":3000}
        }, ["project_id","claim_id","source_id","chunk_id","relation","directness","scope_fit","recency_state","evidence_span","reason"]), self._create_evidence_relation_proposal))
        self._register(ToolSpec("create_change_proposal", "Create a user-reviewable change proposal against the current Snapshot.", "L1", _object_schema({
            "project_id": string_id, "summary": {"type":"string","minLength":1,"maxLength":1000}, "reason": {"type":"string","minLength":1,"maxLength":3000}
        }, ["project_id","summary","reason"]), self._create_change_proposal))
        self._register(ToolSpec("confirm_solution_decision", "Confirm a previously generated solution choice; host human confirmation is mandatory.", "L2", _object_schema({
            "project_id": string_id, "strategy": {"type":"string","enum":["single","staged"]}, "candidate_ids": {"type":"array","items":string_id,"minItems":1,"maxItems":3}, "rationale": {"type":"string","minLength":1,"maxLength":4000}
        }, ["project_id","strategy","candidate_ids","rationale"]), self._confirm_solution_decision))
        self._register(ToolSpec("accept_change_proposal", "Accept an open Change Proposal; host human confirmation is mandatory.", "L2", _object_schema({"proposal_id": string_id, "note": {"type":"string","minLength":0,"maxLength":1000}}, ["proposal_id","note"]), self._accept_change_proposal))
        self._register(ToolSpec("confirm_document_version", "Confirm one validated healthy document version; host human confirmation is mandatory.", "L2", _object_schema({"version_id": string_id, "note": {"type":"string","minLength":0,"maxLength":1000}}, ["version_id","note"]), self._confirm_document_version))

    def _register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        return [self._tools[name].as_openai_schema() for name in sorted(self._tools)]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        actor: str,
        human_confirmed: bool = False,
    ) -> Any:
        if not actor.strip():
            raise ValueError("actor is required")
        spec = self._tools.get(name)
        if spec is None:
            raise KeyError(f"tool not registered: {name}")
        self._validate_arguments(spec, arguments)
        requires_confirmation = spec.permission_class != "local_read"
        if requires_confirmation and human_confirmed is not True:
            raise PermissionError(f"tool {name} requires explicit human confirmation")
        result = spec.handler(dict(arguments), actor)
        self.db.insert_audit(
            actor=actor,
            action="tool_executed",
            entity_type="tool",
            entity_id=name,
            payload={
                "risk_level": spec.risk_level,
                "permission_class": spec.permission_class,
                "arguments": arguments,
            },
        )
        return result

    @staticmethod
    def _validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        properties = spec.parameters["properties"]
        required = set(spec.parameters.get("required", []))
        missing = sorted(required - arguments.keys())
        unknown = sorted(arguments.keys() - properties.keys())
        if missing:
            raise ValueError(f"missing required arguments: {missing}")
        if unknown:
            raise ValueError(f"unknown arguments: {unknown}")
        for key, value in arguments.items():
            _validate_json_type(key, value, properties[key])

    def _retrieve_project_sources(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        source_types = args["source_types"] or None
        return self.retrieval.execute_retrieval(
            args["project_id"],
            args["query"],
            profile_id=args.get("profile_id") or "balanced_traceable_v1",
            top_k=args["top_k"],
            source_types=source_types,
            purpose="tool_retrieval",
            actor=actor,
        )

    def _get_project_canvas(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.projects.get_canvas(args["project_id"])

    def _get_document_version(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        row = self.db.fetch_one(
            "SELECT * FROM document_versions WHERE id = ? AND lifecycle_status = 'active'", (args["version_id"],)
        )
        if row is None:
            raise KeyError("document version not found")
        row["citations"] = json.loads(row.pop("citations_json"))
        row["artifact_health"] = self.db.fetch_one(
            "SELECT * FROM artifact_health WHERE artifact_type='document_version' AND artifact_id=?",
            (row["id"],),
        )
        row["dependencies"] = self.db.fetch_all(
            """
            SELECT dependency_type, dependency_id, dependency_version, created_at
            FROM artifact_dependencies
            WHERE artifact_type='document_version' AND artifact_id=?
            ORDER BY dependency_type, dependency_id
            """,
            (row["id"],),
        )
        return row

    def _get_document_claims(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.claims.list_for_version(args["version_id"])

    def _get_handoff_readiness(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.handoff.readiness(args["project_id"])

    def _prepare_handoff_manifest(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.handoff.preview_manifest(
            args["project_id"], target_client=args["target_client"]
        )

    def _create_document_draft(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.loop.run(
            args["project_id"],
            args["doc_type"],
            idempotency_key=args["idempotency_key"],
        )

    def _run_document_validator(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        version = self._get_document_version(args, _actor)
        canvas = self.db.get_canvas(version["project_id"], int(version["canvas_version"]))
        if canvas is None:
            raise RuntimeError("document canvas snapshot is missing")
        claim_payload = self.claims.list_for_version(version["id"])
        issues = self.validator.validate(
            content=version["content"],
            valid_citations=self.retrieval.valid_citations(version["project_id"]),
            canvas=canvas,
            doc_type=version["doc_type"],
            claims=claim_payload["items"],
        )
        blocking_issues = [issue for issue in issues if issue.get("severity") != "warning"]
        validation_status = "passed" if not blocking_issues else "needs_human_review"
        with self.db.connect() as connection:
            connection.execute(
                "UPDATE document_versions SET validation_status = ? WHERE id = ?",
                (validation_status, version["id"]),
            )
            health_status = "needs_review"
            health_reason = "deterministic document validation found issues"
            if validation_status == "passed":
                project = connection.execute(
                    "SELECT current_snapshot_id FROM projects WHERE id=?",
                    (version["project_id"],),
                ).fetchone()
                dependencies = connection.execute(
                    """
                    SELECT dependency_type,dependency_id
                    FROM artifact_dependencies
                    WHERE artifact_type='document_version' AND artifact_id=?
                    """,
                    (version["id"],),
                ).fetchall()
                snapshot_dependencies = [row["dependency_id"] for row in dependencies if row["dependency_type"] == "project_snapshot"]
                source_dependencies = [row["dependency_id"] for row in dependencies if row["dependency_type"] == "source"]
                snapshot_current = not snapshot_dependencies or (project is not None and project["current_snapshot_id"] in snapshot_dependencies)
                sources_current = True
                if source_dependencies:
                    placeholders = ",".join("?" for _ in source_dependencies)
                    active = connection.execute(
                        f"SELECT COUNT(*) AS n FROM sources WHERE id IN ({placeholders}) AND status='active'",
                        tuple(source_dependencies),
                    ).fetchone()["n"]
                    sources_current = int(active) == len(set(source_dependencies))
                if snapshot_current and sources_current:
                    health_status = "current"
                    health_reason = "deterministic validation passed against current document dependencies"
                else:
                    health_status = "stale_evidence" if not sources_current else "needs_review"
                    health_reason = "document dependencies changed before validation completed"
            self.artifact_health.set_tx(
                connection,
                artifact_type="document_version",
                artifact_id=version["id"],
                health_status=health_status,
                reason=health_reason,
            )
        return {
            "version_id": version["id"],
            "validation_status": validation_status,
            "issues": issues,
        }

    def _export_artifact(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        from app.exporters import ArtifactExporter

        version = self._get_document_version({"version_id": args["version_id"]}, _actor)
        exporter = ArtifactExporter()
        export_format = args["format"]
        if export_format == "md":
            return {"format": "md", "content": exporter.to_markdown(version)}
        if export_format == "json":
            return {"format": "json", "content": exporter.to_json_text(version)}
        return {
            "format": "docx",
            "encoding": "base64",
            "content": base64.b64encode(exporter.to_docx_bytes(version)).decode("ascii"),
        }

    def _get_current_snapshot(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.snapshots.get_current(args["project_id"])

    def _get_project_claims_v3(self, args: dict[str, Any], _actor: str) -> list[dict[str, Any]]:
        return self.project_claims.list_claims(args["project_id"])

    def _retrieve_project_evidence(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.retrieval.execute_retrieval(
            args["project_id"], args["query"], profile_id="balanced_traceable_v1",
            top_k=args["top_k"], source_types=None, purpose="tool_project_evidence", actor=actor,
        )

    def _get_solution_candidates(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        return self.solution_design.list_candidates(args["project_id"])

    def _create_solution_proposal(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.solution_design.generate(args["project_id"], actor=actor)

    def _create_evidence_relation_proposal(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        proposal = dict(args)
        proposal.update({"retrieval_run_id": None, "analysis_version": "tool-proposal-v1"})
        return self.project_claims.validate_relation_proposal(**proposal)

    def _create_change_proposal(self, args: dict[str, Any], _actor: str) -> dict[str, Any]:
        project = self.db.fetch_one("SELECT current_snapshot_id FROM projects WHERE id=?", (args["project_id"],))
        if project is None:
            raise KeyError("project not found")
        if not project.get("current_snapshot_id"):
            raise ValueError("current Snapshot is required")
        return self.change_proposals.create(
            project_id=args["project_id"], from_snapshot_id=project["current_snapshot_id"],
            proposal_type="tool_suggested_change", summary=args["summary"], reason=args["reason"],
            affected_claim_ids=[], affected_decision_ids=[], suggested_changes={"snapshot_patch":{}}, trigger_source_id=None,
        )

    def _confirm_solution_decision(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.snapshots.confirm_initial_solution(
            args["project_id"], strategy=args["strategy"], candidate_ids=args["candidate_ids"],
            rationale=args["rationale"], human_confirmed=True, actor=actor,
        )

    def _accept_change_proposal(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.change_proposals.accept(
            args["proposal_id"], human_confirmed=True, note=args.get("note", ""), actor=actor
        )

    def _confirm_document_version(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.document_versions.confirm(
            args["version_id"], actor=actor, note=args.get("note", ""), human_confirmed=True
        )

    def _approve_document_version(self, args: dict[str, Any], actor: str) -> dict[str, Any]:
        return self.document_versions.confirm(
            args["version_id"], actor=actor, note=args.get("note", ""), human_confirmed=True
        )
