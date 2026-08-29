from app.services.guided_project import GuidedProjectService


def test_completed_project_keeps_three_comparable_options_and_an_idea_plan(db):
    proposals = GuidedProjectService(db).solution_proposals("project_insightforge_demo")

    assert len(proposals["options"]) == 3
    assert all({"title", "benefits", "costs", "risks", "unknowns"} <= option.keys() for option in proposals["options"])
    assert proposals["idea_plan"]["steps"]
    assert proposals["idea_plan"]["acceptance_checks"]
    assert "建议" in proposals["idea_plan"]["boundary"]


def test_solution_proposals_api_is_available_after_canvas_is_completed(client):
    response = client.get("/api/projects/project_insightforge_demo/solution-proposals")

    assert response.status_code == 200
    assert len(response.json()["options"]) == 3
