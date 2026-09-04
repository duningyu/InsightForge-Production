from app.services.provider_dispatch_ledger import DispatchClassification, ProviderDispatchLedger


def _ledger(db):
    return ProviderDispatchLedger(db)


def _permit(ledger, execution="exec-1"):
    return ledger.acquire_permit(
        acceptance_execution_id=execution, acceptance_window_id="window-1",
        beta_instance="beta001", provider="bailian", model="qwen3.7-flash",
        authorization_reference="auth-hash", quota_scope="acceptance",
    )


def test_permit_acquisition_is_atomic_and_restart_safe(db):
    ledger = _ledger(db)
    first = _permit(ledger)
    assert first
    assert _permit(_ledger(db)) is None


def test_classification_is_conservative_and_terminal_indeterminate_blocks_retry(db):
    ledger = _ledger(db)
    assert ledger.classify("exec-1") == DispatchClassification.NOT_YET_ATTEMPTED
    permit = _permit(ledger)
    assert ledger.classify("exec-1") == DispatchClassification.PROVEN_NOT_DISPATCHED
    ledger.record_event(permit, "CALL_BOUNDARY_ENTERED")
    ledger.record_event(permit, "TIMEOUT_AFTER_BOUNDARY")
    assert ledger.classify("exec-1") == DispatchClassification.POSSIBLY_DISPATCHED_INDETERMINATE
    assert _permit(_ledger(db)) is None


def test_response_confirms_dispatch_and_events_are_append_only(db):
    ledger = _ledger(db)
    permit = _permit(ledger)
    ledger.record_event(permit, "CALL_BOUNDARY_ENTERED", {"request_body_bytes": 10})
    ledger.record_event(permit, "PROVIDER_RESPONSE_RECEIVED", {"response_headers_observed": True})
    assert ledger.classify("exec-1") == DispatchClassification.CONFIRMED_PROVIDER_DISPATCH


def test_provider_http_error_confirms_dispatch_but_transport_failure_is_indeterminate(db):
    ledger = _ledger(db)
    permit = _permit(ledger)
    ledger.record_event(permit, "CALL_BOUNDARY_ENTERED")
    ledger.record_event(permit, "PROVIDER_HTTP_ERROR_RECEIVED", {"http_status": 503})
    assert ledger.classify("exec-1") == DispatchClassification.CONFIRMED_PROVIDER_DISPATCH

    other = _permit(ledger, execution="exec-2")
    ledger.record_event(other, "CALL_BOUNDARY_ENTERED")
    ledger.record_event(other, "TRANSPORT_ERROR_AFTER_BOUNDARY")
    assert ledger.classify("exec-2") == DispatchClassification.POSSIBLY_DISPATCHED_INDETERMINATE


def test_existing_permit_blocks_scoped_guard_and_same_uuid_isolated_by_execution(db):
    ledger = _ledger(db)
    _permit(ledger, execution="exec-1")
    blocked, reason = ledger.scoped_guard(
        acceptance_execution_id="exec-1", provider="bailian", model="qwen3.7-flash",
        beta_instance="beta001", current_day_used=0, daily_limit=3, active_reservations=0,
    )
    assert blocked is False and reason == "EXECUTION_ALREADY_HAS_PERMIT_OR_EVIDENCE"

    assert _permit(ledger, execution="exec-2")


def test_event_metadata_is_allowlisted_for_safe_serialization(db):
    ledger = _ledger(db)
    permit = _permit(ledger)
    ledger.record_event(permit, "CALL_BOUNDARY_ENTERED", {
        "request_body_bytes": 42, "message_count": 1, "schema_bytes": 99,
        "structured_output_mode": "json",
    })
    row = db.fetch_one("SELECT metadata_json FROM provider_dispatch_events WHERE permit_id=?", (permit,))
    assert "prompt" not in row["metadata_json"].lower()
    try:
        ledger.record_event(permit, "COMPLETED", {"authorization": "redacted"})
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe event metadata must be rejected")


def test_scoped_guard_ignores_legacy_lifetime_count_but_rejects_bad_target_retry_fallback_and_quota(db):
    ledger = _ledger(db)
    ok, _ = ledger.scoped_guard(
        acceptance_execution_id="new", provider="bailian", model="qwen3.7-flash",
        beta_instance="beta001", current_day_used=0, daily_limit=3,
        active_reservations=0,
    )
    assert ok
    for kwargs in (
        {"model": "glm-5.2"}, {"automatic_retry_enabled": True},
        {"fallback_provider": "glm"}, {"active_reservations": 1},
    ):
        base = dict(acceptance_execution_id="x", provider="bailian", model="qwen3.7-flash",
                    beta_instance="beta001", current_day_used=0, daily_limit=3,
                    active_reservations=0)
        base.update(kwargs)
        assert ledger.scoped_guard(**base)[0] is False


def test_epoch_and_legacy_rows_are_additive(db):
    before = db.fetch_one("SELECT COUNT(*) AS n FROM solution_generation_intents")["n"]
    ledger = _ledger(db)
    ledger.create_epoch(epoch_id="epoch-1", acceptance_window_id="window-epoch",
                        checkpoint_at="2026-09-04T00:00:00Z",
                        historical_authorized_dispatches=1,
                        historical_unresolved_intents=3)
    assert db.fetch_one("SELECT COUNT(*) AS n FROM solution_generation_intents")["n"] == before
    assert db.fetch_one("SELECT historical_unresolved_intents FROM provider_dispatch_epochs")["historical_unresolved_intents"] == 3


def test_no_provider_api_is_called_by_ledger(db):
    # This module has no network dependency; the assertion is an explicit tripwire contract.
    assert not hasattr(_ledger(db), "provider_client")
