"""Provider-free evidence and external-action guards for IF Guide M3."""

from __future__ import annotations

from typing import Any


SOURCE_IDENTITIES = frozenset(
    {
        "USER_INPUT",
        "MODEL_HYPOTHESIS",
        "REAL_OBSERVATION",
        "SIMULATION",
        "IMPLEMENTATION_EVIDENCE",
    }
)
EVIDENCE_LEVELS = frozenset({"USER_REPORTED", "ARTIFACT_CHECKED", "AUTHORIZED_RUN"})
FORBIDDEN_EXTERNAL_ACTIONS = frozenset(
    {"PROVIDER", "SEARCH", "TERMINAL_EXECUTION", "GITHUB_WRITE", "DEPLOYMENT"}
)
_EXECUTION_KEYS = frozenset(
    {"executed", "tested", "deployed", "verified", "system_verified", "authorized_run"}
)


def validate_source_identity(value: str) -> str:
    if value not in SOURCE_IDENTITIES:
        raise ValueError("INVALID_SOURCE_IDENTITY")
    return value


def validate_evidence_level(level: str, evidence_refs: list[Any]) -> str:
    if level not in EVIDENCE_LEVELS:
        raise ValueError("INVALID_EVIDENCE_LEVEL")
    if level == "AUTHORIZED_RUN":
        raise ValueError("AUTHORIZED_RUN_NOT_ALLOWED")
    if level == "ARTIFACT_CHECKED" and (
        not isinstance(evidence_refs, list) or not evidence_refs
    ):
        raise ValueError("ARTIFACT_EVIDENCE_REQUIRED")
    return level


def validate_execution_claim(claim: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(claim, dict):
        raise ValueError("EXECUTION_CLAIM_OBJECT_REQUIRED")
    for key, value in claim.items():
        if str(key).casefold() in _EXECUTION_KEYS and bool(value):
            raise ValueError("EXECUTION_CLAIM_NOT_VERIFIED")
        if str(key).casefold() == "evidence_level" and str(value).upper() == "AUTHORIZED_RUN":
            raise ValueError("AUTHORIZED_RUN_NOT_ALLOWED")
    return claim


def validate_external_action(action: str) -> str:
    if str(action).upper() in FORBIDDEN_EXTERNAL_ACTIONS:
        raise ValueError("UNAUTHORIZED_EXTERNAL_ACTION")
    return action
