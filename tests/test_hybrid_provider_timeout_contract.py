import httpx
import pytest

from app.errors import StructuredRuntimeRecoveryError, StructuredRuntimeUnavailableError
from app.schemas import IdeaBriefDraft
from app.services.ai_runtime import ManagedModelStructuredRuntime
from app.services.provider_adapters import ModelAdapter, ProviderCallError


def test_model_adapter_default_uses_approved_phase_timeouts():
    adapter = ModelAdapter(
        provider="openai",
        model="test-model",
        api_key="test-only-secret",
    )
    try:
        assert adapter.effective_timeout == {
            "connect_timeout_seconds": 10.0,
            "pool_timeout_seconds": 5.0,
            "write_timeout_seconds": 15.0,
            "read_timeout_seconds": 60.0,
            "overall_timeout_seconds": 75.0,
        }
        assert adapter._client.timeout.connect == 10.0
        assert adapter._client.timeout.pool == 5.0
        assert adapter._client.timeout.write == 15.0
        assert adapter._client.timeout.read == 60.0
    finally:
        adapter.close()


def test_explicit_timeout_remains_available_for_deterministic_harness():
    adapter = ModelAdapter(
        provider="openai",
        model="test-model",
        api_key="test-only-secret",
        client=httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
        timeout=httpx.Timeout(connect=1.0, pool=2.0, write=3.0, read=4.0),
    )
    try:
        assert adapter.effective_timeout["connect_timeout_seconds"] == 1.0
        assert adapter.effective_timeout["read_timeout_seconds"] == 4.0
    finally:
        adapter.close()


def _brief() -> IdeaBriefDraft:
    return IdeaBriefDraft(
        original_idea="research support",
        target_user="master students",
        problem="finding relevant papers",
        desired_outcome="a review path",
        provenance={
            "target_user": "user_input",
            "problem": "model_hypothesis",
            "desired_outcome": "model_hypothesis",
        },
    )


def test_managed_runtime_forwards_approved_timeout_contract():
    captured = {}

    def factory(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("test-only construction failure")

    runtime = ManagedModelStructuredRuntime(
        model="glm-5.2",
        provider="bailian",
        api_key="test-only-secret",
        adapter_factory=factory,
    )
    with pytest.raises(StructuredRuntimeUnavailableError):
        runtime.design_solutions(_brief())

    timeout = captured["timeout"]
    assert timeout.connect == 10.0
    assert timeout.pool == 5.0
    assert timeout.write == 15.0
    assert timeout.read == 60.0


def test_managed_runtime_preserves_provider_error_cause_chain():
    provider_error = ProviderCallError(
        "timeout",
        "Provider transport timeout.",
        True,
        safe_diagnostic={"provider_error_source": "UPSTREAM_TIMEOUT_READ"},
    )

    class FailingAdapter:
        def __init__(self, **_kwargs):
            pass

        def design_solutions(self, _brief):
            raise provider_error

        def close(self):
            pass

    runtime = ManagedModelStructuredRuntime(
        model="glm-5.2",
        provider="bailian",
        api_key="test-only-secret",
        adapter_factory=FailingAdapter,
    )
    with pytest.raises(StructuredRuntimeRecoveryError) as caught:
        runtime.design_solutions(_brief())

    assert caught.value.__cause__ is provider_error
    assert caught.value.__cause__.safe_diagnostic["provider_error_source"] == "UPSTREAM_TIMEOUT_READ"
