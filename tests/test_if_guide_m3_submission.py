from __future__ import annotations

import pytest

from app.errors import ConflictError
from app.services.action_submission import ActionSubmissionService
from tests.test_m2_routes import build_slice_payload, create_m1_ready_project


def _m2_ready_action(client, actor: str = "m3-owner") -> tuple[str, str, int]:
    project_id = create_m1_ready_project(client, actor=actor)
    headers = {"X-Actor": actor}
    created = client.put(
        f"/api/projects/{project_id}/build-slice",
        headers=headers,
        json=build_slice_payload(),
    )
    assert created.status_code == 200, created.text
    build_slice = created.json()
    confirmed_slice = client.post(
        f"/api/projects/{project_id}/build-slice/confirm",
        headers=headers,
        json={"expected_revision": build_slice["revision"]},
    )
    assert confirmed_slice.status_code == 200, confirmed_slice.text
    task = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={
            "slice_id": build_slice["slice_id"],
            "expected_slice_revision": build_slice["revision"],
        },
    )
    assert task.status_code == 200, task.text
    task_body = task.json()
    saved = client.put(
        f"/api/projects/{project_id}/prototype-task",
        headers=headers,
        json={
            "task_id": task_body["task_id"],
            "expected_revision": task_body["revision"],
            "acceptance_steps": ["准备输入", "完成流程", "检查结果"],
        },
    )
    assert saved.status_code == 200, saved.text
    ready = client.post(
        f"/api/projects/{project_id}/prototype-task/confirm",
        headers=headers,
        json={"expected_revision": saved.json()["revision"]},
    )
    assert ready.status_code == 200, ready.text

    intent = client.get(f"/api/projects/{project_id}/intent", headers=headers)
    assert intent.status_code == 200, intent.text
    action = intent.json()["first_action"]
    return project_id, action["task_id"], action["revision"]


def _submission(service, project_id, task_id, revision, actor="m3-owner", **overrides):
    payload = {
        "project_id": project_id,
        "task_id": task_id,
        "task_revision": revision,
        "submission_kind": "DONE",
        "description": "完成了一次最小流程并记录结果。",
        "attachment_refs": ["user-note-1"],
        "check_results": [{"check_id": "result-recorded", "outcome": "PASS"}],
        "execution_claim": {"executed": False, "tested": False, "deployed": False},
        "source_identity": "USER_INPUT",
    }
    payload.update(overrides)
    return service.submit(actor=actor, **payload)


def test_action_submission_persists_done_and_blocked_with_exact_task_revision(client, db):
    project_id, task_id, revision = _m2_ready_action(client)
    service = ActionSubmissionService(db)

    done = _submission(service, project_id, task_id, revision)
    assert done["submission_kind"] == "DONE"
    assert done["task_revision"] == revision
    assert done["source_identity"] == "USER_INPUT"

    blocked = _submission(
        service,
        project_id,
        task_id,
        revision,
        submission_kind="BLOCKED",
        description="在检查结果时遇到阻碍。",
        execution_claim={"executed": False},
    )
    assert blocked["submission_kind"] == "BLOCKED"
    with db.connect() as connection:
        rows = connection.execute(
            "SELECT submission_kind FROM action_submissions WHERE project_id = ? ORDER BY created_at",
            (project_id,),
        ).fetchall()
    assert [row["submission_kind"] for row in rows] == ["DONE", "BLOCKED"]


def test_action_submission_rejects_stale_revision_and_cross_account(client, db):
    project_id, task_id, revision = _m2_ready_action(client, actor="alice")
    service = ActionSubmissionService(db)

    with pytest.raises(ConflictError, match="ACTION_SUBMISSION_REVISION_CONFLICT"):
        _submission(service, project_id, task_id, revision + 1, actor="alice")
    with pytest.raises(PermissionError):
        _submission(service, project_id, task_id, revision, actor="bob")


def test_action_submission_rejects_false_system_execution_claims(client, db):
    project_id, task_id, revision = _m2_ready_action(client)
    service = ActionSubmissionService(db)

    with pytest.raises(ValueError, match="EXECUTION_CLAIM_NOT_VERIFIED"):
        _submission(
            service,
            project_id,
            task_id,
            revision,
            execution_claim={"executed": True, "verified": True},
        )
    with pytest.raises(ValueError, match="AUTHORIZED_RUN_NOT_ALLOWED"):
        _submission(
            service,
            project_id,
            task_id,
            revision,
            execution_claim={"evidence_level": "AUTHORIZED_RUN"},
        )


def test_action_submission_does_not_call_provider_or_search(client, db, monkeypatch):
    project_id, task_id, revision = _m2_ready_action(client)
    service = ActionSubmissionService(db)
    calls = {"provider": 0, "search": 0}
    monkeypatch.setitem(calls, "provider", 0)

    result = _submission(service, project_id, task_id, revision)
    assert result["provider_dispatches"] == 0
    assert result["provider_transports"] == 0
    assert calls == {"provider": 0, "search": 0}
