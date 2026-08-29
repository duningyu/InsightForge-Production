from io import BytesIO

from fastapi.testclient import TestClient


def test_health_home_and_demo_project_catalog(client):
    home = client.get("/")
    assert home.status_code == 200
    assert "InsightForge" in home.text

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["max_loop_rounds"] == 2

    projects = client.get("/api/projects")
    assert projects.status_code == 200
    assert projects.json()[0]["id"] == "project_insightforge_demo"

    detail = client.get("/api/projects/project_insightforge_demo")
    assert detail.status_code == 200
    assert detail.json()["canvas"]["version"] == 1
    assert len(detail.json()["sources"]) >= 4


def test_create_project_then_update_canvas(client):
    created = client.post(
        "/api/projects",
        json={"title": "新产品项目", "summary": "用于验证项目与画布生命周期。"},
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    missing_canvas = client.get(f"/api/projects/{project_id}/canvas")
    assert missing_canvas.status_code == 404

    updated = client.put(
        f"/api/projects/{project_id}/canvas",
        json={
            "problem": "资料缺少统一来源和版本。",
            "target_users": "AI 产品经理。",
            "goals": ["生成可追溯文档"],
            "non_goals": ["不自动发布"],
            "success_metrics": ["引用完整率 100%"],
            "constraints": ["默认本地运行"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 1

    updated_again = client.put(
        f"/api/projects/{project_id}/canvas",
        json={
            "problem": "资料缺少统一来源、版本和审批边界。",
            "target_users": "AI 产品经理与 AI coding 协作者。",
            "goals": ["生成可追溯文档"],
            "non_goals": ["不自动发布"],
            "success_metrics": ["引用完整率 100%"],
            "constraints": ["默认本地运行"],
        },
    )
    assert updated_again.json()["version"] == 2


def test_old_document_revalidation_uses_its_canvas_snapshot(client):
    generated = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "prd", "idempotency_key": "snapshot-v1"},
    ).json()
    current = client.get("/api/projects/project_insightforge_demo/canvas").json()
    changed = {
        "problem": "这是之后才出现、与旧文档无关的新问题。",
        "target_users": current["target_users"],
        "goals": current["goals"],
        "non_goals": current["non_goals"],
        "success_metrics": current["success_metrics"],
        "constraints": current["constraints"],
    }
    assert client.put(
        "/api/projects/project_insightforge_demo/canvas", json=changed
    ).json()["version"] == 2

    validated = client.post(f"/api/documents/{generated['version_id']}/validate")
    assert validated.status_code == 200
    assert validated.json()["validation_status"] == "passed"


def test_add_text_and_uploaded_sources(client):
    created = client.post(
        "/api/projects/project_insightforge_demo/sources",
        json={
            "title": "人工补充需求",
            "source_type": "user_input",
            "authority": 0.8,
            "content": "用户要求导出内容必须带版本号和引用。",
            "filename": "manual.txt",
        },
    )
    assert created.status_code == 201
    assert created.json()["source_type"] == "user_input"

    uploaded = client.post(
        "/api/projects/project_insightforge_demo/sources/upload",
        data={
            "title": "补充公开资料",
            "source_type": "public_source",
            "authority": "0.6",
        },
        files={"file": ("notes.md", BytesIO("公开资料强调引用可追溯。".encode()), "text/markdown")},
    )
    assert uploaded.status_code == 201
    assert uploaded.json()["filename"] == "notes.md"


def test_retrieve_generate_validate_and_read_version(client):
    retrieved = client.post(
        "/api/projects/project_insightforge_demo/retrieve",
        json={"query": "项目目标 来源 引用", "top_k": 5, "source_types": None},
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["items"]
    assert {item["project_id"] for item in retrieved.json()["items"]} == {
        "project_insightforge_demo"
    }

    generated = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "prd", "idempotency_key": "api-prd-v1"},
    )
    assert generated.status_code == 200
    body = generated.json()
    assert body["version_id"]
    assert body["terminal_state"] == "completed"
    assert body["validation_status"] == "passed"

    version = client.get(f"/api/documents/{body['version_id']}")
    assert version.status_code == 200
    assert version.json()["project_id"] == "project_insightforge_demo"
    assert "[source:" in version.json()["content"]

    validated = client.post(f"/api/documents/{body['version_id']}/validate")
    assert validated.status_code == 200
    assert validated.json()["validation_status"] == "passed"
    assert validated.json()["issues"] == []


def test_approval_requires_explicit_human_confirmation(client):
    draft = client.post(
        "/api/projects/project_insightforge_demo/generate",
        json={"doc_type": "techdoc", "idempotency_key": "api-approval-v1"},
    ).json()

    denied = client.post(
        f"/api/documents/{draft['version_id']}/approve",
        json={"actor": "pm_demo", "note": "已人工检查", "human_confirmed": False},
    )
    assert denied.status_code == 403

    accepted = client.post(
        f"/api/documents/{draft['version_id']}/approve",
        json={"actor": "pm_demo", "note": "已人工检查", "human_confirmed": True},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "approved"


def test_unknown_project_returns_404(client):
    response = client.post(
        "/api/projects/missing/retrieve",
        json={"query": "anything", "top_k": 5, "source_types": None},
    )
    assert response.status_code == 404


def test_basic_auth_can_protect_internet_facing_app(db, monkeypatch):
    from app.main import create_app

    monkeypatch.setenv("INSIGHTFORGE_ACCESS_USERNAME", "reviewer")
    monkeypatch.setenv("INSIGHTFORGE_ACCESS_PASSWORD", "a-long-test-password")
    with TestClient(create_app(database_path=db.path, seed=False)) as protected:
        assert protected.get("/api/health").status_code == 200
        denied = protected.get("/")
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"].startswith("Basic")
        assert protected.get("/", auth=("reviewer", "a-long-test-password")).status_code == 200


def test_upload_size_limit_is_enforced_before_ingestion(client):
    oversized = BytesIO(b"x" * (12 * 1024 * 1024 + 1))
    response = client.post(
        "/api/projects/project_insightforge_demo/sources/upload",
        data={"title": "oversized", "source_type": "user_input", "authority": "0.5"},
        files={"file": ("large.txt", oversized, "text/plain")},
    )
    assert response.status_code == 422
    assert "file exceeds" in response.json()["detail"]
