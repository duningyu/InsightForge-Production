from __future__ import annotations

from dataclasses import dataclass
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


class CompetitorComparisonRequest(StrictModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_unique_candidates(self) -> "CompetitorComparisonRequest":
        if len(set(self.candidate_ids)) != len(self.candidate_ids):
            raise ValueError("candidate_ids must be unique")
        return self


class CompetitorDecisionRequest(StrictModel):
    candidate_id: str
    decision: Literal["adopt", "avoid", "defer"]
    rationale: str = Field(default="", max_length=2000)
    reason: str | None = Field(default=None, max_length=2000)


class CompetitorSnapshotCreateRequest(StrictModel):
    comparison_id: str
    decisions: list[CompetitorDecisionRequest] = Field(default_factory=list, max_length=30)


class CompetitorComparisonItem(StrictModel):
    candidate_id: str
    name: str
    target_users: str = "暂未确认"
    core_problem: str = "暂未确认"
    main_flow: str = "暂未确认"
    main_output: str = "暂未确认"
    adoption_barrier: str = "暂未确认"
    strengths_to_learn: list[str] = Field(default_factory=list)
    things_not_to_copy: list[str] = Field(default_factory=list)
    impact_on_current_project: str = "暂未确认"
    uncertainties: list[str] = Field(default_factory=list)


class CompetitorProjectLevel(StrictModel):
    similarities: list[str] = Field(default_factory=list)
    differentiation_options: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    recommended_scope_implications: list[str] = Field(default_factory=list)


class CompetitorComparisonDraft(StrictModel):
    competitors: list[CompetitorComparisonItem]
    project_level: CompetitorProjectLevel
    uncertainty_notice: str = "AI分析参考，建议结合实际产品页面核对。"


class AIReferenceDraft(StrictModel):
    possible_target_users: list[str] = Field(default_factory=list, max_length=20)
    possible_scenarios: list[str] = Field(default_factory=list, max_length=20)
    possible_user_problems: list[str] = Field(default_factory=list, max_length=20)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    mvp_thoughts: list[str] = Field(default_factory=list, max_length=20)
    questions_to_validate: list[str] = Field(default_factory=list, max_length=20)
    research_directions: list[str] = Field(default_factory=list, max_length=20)
    uncertainty_notice: str = "AI生成参考，尚未经外部资料核实。"


class EvidenceActionCard(StrictModel):
    """A concrete, optional plan for collecting useful project material.

    This is guidance only.  It deliberately does not model a source, claim, or
    verification result so generating the cards cannot create evidence by
    accident.
    """

    title: str = Field(min_length=1, max_length=240)
    question_to_validate: str = Field(min_length=1, max_length=2000)
    why_it_matters: str = Field(min_length=1, max_length=2000)
    who_or_where: list[str] = Field(default_factory=list, max_length=10)
    action_steps: list[str] = Field(default_factory=list, max_length=10)
    suggested_questions: list[str] = Field(default_factory=list, max_length=10)
    acceptable_artifacts: list[str] = Field(default_factory=list, max_length=10)
    fill_template: list[str] = Field(default_factory=list, max_length=20)
    decision_impact: str = Field(min_length=1, max_length=2000)
    fallback_if_unavailable: str = Field(min_length=1, max_length=2000)
    limitations: str = Field(min_length=1, max_length=2000)


class EvidenceGuidanceDraft(StrictModel):
    cards: list[EvidenceActionCard] = Field(default_factory=list, max_length=5)
    disclosure: str = "AI建议你去补这些资料，尚未加入项目资料，也不代表已经核实。"


class EvidenceGuidanceGenerateRequest(StrictModel):
    idempotency_key: str | None = Field(default=None, max_length=200)


class AIReferenceGenerateRequest(StrictModel):
    idempotency_key: str | None = Field(default=None, max_length=200)


class AIReferenceDecisionRequest(StrictModel):
    category: str = Field(min_length=1, max_length=80)
    item: str = Field(min_length=1, max_length=1000)
    decision: Literal["adopt", "modify", "ignore"]
    rationale: str = Field(default="", max_length=2000)


class AIReferenceApplyRequest(StrictModel):
    reference_id: str = Field(min_length=1, max_length=200)
    decisions: list[AIReferenceDecisionRequest] = Field(default_factory=list, max_length=100)


class ProjectCreateRequest(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(min_length=1, max_length=3000)


Purpose = Literal["LEARNING", "PERSONAL_USE", "FOR_OTHERS", "UNSPECIFIED"]


class ProjectIntentUpsertRequest(StrictModel):
    purpose: Purpose
    raw_idea: str = Field(min_length=1, max_length=4000)
    expected_revision: int | None = Field(default=None, ge=0)

    @field_validator("raw_idea")
    @classmethod
    def reject_blank_or_placeholder_idea(cls, value: str) -> str:
        value = value.strip()
        if not value or value in {"待定", "暂未确认", "TODO", "TBD"}:
            raise ValueError("raw_idea must contain a substantive user idea")
        return value


class FirstActionUpdateRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    goal: str | None = Field(default=None, min_length=1, max_length=1000)
    why_now: str | None = Field(default=None, min_length=1, max_length=1000)
    inputs: list[str] | None = Field(default=None, max_length=20)
    steps: list[str] | None = Field(default=None, max_length=20)
    expected_artifact: str | None = Field(default=None, min_length=1, max_length=1000)
    checks: list[str] | None = Field(default=None, max_length=20)
    branches: list[str] | None = Field(default=None, max_length=20)
    stop_condition: str | None = Field(default=None, min_length=1, max_length=1000)
    prohibited_actions: list[str] | None = Field(default=None, max_length=20)


class FirstActionConfirmRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class BuildSliceUpsertRequest(StrictModel):
    expected_revision: int | None = Field(default=None, ge=1)
    expected_snapshot_id: str | None = Field(default=None, min_length=1, max_length=200)
    expected_intent_revision: int | None = Field(default=None, ge=1)
    slice_id: str | None = Field(default=None, min_length=1, max_length=200)
    confirmed_constraints: list[str] | None = Field(default=None, max_length=30)
    in_scope: list[str] | None = Field(default=None, max_length=30)
    out_of_scope: list[str] | None = Field(default=None, max_length=30)
    minimal_flow: list[str] | None = Field(default=None, max_length=30)
    acceptance_criteria: list[str] | None = Field(default=None, max_length=30)
    inputs: list[str] | None = Field(default=None, max_length=30)
    expected_outputs: list[str] | None = Field(default=None, max_length=30)
    error_handling: list[str] | None = Field(default=None, max_length=30)
    unknowns: list[str] | None = Field(default=None, max_length=30)
    constraint_notes: list[str] | None = Field(default=None, max_length=30)


class M2RevisionRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class PrototypeTaskUpsertRequest(StrictModel):
    task_id: str | None = Field(default=None, min_length=1, max_length=200)
    expected_revision: int | None = Field(default=None, ge=1)
    slice_id: str | None = Field(default=None, min_length=1, max_length=200)
    expected_slice_revision: int | None = Field(default=None, ge=1)
    scope: list[str] | None = Field(default=None, max_length=30)
    inputs: list[str] | None = Field(default=None, max_length=30)
    outputs: list[str] | None = Field(default=None, max_length=30)
    existing_behaviors_to_preserve: list[str] | None = Field(default=None, max_length=30)
    explicit_non_goals: list[str] | None = Field(default=None, max_length=30)
    known_technical_context: list[str] | None = Field(default=None, max_length=30)
    unknown_dependencies: list[str] | None = Field(default=None, max_length=30)
    implementation_tasks: list[str] | None = Field(default=None, max_length=30)
    acceptance_steps: list[str] | None = Field(default=None, max_length=30)
    failure_recovery_notes: list[str] | None = Field(default=None, max_length=30)
    required_return_evidence: list[str] | None = Field(default=None, max_length=30)
    permission_risk_notes: list[str] | None = Field(default=None, max_length=30)


class ActionSubmissionCreateRequest(StrictModel):
    task_revision: int = Field(ge=1)
    submission_kind: Literal["DONE", "BLOCKED"]
    description: str = Field(min_length=1, max_length=8000)
    attachment_refs: list[Any] = Field(default_factory=list, max_length=30)
    check_results: list[Any] = Field(default_factory=list, max_length=30)
    execution_claim: dict[str, Any] = Field(default_factory=dict)
    source_identity: Literal[
        "USER_INPUT",
        "MODEL_HYPOTHESIS",
        "REAL_OBSERVATION",
        "SIMULATION",
        "IMPLEMENTATION_EVIDENCE",
    ]


class ActionReviewCreateRequest(StrictModel):
    submission_revision: int = Field(ge=1)
    task_id: str = Field(min_length=1, max_length=200)
    task_revision: int = Field(ge=1)
    check_items: list[Any] = Field(default_factory=list, max_length=30)
    overall_status: Literal["PASS", "FAIL", "UNKNOWN", "NOT_APPLICABLE"]
    known_unknowns: list[Any] = Field(default_factory=list, max_length=30)
    evidence_level: Literal["USER_REPORTED", "ARTIFACT_CHECKED", "AUTHORIZED_RUN"]
    recommendation: str = Field(default="", max_length=8000)
    reviewer_role: str = Field(default="system_review", min_length=1, max_length=120)


class RecoveryCreateRequest(StrictModel):
    submission_id: str = Field(min_length=1, max_length=200)
    review_id: str = Field(min_length=1, max_length=200)
    review_revision: int = Field(ge=1)
    goal: str = Field(min_length=1, max_length=8000)
    inputs: list[Any] = Field(default_factory=list, max_length=30)
    steps: list[Any] = Field(default_factory=list, max_length=30)
    checks: list[Any] = Field(default_factory=list, max_length=30)


class M3DecisionRecommendRequest(StrictModel):
    submission_id: str = Field(min_length=1, max_length=200)
    review_id: str = Field(min_length=1, max_length=200)
    review_revision: int = Field(ge=1)
    decision: Literal["CONTINUE", "NARROW", "CHANGE", "STOP", "FINISH"]
    rationale: str = Field(min_length=1, max_length=8000)
    recommendation: str = Field(min_length=1, max_length=8000)
    remaining_unknowns: list[Any] = Field(default_factory=list, max_length=30)


class M3DecisionConfirmRequest(StrictModel):
    expected_revision: int = Field(ge=1)


class M4CreateExperimentRequest(StrictModel):
    experiment_id: str = Field(min_length=1, max_length=200)
    spec_version: str = Field(min_length=1, max_length=120)
    source_commit: str = Field(min_length=1, max_length=120)
    deployment_id: str = Field(default="local", min_length=1, max_length=200)
    condition_definitions: dict[str, Any]
    assignment_rule: str = Field(min_length=1, max_length=2000)
    metric_versions: dict[str, Any]
    rubric_versions: dict[str, Any]
    threshold_policy: dict[str, Any]
    operator_assistance_policy: dict[str, Any]


class M4UpdateExperimentRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    condition_definitions: dict[str, Any] | None = None
    assignment_rule: str | None = Field(default=None, min_length=1, max_length=2000)
    metric_versions: dict[str, Any] | None = None
    rubric_versions: dict[str, Any] | None = None
    threshold_policy: dict[str, Any] | None = None
    operator_assistance_policy: dict[str, Any] | None = None


class M4CreateParticipantRequest(StrictModel):
    participant_id: str = Field(min_length=1, max_length=200)
    purpose: Literal["LEARNING", "PERSONAL_USE", "FOR_OTHERS"]
    prior_ai_familiarity: str = Field(min_length=1, max_length=120)
    prior_product_experience: str = Field(min_length=1, max_length=120)
    task_category: str = Field(min_length=1, max_length=200)


class M4AssignSessionRequest(StrictModel):
    session_id: str = Field(min_length=1, max_length=200)
    participant_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)


class M4TransitionSessionRequest(StrictModel):
    target_state: Literal[
        "ASSIGNED",
        "READY",
        "IN_PROGRESS",
        "COMPLETED",
        "WITHDRAWN",
        "OPERATIONAL_INCOMPLETE",
        "QUALITY_INCOMPLETE",
        "FINALIZED",
    ]
    expected_revision: int = Field(ge=1)
    withdrawal_reason: str | None = Field(default=None, max_length=2000)


class M4OperationalAccountingRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    elapsed_ms: int = Field(default=0, ge=0)
    time_to_first_valid_action_ms: int | None = Field(default=None, ge=0)
    time_to_first_usable_flow_ms: int | None = Field(default=None, ge=0)
    edit_count: int = Field(default=0, ge=0)
    support_minutes: float = Field(default=0, ge=0)
    provider_calls: int = Field(default=0, ge=0)
    provider_cost: float = Field(default=0, ge=0)
    retry_count: int = Field(default=0, ge=0)
    timeout_count: int = Field(default=0, ge=0)
    severe_error_count: int = Field(default=0, ge=0)
    recovery_attempts: int = Field(default=0, ge=0)


class M4GoldSetRequest(StrictModel):
    participant_id: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=200)
    purpose: str = Field(min_length=1, max_length=2000)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    explicit_non_goals: list[str] = Field(default_factory=list, max_length=30)
    requirements: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    participant_confirmed: Literal[True]
    expected_session_revision: int = Field(ge=1)


class M4AnnotationRequest(StrictModel):
    project_id: str = Field(min_length=1, max_length=200)
    artifact_ref: str = Field(min_length=1, max_length=300)
    annotation_type: str = Field(min_length=1, max_length=120)
    target_id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)
    evaluator_role: Literal["participant", "independent_reviewer", "llm_judge"]
    evidence_ref: str | None = Field(default=None, max_length=300)
    disagreement: dict[str, Any] | None = None
    source_identity: str | None = Field(default=None, max_length=80)
    adjudication_status: str | None = Field(default=None, max_length=80)
    expected_session_revision: int | None = Field(default=None, ge=1)


class M4QualityRequest(StrictModel):
    project_id: str = Field(min_length=1, max_length=200)
    expected_session_revision: int = Field(ge=1)
    metrics: dict[str, Any]


class M4FinalizeSessionRequest(StrictModel):
    expected_revision: int = Field(ge=1)
    outcome: Literal[
        "WITHDRAWN",
        "OPERATIONAL_INCOMPLETE",
        "QUALITY_INCOMPLETE",
        "COMPLETED",
        "INTEGRITY_FAIL",
    ]
    reason: str | None = Field(default=None, max_length=2000)


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
    competitor_snapshot_id: str | None = Field(default=None, max_length=200)
    # Competitor context is opt-in for each generation. Ordinary and
    # "暂时不比较" flows must not inherit a project's latest snapshot.
    use_competitor_snapshot: bool = False


class ApprovalRequest(StrictModel):
    actor: str = Field(min_length=1, max_length=80)
    note: str = Field(default="", max_length=1000)
    human_confirmed: bool = False


class WalkthroughAdvanceRequest(StrictModel):
    step: Literal["idea", "solutions", "mvp", "claims", "evidence", "documents", "handoff"]


class DocumentDraftSaveRequest(StrictModel):
    base_version_id: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2_000_000)
    base_revision: int | None = Field(default=None, ge=0)


class UnifiedDraftSaveRequest(StrictModel):
    payload: dict[str, Any]
    base_revision: int | None = Field(default=None, ge=0)
    entity_id: str | None = Field(default=None, max_length=200)
    version_id: str | None = Field(default=None, max_length=200)


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


@dataclass(frozen=True)
class IdeaBriefCompleteness:
    """Deterministic semantic-completeness result for evaluation gates."""

    complete: bool
    missing_fields: tuple[str, ...]
    clarification_required: bool


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
    competitor_context: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_clarification(self) -> "IdeaBriefDraft":
        if self.clarification_required and not (self.clarification_question or "").strip():
            raise ValueError("clarification_question is required when clarification_required=true")
        return self

    def validate_substantive_completeness(self) -> IdeaBriefCompleteness:
        required = (
            ("original_idea", self.original_idea),
            ("target_user", self.target_user),
            ("problem", self.problem),
            ("desired_outcome", self.desired_outcome),
        )
        missing = tuple(name for name, value in required if not value.strip())
        if self.clarification_required and "clarification_required" not in missing:
            missing = (*missing, "clarification_required")
        return IdeaBriefCompleteness(
            complete=not missing,
            missing_fields=missing,
            clarification_required=self.clarification_required,
        )


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
    candidates: list[SolutionCandidateDraft] = Field(min_length=3, max_length=3)
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
