"""Transactional model-profile configuration without public credential material."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.db import Database, utc_now
from app.errors import ConflictError
from app.services.credential_store import CredentialStore, KeyringCredentialStore
from app.services.model_providers import ProviderRegistry
from app.services.provider_adapters import ModelAdapter


AdapterFactory = Callable[..., ModelAdapter]
CAPABILITY_TTL = timedelta(hours=24)
CAPABILITY_FIELDS = (
    "basic_chat",
    "structured_json",
    "function_calling",
    "streaming",
)


def _utc_datetime_now() -> datetime:
    return datetime.now(timezone.utc)


class ModelProfileService:
    def __init__(
        self,
        db: Database,
        credential_store: KeyringCredentialStore | None = None,
        adapter_factory: AdapterFactory = ModelAdapter,
        clock: Callable[[], datetime] = _utc_datetime_now,
    ) -> None:
        self.db = db
        self._credential_store = credential_store
        self.adapter_factory = adapter_factory
        self.clock = clock

    @property
    def credential_store(self) -> KeyringCredentialStore:
        if self._credential_store is None:
            self._credential_store = CredentialStore()
        return self._credential_store

    @credential_store.setter
    def credential_store(self, value: KeyringCredentialStore) -> None:
        self._credential_store = value

    @staticmethod
    def _audit_payload(row: dict[str, Any], action: str) -> dict[str, Any]:
        return {
            "provider": row["provider"],
            "model": row["model_id"],
            "revision": row["revision"],
            "action": action,
        }

    @staticmethod
    def _insert_revision_tx(connection: sqlite3.Connection, row: dict[str, Any]) -> None:
        connection.execute(
            """INSERT INTO model_profile_revisions(
                id, profile_id, revision, display_name, provider, protocol, base_url,
                model_id, enabled, is_default, capabilities_json,
                capabilities_checked_at, last_test_status, last_tested_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                f"model_profile_revision_{uuid.uuid4().hex}",
                row["id"],
                row["revision"],
                row["display_name"],
                row["provider"],
                row["protocol"],
                row["base_url"],
                row["model_id"],
                row["enabled"],
                row["is_default"],
                row["capabilities_json"],
                row["capabilities_checked_at"],
                row["last_test_status"],
                row["last_tested_at"],
                row["updated_at"],
            ),
        )

    @staticmethod
    def _row_tx(connection: sqlite3.Connection, profile_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT * FROM model_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            raise KeyError("Model profile not found.")
        return dict(row)

    def _bump_tx(
        self,
        connection: sqlite3.Connection,
        profile_id: str,
        assignments: dict[str, Any],
    ) -> dict[str, Any]:
        assignments = {**assignments, "updated_at": utc_now()}
        columns = ", ".join(f"{name} = ?" for name in assignments)
        connection.execute(
            f"UPDATE model_profiles SET {columns}, revision = revision + 1 WHERE id = ?",
            (*assignments.values(), profile_id),
        )
        row = self._row_tx(connection, profile_id)
        self._insert_revision_tx(connection, row)
        return row

    @staticmethod
    def _begin_write(connection: sqlite3.Connection) -> None:
        connection.execute("BEGIN IMMEDIATE")

    def _audit_tx(
        self,
        connection: sqlite3.Connection,
        *,
        row: dict[str, Any],
        action: str,
        actor: str,
    ) -> None:
        self.db.insert_audit_tx(
            connection,
            actor=actor,
            action=action,
            entity_type="model_profile",
            entity_id=row["id"],
            payload=self._audit_payload(row, action),
        )

    def _clear_other_defaults_tx(
        self, connection: sqlite3.Connection, profile_id: str, actor: str
    ) -> None:
        rows = connection.execute(
            "SELECT id FROM model_profiles WHERE is_default = 1 AND id <> ?",
            (profile_id,),
        ).fetchall()
        for existing in rows:
            row = self._bump_tx(connection, existing["id"], {"is_default": 0})
            self._audit_tx(connection, row=row, action="model_profile_default_unset", actor=actor)

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            capabilities = json.loads(row["capabilities_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            capabilities = {}
        if not isinstance(capabilities, dict):
            capabilities = {}
        last_test_status = row["last_test_status"]
        checked_at = row["capabilities_checked_at"]
        if capabilities and checked_at:
            try:
                checked = datetime.fromisoformat(checked_at)
                if checked.tzinfo is None:
                    checked = checked.replace(tzinfo=timezone.utc)
                now = self.clock()
                if now.tzinfo is None:
                    now = now.replace(tzinfo=timezone.utc)
                expired = now.astimezone(timezone.utc) - checked.astimezone(
                    timezone.utc
                ) > CAPABILITY_TTL
            except (TypeError, ValueError):
                expired = True
            if expired:
                capabilities = {field: "unknown" for field in CAPABILITY_FIELDS}
                last_test_status = "expired"
        credential_status = "missing"
        if row["credential_ref"] is not None and self.credential_store.configured(
            row["credential_ref"]
        ):
            credential_status = "configured"
        return {
            "id": row["id"],
            "display_name": row["display_name"],
            "provider": row["provider"],
            "protocol": row["protocol"],
            "base_url": row["base_url"],
            "model_id": row["model_id"],
            "credential_status": credential_status,
            "enabled": bool(row["enabled"]),
            "is_default": bool(row["is_default"]),
            "capabilities": capabilities,
            "capabilities_checked_at": row["capabilities_checked_at"],
            "last_test_status": last_test_status,
            "last_tested_at": row["last_tested_at"],
            "last_live_test_status": row.get("last_live_test_status"),
            "last_live_tested_at": row.get("last_live_tested_at"),
            "last_live_latency_ms": row.get("last_live_latency_ms"),
            "last_live_error_code": row.get("last_live_error_code"),
            "last_live_model_returned": row.get("last_live_model_returned"),
            "revision": row["revision"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _get_internal(self, profile_id: str) -> dict[str, Any]:
        row = self.db.fetch_one("SELECT * FROM model_profiles WHERE id = ?", (profile_id,))
        if row is None:
            raise KeyError("Model profile not found.")
        return row

    def _resolve_credential(self, credential_ref: str) -> str:
        try:
            return self.credential_store.resolve(credential_ref)
        except KeyError:
            raise ConflictError("The model profile credential is missing.") from None

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.fetch_all("SELECT * FROM model_profiles ORDER BY created_at, id")
        return [self._public(row) for row in rows]

    def create(
        self,
        *,
        display_name: str,
        provider: str,
        model_id: str,
        api_key: str | None = None,
        protocol: str | None = None,
        base_url: str | None = None,
        enabled: bool = True,
        is_default: bool = False,
        actor: str = "web_user",
    ) -> dict[str, Any]:
        resolved = ProviderRegistry.resolve(provider, protocol=protocol, base_url=base_url)
        if is_default and not enabled:
            raise ConflictError("A disabled model profile cannot be the default.")
        profile_id = f"model_profile_{uuid.uuid4().hex}"
        credential_ref: str | None = None
        clean_key = api_key if api_key and api_key.strip() else None
        if clean_key is not None:
            credential_ref = self.credential_store.put(profile_id, clean_key)
        timestamp = utc_now()
        try:
            with self.db.connect() as connection:
                self._begin_write(connection)
                if is_default:
                    self._clear_other_defaults_tx(connection, profile_id, actor)
                connection.execute(
                    """INSERT INTO model_profiles(
                        id, display_name, provider, protocol, base_url, model_id,
                        credential_ref, enabled, is_default, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        profile_id,
                        display_name.strip(),
                        resolved.provider,
                        resolved.protocol,
                        resolved.default_base_url,
                        model_id.strip(),
                        credential_ref,
                        int(enabled),
                        int(is_default),
                        timestamp,
                        timestamp,
                    ),
                )
                row = self._row_tx(connection, profile_id)
                self._insert_revision_tx(connection, row)
                self._audit_tx(connection, row=row, action="model_profile_created", actor=actor)
        except Exception:
            if credential_ref is not None:
                self.credential_store.delete(credential_ref)
            raise
        return self._public(self._get_internal(profile_id))

    def update(
        self,
        profile_id: str,
        *,
        changes: dict[str, Any],
        actor: str = "web_user",
    ) -> dict[str, Any]:
        replacement = changes.get("api_key")
        replace_key = isinstance(replacement, str) and bool(replacement.strip())
        old_secret: str | None = None
        replacement_ref: str | None = None
        replacement_installed = False
        result_row: dict[str, Any] | None = None
        try:
            with self.db.connect() as connection:
                self._begin_write(connection)
                current = self._row_tx(connection, profile_id)
                requested_provider = changes.get("provider", current["provider"])
                provider_changed = (
                    "provider" in changes and requested_provider != current["provider"]
                )
                requested_protocol = (
                    changes.get("protocol")
                    if provider_changed
                    else changes.get("protocol", current["protocol"])
                )
                requested_base_url = (
                    changes.get("base_url")
                    if provider_changed
                    else changes.get("base_url", current["base_url"])
                )
                resolved = ProviderRegistry.resolve(
                    requested_provider,
                    protocol=requested_protocol,
                    base_url=requested_base_url,
                )
                enabled = changes.get("enabled", bool(current["enabled"]))
                if not enabled:
                    referenced = connection.execute(
                        "SELECT project_id FROM project_model_profiles "
                        "WHERE profile_id = ? LIMIT 1",
                        (profile_id,),
                    ).fetchone()
                    if current["is_default"] or referenced is not None:
                        raise ConflictError("A selected model profile cannot be disabled.")

                assignments: dict[str, Any] = {
                    "display_name": changes.get(
                        "display_name", current["display_name"]
                    ).strip(),
                    "provider": resolved.provider,
                    "protocol": resolved.protocol,
                    "base_url": resolved.default_base_url,
                    "model_id": changes.get("model_id", current["model_id"]).strip(),
                    "enabled": int(enabled),
                }
                configuration_changed = any(
                    current[column] != value for column, value in assignments.items()
                )
                if not configuration_changed and not replace_key:
                    result_row = current
                else:
                    if replace_key:
                        if current["credential_ref"] is not None:
                            try:
                                old_secret = self.credential_store.resolve(
                                    current["credential_ref"]
                                )
                            except KeyError:
                                old_secret = None
                        replacement_ref = self.credential_store.put(profile_id, replacement)
                        replacement_installed = True
                        assignments["credential_ref"] = replacement_ref
                    capability_inputs_changed = replace_key or any(
                        current[column] != assignments[column]
                        for column in ("provider", "protocol", "base_url", "model_id")
                    )
                    if capability_inputs_changed:
                        assignments.update(
                            {
                                "capabilities_json": "{}",
                                "capabilities_checked_at": None,
                                "last_test_status": None,
                                "last_tested_at": None,
                                "last_live_test_status": None,
                                "last_live_tested_at": None,
                                "last_live_latency_ms": None,
                                "last_live_error_code": None,
                                "last_live_model_returned": None,
                            }
                        )
                    result_row = self._bump_tx(connection, profile_id, assignments)
                    self._audit_tx(
                        connection,
                        row=result_row,
                        action="model_profile_updated",
                        actor=actor,
                    )
        except Exception:
            if replacement_installed:
                if old_secret is not None:
                    self.credential_store.put(profile_id, old_secret)
                elif replacement_ref is not None:
                    self.credential_store.delete(replacement_ref)
            raise
        assert result_row is not None
        return self._public(result_row)

    def delete(self, profile_id: str, *, actor: str = "web_user") -> None:
        old_secret: str | None = None
        credential_ref: str | None = None
        credential_deleted = False
        try:
            with self.db.connect() as connection:
                self._begin_write(connection)
                current = self._row_tx(connection, profile_id)
                if current["is_default"]:
                    raise ConflictError(
                        "The default model profile must be reassigned before deletion."
                    )
                reference = connection.execute(
                    "SELECT project_id FROM project_model_profiles "
                    "WHERE profile_id = ? LIMIT 1",
                    (profile_id,),
                ).fetchone()
                if reference is not None:
                    raise ConflictError(
                        "A project-referenced model profile must be reassigned before deletion."
                    )
                credential_ref = current["credential_ref"]
                if credential_ref is not None and self.credential_store.configured(
                    credential_ref
                ):
                    try:
                        old_secret = self.credential_store.resolve(credential_ref)
                    except KeyError:
                        old_secret = None
                    if old_secret is not None:
                        self.credential_store.delete(credential_ref)
                        credential_deleted = True
                self._audit_tx(
                    connection, row=current, action="model_profile_deleted", actor=actor
                )
                connection.execute(
                    "DELETE FROM model_profile_revisions WHERE profile_id = ?", (profile_id,)
                )
                connection.execute("DELETE FROM model_profiles WHERE id = ?", (profile_id,))
        except Exception:
            if credential_deleted and old_secret is not None:
                self.credential_store.put(profile_id, old_secret)
            raise

    def set_default(self, profile_id: str, *, actor: str = "web_user") -> dict[str, Any]:
        with self.db.connect() as connection:
            self._begin_write(connection)
            current = self._row_tx(connection, profile_id)
            if not current["enabled"]:
                raise ConflictError("A disabled model profile cannot be the default.")
            self._clear_other_defaults_tx(connection, profile_id, actor)
            row = self._row_tx(connection, profile_id)
            if not row["is_default"]:
                row = self._bump_tx(connection, profile_id, {"is_default": 1})
            self._audit_tx(connection, row=row, action="model_profile_default_set", actor=actor)
        return self._public(self._get_internal(profile_id))

    def get_project_override(self, project_id: str) -> dict[str, Any]:
        if self.db.fetch_one("SELECT id FROM projects WHERE id=?", (project_id,)) is None:
            raise KeyError("Project not found.")
        row = self.db.fetch_one(
            "SELECT profile_id FROM project_model_profiles WHERE project_id=? AND enabled=1",
            (project_id,),
        )
        return {"project_id": project_id, "profile_id": row["profile_id"] if row else None}

    def set_project_override(
        self,
        project_id: str,
        profile_id: str | None,
        *,
        actor: str = "web_user",
    ) -> dict[str, Any]:
        timestamp = utc_now()
        with self.db.connect() as connection:
            self._begin_write(connection)
            if connection.execute(
                "SELECT id FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is None:
                raise KeyError("Project not found.")
            if profile_id is None:
                previous = connection.execute(
                    "SELECT profile_id FROM project_model_profiles WHERE project_id = ?",
                    (project_id,),
                ).fetchone()
                connection.execute(
                    "DELETE FROM project_model_profiles WHERE project_id = ?", (project_id,)
                )
                if previous is not None and previous["profile_id"] is not None:
                    row = self._row_tx(connection, previous["profile_id"])
                    self._audit_tx(
                        connection,
                        row=row,
                        action="project_model_profile_override_cleared",
                        actor=actor,
                    )
            else:
                row = self._row_tx(connection, profile_id)
                if not row["enabled"]:
                    raise ConflictError("A disabled model profile cannot be selected for a project.")
                connection.execute(
                    """INSERT INTO project_model_profiles(
                        project_id, profile_id, enabled, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        profile_id = excluded.profile_id,
                        enabled = 1,
                        updated_at = excluded.updated_at""",
                    (project_id, profile_id, timestamp, timestamp),
                )
                self._audit_tx(
                    connection,
                    row=row,
                    action="project_model_profile_override_set",
                    actor=actor,
                )
        return {"project_id": project_id, "profile_id": profile_id}


    def live_test_connection(
        self, profile_id: str, *, actor: str = "web_user"
    ) -> dict[str, Any]:
        """Run one explicit real provider request and persist only safe metadata."""
        current = self._get_internal(profile_id)
        credential_ref = current["credential_ref"]
        if credential_ref is None or not self.credential_store.configured(credential_ref):
            raise ConflictError("The model profile has no configured credential.")
        api_key = self._resolve_credential(credential_ref)
        adapter = self.adapter_factory(
            provider=current["provider"],
            protocol=current["protocol"],
            base_url=current["base_url"],
            model=current["model_id"],
            api_key=api_key,
        )
        try:
            result = adapter.live_check().as_dict()
        finally:
            adapter.close()

        checked = self.clock()
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
        checked_at = checked.astimezone(timezone.utc).isoformat()
        stored_status = "passed" if result["status"] == "PASS" else "failed"
        with self.db.connect() as connection:
            connection.execute(
                """UPDATE model_profiles SET
                    last_live_test_status = ?,
                    last_live_tested_at = ?,
                    last_live_latency_ms = ?,
                    last_live_error_code = ?,
                    last_live_model_returned = ?
                WHERE id = ?""",
                (
                    stored_status,
                    checked_at,
                    result["latency_ms"],
                    result["error_code"],
                    result["model_returned"],
                    profile_id,
                ),
            )
            row = self._row_tx(connection, profile_id)
            self._audit_tx(
                connection,
                row=row,
                action="model_profile_live_connection_tested",
                actor=actor,
            )

        return {"profile_id": profile_id, **result, "checked_at": checked_at}

    def test_connection(
        self, profile_id: str, *, actor: str = "web_user"
    ) -> dict[str, Any]:
        current = self._get_internal(profile_id)
        credential_ref = current["credential_ref"]
        if credential_ref is None or not self.credential_store.configured(credential_ref):
            raise ConflictError("The model profile has no configured credential.")
        api_key = self._resolve_credential(credential_ref)
        adapter = self.adapter_factory(
            provider=current["provider"],
            protocol=current["protocol"],
            base_url=current["base_url"],
            model=current["model_id"],
            api_key=api_key,
        )
        try:
            report = adapter.probe()
        finally:
            adapter.close()
        report_dict = report.as_dict()
        checked_at = report_dict.pop("checked_at")
        if report.basic_chat == "supported":
            status = "passed"
        elif report.basic_chat == "unsupported":
            status = "failed"
        else:
            status = "inconclusive"
        with self.db.connect() as connection:
            row = self._bump_tx(
                connection,
                profile_id,
                {
                    "capabilities_json": json.dumps(report_dict, ensure_ascii=False),
                    "capabilities_checked_at": checked_at,
                    "last_test_status": status,
                    "last_tested_at": checked_at,
                },
            )
            self._audit_tx(connection, row=row, action="model_profile_connection_tested", actor=actor)
        return self._public(self._get_internal(profile_id))
