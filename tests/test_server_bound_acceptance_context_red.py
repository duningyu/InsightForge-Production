"""RED tests for server-bound acceptance context integration.

These tests intentionally capture the incident boundary before the
implementation exists.  They must fail because the server-side acceptance
binding is missing, never because of a real Provider call.
"""

import inspect

from app.db import Database
from app.main import create_app


def test_application_exposes_server_side_acceptance_authorization_repository(tmp_path):
    application = create_app(database_path=tmp_path / "acceptance-auth.sqlite3", seed=False)

    assert hasattr(application.state, "acceptance_authorization_repository")


def test_generate_endpoint_accepts_server_authorization_reference(tmp_path):
    application = create_app(database_path=tmp_path / "acceptance-endpoint.sqlite3", seed=False)
    route = next(
        route for route in application.routes
        if getattr(route, "path", None) == "/api/projects/{project_id}/solutions/generate"
    )

    assert "x_acceptance_authorization_id" in inspect.signature(route.endpoint).parameters


def test_async_generation_run_persists_acceptance_authorization_link(tmp_path):
    database = Database(tmp_path / "acceptance-link.sqlite3")
    database.init_schema()

    with database.connect() as connection:
        columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(async_solution_generation_runs)"
            ).fetchall()
        }

    assert "acceptance_authorization_id" in columns


def test_client_supplied_execution_id_is_not_the_authorization_source(tmp_path):
    application = create_app(database_path=tmp_path / "client-claim.sqlite3", seed=False)
    route = next(
        route for route in application.routes
        if getattr(route, "path", None) == "/api/projects/{project_id}/solutions/generate"
    )
    parameter_names = set(inspect.signature(route.endpoint).parameters)

    assert "x_acceptance_execution_id" in parameter_names
    assert "x_acceptance_authorization_id" in parameter_names
    assert "x_acceptance_execution_id" != "x_acceptance_authorization_id"
