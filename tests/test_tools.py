import pytest


def _tool_names(registry):
    return {item["function"]["name"] for item in registry.schemas()}


def test_tool_schemas_are_strict(registry):
    schemas = registry.schemas()
    assert schemas
    for tool in schemas:
        function = tool["function"]
        assert function["strict"] is True
        assert function["parameters"]["additionalProperties"] is False
        assert function["x-risk-level"] in {"L0", "L1", "L2"}


def test_required_tools_are_registered_and_dangerous_tools_are_absent(registry):
    names = _tool_names(registry)
    assert {
        "retrieve_project_sources",
        "get_project_canvas",
        "get_document_version",
        "create_document_draft",
        "run_document_validator",
        "export_artifact",
        "approve_document_version",
    } <= names
    assert {
        "delete_project",
        "publish_external",
        "overwrite_approved_version",
    }.isdisjoint(names)


def test_unknown_arguments_are_rejected(registry):
    with pytest.raises(ValueError, match="unknown arguments"):
        registry.execute(
            "get_project_canvas",
            {"project_id": "project_insightforge_demo", "secret": "x"},
            actor="product_manager",
        )


def test_retrieval_tool_is_project_scoped_and_audited(registry, db):
    result = registry.execute(
        "retrieve_project_sources",
        {
            "project_id": "project_insightforge_demo",
            "query": "项目目标和来源引用",
            "top_k": 5,
            "source_types": [],
        },
        actor="product_manager",
    )
    assert result["items"]
    assert {item["project_id"] for item in result["items"]} == {
        "project_insightforge_demo"
    }
    event = db.fetch_one(
        "SELECT * FROM audit_events WHERE action = 'tool_executed' ORDER BY created_at DESC LIMIT 1"
    )
    assert event is not None
    assert event["entity_id"] == "retrieve_project_sources"


def test_create_document_draft_is_idempotent(registry):
    arguments = {
        "project_id": "project_insightforge_demo",
        "doc_type": "prd",
        "idempotency_key": "tool-test-prd-v1",
    }
    first = registry.execute(
        "create_document_draft",
        arguments,
        actor="product_manager",
        human_confirmed=True,
    )
    second = registry.execute(
        "create_document_draft",
        arguments,
        actor="product_manager",
        human_confirmed=True,
    )
    assert first["version_id"] == second["version_id"]
    assert second["reused"] is True


def test_l2_approval_requires_host_confirmation(registry):
    draft = registry.execute(
        "create_document_draft",
        {
            "project_id": "project_insightforge_demo",
            "doc_type": "techdoc",
            "idempotency_key": "approval-test-techdoc-v1",
        },
        actor="product_manager",
        human_confirmed=True,
    )
    with pytest.raises(PermissionError):
        registry.execute(
            "approve_document_version",
            {"version_id": draft["version_id"], "note": "人工复核通过"},
            actor="product_manager",
            human_confirmed=False,
        )
    approved = registry.execute(
        "approve_document_version",
        {"version_id": draft["version_id"], "note": "人工复核通过"},
        actor="product_manager",
        human_confirmed=True,
    )
    assert approved["status"] == "approved"
    assert approved["approved_at"]
