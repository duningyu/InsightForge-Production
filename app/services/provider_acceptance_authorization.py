"""Server-owned, single-use authorization for strict beta acceptance runs."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from app.db import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class AcceptanceAuthorization:
    authorization_id: str
    project_id: str
    actor_scope: str
    beta_instance: str
    provider: str
    model: str
    forward_ledger_epoch_id: str
    state: str
    created_at: str
    expires_at: str
    acceptance_execution_id: str | None


class ProviderAcceptanceAuthorizationRepository:
    """Internal issuance and read-only lookup; no public HTTP issuance route."""

    def __init__(self, database: Database):
        self.db = database

    def issue_pending(
        self, *, project_id: str, actor_scope: str, forward_ledger_epoch_id: str,
        expires_at: str, created_by: str,
    ) -> AcceptanceAuthorization:
        created_at = _now()
        authorization_id = str(uuid4())
        evidence = hashlib.sha256(json.dumps({
            "project_id": project_id, "actor_scope": actor_scope,
            "beta_instance": "beta001", "provider": "bailian",
            "model": "qwen3.7-flash", "epoch": forward_ledger_epoch_id,
            "operation": "solution_generation", "created_at": created_at,
        }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self.db.connect() as cx:
            cx.execute(
                """INSERT INTO provider_acceptance_authorizations(
                authorization_id, project_id, actor_scope, beta_instance, provider,
                model, forward_ledger_epoch_id, operation_type, state, created_at,
                expires_at, authorization_evidence_hash, created_by
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (authorization_id, project_id, actor_scope, "beta001", "bailian",
                 "qwen3.7-flash", forward_ledger_epoch_id, "solution_generation",
                 "PENDING", created_at, expires_at, evidence, created_by),
            )
        return self.get(authorization_id)  # type: ignore[return-value]

    def get(self, authorization_id: str) -> AcceptanceAuthorization | None:
        with self.db.connect() as cx:
            row = cx.execute(
                "SELECT authorization_id,project_id,actor_scope,beta_instance,provider,model,"
                "forward_ledger_epoch_id,state,created_at,expires_at,acceptance_execution_id "
                "FROM provider_acceptance_authorizations WHERE authorization_id=?",
                (authorization_id,),
            ).fetchone()
        if row is None:
            return None
        return AcceptanceAuthorization(*row)

