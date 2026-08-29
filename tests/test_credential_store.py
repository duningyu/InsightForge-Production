import builtins
import traceback

import pytest

from app.services.credential_store import (
    CredentialBackendUnavailable,
    CredentialStore,
)


class MemoryBackend:
    def __init__(self):
        self.values = {}

    def set_password(self, service, username, password):
        self.values[(service, username)] = password

    def get_password(self, service, username):
        return self.values.get((service, username))

    def delete_password(self, service, username):
        del self.values[(service, username)]


def test_put_resolve_replace_and_delete_use_opaque_reference():
    backend = MemoryBackend()
    store = CredentialStore(backend=backend)

    ref = store.put("profile-1", "sk-SENTINEL-DO-NOT-LEAK")
    assert ref == "insightforge:model-profile:profile-1"
    assert store.resolve(ref) == "sk-SENTINEL-DO-NOT-LEAK"
    assert store.configured(ref)

    store.put("profile-1", "replacement")
    assert store.resolve(ref) == "replacement"

    store.delete(ref)
    assert not store.configured(ref)
    with pytest.raises(KeyError):
        store.resolve(ref)


def test_store_representation_and_serialized_metadata_never_contain_secret():
    store = CredentialStore(backend=MemoryBackend())
    ref = store.put("profile-1", "sk-SENTINEL-DO-NOT-LEAK")

    assert "sk-SENTINEL-DO-NOT-LEAK" not in repr(store)
    assert "sk-SENTINEL-DO-NOT-LEAK" not in repr({"credential_ref": ref})


def test_backend_failures_raise_without_plaintext_fallback():
    class BrokenBackend(MemoryBackend):
        def set_password(self, service, username, password):
            raise RuntimeError("vault unavailable")

    store = CredentialStore(backend=BrokenBackend())
    with pytest.raises(CredentialBackendUnavailable):
        store.put("profile-1", "sk-SENTINEL-DO-NOT-LEAK")


def test_secret_in_backend_exception_is_removed_from_error_details():
    sentinel = "sk-SENTINEL-DO-NOT-LEAK"

    class LeakingBackend(MemoryBackend):
        def set_password(self, service, username, password):
            raise RuntimeError(f"backend rejected {password}")

    with pytest.raises(CredentialBackendUnavailable) as caught:
        CredentialStore(backend=LeakingBackend()).put("profile-1", sentinel)

    error = caught.value
    assert sentinel not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert sentinel not in "".join(traceback.format_exception(error))


def test_keyring_import_failure_is_sanitized(monkeypatch):
    real_import = builtins.__import__

    def fail_keyring(name, *args, **kwargs):
        if name == "keyring":
            raise ModuleNotFoundError("keyring contains sk-SENTINEL-DO-NOT-LEAK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_keyring)
    with pytest.raises(CredentialBackendUnavailable) as caught:
        CredentialStore()

    error = caught.value
    assert "sk-SENTINEL-DO-NOT-LEAK" not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "sk-SENTINEL-DO-NOT-LEAK" not in "".join(traceback.format_exception(error))


def test_configured_none_and_invalid_reference_are_false():
    store = CredentialStore(backend=MemoryBackend())
    assert not store.configured(None)
    assert not store.configured("not-an-insightforge-reference")
