from pathlib import Path

import pytest

from app.db import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "insightforge_test.sqlite3")
    database.init_schema()
    database.seed_demo_data()
    return database


@pytest.fixture()
def registry(db):
    from app.tools import ToolRegistry

    return ToolRegistry(db)


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    from app.main import create_app

    application = create_app(database_path=db.path, seed=False)
    with TestClient(application) as test_client:
        yield test_client
