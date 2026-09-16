from tests.test_if_guide_m3_submission import _m2_ready_action


def _submission_payload(task_revision: int, *, kind: str = "DONE") -> dict:
    return {
        "task_revision": task_revision,
        "submission_kind": kind,
        "description": "private execution note that must not appear in the safe history",
        "attachment_refs": ["private-log.txt"],
        "check_results": [{"check_id": "result-recorded", "outcome": "PASS"}],
        "execution_claim": {"executed": False, "tested": False},
        "source_identity": "USER_INPUT",
    }


def _review_payload(submission: dict, *, status: str = "PASS") -> dict:
    return {
        "submission_revision": submission["revision"],
        "task_id": submission["task_id"],
        "task_revision": submission["task_revision"],
        "check_items": [
            {
                "check_id": "result-recorded",
                "outcome": status,
                "evidence_refs": ["user-note-1"],
            }
        ],
        "overall_status": status,
        "known_unknowns": [],
        "evidence_level": "USER_REPORTED",
        "recommendation": "继续沿用当前最小流程。",
        "reviewer_role": "system_review",
    }


def test_m3_review_decision_routes_and_safe_history(client):
    project_id, task_id, task_revision = _m2_ready_action(client)
    submission_response = client.post(
        f"/api/projects/{project_id}/actions/{task_id}/submissions",
        json=_submission_payload(task_revision),
        headers={"X-Actor": "m3-owner"},
    )
    assert submission_response.status_code == 201
    submission = submission_response.json()

    review_response = client.post(
        f"/api/projects/{project_id}/submissions/{submission['submission_id']}/review",
        json=_review_payload(submission),
        headers={"X-Actor": "m3-owner"},
    )
    assert review_response.status_code == 201
    review = review_response.json()
    assert review["overall_status"] == "PASS"
    assert client.get(
        f"/api/projects/{project_id}/submissions/{submission['submission_id']}/review",
        headers={"X-Actor": "m3-owner"},
    ).status_code == 200

    recommendation_response = client.post(
        f"/api/projects/{project_id}/decisions/recommend",
        json={
            "submission_id": submission["submission_id"],
            "review_id": review["review_id"],
            "review_revision": review["revision"],
            "decision": "CONTINUE",
            "rationale": "评审结果支持继续。",
            "recommendation": "继续下一步。",
            "remaining_unknowns": [],
        },
        headers={"X-Actor": "m3-owner"},
    )
    assert recommendation_response.status_code == 201
    decision = recommendation_response.json()
    assert decision["confirmed"] is False

    confirm_response = client.post(
        f"/api/projects/{project_id}/decisions/{decision['decision_id']}/confirm",
        json={"expected_revision": decision["revision"]},
        headers={"X-Actor": "m3-owner"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["confirmed"] is True

    history_response = client.get(
        f"/api/projects/{project_id}/m3/history",
        headers={"X-Actor": "m3-owner"},
    )
    assert history_response.status_code == 200
    history = history_response.json()
    assert history["safe_only"] is True
    assert {event["category"] for event in history["events"]} >= {
        "submission",
        "review",
        "decision",
    }
    assert all("description" not in event for event in history["events"])
    assert all("attachment_refs" not in event for event in history["events"])
    assert all("rationale" not in event for event in history["events"])
    assert all("private execution note" not in str(event) for event in history["events"])


def test_m3_recovery_routes_preserve_exact_review_binding(client):
    project_id, task_id, task_revision = _m2_ready_action(client)
    submission = client.post(
        f"/api/projects/{project_id}/actions/{task_id}/submissions",
        json=_submission_payload(task_revision, kind="BLOCKED"),
        headers={"X-Actor": "m3-owner"},
    ).json()
    review = client.post(
        f"/api/projects/{project_id}/submissions/{submission['submission_id']}/review",
        json=_review_payload(submission, status="FAIL"),
        headers={"X-Actor": "m3-owner"},
    ).json()

    recovery_response = client.post(
        f"/api/projects/{project_id}/actions/{task_id}/recovery",
        json={
            "submission_id": submission["submission_id"],
            "review_id": review["review_id"],
            "review_revision": review["revision"],
            "goal": "补齐评审指出的最小缺口",
            "inputs": ["评审中的未知项"],
            "steps": ["完成一个最小验证动作"],
            "checks": ["重新提交并记录结果"],
        },
        headers={"X-Actor": "m3-owner"},
    )
    assert recovery_response.status_code == 201
    recovery = recovery_response.json()
    assert recovery["kind"] == "RECOVERY"
    assert recovery["source_submission_id"] == submission["submission_id"]
    assert recovery["source_review_id"] == review["review_id"]

    recovery_read = client.get(
        f"/api/projects/{project_id}/actions/{task_id}/recovery",
        headers={"X-Actor": "m3-owner"},
    )
    assert recovery_read.status_code == 200
    assert recovery_read.json()["task_id"] == recovery["task_id"]


def test_m3_history_read_is_account_isolated(client):
    project_id, task_id, task_revision = _m2_ready_action(client, actor="alice")
    response = client.post(
        f"/api/projects/{project_id}/actions/{task_id}/submissions",
        json=_submission_payload(task_revision),
        headers={"X-Actor": "alice"},
    )
    assert response.status_code == 201

    denied = client.get(
        f"/api/projects/{project_id}/m3/history",
        headers={"X-Actor": "bob"},
    )
    assert denied.status_code == 403

    denied_review = client.post(
        f"/api/projects/{project_id}/submissions/{response.json()['submission_id']}/review",
        json=_review_payload(response.json()),
        headers={"X-Actor": "bob"},
    )
    assert denied_review.status_code == 403
