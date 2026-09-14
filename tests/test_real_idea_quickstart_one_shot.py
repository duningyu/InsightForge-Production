from __future__ import annotations

from pathlib import Path

import pytest

from app.errors import StructuredRuntimeRecoveryError
from app.schemas import IdeaBriefDraft, QuickStartRequest
from app.services.ai_runtime import DeterministicDemoRuntime
from app.services.evaluation_policy import EvaluationExecutionPolicy
from app.services.hybrid_runtime import HybridStructuredRuntime
from app.services.model_profiles import ModelProfileService
from app.services.projects import ProjectService
from app.services.provider_adapters import ProviderCallError
from app.services.credential_store import CredentialStore
from app.services.quick_start import QuickStartService


class MemoryCredentialBackend:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        self.values.pop((service, username), None)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"


class CountingAdapter:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def interpret_idea(self, request: QuickStartRequest):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome

    def close(self):
        return None


class AdapterFactory:
    def __init__(self, outcome):
        self.adapter = CountingAdapter(outcome)

    def __call__(self, **_configuration):
        return self.adapter


def _brief(idea: str) -> IdeaBriefDraft:
    return IdeaBriefDraft(
        original_idea=idea,
        target_user="设备运维人员",
        problem="需要更早识别风险",
        desired_outcome="获得可复核的预警",
        known_resources=[],
        constraints=[],
        unknowns=[],
        provenance={"problem": "model_hypothesis"},
        clarification_required=False,
        clarification_question=None,
    )


def _profile(profile_service: ModelProfileService) -> None:
    profile_service.create(
        display_name="one-shot-model",
        provider="qwen",
        model_id="one-shot-model",
        api_key="test-secret",
        is_default=True,
    )


@pytest.fixture()
def profile_service(db):
    return ModelProfileService(
        db,
        credential_store=CredentialStore(backend=MemoryCredentialBackend()),
    )


def _runtime(profile_service, factory):
    return HybridStructuredRuntime(
        profile_service,
        local_runtime=DeterministicDemoRuntime(fixture_path=FIXTURE_PATH),
        adapter_factory=factory,
        max_model_rounds=2,
    )


def test_quickstart_policy_allows_one_transport_and_rejects_second_attempt(
    profile_service,
):
    factory = AdapterFactory(_brief("one-shot idea"))
    runtime = _runtime(profile_service, factory)
    _profile(profile_service)
    policy = EvaluationExecutionPolicy(
        batch_id="batch-01",
        sample_id="sample-01",
        stage="QUICKSTART",
    )
    selected = runtime.for_project(None, evaluation_policy=policy)

    selected.interpret_idea(QuickStartRequest(idea="one-shot idea"))
    with pytest.raises(StructuredRuntimeRecoveryError) as caught:
        selected.interpret_idea(QuickStartRequest(idea="one-shot idea"))

    assert caught.value.error_code == "EVALUATION_TRANSPORT_LIMIT_REACHED"
    assert factory.adapter.calls == 1
    assert selected.model_rounds_used == 1


def test_quickstart_policy_does_not_retry_provider_503(profile_service):
    factory = AdapterFactory(
        ProviderCallError("rate_limited", "busy", True)
    )
    runtime = _runtime(profile_service, factory)
    _profile(profile_service)
    policy = EvaluationExecutionPolicy(
        batch_id="batch-01",
        sample_id="sample-01",
        stage="QUICKSTART",
    )
    selected = runtime.for_project(None, evaluation_policy=policy)

    with pytest.raises(StructuredRuntimeRecoveryError) as caught:
        selected.interpret_idea(QuickStartRequest(idea="one-shot idea"))

    assert caught.value.error_code == "MODEL_RATE_LIMITED"
    assert factory.adapter.calls == 1
    assert selected.model_rounds_used == 1


def test_quickstart_success_enters_brief_review_under_evaluation_policy(
    db, profile_service
):
    factory = AdapterFactory(_brief("one-shot idea"))
    runtime = _runtime(profile_service, factory)
    _profile(profile_service)
    service = QuickStartService(db, ProjectService(db), runtime)
    policy = EvaluationExecutionPolicy(
        batch_id="batch-01",
        sample_id="sample-01",
        stage="QUICKSTART",
    )

    result = service.quick_start(
        QuickStartRequest(idea="one-shot idea"),
        actor="evaluation",
        evaluation_policy=policy,
    )

    assert result["status"] == "AWAITING_BRIEF_REVIEW"
    assert result["provider_transport_count"] == 1
    assert result["idea_brief"]["confirmation_status"] == "inferred"
    assert result["idea_brief"]["clarification_required"] is False
