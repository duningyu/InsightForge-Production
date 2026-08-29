from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.db import Database
from app.main import create_app


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v206_schema.sql"


def _build_v206_database(path: Path) -> dict[str, str]:
    connection = sqlite3.connect(path)
    connection.executescript(FIXTURE.read_text(encoding="utf-8"))
    now = "2026-08-24T10:00:00+00:00"
    ids = {
        "project": "legacy_project_1",
        "source": "legacy_source_1",
        "chunk": "legacy_chunk_1",
        "document": "legacy_doc_prd",
        "version": "legacy_prd_v1",
        "doc_claim": "legacy_doc_claim_1",
        "decision": "legacy_decision_1",
    }
    connection.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (ids["project"], "旧版补货项目", "帮助小店减少补货遗漏", "active", now, now),
    )
    canvas = {
        "problem": "店主依赖人工经验判断补货，容易遗漏畅销商品。",
        "target_users": "小型便利店店主",
        "goals": ["每天得到待补货清单"],
        "non_goals": ["不自动下采购单"],
        "success_metrics": ["店主能完成一次补货确认"],
        "constraints": ["单人两周内完成", "不接 ERP"],
    }
    connection.execute(
        """
        INSERT INTO project_canvas(
            project_id,version,problem,target_users,goals_json,non_goals_json,
            success_metrics_json,constraints_json,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ids["project"], 2, canvas["problem"], canvas["target_users"],
            json.dumps(canvas["goals"], ensure_ascii=False),
            json.dumps(canvas["non_goals"], ensure_ascii=False),
            json.dumps(canvas["success_metrics"], ensure_ascii=False),
            json.dumps(canvas["constraints"], ensure_ascii=False), now, now,
        ),
    )
    connection.execute(
        """
        INSERT INTO project_canvas_versions(
            project_id,version,problem,target_users,goals_json,non_goals_json,
            success_metrics_json,constraints_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            ids["project"], 2, canvas["problem"], canvas["target_users"],
            json.dumps(canvas["goals"], ensure_ascii=False),
            json.dumps(canvas["non_goals"], ensure_ascii=False),
            json.dumps(canvas["success_metrics"], ensure_ascii=False),
            json.dumps(canvas["constraints"], ensure_ascii=False), now,
        ),
    )
    options = [
        {"id": "legacy_rule", "title": "规则补货提醒", "summary": "根据库存阈值提醒"},
        {"id": "legacy_manual", "title": "人工盘点流程", "summary": "保留人工确认"},
    ]
    connection.execute(
        """
        INSERT INTO project_decisions(id,project_id,decision_type,options_json,selected_option_id,rationale,status,created_at,confirmed_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            ids["decision"], ids["project"], "guided_solution",
            json.dumps(options, ensure_ascii=False), "legacy_rule", "旧版用户明确选择", "confirmed", now, now,
        ),
    )
    source_content = "这是公开补货规则说明，不是用户访谈，也不能证明市场需求。"
    connection.execute(
        """
        INSERT INTO sources(
            id,project_id,title,filename,source_type,authority,content,sha256,
            source_url,publisher,published_at,captured_at,authority_label,authority_basis,status,metadata_json,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ids["source"], ids["project"], "公开规则", "rules.md", "public_source", 0.7,
            source_content, "legacysha", None, None, None, now, "medium", "legacy fixture", "active", "{}", now,
        ),
    )
    connection.execute(
        "INSERT INTO source_chunks(id,source_id,project_id,chunk_index,content,created_at) VALUES (?,?,?,?,?,?)",
        (ids["chunk"], ids["source"], ids["project"], 0, source_content, now),
    )
    connection.execute(
        "INSERT INTO documents(id,project_id,doc_type,title,created_at) VALUES (?,?,?,?,?)",
        (ids["document"], ids["project"], "prd", "旧版 PRD", now),
    )
    connection.execute(
        """
        INSERT INTO document_versions(
            id,document_id,project_id,doc_type,version,canvas_version,status,content,citations_json,
            validation_status,idempotency_key,created_at,approved_at,lifecycle_status,trashed_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ids["version"], ids["document"], ids["project"], "prd", 1, 2, "approved",
            "# 旧版 PRD\n\nAI 曾写过：所有便利店都需要这个功能。该句不能被迁移成市场事实。",
            json.dumps([ids["chunk"]]), "passed", "legacy-idem", now, now, "active", None,
        ),
    )
    connection.execute(
        """
        INSERT INTO document_claims(id,version_id,project_id,section,claim_text,claim_type,support_status,explanation,metadata_json,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ids["doc_claim"], ids["version"], ids["project"], "用户问题",
            "所有便利店都需要这个功能", "model_suggestion", "unresolved", "旧模型建议", "{}", now,
        ),
    )
    connection.commit()
    connection.close()
    return ids


def test_legacy_migration_is_idempotent_preserves_ids_and_does_not_invent_market_validation(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    ids = _build_v206_database(path)
    db = Database(path)
    db.init_schema()

    from app.services.legacy_migration import LegacyMigrationService

    service = LegacyMigrationService(db)
    first = service.migrate_project(ids["project"])
    second = service.migrate_project(ids["project"])

    assert first is not None
    assert first["snapshot_origin"] == "legacy_migration"
    assert second["id"] == first["id"]
    assert db.fetch_one("SELECT COUNT(*) AS n FROM project_snapshots WHERE project_id=?", (ids["project"],))["n"] == 1
    assert db.fetch_one("SELECT current_snapshot_id FROM projects WHERE id=?", (ids["project"],))["current_snapshot_id"] == first["id"]

    assert db.fetch_one("SELECT id FROM sources WHERE id=?", (ids["source"],))["id"] == ids["source"]
    assert db.fetch_one("SELECT id FROM source_chunks WHERE id=?", (ids["chunk"],))["id"] == ids["chunk"]
    assert db.fetch_one("SELECT id FROM document_versions WHERE id=?", (ids["version"],))["id"] == ids["version"]
    historical_claim = db.fetch_one("SELECT * FROM document_claims WHERE id=?", (ids["doc_claim"],))
    assert historical_claim["claim_text"] == "所有便利店都需要这个功能"
    assert historical_claim["claim_type"] == "model_suggestion"

    project_claims = db.fetch_all("SELECT provenance,verification_status,statement FROM project_claims WHERE project_id=?", (ids["project"],))
    assert project_claims
    assert all(row["provenance"] in {"user_input", "model_hypothesis"} for row in project_claims)
    assert all(row["verification_status"] == "unverified" for row in project_claims)
    assert all("所有便利店都需要" not in row["statement"] for row in project_claims)
    assert db.fetch_one(
        "SELECT COUNT(*) AS n FROM project_claim_evidence_links pcl JOIN project_claims pc ON pc.id=pcl.claim_id WHERE pc.project_id=?",
        (ids["project"],),
    )["n"] == 0


def test_new_quick_start_project_has_no_guided_session_and_guide_get_is_404(client):
    quick = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    )
    assert quick.status_code == 201, quick.text
    project_id = quick.json()["project_id"]
    assert client.app.state.db.fetch_one("SELECT id FROM guided_sessions WHERE project_id=?", (project_id,)) is None
    response = client.get(f"/api/projects/{project_id}/guide")
    assert response.status_code == 404
    assert "legacy guided session not found" in response.json()["detail"]


def test_existing_legacy_guided_session_remains_readable_and_writable_in_3_0_release_line(client):
    project = client.post("/api/projects", json={"title": "Legacy Guide", "summary": "旧项目"}).json()
    raw = client.app.state.projects.get_project(project["id"])
    client.app.state.guided._create_session(raw)

    read = client.get(f"/api/projects/{project['id']}/guide")
    assert read.status_code == 200
    response = client.post(
        f"/api/projects/{project['id']}/guide/respond",
        json={"answer": "转岗产品经理", "choice_id": None},
    )
    assert response.status_code == 200
    assert response.json()["current_step"] == "problem"


def test_seeded_legacy_examples_receive_explicit_legacy_snapshots_on_startup(tmp_path):
    app = create_app(database_path=tmp_path / "seeded.sqlite3", seed=True)
    with TestClient(app) as client:
        detail = client.get("/api/projects/project_example_inventory_alert").json()
        assert detail["current_snapshot_id"]
        snapshot = client.get("/api/projects/project_example_inventory_alert/snapshot")
        assert snapshot.status_code == 200
        assert snapshot.json()["snapshot_origin"] == "legacy_migration"
        simulated = [item for item in detail["sources"] if item["source_type"] == "simulated_research"]
        assert simulated
        claims = client.get("/api/projects/project_example_inventory_alert/claims").json()
        assert all(item["verification_status"] == "unverified" for item in claims)


def test_legacy_guide_routes_are_marked_deprecated_in_openapi(client):
    schema = client.get("/openapi.json").json()
    for path, method in (
        ("/api/projects/{project_id}/guide", "get"),
        ("/api/projects/{project_id}/guide/respond", "post"),
        ("/api/projects/{project_id}/guide/apply", "post"),
        ("/api/projects/{project_id}/guide/reset", "post"),
        ("/api/projects/{project_id}/guide/back", "post"),
    ):
        assert schema["paths"][path][method]["deprecated"] is True
