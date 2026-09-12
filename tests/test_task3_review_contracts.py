from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from app.errors import StructuredOutputContractError
from app.schemas import AIReferenceDraft
from app.services.async_generation import AsyncGenerationRepository
from app.services.generation import LocalDocumentGenerator
from app.services.loop import DocumentLoop
from surface_fixtures import complete_solution_payload


@pytest.mark.parametrize("response", [None, {}, {"candidates": []}, {"candidates": [{}, {}]}])
def test_async_public_rejects_legacy_incomplete_success(db, response):
    run = AsyncGenerationRepository(db).create_or_replay("test", "project_insightforge_demo", "legacy")
    public = replace(run, status="SUCCEEDED", status_code=201, response=response).public()
    assert public["status"] == "FAILED"
    assert public["status_code"] == 503
    assert public["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
    assert "candidates" not in public


@pytest.mark.parametrize("kind", ["two", "missing", "malformed", "valid"])
def test_async_poll_and_post_replay_check_stored_success(client, kind):
    project = "project_insightforge_demo"
    repository = client.app.state.async_generation_repository
    participant = client.app.state.beta_context.participant_id
    run = repository.create_or_replay(participant, project, "legacy-two", use_competitor_snapshot=False)
    payload = complete_solution_payload()
    if kind == "two":
        payload["candidates"] = payload["candidates"][:2]
    elif kind == "missing":
        payload = {}
    elif kind == "malformed":
        payload["candidates"][0]["summary"] = {"raw_response": "PRIVATE_SENTINEL"}
    # Simulate a persisted result written before the exact-three contract.
    client.app.state.db.execute(
        "UPDATE async_solution_generation_runs SET status='SUCCEEDED', status_code=201, quota_status='CHARGED', response_json=? WHERE generation_run_id=?",
        (json.dumps(payload), run.generation_run_id),
    )
    responses = [client.get(f"/api/projects/{project}/solutions/generate/{run.generation_run_id}"),
                 client.post(f"/api/projects/{project}/solutions/generate", headers={"X-Generation-Mode": "async", "X-Idempotency-Key": "legacy-two"})]
    for response in responses:
        assert response.status_code == 200, response.text
        assert response.json()["generation_run_id"] == run.generation_run_id
        if kind == "valid":
            assert response.json()["status"] == "SUCCEEDED"
            assert len(response.json()["candidates"]) == 3
        else:
            assert response.json()["status"] == "FAILED"
            assert response.json()["status_code"] == 503
            assert response.json()["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
            assert "candidates" not in response.json()
        assert "PRIVATE_SENTINEL" not in response.text
    stored = client.app.state.db.fetch_one("SELECT status, quota_status, provider_call_count FROM async_solution_generation_runs WHERE generation_run_id=?", (run.generation_run_id,))
    assert stored == {"status": "SUCCEEDED", "quota_status": "CHARGED", "provider_call_count": 0}
    assert repository.claim_next() is None


@pytest.mark.parametrize("stored", [None, "stored"])
def test_async_public_model_metadata_is_owned_by_run(db, stored):
    run = AsyncGenerationRepository(db).create_or_replay(
        "test", "project_insightforge_demo", "metadata", requested_model_preference=stored,
        resolved_model_family=stored, resolved_model_id=stored,
    )
    payload = complete_solution_payload()
    fields = ("requested_model_preference", "resolved_model_family", "resolved_model_id")
    payload.update({field: "forged" for field in fields})
    public = replace(run, status="SUCCEEDED", status_code=201, response=payload).public()
    for field in fields:
        assert public.get(field) == stored


@pytest.mark.parametrize("boundary", ["finish", "public", "route", "replay"])
def test_normalized_solution_values_survive_publication(client, monkeypatch, boundary):
    payload = complete_solution_payload()
    payload["candidates"][0].update(summary=b"normalized summary", user_flow=("normalized step",), requires_rag_runtime="true")
    project = "project_insightforge_demo"
    if boundary in {"finish", "public"}:
        repository = client.app.state.async_generation_repository
        run = repository.create_or_replay("test", project, "normalized")
        if boundary == "finish":
            repository.claim_next()
            repository.finish(run.generation_run_id, payload, status_code=201)
            run = repository.get("test", project, run.generation_run_id)
            assert run.response["candidates"][0]["summary"] == "normalized summary"
        else:
            run = replace(run, status="SUCCEEDED", status_code=201, response=payload)
        result = run.public()
        assert result["status"] == "SUCCEEDED"
    else:
        if boundary == "route":
            monkeypatch.setattr(client.app.state.solution_design, "generate", lambda *a, **kw: payload)
        else:
            monkeypatch.setattr(client.app.state.solution_generation_guard, "begin", lambda *a, **kw: SimpleNamespace(owner=False, error_code="SOLUTION_GENERATION_ALREADY_COMPLETED", status_code=201, payload=payload))
        response = client.post(f"/api/projects/{project}/solutions/generate")
        assert response.status_code == 201, response.text
        result = response.json()
    candidate = result["candidates"][0]
    assert candidate["summary"] == "normalized summary"
    assert candidate["user_flow"] == ["normalized step"]
    assert candidate["requires_rag_runtime"] is True
    from app.services.generation_contracts import validate_solution_response
    serialized = json.loads(json.dumps(result))
    assert validate_solution_response(serialized)["candidates"] == serialized["candidates"]


@pytest.mark.parametrize("doc_type", ["prd", "techdoc"])
@pytest.mark.parametrize("malformation", ["not_object", "missing_content", "null_content", "object_content", "missing_citations", "object_citations", "object_claims", "invalid_claim", "invalid_evidence", "invalid_metadata", "schema_exception", "repair_null"])
def test_malformed_documents_are_typed_and_terminal_before_persistence(db, malformation, doc_type):
    local = LocalDocumentGenerator()
    def generate(*args, **kwargs):
        payload = local.generate(*args, **kwargs)
        if malformation == "not_object":
            return None
        if malformation == "schema_exception":
            AIReferenceDraft.model_validate({"mvp_thoughts": {"raw_response": "PRIVATE_SENTINEL"}})
        if malformation.startswith("missing_"):
            payload.pop(malformation.removeprefix("missing_"))
        elif malformation == "null_content":
            payload["content"] = None
        elif malformation == "object_content":
            payload["content"] = {"raw_response": "PRIVATE_SENTINEL"}
        elif malformation == "object_citations":
            payload["citations"] = {"raw_response": "PRIVATE_SENTINEL"}
        elif malformation == "object_claims":
            payload["claims"] = {"raw_response": "PRIVATE_SENTINEL"}
        elif malformation == "invalid_claim":
            payload["claims"] = ["PRIVATE_SENTINEL"]
        elif malformation == "invalid_evidence":
            payload["claims"] = [{"claim_type": "source_backed", "evidence": ["PRIVATE_SENTINEL"]}]
        elif malformation == "invalid_metadata":
            payload["claims"] = [{"metadata": "PRIVATE_SENTINEL"}]
        elif malformation == "repair_null":
            payload["content"] = "incomplete document"
        return payload
    loop = DocumentLoop(db, generator=SimpleNamespace(generate=generate, repair=lambda *args: None))
    with pytest.raises(StructuredOutputContractError) as caught:
        loop.run("project_insightforge_demo", doc_type)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "PRIVATE_SENTINEL" not in json.dumps(caught.value.as_payload())
    run = db.fetch_one("SELECT status, terminal_state, version_id FROM generation_runs")
    assert run == {"status": "failed", "terminal_state": "failed", "version_id": None}
    assert db.fetch_one("SELECT COUNT(*) AS n FROM document_versions")["n"] == 0
