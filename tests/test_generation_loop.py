from app.services.generation import LocalDocumentGenerator
from app.services.loop import DocumentLoop
from app.services.validation import DocumentValidator


def test_generated_prd_contains_citations_and_source_labels(db):
    result = DocumentLoop(db).run("project_insightforge_demo", "prd")
    assert result["terminal_state"] == "completed"
    assert "[source:" in result["content"]
    assert "simulated_research" in result["content"]
    assert result["citations"]
    assert result["rounds"] <= 2


def test_generated_techdoc_is_persisted_as_version(db):
    result = DocumentLoop(db).run("project_insightforge_demo", "techdoc")
    row = db.fetch_one("SELECT * FROM document_versions WHERE id = ?", (result["version_id"],))
    assert row is not None
    assert row["doc_type"] == "techdoc"
    assert row["validation_status"] == "passed"


def test_validator_rejects_unqualified_real_research_claim():
    issues = DocumentValidator().validate(
        content="真实用户调研证明所有用户都需要该功能。",
        valid_citations={},
        canvas={},
    )
    assert any(issue["code"] == "unsupported_real_research_claim" for issue in issues)


def test_validator_rejects_out_of_project_citation():
    issues = DocumentValidator().validate(
        content="# 文档\n[source:other#chunk:outside]",
        valid_citations={"[source:ok#chunk:inside]": {}},
        canvas={},
    )
    assert any(issue["code"] == "citation_out_of_scope" for issue in issues)


def test_idempotency_key_reuses_existing_version(db):
    loop = DocumentLoop(db)
    first = loop.run(
        "project_insightforge_demo", "prd", idempotency_key="same-request"
    )
    second = loop.run(
        "project_insightforge_demo", "prd", idempotency_key="same-request"
    )
    assert first["version_id"] == second["version_id"]
    assert second["reused"] is True
