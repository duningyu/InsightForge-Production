from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

SourceType = Literal[
    "real_user_research",
    "simulated_research",
    "public_source",
    "user_input",
    "model_hypothesis",
    "implementation_evidence",
]
DocType = Literal["prd", "techdoc"]

SourceOriginKind = Literal[
    "real_interview",
    "official_page",
    "public_report",
    "owner_input",
    "simulation",
    "model_output",
    "implementation",
    "unknown",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompetitorCandidateCreateRequest(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    url: str = Field(default="", max_length=2000)
    description: str = Field(default="", max_length=3000)

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请输入产品名称")
        return value.strip()

    @field_validator("url")
    @classmethod
    def safe_reference_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        value = value.strip()
        if not value:
            return value
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(char.isspace() for char in value)):
            raise ValueError("请填写不含账号密码的 HTTP 或 HTTPS 网址")
        return value


class CompetitorSelectionRequest(StrictModel):
    selected: bool = Field(strict=True)


class ProjectCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=3000)


class CanonicalExampleResponse(StrictModel):
    id: str
    title: str
    summary: str
    status: Literal["example"]
    current_snapshot_id: str | None
    created_at: str
    updated_at: str


class ExampleCopyResponse(StrictModel):
    id: str
    title: str
    summary: str
    status: Literal["active"]
    current_snapshot_id: str | None
    created_at: str
    updated_at: str
    parent_project_id: str
    relation_type: Literal["example_copy"]


class ModelProfileCreateRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    display_name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    protocol: Literal["openai_chat_completions", "anthropic_messages"] | None = None
    base_url: str | None = Field(default=None, max_length=2000)
    model_id: str = Field(min_length=1, max_length=240)
    api_key: SecretStr | None = None
    enabled: bool = True
    is_default: bool = False

    @field_validator("display_name", "model_id")
    @classmethod
    def reject_blank_identity_fields(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace characters")
        return value


class ModelProfileUpdateRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=160)
    provider: str | None = Field(default=None, min_length=1, max_length=80)
    protocol: Literal["openai_chat_completions", "anthropic_messages"] | None = None
    base_url: str | None = Field(default=None, max_length=2000)
    model_id: str | None = Field(default=None, min_length=1, max_length=240)
    api_key: SecretStr | None = None
    enabled: bool | None = None

    @field_validator("display_name", "model_id")
    @classmethod
    def reject_blank_identity_fields(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("value must contain non-whitespace characters")
        return value

    @model_validator(mode="after")
    def reject_null_required_configuration(self) -> "ModelProfileUpdateRequest":
        for field_name in ("display_name", "provider", "model_id", "enabled"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        return self


class ProjectModelProfileRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    profile_id: str | None = Field(default=None, min_length=1, max_length=200)


class ModelProfileResponse(StrictModel):
    id: str
    display_name: str
    provider: str
    protocol: str
    base_url: str
    model_id: str
    credential_status: Literal["configured", "missing"]
    enabled: bool
    is_default: bool
    capabilities: dict[
        str, Literal["supported", "unsupported", "unknown"]
    ] = Field(default_factory=dict)
    capabilities_checked_at: str | None = None
    last_test_status: str | None = None
    last_tested_at: str | None = None
    last_live_test_status: Literal["passed", "failed"] | None = None
    last_live_tested_at: str | None = None
    last_live_latency_ms: int | None = None
    last_live_error_code: str | None = None
    last_live_model_returned: str | None = None
    revision: int
    created_at: str
    updated_at: str


class LiveProviderTestRequest(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirm_live_call: Literal[True]


class LiveProviderTestResponse(StrictModel):
    profile_id: str
    provider: str
    status: Literal["PASS", "FAIL"]
    model_requested: str
    model_returned: str | None = None
    latency_ms: int = Field(ge=0)
    content_received: bool
    usage_available: bool
    error_code: str | None = None
    safe_message: str
    retryable: bool
    checked_at: str
    secret_exposed: Literal[False] = False
    safe_diagnostic: dict[str, Any] | None = None


class ProjectModelProfileResponse(StrictModel):
    project_id: str
    profile_id: str | None


class CanvasUpdateRequest(StrictModel):
    problem: str = Field(min_length=1, max_length=4000)
    target_users: str = Field(min_length=1, max_length=3000)
    goals: list[str] = Field(min_length=1, max_length=20)
    non_goals: list[str] = Field(default_factory=list, max_length=20)
    success_metrics: list[str] = Field(min_length=1, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)


class SourceCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    authority: float = Field(ge=0, le=1)
    content: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(default="source.txt", min_length=1, max_length=240)


class GuidedSourceCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    origin_kind: SourceOriginKind
    content: str = Field(min_length=1, max_length=2_000_000)
    filename: str = Field(default="source.txt", min_length=1, max_length=240)
    source_url: str | None = Field(default=None, max_length=2000)
    publisher: str | None = Field(default=None, max_length=240)
    published_at: str | None = Field(default=None, max_length=40)


class GuidedRespondRequest(StrictModel):
    answer: str = Field(default="", max_length=6000)
    choice_id: str | None = Field(default=None, max_length=120)


class RetrievalRequest(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    profile_id: str = Field(default="balanced_traceable_v1", min_length=1, max_length=80)
    top_k: int | None = Field(default=None, ge=1, le=30)
    source_types: list[SourceType] | None = None


class HandoffExportRequest(StrictModel):
    target_client: Literal["codex", "claude_code", "cursor", "generic"] = "codex"


class GenerateRequest(StrictModel):
    doc_type: DocType
    idempotency_key: str | None = Field(default=None, max_length=200)


class ApprovalRequest(StrictModel):
    actor: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
    human_confirmed: bool = False


class WalkthroughAdvanceRequest(StrictModel):
    step: Literal["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"]


class DocumentDraftSaveRequest(StrictModel):
    base_version_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)


class DocumentDraftCommitRequest(StrictModel):
    actor: str = Field(default="web_user", min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
    expected_base_version_id: str | None = Field(default=None, min_length=1, max_length=200)


class DocumentRestoreAsNewRequest(StrictModel):
    actor: str = Field(default="web_user", min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)


QuickStartPriority = Literal["fast_mvp", "best_effect", "lowest_cost", "portfolio"]
RuntimeMode = Literal["llm_structured", "deterministic_demo", "managed_qwen"]
HypothesisProvenance = Literal["model_hypothesis", "user_input"]


class QuickStartRequest(StrictModel):
    idea: str = Field(min_length=1, max_length=4000)
    target_user: str | None = Field(default=None, max_length=1000)
    resources: list[str] = Field(default_factory=list, max_length=30)
    priority: QuickStartPriority = "fast_mvp"


class IdeaBriefRefineRequest(StrictModel):
    target_user: str | None = Field(default=None, max_length=1000)
    problem: str | None = Field(default=None, max_length=3000)
    desired_outcome: str | None = Field(default=None, max_length=3000)
    known_resources: list[str] | None = Field(default=None, max_length=30)
    constraints: list[str] | None = Field(default=None, max_length=30)
    unknowns: list[str] | None = Field(default=None, max_length=30)
    clarification_answer: str | None = Field(default=None, max_length=3000)


class HumanConfirmRequest(StrictModel):
    human_confirmed: bool = False
    note: str = Field(default="", max_length=1000)


class SolutionSelectRequest(StrictModel):
    strategy: Literal["single", "staged"]
    candidate_ids: list[str] = Field(min_length=1, max_length=3)
    rationale: str = Field(min_length=1, max_length=4000)
    human_confirmed: bool = False

    @model_validator(mode="after")
    def validate_cardinality(self) -> "SolutionSelectRequest":
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate_ids must be unique")
        if self.strategy == "single" and len(self.candidate_ids) != 1:
            raise ValueError("single strategy requires exactly one candidate_id")
        if self.strategy == "staged" and len(self.candidate_ids) < 2:
            raise ValueError("staged strategy requires at least two ordered candidate_ids")
        return self


class IdeaBriefDraft(StrictModel):
    original_idea: str
    target_user: str
    problem: str
    desired_outcome: str
    known_resources: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    provenance: dict[str, HypothesisProvenance]
    clarification_required: bool = False
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_clarification(self) -> "IdeaBriefDraft":
        if self.clarification_required and not (self.clarification_question or "").strip():
            raise ValueError("clarification_question is required when clarification_required=true")
        return self


class SolutionCandidateDraft(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    mechanism: Literal[
        "rule_based", "workflow_based", "prediction_based", "recommendation_based",
        "optimization", "search_retrieval", "automation", "human_in_the_loop",
        "assistant", "marketplace", "other",
    ]
    summary: str = Field(min_length=1, max_length=3000)
    why_fit: str = Field(min_length=1, max_length=3000)
    user_flow: list[str] = Field(min_length=1, max_length=30)
    mvp_pages: list[str] = Field(min_length=1, max_length=20)
    features: list[str] = Field(min_length=1, max_length=30)
    inputs: list[str] = Field(min_length=1, max_length=30)
    outputs: list[str] = Field(min_length=1, max_length=30)
    decision_logic: list[str] = Field(min_length=1, max_length=30)
    data_requirements: list[str] = Field(min_length=1, max_length=30)
    technical_components: list[str] = Field(min_length=1, max_length=30)
    implementation_plan: list[str] = Field(min_length=1, max_length=30)
    acceptance_cases: list[str] = Field(min_length=1, max_length=30)
    risks: list[str] = Field(min_length=1, max_length=30)
    unknowns: list[str] = Field(min_length=1, max_length=30)
    complexity: Literal["low", "medium", "high"]
    provenance: HypothesisProvenance
    required_data_class: str = Field(min_length=1, max_length=240)
    automation_level: Literal["low", "medium", "high"]
    human_role: str = Field(min_length=1, max_length=500)
    core_decision_logic: str = Field(min_length=1, max_length=1000)
    major_dependency: str = Field(min_length=1, max_length=1000)
    requires_llm_runtime: bool = False
    requires_rag_runtime: bool = False
    requires_agent_runtime: bool = False


class SolutionSetDraft(StrictModel):
    candidates: list[SolutionCandidateDraft] = Field(min_length=2, max_length=3)
    recommendation_candidate_id: str | None = None
    recommendation_rationale: str = ""
    llm_core_required: bool = False


class EvidenceAnalyzeRequest(StrictModel):
    claim_ids: list[str] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_claim_ids(self) -> "EvidenceAnalyzeRequest":
        if self.claim_ids is not None:
            if not self.claim_ids:
                raise ValueError("claim_ids must be omitted or non-empty")
            if len(set(self.claim_ids)) != len(self.claim_ids):
                raise ValueError("claim_ids must be unique")
        return self


class EvidenceRelationDraft(StrictModel):
    source_id: str = Field(min_length=1, max_length=200)
    chunk_id: str = Field(min_length=1, max_length=200)
    relation: Literal["supports", "contradicts", "contextualizes"]
    directness: Literal["direct", "indirect"]
    scope_fit: Literal["fit", "limited"]
    recency_state: Literal["current", "unknown", "stale"]
    evidence_span: str = Field(min_length=1, max_length=12000)
    reason: str = Field(default="", max_length=4000)


class EvidenceRelationSetDraft(StrictModel):
    relations: list[EvidenceRelationDraft] = Field(default_factory=list, max_length=30)


class BetaConsentRequest(StrictModel):
    accepted: Literal[True]
    consent_version: int = Field(ge=1)


class BetaEventRequest(StrictModel):
    event_name: str = Field(min_length=1, max_length=80)
    project_id: str | None = Field(default=None, min_length=1, max_length=200)
    properties: dict[str, Any] = Field(default_factory=dict)


class BetaFeedbackRequest(StrictModel):
    project_id: str | None = Field(default=None, min_length=1, max_length=200)
    project_stage: Literal[
        "idea", "solutions", "snapshot", "evidence", "documents", "handoff",
        "history", "walkthrough", "other",
    ]
    rating: int = Field(ge=1, le=5)
    feedback_type: Literal[
        "confusing", "helpful", "missing", "incorrect", "bug", "other",
    ]
    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("comment must not be blank")
        if len(normalized) > 2000:
            raise ValueError("comment must not exceed 2000 characters")
        return normalized
