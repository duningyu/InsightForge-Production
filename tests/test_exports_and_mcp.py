import json

import pytest

from app.services.loop import DocumentLoop


@pytest.fixture()
def completed_version(db):
    result = DocumentLoop(db).run(
        "project_insightforge_demo",
        "prd",
        idempotency_key="completed-version-fixture",
    )
    row = db.fetch_one(
        "SELECT * FROM document_versions WHERE id = ?", (result["version_id"],)
    )
    assert row is not None
    row["citations"] = json.loads(row.pop("citations_json"))
    return row


@pytest.fixture()
def exporter():
    from app.exporters import ArtifactExporter

    return ArtifactExporter()


@pytest.fixture()
def mcp_functions(db):
    from app.mcp_functions import InsightForgeMCPFunctions

    return InsightForgeMCPFunctions(db)


def test_markdown_json_and_docx_exports_are_nonempty(exporter, completed_version):
    markdown = exporter.to_markdown(completed_version)
    json_text = exporter.to_json_text(completed_version)
    docx = exporter.to_docx_bytes(completed_version)

    assert markdown.startswith("#")
    payload = json.loads(json_text)
    assert payload["id"] == completed_version["id"]
    assert payload["citations"]
    assert docx.startswith(b"PK")
    assert len(docx) > 500


def test_mcp_retrieval_wrapper_is_project_scoped(mcp_functions):
    result = mcp_functions.retrieve_project_sources(
        "project_insightforge_demo", "项目目标和来源", 5
    )
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {
        "project_insightforge_demo"
    }


def test_mcp_resource_wrappers_enforce_project_scope(mcp_functions, db):
    source = db.fetch_one(
        "SELECT id FROM sources WHERE project_id = ? LIMIT 1",
        ("project_insightforge_demo",),
    )
    assert source is not None
    resource = mcp_functions.get_source_resource(
        "project_insightforge_demo", source["id"]
    )
    assert resource["project_id"] == "project_insightforge_demo"

    with pytest.raises(KeyError):
        mcp_functions.get_source_resource("wrong_project", source["id"])


def test_mcp_create_draft_and_get_document(mcp_functions):
    created = mcp_functions.create_artifact_draft(
        "project_insightforge_demo",
        "techdoc",
        "mcp-techdoc-v1",
    )
    assert created["terminal_state"] == "completed"
    resource = mcp_functions.get_document_version(created["version_id"])
    assert resource["project_id"] == "project_insightforge_demo"
    assert resource["doc_type"] == "techdoc"


def test_api_exports_markdown_json_and_docx(client):
    generated = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "prd", "idempotency_key": "api-export-v1"},
    ).json()
    version_id = generated["version_id"]

    markdown = client.get(f"/api/documents/{version_id}/export", params={"format": "md"})
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert markdown.text.startswith("#")

    json_response = client.get(
        f"/api/documents/{version_id}/export", params={"format": "json"}
    )
    assert json_response.status_code == 200
    assert json_response.json()["id"] == version_id

    docx = client.get(f"/api/documents/{version_id}/export", params={"format": "docx"})
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
    assert len(docx.content) > 500
