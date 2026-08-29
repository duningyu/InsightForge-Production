from app.services.source_guidance import SourceGuidanceService


def test_source_guidance_explains_categories_in_user_language():
    categories = SourceGuidanceService().describe_categories()
    by_id = {item["id"]: item for item in categories}
    assert "official_page" in by_id
    assert by_id["official_page"]["label"] == "产品官网或官方说明"
    assert "能证明什么" in by_id["official_page"]["help"]
    assert "不能证明" in by_id["official_page"]["help"]
    assert by_id["model_output"]["source_type"] == "model_hypothesis"


def test_official_page_mapping_is_transparent_and_not_market_validation():
    proposal = SourceGuidanceService().classify(
        origin_kind="official_page",
        title="竞品功能页",
        source_url="https://example.com/features",
        filename="features.html",
        content="官方页面展示了引用功能。",
    )
    assert proposal["source_type"] == "public_source"
    assert proposal["authority_label"] == "medium"
    assert proposal["authority"] == 0.75
    assert "官方公开页面" in proposal["authority_basis"]
    assert "不能证明用户真实需要" in proposal["limitations"]
    assert proposal["needs_confirmation"] is False


def test_unknown_origin_is_provisional_and_requires_confirmation():
    proposal = SourceGuidanceService().classify(
        origin_kind="unknown",
        title="一段资料",
        source_url=None,
        filename="note.txt",
        content="不知道来源。",
    )
    assert proposal["needs_confirmation"] is True
    assert proposal["authority_label"] == "low"
    assert "暂定" in proposal["authority_basis"]


def test_claimed_real_interview_with_simulation_language_is_downgraded():
    proposal = SourceGuidanceService().classify(
        origin_kind="real_interview",
        title="模拟访谈记录",
        source_url=None,
        publisher="受访者-01",
        published_at="2026-08-27",
        filename="interview.txt",
        content="这是合成测试材料，并非真实受访者。",
    )

    assert proposal["source_type"] == "simulated_research"
    assert proposal["authority"] <= 0.4
    assert proposal["needs_confirmation"] is True


def test_official_page_without_url_is_provisional_not_medium_authority():
    proposal = SourceGuidanceService().classify(
        origin_kind="official_page",
        title="没有链接的官网摘录",
        source_url=None,
        publisher=None,
        published_at=None,
        filename="note.txt",
        content="产品支持审批流。",
    )

    assert proposal["source_type"] == "public_source"
    assert proposal["authority"] <= 0.4
    assert proposal["needs_confirmation"] is True


def test_guided_source_creation_persists_provenance_and_claim_boundary(client):
    response = client.post(
        "/api/projects/project_insightforge_demo/sources/guided",
        json={
            "title": "ChatPRD 官方功能页",
            "origin_kind": "official_page",
            "content": "官方页面公开展示 PRD 生成与集成功能。",
            "filename": "chatprd_features.txt",
            "source_url": "https://www.chatprd.ai/product/features",
            "publisher": "ChatPRD",
            "published_at": "2026-08-20",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "public_source"
    assert payload["source_url"] == "https://www.chatprd.ai/product/features"
    assert payload["publisher"] == "ChatPRD"
    assert payload["authority_label"] == "medium"
    assert "不能证明用户真实需要" in payload["guidance"]["limitations"]
    assert payload["metadata"]["origin_kind"] == "official_page"

    listed = client.get("/api/projects/project_insightforge_demo/sources")
    assert listed.status_code == 200
    stored = next(item for item in listed.json() if item["id"] == payload["id"])
    assert stored["source_url"] == payload["source_url"]
    assert stored["authority_basis"] == payload["authority_basis"]


def test_existing_advanced_source_endpoint_remains_compatible(client):
    response = client.post(
        "/api/projects/project_insightforge_demo/sources",
        json={
            "title": "高级模式手工来源",
            "source_type": "user_input",
            "authority": 0.8,
            "content": "这是项目所有者明确输入。",
            "filename": "owner_input.txt",
        },
    )
    assert response.status_code == 201
    assert response.json()["source_type"] == "user_input"
    assert response.json()["status"] == "active"
