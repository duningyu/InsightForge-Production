"""Contract checks that M3 leaves the established M1/M2 surface reachable."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_m1_m2_and_formal_handoff_routes_remain_declared():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    required_routes = (
        '/api/projects/{project_id}/intent',
        '/api/projects/{project_id}/build-slice',
        '/api/projects/{project_id}/prototype-task',
        '/api/projects/{project_id}/handoff/readiness',
        '/api/projects/{project_id}/handoff/export',
    )
    missing = [route for route in required_routes if route not in source]
    assert not missing, f"existing product route surface regressed: {missing}"


def test_m3_frontend_is_an_increment_of_the_existing_project_shell():
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    for element_id in ("project-shell", "m1-action-panel", "m2-build-slice-panel", "m3-action-panel"):
        assert f'id="{element_id}"' in html


def test_m3_does_not_create_a_second_formal_handoff_service():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert source.count("HandoffService(db)") == 1
