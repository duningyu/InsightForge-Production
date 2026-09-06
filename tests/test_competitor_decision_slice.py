"""RED coverage for the competitor decision vertical slice."""

import asyncio
import json
from pathlib import Path

import httpx

from test_open_accounts import claim, portal
from app.services.provider_adapters import AsyncModelAdapter

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "v3_golden_cases.json"


def test_async_adapter_exposes_competitor_comparison_business_call():
    """The managed async runtime must reach the real adapter transport."""
    response_payload = {
        "competitors": [{"candidate_id": "candidate-a", "name": "合成产品A"}],
        "project_level": {},
        "uncertainty_notice": "AI分析参考，建议结合实际产品页面核对。",
    }

    async def run():
        calls = []

        async def send(request):
            calls.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": json.dumps(response_payload, ensure_ascii=False)}}]},
            )

        adapter = AsyncModelAdapter(
            provider="qwen",
            model="synthetic-model",
            api_key="SYNTHETIC-TEST-ONLY",
            client=httpx.AsyncClient(transport=httpx.MockTransport(send)),
        )
        try:
            result = await adapter.compare_competitors_async(
                [{"candidate_id": "candidate-a", "name": "合成产品A"}]
            )
            assert result.competitors[0].candidate_id == "candidate-a"
            assert len(calls) == 1
        finally:
            await adapter.aclose()

    asyncio.run(run())


def _project(client, title="竞品决策项目"):
    response = client.post("/api/projects", json={"title": title, "summary": "合成项目"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _candidate(client, project_id, name):
    response = client.post(
        f"/api/projects/{project_id}/competitors",
        json={"name": name, "description": f"{name} 的用户输入说明"},
    )
    assert response.status_code == 201, response.text
    candidate = response.json()
    selected = client.put(
        f"/api/projects/{project_id}/competitors/{candidate['id']}/selection",
        json={"selected": True},
    )
    assert selected.status_code == 200, selected.text
    return candidate


def test_selected_candidates_can_be_compared_and_saved_as_immutable_snapshot(portal):
    app, client = portal
    claim(app, client, 801)
    project_id = _project(client)
    first = _candidate(client, project_id, "合成产品A")
    second = _candidate(client, project_id, "合成产品B")

    comparison = client.post(
        f"/api/projects/{project_id}/competitor-comparisons",
        json={"candidate_ids": [first["id"], second["id"]]},
    )
    assert comparison.status_code == 201, comparison.text
    comparison_body = comparison.json()
    assert comparison_body["comparison"]["competitors"][0]["name"] == "合成产品A"
    assert comparison_body["comparison"]["uncertainty_notice"]

    snapshot = client.post(
        f"/api/projects/{project_id}/competitor-snapshots",
        json={
            "comparison_id": comparison_body["id"],
            "decisions": [
                {"candidate_id": first["id"], "decision": "adopt", "reason": "借鉴分步引导"},
                {"candidate_id": second["id"], "decision": "defer", "reason": "先验证个人流程"},
            ],
        },
    )
    assert snapshot.status_code == 201, snapshot.text
    snapshot_body = snapshot.json()
    assert snapshot_body["decision_snapshot"]["decisions"][0]["decision"] == "adopt"
    assert snapshot_body["decision_snapshot"]["content_sha256"]

    before = client.get(
        f"/api/projects/{project_id}/competitor-snapshots/{snapshot_body['id']}"
    ).json()
    changed = client.post(
        f"/api/projects/{project_id}/competitor-snapshots",
        json={
            "comparison_id": comparison_body["id"],
            "decisions": [
                {"candidate_id": first["id"], "decision": "avoid", "reason": "不复制复杂后台"},
            ],
        },
    )
    assert changed.status_code == 201, changed.text
    assert client.get(
        f"/api/projects/{project_id}/competitor-snapshots/{snapshot_body['id']}"
    ).json() == before


def test_competitor_comparison_and_snapshot_are_project_scoped(portal):
    app, client = portal
    claim(app, client, 802)
    project_a = _project(client, "A 的竞品项目")
    candidate_a = _candidate(client, project_a, "A 私有产品")
    comparison = client.post(
        f"/api/projects/{project_a}/competitor-comparisons",
        json={"candidate_ids": [candidate_a["id"]]},
    )
    assert comparison.status_code == 201, comparison.text
    snapshot = client.post(
        f"/api/projects/{project_a}/competitor-snapshots",
        json={"comparison_id": comparison.json()["id"], "decisions": []},
    )
    assert snapshot.status_code == 201, snapshot.text
    snapshot_id = snapshot.json()["id"]

    client.post("/api/auth/logout")
    claim(app, client, 803)
    project_b = _project(client, "B 的竞品项目")
    for path in (
        f"/api/projects/{project_b}/competitor-comparisons",
        f"/api/projects/{project_b}/competitor-snapshots/{snapshot_id}",
    ):
        response = client.get(path) if "snapshots/" in path else client.post(path, json={"candidate_ids": [candidate_a["id"]]})
        assert response.status_code in {403, 404}
        assert "A 私有产品" not in response.text


def test_solution_brief_contract_carries_competitor_decision_context():
    from app.services.solution_design import SolutionDesignService

    row = {
        "original_idea": "帮助新手做决定",
        "target_user": "初学者",
        "problem": "不知道先做什么",
        "desired_outcome": "得到可执行方案",
        "known_resources_json": "[]",
        "constraints_json": "[]",
        "unknowns_json": "[]",
        "provenance_json": json.dumps({"original_idea": "user_input", "target_user": "user_input", "problem": "user_input", "desired_outcome": "user_input"}),
        "clarification_required": 0,
        "clarification_question": None,
    }
    brief = SolutionDesignService._brief_from_row(
        row,
        competitor_context={
            "adopt": ["借鉴竞品A的分步引导"],
            "avoid": ["第一版不做团队协作"],
            "defer": ["复杂报表以后再考虑"],
        },
    )
    assert brief.competitor_context["adopt"] == ["借鉴竞品A的分步引导"]


def test_solution_generation_passes_snapshot_decisions_into_model_context(db):
    from app.schemas import SolutionSetDraft
    from app.services.solution_design import SolutionDesignService
    from test_v3_solution_design import candidate

    project_id = "project_competitor_context"
    now = "2026-09-06T00:00:00+00:00"
    db.execute(
        "INSERT INTO projects(id,title,summary,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
        (project_id, "上下文捕获项目", "合成", "active", now, now),
    )
    db.execute(
        """
        INSERT INTO idea_briefs(
            id, project_id, version, original_idea, target_user, problem,
            desired_outcome, known_resources_json, constraints_json, unknowns_json,
            provenance_json, confirmation_status, created_at
        ) VALUES (?, ?, 1, ?, ?, ?, ?, '[]', '[]', '[]', ?, 'confirmed', ?)
        """,
        (
            "brief_competitor_context",
            project_id,
            "帮助新手做决定",
            "初学者",
            "不知道先做什么",
            "得到可执行方案",
            json.dumps({"original_idea": "user_input", "target_user": "user_input"}),
            now,
        ),
    )
    snapshot_id = "competitor_snapshot_context"
    db.execute(
        """
        INSERT INTO competitor_comparisons(
            id, project_id, created_by, candidate_ids_json, result_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "comparison_context",
            project_id,
            "synthetic-owner",
            json.dumps(["candidate-a"]),
            json.dumps({"competitors": []}),
            now,
        ),
    )
    db.execute(
        """
        INSERT INTO competitor_decision_snapshots(
            id, project_id, created_by, comparison_id, candidate_ids_json,
            content_json, content_sha256, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_id,
            project_id,
            "synthetic-owner",
            "comparison_context",
            json.dumps(["candidate-a"]),
            json.dumps(
                {
                    "project_id": project_id,
                    "decisions": [
                        {"candidate_id": "candidate-a", "decision": "adopt", "rationale": "借鉴分步引导"},
                        {"candidate_id": "candidate-a", "decision": "avoid", "rationale": "第一版不做团队协作"},
                        {"candidate_id": "candidate-a", "decision": "defer", "rationale": "复杂报表以后再考虑"},
                    ],
                    "boundary": "AI分析参考，建议结合实际产品页面核对。",
                },
                ensure_ascii=False,
            ),
            "synthetic-hash",
            now,
        ),
    )
    db.execute(
        "UPDATE projects SET current_competitor_snapshot_id=? WHERE id=?",
        (snapshot_id, project_id),
    )

    class CaptureRuntime:
        provider = "fake"
        model = "fake-model"
        mode = "test"
        prompt_version = "test"
        schema_version = "test"

        def __init__(self):
            self.captured = None

        def design_solutions(self, brief, **_kwargs):
            self.captured = brief
            return SolutionSetDraft(
                candidates=[
                    candidate("rule_based", "profile", "low", "confirm", "threshold", "sqlite", title="轻量方案"),
                    candidate("workflow_based", "profile", "medium", "review", "checklist", "web", title="流程方案"),
                ],
                llm_core_required=False,
            )

    runtime = CaptureRuntime()
    result = SolutionDesignService(db, runtime).generate(project_id, actor="synthetic-owner")

    assert result["run"]["status"] == "completed_two_candidates"
    assert runtime.captured.competitor_context == {
        "snapshot_id": snapshot_id,
        "boundary": "AI分析参考，建议结合实际产品页面核对。",
        "adopt": [{"candidate_id": "candidate-a", "rationale": "借鉴分步引导"}],
        "avoid": [{"candidate_id": "candidate-a", "rationale": "第一版不做团队协作"}],
        "defer": [{"candidate_id": "candidate-a", "rationale": "复杂报表以后再考虑"}],
    }


def test_document_version_records_exact_competitor_snapshot_and_old_version_stays_stable(db):
    from app.services.loop import DocumentLoop

    project_id = "project_insightforge_demo"
    first_snapshot = "competitor_snapshot_v1"
    second_snapshot = "competitor_snapshot_v2"
    now = "2026-09-06T00:00:00+00:00"
    for snapshot_id, marker in ((first_snapshot, "第一版取舍"), (second_snapshot, "第二版取舍")):
        comparison_id = "comparison-" + snapshot_id
        db.execute(
            """
            INSERT INTO competitor_comparisons(
                id, project_id, created_by, candidate_ids_json, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                comparison_id,
                project_id,
                "synthetic-owner",
                "[]",
                json.dumps({"competitors": []}),
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO competitor_decision_snapshots(
                id, project_id, created_by, comparison_id, candidate_ids_json,
                content_json, content_sha256, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (snapshot_id, project_id, "synthetic-owner", comparison_id,
             "[]", json.dumps({"marker": marker}, ensure_ascii=False), "hash-" + snapshot_id, now),
        )

    db.execute("UPDATE projects SET current_competitor_snapshot_id=? WHERE id=?", (first_snapshot, project_id))
    first = DocumentLoop(db).run(project_id, "prd", idempotency_key="competitor-doc-v1")
    first_row = db.fetch_one("SELECT * FROM document_versions WHERE id=?", (first["version_id"],))
    assert first_row["competitor_snapshot_id"] == first_snapshot

    db.execute("UPDATE projects SET current_competitor_snapshot_id=? WHERE id=?", (second_snapshot, project_id))
    second = DocumentLoop(db).run(project_id, "prd", idempotency_key="competitor-doc-v2")
    second_row = db.fetch_one("SELECT * FROM document_versions WHERE id=?", (second["version_id"],))
    assert second_row["competitor_snapshot_id"] == second_snapshot
    assert db.fetch_one("SELECT competitor_snapshot_id FROM document_versions WHERE id=?", (first["version_id"],))["competitor_snapshot_id"] == first_snapshot


def test_document_versions_have_competitor_snapshot_reference_column(db):
    columns = {row["name"] for row in db.fetch_all("PRAGMA table_info(document_versions)")}
    assert "competitor_snapshot_id" in columns


def test_skipping_competitor_comparison_keeps_solution_and_document_flow_optional(db):
    from app.services.loop import DocumentLoop
    from app.services.solution_design import SolutionDesignService
    from app.services.ai_runtime import DeterministicDemoRuntime

    project_id = "project_insightforge_demo"
    assert db.fetch_one("SELECT current_competitor_snapshot_id FROM projects WHERE id=?", (project_id,))["current_competitor_snapshot_id"] is None
    assert SolutionDesignService(
        db, DeterministicDemoRuntime(fixture_path=FIXTURE_PATH)
    )._competitor_context(project_id) is None

    result = DocumentLoop(db).run(project_id, "prd", idempotency_key="competitor-skip-prd")
    version = db.fetch_one("SELECT * FROM document_versions WHERE id=?", (result["version_id"],))
    assert version["competitor_snapshot_id"] is None
