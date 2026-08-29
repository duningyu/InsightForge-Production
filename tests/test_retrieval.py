from app.db import utc_now
from app.retrieval import HybridRetriever
from app.services.retrieval_service import ProjectRetrievalService


def test_retrieval_never_crosses_project_scope(db):
    now = utc_now()
    db.execute(
        "INSERT INTO projects(id, title, summary, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        ("project_other", "Other", "Other project", "active", now, now),
    )
    db.add_source(
        project_id="project_other",
        title="竞品分析绝密",
        source_type="user_input",
        authority=1.0,
        content="竞品分析包含另一个项目的唯一敏感词 CROSS_PROJECT_SECRET。",
        filename="other.txt",
    )
    service = ProjectRetrievalService(db)
    hits = service.retrieve_project_sources(
        "project_insightforge_demo", "竞品分析 CROSS_PROJECT_SECRET", 20
    )
    assert hits
    assert {hit["project_id"] for hit in hits} == {"project_insightforge_demo"}
    assert all("CROSS_PROJECT_SECRET" not in hit["content"] for hit in hits)


def test_authority_breaks_close_score_ties():
    docs = [
        {"chunk_id": "low", "content": "目标用户需要结构化 PRD", "authority": 0.2},
        {"chunk_id": "high", "content": "目标用户需要结构化 PRD", "authority": 0.9},
    ]
    assert HybridRetriever().search("结构化 PRD", docs, 1)[0]["chunk_id"] == "high"


def test_source_type_filter_is_enforced(db):
    hits = ProjectRetrievalService(db).retrieve_project_sources(
        "project_insightforge_demo",
        "项目目标和关键要求",
        10,
        source_types=["user_input"],
    )
    assert hits
    assert {hit["source_type"] for hit in hits} == {"user_input"}


def test_retrieval_payload_contains_score_components(db):
    hits = ProjectRetrievalService(db).retrieve_project_sources(
        "project_insightforge_demo", "来源引用和版本", 5
    )
    assert hits
    assert {"bm25_score", "cosine_score", "authority_score", "hybrid_score"} <= hits[0].keys()
