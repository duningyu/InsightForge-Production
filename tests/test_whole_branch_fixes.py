"""R1-R4 local contracts: real services/SQLite/API and the actual JS adapters."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from app.errors import StructuredOutputContractError
from app.services.ai_reference import AIReferenceService
from app.services.evidence_coach import EvidenceCoachService
from app.services.generation import LocalDocumentGenerator
from app.services.generation_contracts import (
    failure_public, validate_document_draft, validate_document_sections,
    validate_guidance, validate_solution_response,
)
from app.services.loop import DocumentLoop
from app.services.validation import PRD_HEADINGS, TECHDOC_HEADINGS
from surface_fixtures import complete_solution_payload
from test_stage_b_output_contract import _card

CASES = json.loads((Path(__file__).parent / "fixtures/whole_branch_value_cases.json").read_text(encoding="utf-8"))
CASES["rejected"] += list(CASES["rereview_rejected"].values())
PROJECT = "project_insightforge_demo"


@pytest.mark.parametrize("raw", CASES["rejected"])
@pytest.mark.parametrize("field", ["possible_target_users", "uncertainty_notice", "fixture_disclosure"])
def test_reference_raw_values_rejected_before_persistence(db, raw, field):
    body = {"possible_target_users": ["门店运营人员"]}
    runtime = SimpleNamespace(generate_ai_reference=lambda context: body)
    if field == "fixture_disclosure":
        runtime.fixture_origin = "STAGE_A_SYNTHETIC"
        runtime.disclosure = raw
    else:
        body[field] = [raw] if field == "possible_target_users" else raw
    with pytest.raises(StructuredOutputContractError) as caught:
        AIReferenceService(db).generate(PROJECT, actor="test", runtime=runtime)
    assert raw not in str(caught.value.as_public_payload())
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert db.fetch_one("SELECT COUNT(*) AS n FROM ai_reference_results")["n"] == 0


@pytest.mark.parametrize("surface", ["reference", "guidance"])
@pytest.mark.parametrize("boundary", ["get", "retry", "api"])
@pytest.mark.parametrize("field", ["list", "disclosure", "empty"])
def test_stored_invalid_values_are_revalidated(client, surface, boundary, field):
    db = client.app.state.db
    service = AIReferenceService(db) if surface == "reference" else EvidenceCoachService(db)
    body = {"possible_target_users": ["门店运营人员"]} if surface == "reference" else {"cards": [_card()]}
    runtime = SimpleNamespace(generate_ai_reference=lambda c: body, generate_evidence_guidance=lambda c: body)
    saved = service.generate(PROJECT, actor="test", runtime=runtime, idempotency_key="stored")
    stored = saved["result"]
    raw = CASES["rejected"][0]
    if field == "disclosure":
        stored["fixture_disclosure"] = raw
    elif surface == "reference":
        stored["possible_target_users"] = [raw] if field == "list" else []
    else:
        stored["cards"][0]["action_steps"] = [raw] if field == "list" else []
    table = "ai_reference_results" if surface == "reference" else "evidence_guidance_results"
    db.execute(f"UPDATE {table} SET result_json=? WHERE id=?", (json.dumps(stored), saved["id"]))
    if boundary == "api":
        route = "ai-reference" if surface == "reference" else "evidence-guidance"
        response = client.get(f"/api/projects/{PROJECT}/{route}")
        assert response.status_code == 503
        assert response.json()["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"
        assert "SYNTHETIC_PRIVATE" not in response.text
    else:
        with pytest.raises(StructuredOutputContractError):
            if boundary == "get":
                service.get(PROJECT, saved["id"], actor="test")
            else:
                service.generate(PROJECT, actor="test", runtime=runtime, idempotency_key="stored")


@pytest.mark.parametrize("surface", ["guidance_scalar", "guidance_list", "guidance_disclosure", "solution", "document"])
@pytest.mark.parametrize("raw", CASES["rejected"])
def test_allowed_value_positions_reject_raw_material(surface, raw):
    with pytest.raises(StructuredOutputContractError):
        if surface.startswith("guidance"):
            body = {"cards": [_card()]}
            if surface == "guidance_disclosure":
                body["disclosure"] = raw
            else:
                body["cards"][0]["title" if surface == "guidance_scalar" else "action_steps"] = raw if surface == "guidance_scalar" else [raw]
            validate_guidance(body)
        elif surface == "solution":
            body = complete_solution_payload()
            body["candidates"][0]["summary"] = raw
            validate_solution_response(body)
        else:
            validate_document_draft({"content": "# 文档\n" + raw, "citations": [], "claims": []})


@pytest.mark.parametrize("field", ["quota_status", "failure_stage", "fixture_origin", "fixture_disclosure"])
def test_failure_metadata_uses_only_owned_values(field):
    public = failure_public({"error_code": "MODEL_OUTPUT_CONTRACT_FAILED", field: "arbitrary private material"})
    assert "arbitrary private material" not in str(public)
    assert public["error_code"] == "MODEL_OUTPUT_CONTRACT_FAILED"


def test_known_failure_metadata_keeps_enum_and_owned_fixture_copy():
    result = failure_public({"error_code": "MODEL_OUTPUT_CONTRACT_FAILED", "quota_status": "RELEASED",
                             "fixture_origin": "STAGE_A_SYNTHETIC", "fixture_disclosure": "arbitrary private material"})
    assert result["quota_status"] == "RELEASED"
    assert result["fixture_origin"] == "STAGE_A_SYNTHETIC"
    assert result["fixture_disclosure"] == "Stage A 演示结果 · 非真实 AI 生成"


@pytest.mark.parametrize("prose", CASES["ordinary"])
def test_partial_reference_generation_load_and_retry_preserve_ordinary_prose(db, prose):
    service = AIReferenceService(db)
    runtime = SimpleNamespace(generate_ai_reference=lambda c: {"possible_target_users": [prose]})
    generated = service.generate(PROJECT, actor="test", runtime=runtime, idempotency_key="partial")
    assert generated["result"]["possible_target_users"] == [prose]
    assert generated["result"]["research_directions"] == []
    assert service.get(PROJECT, generated["id"], actor="test") == generated
    assert service.generate(PROJECT, actor="test", runtime=runtime, idempotency_key="partial") == generated


@pytest.mark.parametrize("doc_type", ["prd", "techdoc"])
def test_generated_selected_b_document_passes_actual_frontend_adapter(db, doc_type):
    snapshot = {
        "solution": {"title": "SELECTED_B", "summary": "B_SUMMARY", "core_idea": "B_CORE_IDEA",
                     "why_fit": "B_VALUE", "rationale": "B_RATIONALE", "explicit_non_goals": []},
        "target_user": {"primary": "B_USER"}, "problem": {"statement": "B_PROBLEM"},
        "mvp": {"pages": ["UNIQUE_B_PAGE_1", "UNIQUE_B_PAGE_2"], "features": ["B_FEATURE_1", "B_FEATURE_2"]},
        "user_flow": ["B_FLOW_1", "B_FLOW_2"],
    }
    canvas = db.get_canvas(PROJECT)
    canvas.update(problem="B_PROBLEM", target_users="B_USER", selected_solution_context=snapshot)
    generated = LocalDocumentGenerator().generate(doc_type, canvas, [], project_title="B project")
    validate_document_sections(generated["content"], PRD_HEADINGS if doc_type == "prd" else TECHDOC_HEADINGS)
    payload = {"snapshot": snapshot, "docType": doc_type, "content": generated["content"]}
    result = subprocess.run(["node", "tests/whole_branch_fix_harness.js", "--document"],
                            input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8", timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr


def test_frontend_value_optional_reference_and_scope_regressions():
    result = subprocess.run(["node", "tests/whole_branch_fix_harness.js"], capture_output=True,
                            text=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reference_api_rejects_raw_generation_without_saving(client, monkeypatch):
    runtime = SimpleNamespace(generate_ai_reference=lambda c: {"possible_target_users": [CASES["rejected"][0]]})
    monkeypatch.setattr(client.app.state, "structured_runtime", SimpleNamespace(mode="fake", for_project=lambda p: runtime))
    response = client.post(f"/api/projects/{PROJECT}/ai-reference", json={})
    assert response.status_code == 503
    assert "SYNTHETIC_PRIVATE" not in response.text
    assert client.app.state.db.fetch_one("SELECT COUNT(*) AS n FROM ai_reference_results")["n"] == 0


@pytest.mark.parametrize("boundary", ["generate", "versions_api", "replay", "replay_citation", "lifecycle_api", "draft", "draft_load"])
def test_document_raw_content_rejected_at_persistence_and_public_boundaries(client, boundary):
    db = client.app.state.db
    raw = CASES["rejected"][0]
    local = LocalDocumentGenerator()
    if boundary == "generate":
        def generate(*args, **kwargs):
            result = local.generate(*args, **kwargs)
            result["content"] += "\n" + raw
            return result
        with pytest.raises(StructuredOutputContractError):
            DocumentLoop(db, generator=SimpleNamespace(generate=generate)).run(PROJECT, "prd")
        assert db.fetch_one("SELECT COUNT(*) AS n FROM document_versions")["n"] == 0
        return
    saved = DocumentLoop(db, generator=local).run(PROJECT, "prd", idempotency_key="doc-safe")
    version_id = saved["version_id"]
    if boundary == "draft_load":
        workspace = client.app.state.document_workspace
        workspace.save_draft(PROJECT, "prd", base_version_id=version_id, content="安全文档草稿", actor="test")
        db.execute("UPDATE document_edit_drafts SET content=? WHERE project_id=?", (raw, PROJECT))
        response = client.get(f"/api/projects/{PROJECT}/documents/prd/draft")
        assert response.status_code == 503
        assert "SYNTHETIC_PRIVATE" not in response.text
        return
    if boundary == "draft":
        with pytest.raises(StructuredOutputContractError):
            client.app.state.document_workspace.save_draft(PROJECT, "prd", base_version_id=version_id, content=raw, actor="test")
        assert db.fetch_one("SELECT COUNT(*) AS n FROM document_edit_drafts")["n"] == 0
        return
    db.execute("UPDATE document_versions SET content=? WHERE id=?", (saved["content"] + "\n" + raw, version_id))
    if boundary == "replay_citation":
        db.execute("UPDATE document_versions SET content=?,citations_json=? WHERE id=?",
                   (saved["content"], json.dumps([raw]), version_id))
    if boundary == "lifecycle_api":
        from app.services.document_versions import DocumentVersionService
        with pytest.raises(StructuredOutputContractError):
            DocumentVersionService(db).move_to_trash(version_id, actor="test")
        assert db.fetch_one("SELECT lifecycle_status FROM document_versions WHERE id=?", (version_id,))["lifecycle_status"] == "active"
        return
    if boundary == "versions_api":
        response = client.get(f"/api/projects/{PROJECT}/documents/prd/versions")
        assert response.status_code == 503
        assert "SYNTHETIC_PRIVATE" not in response.text
    else:
        with pytest.raises(StructuredOutputContractError):
            DocumentLoop(db, generator=local).run(PROJECT, "prd", idempotency_key="doc-safe")


def test_async_solution_api_revalidates_raw_strings_on_poll_and_replay(client):
    client.app.state.async_generation_worker.stop()
    repository = client.app.state.async_generation_repository
    participant = client.app.state.beta_context.participant_id
    run = repository.create_or_replay(participant, PROJECT, "raw-stored", use_competitor_snapshot=False)
    payload = complete_solution_payload()
    payload["candidates"][0]["features"] = [CASES["rejected"][0]]
    client.app.state.db.execute(
        "UPDATE async_solution_generation_runs SET status='SUCCEEDED', status_code=201, response_json=? WHERE generation_run_id=?",
        (json.dumps(payload), run.generation_run_id),
    )
    for response in [client.get(f"/api/projects/{PROJECT}/solutions/generate/{run.generation_run_id}"),
                     client.post(f"/api/projects/{PROJECT}/solutions/generate", headers={"X-Generation-Mode": "async", "X-Idempotency-Key": "raw-stored"})]:
        assert response.status_code == 200
        assert response.json()["status"] == "FAILED"
        assert "SYNTHETIC_PRIVATE" not in response.text


def test_selected_b_persisted_documents_are_accepted_by_frontend_without_forced_validation(client):
    from test_v3_solution_api import quick_project
    project = quick_project(client)
    generated = client.post(f"/api/projects/{project}/solutions/generate")
    assert generated.status_code == 201
    selected = generated.json()["candidates"][1]
    client.app.state.db.execute("UPDATE solution_candidates SET mvp_pages_json=? WHERE id=?",
                                (json.dumps(["UNIQUE_B_PAGE_1", "UNIQUE_B_PAGE_2"]), selected["id"]))
    response = client.post(f"/api/projects/{project}/solutions/select", json={"strategy": "single", "candidate_ids": [selected["id"]], "rationale": "选择人工复核方案", "human_confirmed": True})
    assert response.status_code == 201
    snapshot = response.json()
    for doc_type in ("prd", "techdoc"):
        response = client.post(f"/api/projects/{project}/documents/generate", json={"doc_type": doc_type, "use_competitor_snapshot": False})
        assert response.status_code == 200, response.text
        versions = client.get(f"/api/projects/{project}/documents/{doc_type}/versions").json()
        assert versions[0]["content"] == response.json()["content"]
        result = subprocess.run(["node", "tests/whole_branch_fix_harness.js", "--document"],
                                input=json.dumps({"snapshot": snapshot, "docType": doc_type, "content": versions[0]["content"]}),
                                capture_output=True, text=True, encoding="utf-8", timeout=15)
        assert result.returncode == 0, result.stdout + result.stderr
