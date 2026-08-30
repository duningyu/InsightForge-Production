"""Backend-only storage for provider credentials.

Credential values are deliberately never retained by this module.  The default
backend is the operating system keyring; tests and callers may inject a
keyring-compatible backend explicitly.
"""

from __future__ import annotations

from typing import Any, Protocol
import os


SERVICE_NAME = "InsightForge"
REFERENCE_PREFIX = "insightforge:model-profile:"


class CredentialBackend(Protocol):
    def set_password(self, service: str, username: str, password: str) -> Any: ...

    def get_password(self, service: str, username: str) -> str | None: ...

    def delete_password(self, service: str, username: str) -> Any: ...


class CredentialBackendUnavailable(RuntimeError):
    """Raised when the configured credential backend cannot be reached."""


class EnvironmentCredentialBackend:
    """Read-only container backend; secrets are supplied per profile by environment."""

    def _name(self, username: str) -> str:
        profile = username.removeprefix(REFERENCE_PREFIX)
        if not profile or not profile.replace("_", "").replace("-", "").isalnum():
            raise KeyError(username)
        return "INSIGHTFORGE_MODEL_PROFILE_" + profile.upper().replace("-", "_") + "_API_KEY"

    def set_password(self, service: str, username: str, password: str) -> None:
        raise CredentialBackendUnavailable("environment credential backend is read-only")

    def get_password(self, service: str, username: str) -> str | None:
        return os.getenv(self._name(username))

    def delete_password(self, service: str, username: str) -> None:
        raise CredentialBackendUnavailable("environment credential backend is read-only")


class KeyringCredentialStore:
    """Store credentials using a keyring-compatible backend only."""

    def __init__(self, backend: CredentialBackend | None = None) -> None:
        if backend is None:
            if os.getenv("INSIGHTFORGE_CREDENTIAL_BACKEND", "").strip().lower() == "environment":
                backend = EnvironmentCredentialBackend()
            else:
                imported_backend: CredentialBackend | None = None
                try:
                    import keyring
                except Exception:
                    pass
                else:
                    imported_backend = keyring
                if imported_backend is None:
                    raise CredentialBackendUnavailable("credential backend is unavailable")
                backend = imported_backend
        self._backend = backend

    @staticmethod
    def _reference(profile_id: str) -> str:
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("profile_id must be a non-empty string")
        return f"{REFERENCE_PREFIX}{profile_id}"

    @staticmethod
    def _profile_id(credential_ref: str) -> str:
        if not isinstance(credential_ref, str) or not credential_ref.startswith(REFERENCE_PREFIX):
            raise KeyError(credential_ref)
        profile_id = credential_ref[len(REFERENCE_PREFIX) :]
        if not profile_id:
            raise KeyError(credential_ref)
        return profile_id

    def put(self, profile_id: str, value: str) -> str:
        reference = self._reference(profile_id)
        failed = False
        try:
            self._backend.set_password(SERVICE_NAME, reference, value)
        except Exception:
            failed = True
        if failed:
            raise CredentialBackendUnavailable("credential backend is unavailable")
        return reference

    def resolve(self, credential_ref: str) -> str:
        self._profile_id(credential_ref)
        failed = False
        value: str | None = None
        try:
            value = self._backend.get_password(SERVICE_NAME, credential_ref)
        except Exception:
            failed = True
        if failed:
            raise CredentialBackendUnavailable("credential backend is unavailable")
        if value is None:
            raise KeyError(credential_ref)
        return value

    def delete(self, credential_ref: str) -> None:
        self._profile_id(credential_ref)
        failed = False
        try:
            self._backend.delete_password(SERVICE_NAME, credential_ref)
        except Exception:
            failed = True
        if failed:
            raise CredentialBackendUnavailable("credential backend is unavailable")

    def configured(self, ref: str | None) -> bool:
        if ref is None:
            return False
        try:
            self._profile_id(ref)
        except KeyError:
            return False
        try:
            configured = self._backend.get_password(SERVICE_NAME, ref) is not None
        except Exception:
            configured = None
        if configured is None:
            raise CredentialBackendUnavailable("credential backend is unavailable")
        return configured

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


CredentialStore = KeyringCredentialStore
