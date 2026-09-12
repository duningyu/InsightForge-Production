"""Remaining rereview leaks: real public API and persisted idempotent replay."""
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.errors import StructuredOutputContractError
from app.services.ai_reference import AIReferenceService
from test_whole_branch_fixes import CASES, PROJECT


@pytest.fixture(autouse=True)
def local_participant(client):
    client.app.state.beta_context = replace(client.app.state.beta_context, participant_id="test")


@pytest.mark.parametrize("raw", CASES["rereview_rejected"].values(), ids=CASES["rereview_rejected"])
def test_serialized_private_values_rejected_by_api_generation(client, monkeypatch, raw):
    client.app.state.async_generation_worker.stop()
    db = client.app.state.db
    body = {"possible_target_users": [raw]}
    runtime = SimpleNamespace(generate_ai_reference=lambda context: body)
    monkeypatch.setattr(client.app.state, "structured_runtime", SimpleNamespace(mode="fake", for_project=lambda p: runtime))
    response = client.post(f"/api/projects/{PROJECT}/ai-reference", json={})
    assert response.status_code == 503
    assert response.json()["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
    assert "SYNTHETIC_REREVIEW" not in response.text
    assert db.fetch_one("SELECT COUNT(*) AS n FROM ai_reference_results")["n"] == 0


@pytest.mark.parametrize("raw", CASES["rereview_rejected"].values(), ids=CASES["rereview_rejected"])
@pytest.mark.parametrize("boundary", ["api_get", "api_replay", "service_get", "service_replay"])
def test_serialized_private_values_in_legacy_storage_fail_get_and_replay(client, monkeypatch, raw, boundary):
    client.app.state.async_generation_worker.stop()
    db = client.app.state.db
    runtime = SimpleNamespace(generate_ai_reference=lambda context: {"possible_target_users": ["门店运营人员"]})
    monkeypatch.setattr(client.app.state, "structured_runtime", SimpleNamespace(mode="fake", for_project=lambda p: runtime))
    service = AIReferenceService(db)
    saved = service.generate(PROJECT, actor="test", runtime=runtime, idempotency_key="f1-stored")
    saved["result"]["possible_target_users"] = [raw]
    db.execute("UPDATE ai_reference_results SET result_json=? WHERE id=?", (json.dumps(saved["result"]), saved["id"]))
    if boundary.startswith("api"):
        response = (client.get(f"/api/projects/{PROJECT}/ai-reference") if boundary == "api_get" else
                    client.post(f"/api/projects/{PROJECT}/ai-reference", json={"idempotency_key": "f1-stored"}))
        assert response.status_code == 503
        assert response.json()["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
        assert "SYNTHETIC_REREVIEW" not in response.text
    else:
        with pytest.raises(StructuredOutputContractError) as caught:
            if boundary == "service_get":
                service.get(PROJECT, saved["id"], actor="test")
            else:
                service.generate(PROJECT, actor="test", runtime=runtime, idempotency_key="f1-stored")
        assert "SYNTHETIC_REREVIEW" not in str(caught.value.as_public_payload())
    assert db.fetch_one("SELECT COUNT(*) AS n FROM ai_reference_results")["n"] == 1
