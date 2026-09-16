from __future__ import annotations

from tests.test_if_guide_m3_submission import _m2_ready_action


def _payload(revision: int, **overrides):
    payload = {
        "task_revision": revision,
        "submission_kind": "DONE",
        "description": "完成了一次最小流程并记录结果。",
        "attachment_refs": ["user-note-1"],
        "check_results": [{"check_id": "result-recorded", "outcome": "PASS"}],
        "execution_claim": {"executed": False, "tested": False},
        "source_identity": "USER_INPUT",
    }
    payload.update(overrides)
    return payload


def test_submission_routes_create_and_list_history(client):
    project_id, task_id, revision = _m2_ready_action(client)
    path = f"/api/projects/{project_id}/actions/{task_id}/submissions"

    created = client.post(path, headers={"X-Actor": "m3-owner"}, json=_payload(revision))
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["submission_kind"] == "DONE"
    assert body["task_revision"] == revision
    assert body["source_identity"] == "USER_INPUT"
    assert "execution_claim" in body

    history = client.get(path, headers={"X-Actor": "m3-owner"})
    assert history.status_code == 200, history.text
    assert history.json()["submissions"][0]["submission_id"] == body["submission_id"]


def test_submission_routes_enforce_owner_revision_and_claim_guards(client):
    project_id, task_id, revision = _m2_ready_action(client, actor="alice")
    path = f"/api/projects/{project_id}/actions/{task_id}/submissions"

    forbidden = client.post(path, headers={"X-Actor": "bob"}, json=_payload(revision))
    assert forbidden.status_code == 403, forbidden.text

    stale = client.post(path, headers={"X-Actor": "alice"}, json=_payload(revision + 1))
    assert stale.status_code == 409, stale.text

    invalid_claim = client.post(
        path,
        headers={"X-Actor": "alice"},
        json=_payload(revision, execution_claim={"tested": True}),
    )
    assert invalid_claim.status_code == 422, invalid_claim.text

    foreign_history = client.get(path, headers={"X-Actor": "bob"})
    assert foreign_history.status_code == 403, foreign_history.text
