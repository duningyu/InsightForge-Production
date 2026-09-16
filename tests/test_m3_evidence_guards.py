import pytest

from app.services.if_guide_m3_guards import (
    validate_evidence_level,
    validate_execution_claim,
    validate_source_identity,
    validate_external_action,
)


def test_source_identity_is_a_closed_vocabulary():
    assert validate_source_identity("USER_INPUT") == "USER_INPUT"
    with pytest.raises(ValueError, match="INVALID_SOURCE_IDENTITY"):
        validate_source_identity("USER_REPORTED")


def test_artifact_checked_requires_a_concrete_reference():
    with pytest.raises(ValueError, match="ARTIFACT_EVIDENCE_REQUIRED"):
        validate_evidence_level("ARTIFACT_CHECKED", [])
    assert validate_evidence_level("ARTIFACT_CHECKED", ["sha256:fixture"]) == "ARTIFACT_CHECKED"


def test_authorized_run_cannot_be_claimed_by_default_m3_flow():
    with pytest.raises(ValueError, match="AUTHORIZED_RUN_NOT_ALLOWED"):
        validate_evidence_level("AUTHORIZED_RUN", ["run:fixture"])


def test_claims_and_external_actions_fail_closed():
    with pytest.raises(ValueError, match="EXECUTION_CLAIM_NOT_VERIFIED"):
        validate_execution_claim({"executed": True})
    with pytest.raises(ValueError, match="UNAUTHORIZED_EXTERNAL_ACTION"):
        validate_external_action("TERMINAL_EXECUTION")
