from __future__ import annotations

import threading
import time
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def test_client_generation_has_inflight_loading_guard():
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "generationInFlight" in js
    assert "正在生成方案" in js
    assert "aria-disabled" in js


def test_server_duplicate_inflight_is_not_daily_limit():
    from app.services.solution_generation_guard import SolutionGenerationGuard

    guard = SolutionGenerationGuard()
    first = guard.begin("beta_001", "project-a", "attempt-1")
    second = guard.begin("beta_001", "project-a", "attempt-1")
    assert first.owner is True
    assert second.owner is False
    assert second.error_code == "SOLUTION_GENERATION_IN_PROGRESS"
    assert second.error_code != "BETA_DAILY_LIMIT_REACHED"


def test_server_allows_explicit_regeneration_with_new_attempt():
    from app.services.solution_generation_guard import SolutionGenerationGuard

    guard = SolutionGenerationGuard()
    assert guard.begin("beta_001", "project-a", "attempt-1").owner
    guard.complete("beta_001", "project-a", "attempt-1", {"candidates": []})
    assert guard.begin("beta_001", "project-a", "attempt-2").owner


def test_server_duplicate_does_not_create_second_provider_call():
    from app.services.solution_generation_guard import SolutionGenerationGuard

    guard = SolutionGenerationGuard()
    entered = threading.Event()
    release = threading.Event()
    provider_calls = 0

    def generate():
        nonlocal provider_calls
        first = guard.begin("beta_001", "project-a", "attempt-1")
        assert first.owner
        entered.set()
        release.wait(timeout=2)
        provider_calls += 1
        guard.complete("beta_001", "project-a", "attempt-1", {"candidates": []})

    worker = threading.Thread(target=generate)
    worker.start()
    assert entered.wait(timeout=2)
    duplicate = guard.begin("beta_001", "project-a", "attempt-1")
    release.set()
    worker.join(timeout=2)
    assert duplicate.owner is False
    assert provider_calls == 1


def test_api_reuses_completed_attempt_without_second_solution_run(client):
    project = client.post(
        "/api/projects/quick-start",
        json={"idea": "帮小型便利店减少缺货", "target_user": None, "resources": [], "priority": "fast_mvp"},
    ).json()["project_id"]
    confirmed = client.post(
        f"/api/projects/{project}/idea-brief/confirm",
        json={"human_confirmed": True, "note": "理解准确"},
    )
    assert confirmed.status_code == 200
    headers = {"X-Idempotency-Key": "acceptance-attempt-1"}
    first = client.post(f"/api/projects/{project}/solutions/generate", headers=headers)
    second = client.post(f"/api/projects/{project}/solutions/generate", headers=headers)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    runs = client.app.state.db.fetch_all(
        "SELECT id FROM solution_runs WHERE project_id = ?", (project,)
    )
    assert len(runs) == 1
