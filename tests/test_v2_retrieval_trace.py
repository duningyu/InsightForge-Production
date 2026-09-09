import json

from app.services.retrieval_service import ProjectRetrievalService


def test_execute_retrieval_persists_profile_and_ranked_hits(db):
    result = ProjectRetrievalService(db).execute_retrieval(
        "project_insightforge_demo",
        "来源引用和版本",
        profile_id="quick_explore_v1",
        purpose="guided_evidence_check",
        actor="tester",
    )

    assert result["run_id"].startswith("retrieval_")
    assert result["config"]["profile_id"] == "quick_explore_v1"
    assert result["config"]["effective_top_k"] == 4
    assert result["config"]["validation_status"] == "manual_baseline_not_frozen_best"
    assert "未通过冻结评测集证明最优" in result["config"]["selection_basis"]
    assert result["candidate_count"] >= result["returned_count"] >= 1
    assert len(result["items"]) <= 4

    run = db.fetch_one("SELECT * FROM retrieval_runs WHERE id = ?", (result["run_id"],))
    assert run is not None
    assert run["purpose"] == "guided_evidence_check"
    assert run["actor"] == "tester"
    assert json.loads(run["source_types_json"]) == []

    hits = db.fetch_all(
        "SELECT * FROM retrieval_hits WHERE run_id = ? ORDER BY rank",
        (result["run_id"],),
    )
    assert len(hits) == result["returned_count"]
    assert hits[0]["project_id"] == "project_insightforge_demo"
    assert hits[0]["rank"] == 1


def test_explicit_top_k_is_disclosed_as_override(db):
    result = ProjectRetrievalService(db).execute_retrieval(
        "project_insightforge_demo",
        "项目目标",
        profile_id="balanced_traceable_v1",
        top_k=2,
        purpose="advanced_manual_search",
        actor="tester",
    )
    assert result["config"]["effective_top_k"] == 2
    assert result["config"]["top_k_source"] == "explicit_override"
    assert len(result["items"]) <= 2


def test_trace_endpoint_returns_run_and_project_scoped_hits(client):
    response = client.post(
        "/api/projects/project_insightforge_demo/retrieve",
        json={
            "query": "项目目标和来源",
            "profile_id": "balanced_traceable_v1",
            "source_types": None,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"]
    assert payload["config"]["profile_id"] == "balanced_traceable_v1"

    detail = client.get(f"/api/retrieval/runs/{payload['run_id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == payload["run_id"]
    assert {item["project_id"] for item in detail.json()["items"]} == {
        "project_insightforge_demo"
    }

    listed = client.get(
        "/api/projects/project_insightforge_demo/retrieval-runs", params={"limit": 10}
    )
    assert listed.status_code == 200
    assert any(item["id"] == payload["run_id"] for item in listed.json())


def test_profiles_endpoint_explains_beginner_tradeoffs(client):
    response = client.get("/api/retrieval/profiles")
    assert response.status_code == 200
    profiles = response.json()
    balanced = next(item for item in profiles if item["id"] == "balanced_traceable_v1")
    assert balanced["label"] == "平衡查证"
    assert balanced["top_k"] == 8
    assert balanced["tradeoff"]


def test_unknown_profile_is_rejected(client):
    response = client.post(
        "/api/projects/project_insightforge_demo/retrieve",
        json={"query": "项目", "profile_id": "made_up", "source_types": None},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "INVALID_RETRIEVAL_PROFILE"
    assert "检索配置" in response.json()["detail"]
