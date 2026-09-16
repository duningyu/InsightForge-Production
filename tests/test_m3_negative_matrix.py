"""Small executable checks for the M3 fail-closed boundary."""

import pytest

from app.services.if_guide_m3_guards import (
    validate_evidence_level,
    validate_execution_claim,
    validate_external_action,
    validate_source_identity,
)


def test_m3_rejects_unbounded_source_and_execution_claims():
    with pytest.raises(ValueError, match="INVALID_SOURCE_IDENTITY"):
        validate_source_identity("USER_REPORTED")
    with pytest.raises(ValueError, match="AUTHORIZED_RUN_NOT_ALLOWED"):
        validate_evidence_level("AUTHORIZED_RUN", [])
    with pytest.raises(ValueError, match="EXECUTION_CLAIM_NOT_VERIFIED"):
        validate_execution_claim({"executed": True})


def test_m3_rejects_unauthorized_external_actions_and_missing_artifact_evidence():
    with pytest.raises(ValueError, match="UNAUTHORIZED_EXTERNAL_ACTION"):
        validate_external_action("TERMINAL_EXECUTION")
    with pytest.raises(ValueError, match="ARTIFACT_EVIDENCE_REQUIRED"):
        validate_evidence_level("ARTIFACT_CHECKED", [])
