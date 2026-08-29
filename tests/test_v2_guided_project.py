from app.services.guided_project import GuidedProjectService
from app.services.projects import ProjectService


def _create_blank_project(db):
    return ProjectService(db).create_project(
        title="新手项目",
        summary="我想做一个帮助新手完成产品方案的工具",
        actor="tester",
    )


def _create_legacy_guided_service(db, project):
    """Create an explicit pre-3.0 Guided session for legacy-regression tests.

    InsightForge 3.0 must not bootstrap Guided sessions for new projects; these
    tests intentionally exercise only the retained legacy-session behavior.
    """
    service = GuidedProjectService(db)
    service._create_session(project)
    return service


def test_legacy_initial_state_uses_project_summary_and_asks_one_audience_question(db):
    project = _create_blank_project(db)
    state = _create_legacy_guided_service(db, project).get_state(project["id"])

    assert state["state"]["idea"] == "我想做一个帮助新手完成产品方案的工具"
    assert state["current_step"] == "audience"
    assert state["coach"]["question"]
    assert "哪一类" in state["coach"]["question"]
    assert state["coach"]["why"]
    assert state["coach"]["examples"]
    assert state["coach"]["choices"]
    assert len([m for m in state["messages"] if m["role"] == "assistant"]) == 1


def test_legacy_guided_responses_progress_one_question_at_a_time_and_keep_trace(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)

    audience = service.respond(
        project["id"],
        answer="准备转岗产品经理、但不知道怎么做完整项目的人",
        choice_id=None,
        actor="tester",
    )
    assert audience["current_step"] == "problem"
    assert audience["state"]["target_users"].startswith("准备转岗")
    assert audience["coach"]["question"].count("？") <= 1
    assert audience["trace"]["written_fields"] == ["target_users"]
    assert audience["trace"]["source"] == "user_confirmed"

    problem = service.respond(
        project["id"],
        answer="他们面对空白模板时，不知道目标、约束和证据该怎么写",
        choice_id=None,
        actor="tester",
    )
    assert problem["current_step"] == "constraints"
    assert "空白模板" in problem["state"]["user_problem"]


def test_legacy_solution_step_offers_three_alternatives_and_requires_selection(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)
    service.respond(project["id"], answer="产品转岗者", choice_id=None, actor="tester")
    service.respond(
        project["id"],
        answer="不知道如何把想法变成可执行方案",
        choice_id=None,
        actor="tester",
    )
    service.respond(
        project["id"],
        answer="两周内完成；不依赖付费模型；单人开发",
        choice_id=None,
        actor="tester",
    )
    service.respond(
        project["id"],
        answer="目前只有公开竞品资料和一条产品经理反馈",
        choice_id=None,
        actor="tester",
    )
    result = service.respond(
        project["id"],
        answer="用户能在 30 分钟内完成一个可解释的项目框架",
        choice_id=None,
        actor="tester",
    )

    assert result["current_step"] == "solution"
    options = result["state"]["solution_options"]
    assert len(options) == 3
    assert {"id", "title", "summary", "benefits", "costs", "risks", "unknowns"} <= options[0].keys()
    assert result["coach"]["choices"]
    assert result["state"]["selected_solution_id"] is None


def test_legacy_selecting_solution_creates_proposal_but_does_not_write_canvas(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)
    answers = [
        "产品转岗者",
        "不知道如何把想法变成可执行方案",
        "两周内完成；单人开发",
        "公开资料",
        "完成一个带证据的 PRD",
    ]
    for answer in answers:
        result = service.respond(project["id"], answer=answer, choice_id=None, actor="tester")
    option_id = result["state"]["solution_options"][0]["id"]

    selected = service.respond(
        project["id"], answer="", choice_id=option_id, actor="tester"
    )

    assert selected["current_step"] == "canvas_ready"
    assert selected["proposed_canvas_patch"]["problem"]
    assert selected["proposed_canvas_patch"]["target_users"] == "产品转岗者"
    assert selected["proposed_canvas_patch"]["goals"]
    assert selected["proposed_canvas_patch"]["success_metrics"]
    assert db.get_canvas(project["id"]) is None
    decision = db.fetch_one(
        "SELECT * FROM project_decisions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project["id"],),
    )
    assert decision is not None
    assert decision["status"] == "proposed"


def test_legacy_custom_solution_is_saved_as_a_user_confirmed_project_direction(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)
    for answer in [
        "小店店主",
        "经常忘记补货",
        "每天只能花五分钟；不能接 ERP",
        "有手写进货本",
        "每天得到一份补货清单",
    ]:
        result = service.respond(project["id"], answer=answer, choice_id=None, actor="tester")

    selected = service.respond(
        project["id"],
        answer="组合轻量提醒和手动确认，先只覆盖五种商品。",
        choice_id="custom_solution",
        actor="tester",
    )

    assert selected["current_step"] == "canvas_ready"
    assert selected["state"]["selected_solution_id"] == "custom_solution"
    assert any(item["id"] == "custom_solution" for item in selected["state"]["solution_options"])
    assert "五种商品" in selected["proposed_canvas_patch"]["goals"][0]
    assert all("多智能体" not in item for item in selected["proposed_canvas_patch"]["non_goals"])
    assert any(
        message["role"] == "user"
        and message["content"] == "组合轻量提醒和手动确认，先只覆盖五种商品。"
        for message in selected["messages"]
    )


def test_legacy_back_returns_to_previous_answer_and_clears_only_later_guidance(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)
    service.respond(project["id"], answer="小店店主", choice_id=None, actor="tester")
    state = service.respond(project["id"], answer="经常忘记补货", choice_id=None, actor="tester")
    assert state["current_step"] == "constraints"

    back = service.go_back(project["id"], actor="tester")
    assert back["current_step"] == "problem"
    assert back["state"]["user_problem"] == ""
    assert back["state"]["target_users"] == "小店店主"


def test_legacy_apply_canvas_requires_ready_state_and_creates_versioned_canvas(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)

    try:
        service.apply_canvas(project["id"], actor="tester")
    except ValueError as exc:
        assert "not ready" in str(exc)
    else:
        raise AssertionError("apply should fail before a proposal is ready")

    for answer in [
        "产品转岗者",
        "不知道如何把想法变成可执行方案",
        "两周内完成；单人开发",
        "公开资料",
        "完成一个带证据的 PRD",
    ]:
        result = service.respond(project["id"], answer=answer, choice_id=None, actor="tester")
    service.respond(
        project["id"],
        answer="",
        choice_id=result["state"]["solution_options"][0]["id"],
        actor="tester",
    )

    applied = service.apply_canvas(project["id"], actor="tester")
    assert applied["current_step"] == "complete"
    assert applied["canvas"]["version"] == 1
    assert db.get_canvas(project["id"])["target_users"] == "产品转岗者"
    assert applied["state"]["confirmed_canvas_version"] == 1
    decision = db.fetch_one(
        "SELECT status, confirmed_at FROM project_decisions WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project["id"],),
    )
    assert decision["status"] == "confirmed"
    assert decision["confirmed_at"]


def test_legacy_reset_creates_clean_session_and_preserves_audit(db):
    project = _create_blank_project(db)
    service = _create_legacy_guided_service(db, project)
    first = service.get_state(project["id"])
    service.respond(project["id"], answer="产品转岗者", choice_id=None, actor="tester")

    reset = service.reset(project["id"], actor="tester")
    assert reset["session_id"] != first["session_id"]
    assert reset["current_step"] == "audience"
    assert reset["state"]["target_users"] == ""
    audit = db.fetch_one(
        "SELECT action FROM audit_events WHERE entity_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (project["id"],),
    )
    assert audit == {"action": "guided_session_reset"}


def test_legacy_guided_api_flow(client):
    created = client.post(
        "/api/projects",
        json={"title": "API 项目", "summary": "帮助小白做产品方案"},
    ).json()
    project_id = created["id"]
    project = client.app.state.projects.get_project(project_id)
    client.app.state.guided._create_session(project)

    state = client.get(f"/api/projects/{project_id}/guide")
    assert state.status_code == 200
    assert state.json()["current_step"] == "audience"

    response = client.post(
        f"/api/projects/{project_id}/guide/respond",
        json={"answer": "转岗产品经理", "choice_id": None},
    )
    assert response.status_code == 200
    assert response.json()["current_step"] == "problem"

    reset = client.post(f"/api/projects/{project_id}/guide/reset")
    assert reset.status_code == 200
    assert reset.json()["current_step"] == "audience"
