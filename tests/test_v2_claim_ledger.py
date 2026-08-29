import json

from app.services.loop import DocumentLoop
from app.services.validation import DocumentValidator


def test_local_prd_returns_typed_claims_with_source_aligned_evidence(db):
    result = DocumentLoop(db).run(
        "project_insightforge_demo",
        "prd",
        idempotency_key="v2-claim-alignment-prd",
    )

    assert result["terminal_state"] == "completed"
    claims = result["claims"]
    assert claims

    target = next(item for item in claims if item["metadata"].get("category") == "target_users")
    assert target["claim_type"] == "user_confirmed"
    assert target["evidence"] == []

    public = next(item for item in claims if item["metadata"].get("category") == "public_context")
    assert public["claim_type"] == "source_backed"
    assert {item["source_type"] for item in public["evidence"]} == {"public_source"}

    implementation = next(
        item for item in claims if item["metadata"].get("category") == "implementation_status"
    )
    assert {item["source_type"] for item in implementation["evidence"]} == {
        "implementation_evidence"
    }

    simulated = next(
        item for item in claims if item["metadata"].get("category") == "simulated_pain_point"
    )
    assert {item["source_type"] for item in simulated["evidence"]} == {
        "simulated_research"
    }
    assert "模拟" in simulated["claim_text"] or "人工构造" in simulated["claim_text"]


def test_claims_and_retrieval_runs_are_persisted_with_document_version(db):
    result = DocumentLoop(db).run(
        "project_insightforge_demo",
        "techdoc",
        idempotency_key="v2-claim-persistence-techdoc",
    )
    claims = db.fetch_all(
        "SELECT * FROM document_claims WHERE version_id = ? ORDER BY id",
        (result["version_id"],),
    )
    assert claims
    assert {item["claim_type"] for item in claims} >= {"user_confirmed", "source_backed"}

    source_backed_ids = [item["id"] for item in claims if item["claim_type"] == "source_backed"]
    placeholders = ",".join("?" for _ in source_backed_ids)
    links = db.fetch_all(
        f"SELECT * FROM claim_evidence_links WHERE claim_id IN ({placeholders})",
        tuple(source_backed_ids),
    )
    assert links
    assert all(item["retrieval_run_id"] for item in links)

    generation = db.fetch_one(
        "SELECT retrieval_run_ids_json FROM generation_runs WHERE id = ?",
        (result["run_id"],),
    )
    run_ids = json.loads(generation["retrieval_run_ids_json"])
    assert run_ids
    runs = db.fetch_all(
        f"SELECT purpose FROM retrieval_runs WHERE id IN ({','.join('?' for _ in run_ids)})",
        tuple(run_ids),
    )
    assert runs
    assert all(item["purpose"].startswith("document_generation") for item in runs)


def test_claim_validator_rejects_source_type_mismatch():
    citation = "[source:public#chunk:one]"
    issues = DocumentValidator().validate(
        content=f"# 文档\n公开资料 {citation}",
        valid_citations={citation: {"source_type": "public_source"}},
        canvas={},
        claims=[
            {
                "section": "architecture",
                "claim_text": "系统已经实现远程 OAuth",
                "claim_type": "source_backed",
                "support_status": "supported_by_source_excerpt",
                "evidence": [
                    {
                        "citation": citation,
                        "source_type": "public_source",
                    }
                ],
                "metadata": {"expected_source_types": ["implementation_evidence"]},
            }
        ],
    )
    assert any(item["code"] == "claim_source_type_mismatch" for item in issues)


def test_claims_api_returns_links_and_human_readable_source_metadata(client):
    generated = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "prd", "idempotency_key": "v2-claims-api"},
    )
    assert generated.status_code == 200
    version_id = generated.json()["version_id"]

    response = client.get(f"/api/documents/{version_id}/claims")
    assert response.status_code == 200
    payload = response.json()
    assert payload["version_id"] == version_id
    assert payload["items"]
    source_backed = next(item for item in payload["items"] if item["claim_type"] == "source_backed")
    assert source_backed["evidence"]
    assert source_backed["evidence"][0]["source_title"]
    assert source_backed["evidence"][0]["source_type"]
