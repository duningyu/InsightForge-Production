from tests.test_m3_routes import _submission_payload
from tests.test_if_guide_m3_submission import _m2_ready_action


def test_m3_history_is_append_only_and_ordered_by_revision(client):
    project_id, task_id, task_revision = _m2_ready_action(client)
    first = client.post(
        f"/api/projects/{project_id}/actions/{task_id}/submissions",
        json=_submission_payload(task_revision),
        headers={"X-Actor": "m3-owner"},
    )
    assert first.status_code == 201
    second = client.get(
        f"/api/projects/{project_id}/actions/{task_id}/submissions",
        headers={"X-Actor": "m3-owner"},
    )
    assert second.status_code == 200
    assert len(second.json()["submissions"]) == 1

    history = client.get(
        f"/api/projects/{project_id}/m3/history",
        headers={"X-Actor": "m3-owner"},
    )
    assert history.status_code == 200
    events = history.json()["events"]
    assert len(events) == 1
    assert events[0]["category"] == "submission"
    assert events[0]["revision"] == 1
    assert "description" not in events[0]
