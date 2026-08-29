from __future__ import annotations

import json

import pytest

from app.db import Database
from app.services.example_copies import ExampleCopyService
from app.services.example_projects import ExampleProjectSeeder
from app.services.legacy_migration import LegacyMigrationService
from app.services.projects import ProjectService


CANONICAL_ID = "project_example_inventory_alert"


@pytest.fixture()
def examples_db(tmp_path) -> Database:
    database = Database(tmp_path / "examples.sqlite3")
    database.init_schema()
    ExampleProjectSeeder(database).seed()
    LegacyMigrationService(database).migrate_all()
    return database


def _rows_for_project(db: Database, table: str, project_id: str) -> list[dict]:
    return db.fetch_all(
        f"SELECT * FROM {table} WHERE project_id = ? ORDER BY rowid",  # noqa: S608 - fixed test tables
        (project_id,),
    )


def _ids(db: Database, table: str, project_id: str) -> set[str]:
    return {row["id"] for row in _rows_for_project(db, table, project_id)}


def _canonical_graph(db: Database) -> dict[str, list[dict]]:
    graph: dict[str, list[dict]] = {}
    for table in (
        "projects", "project_canvas", "project_canvas_versions", "sources",
        "source_chunks", "documents", "document_versions", "generation_runs",
        "retrieval_runs", "retrieval_hits", "document_claims", "idea_briefs",
        "solution_runs", "solution_candidates", "project_decisions", "project_claims",
        "project_snapshots", "change_proposals",
    ):
        graph[table] = (
            db.fetch_all("SELECT * FROM projects WHERE id=?", (CANONICAL_ID,))
            if table == "projects"
            else _rows_for_project(db, table, CANONICAL_ID)
        )
    graph["claim_evidence_links"] = db.fetch_all(
        """SELECT l.* FROM claim_evidence_links l JOIN document_claims c ON c.id=l.claim_id
           WHERE c.project_id=? ORDER BY l.claim_id,l.chunk_id,l.relation""",
        (CANONICAL_ID,),
    )
    graph["artifact_health"] = db.fetch_all(
        """SELECT * FROM artifact_health WHERE artifact_id IN (
               SELECT id FROM project_snapshots WHERE project_id=?
               UNION SELECT id FROM document_versions WHERE project_id=?
           ) ORDER BY artifact_type,artifact_id""",
        (CANONICAL_ID, CANONICAL_ID),
    )
    return graph


def test_project_relations_schema_is_additive_and_idempotent(tmp_path):
    db = Database(tmp_path / "relations.sqlite3")
    db.init_schema()
    db.execute(
        """INSERT INTO projects(id,title,summary,status,created_at,updated_at)
           VALUES ('parent','Parent','Parent','example','now','now'),
                  ('child','Child','Child','active','now','now')"""
    )
    db.execute(
        """INSERT INTO project_relations(
               parent_project_id,child_project_id,relation_type,created_at
           ) VALUES ('parent','child','example_copy','now')"""
    )

    db.init_schema()

    assert db.fetch_one(
        "SELECT * FROM project_relations WHERE child_project_id='child'"
    ) == {
        "parent_project_id": "parent",
        "child_project_id": "child",
        "relation_type": "example_copy",
        "created_at": "now",
    }


def test_copy_creates_fresh_ids_and_rewrites_the_complete_example_graph(examples_db):
    copied = ExampleCopyService(examples_db).copy(CANONICAL_ID, actor="tour_user")
    child_id = copied["id"]

    assert child_id != CANONICAL_ID
    assert copied["status"] == "active"
    assert copied["parent_project_id"] == CANONICAL_ID
    assert copied["relation_type"] == "example_copy"
    assert examples_db.fetch_one(
        "SELECT * FROM project_relations WHERE child_project_id=?", (child_id,)
    )["parent_project_id"] == CANONICAL_ID

    parent_canvas = examples_db.get_canvas(CANONICAL_ID)
    child_canvas = examples_db.get_canvas(child_id)
    assert child_canvas is not None
    for field in (
        "version", "problem", "target_users", "goals", "non_goals",
        "success_metrics", "constraints",
    ):
        assert child_canvas[field] == parent_canvas[field]

    id_tables = (
        "sources", "source_chunks", "documents", "document_versions",
        "retrieval_runs", "generation_runs", "document_claims", "idea_briefs",
        "project_decisions", "project_claims", "project_snapshots",
    )
    for table in id_tables:
        parent_ids = _ids(examples_db, table, CANONICAL_ID)
        child_ids = _ids(examples_db, table, child_id)
        assert len(child_ids) == len(parent_ids), table
        assert child_ids.isdisjoint(parent_ids), table

    parent_sources = {
        row["title"]: row for row in _rows_for_project(examples_db, "sources", CANONICAL_ID)
    }
    child_sources = {
        row["title"]: row for row in _rows_for_project(examples_db, "sources", child_id)
    }
    assert child_sources.keys() == parent_sources.keys()
    for title, source in parent_sources.items():
        copy = child_sources[title]
        assert (copy["source_type"], copy["content"], copy["sha256"]) == (
            source["source_type"], source["content"], source["sha256"]
        )
    simulated = child_sources["模拟缺货记录"]
    assert simulated["source_type"] == "simulated_research"
    assert "不是真实经营数据" in simulated["content"]

    child_source_ids = _ids(examples_db, "sources", child_id)
    child_chunk_ids = _ids(examples_db, "source_chunks", child_id)
    child_retrieval_ids = _ids(examples_db, "retrieval_runs", child_id)
    child_version_ids = _ids(examples_db, "document_versions", child_id)
    child_document_claim_ids = _ids(examples_db, "document_claims", child_id)
    links = examples_db.fetch_all(
        """SELECT l.* FROM claim_evidence_links l
           JOIN document_claims c ON c.id=l.claim_id WHERE c.project_id=?""",
        (child_id,),
    )
    assert links
    assert {row["claim_id"] for row in links} <= child_document_claim_ids
    assert {row["source_id"] for row in links} <= child_source_ids
    assert {row["chunk_id"] for row in links} <= child_chunk_ids
    assert {row["retrieval_run_id"] for row in links} <= child_retrieval_ids

    for version in _rows_for_project(examples_db, "document_versions", child_id):
        assert version["id"] in child_version_ids
        assert CANONICAL_ID not in version["idempotency_key"]
        for citation in json.loads(version["citations_json"]):
            source_part, chunk_part = citation.removeprefix("[source:").removesuffix("]").split("#chunk:")
            assert source_part in child_source_ids
            assert chunk_part in child_chunk_ids
            assert citation in version["content"]

    child = examples_db.fetch_one("SELECT * FROM projects WHERE id=?", (child_id,))
    snapshot = examples_db.fetch_one(
        "SELECT * FROM project_snapshots WHERE id=?", (child["current_snapshot_id"],)
    )
    assert snapshot is not None and snapshot["project_id"] == child_id
    assert snapshot["idea_brief_id"] in _ids(examples_db, "idea_briefs", child_id)
    assert snapshot["decision_id"] in _ids(examples_db, "project_decisions", child_id)
    assert json.loads(snapshot["next_action_json"])["claim_id"] in _ids(
        examples_db, "project_claims", child_id
    )

    child_artifact_ids = child_version_ids | {snapshot["id"]}
    health = examples_db.fetch_all(
        "SELECT * FROM artifact_health WHERE artifact_id IN (%s)"
        % ",".join("?" for _ in child_artifact_ids),
        tuple(child_artifact_ids),
    )
    assert health
    assert {row["artifact_id"] for row in health} <= child_artifact_ids


def test_canonical_seed_has_three_mechanisms_selected_mvp_and_ready_documents(examples_db):
    from app.services.handoff import HandoffService

    for project_id in (
        "project_example_inventory_alert",
        "project_example_procurement_workflow",
    ):
        candidates = _rows_for_project(examples_db, "solution_candidates", project_id)
        assert len(candidates) == 3
        assert len({row["mechanism"] for row in candidates}) == 3
        assert all(row["provenance"] == "model_hypothesis" for row in candidates)

        decision = _rows_for_project(examples_db, "project_decisions", project_id)[-1]
        candidate_ids = {row["id"] for row in candidates}
        assert decision["status"] == "confirmed"
        assert decision["selected_option_id"] in candidate_ids

        project = examples_db.fetch_one("SELECT * FROM projects WHERE id=?", (project_id,))
        snapshot = examples_db.fetch_one(
            "SELECT * FROM project_snapshots WHERE id=?", (project["current_snapshot_id"],)
        )
        assert json.loads(snapshot["solution_json"])["candidate_id"] == decision["selected_option_id"]

        latest_documents = examples_db.fetch_all(
            """SELECT dv.* FROM document_versions dv
               JOIN (SELECT doc_type,MAX(version) AS version FROM document_versions
                     WHERE project_id=? GROUP BY doc_type) latest
                 ON latest.doc_type=dv.doc_type AND latest.version=dv.version
               WHERE dv.project_id=? ORDER BY dv.doc_type""",
            (project_id, project_id),
        )
        assert {row["doc_type"] for row in latest_documents} == {"prd", "techdoc"}
        assert all(row["status"] == "approved" for row in latest_documents)
        assert all(row["validation_status"] == "passed" for row in latest_documents)
        for version in latest_documents:
            assert examples_db.fetch_one(
                """SELECT * FROM artifact_health
                   WHERE artifact_type='document_version' AND artifact_id=?""",
                (version["id"],),
            )["health_status"] == "current"
        assert HandoffService(examples_db).readiness(project_id)["ready"] is True

        simulated = examples_db.fetch_all(
            "SELECT source_type,content FROM sources WHERE project_id=? AND source_type='simulated_research'",
            (project_id,),
        )
        assert simulated
        assert all("人工构造" in row["content"] for row in simulated)


def test_seed_rerun_preserves_canonical_ids_and_does_not_touch_copy_or_ordinary_project(examples_db):
    canonical_before = _canonical_graph(examples_db)
    canonical_solution_ids = _ids(
        examples_db, "solution_candidates", "project_example_inventory_alert"
    )
    canonical_version_ids = _ids(
        examples_db, "document_versions", "project_example_inventory_alert"
    )
    child_id = ExampleCopyService(examples_db).copy(CANONICAL_ID, actor="tour_user")["id"]
    child_before = {
        table: _rows_for_project(examples_db, table, child_id)
        for table in ("projects", "solution_candidates", "document_versions", "sources")
        if table != "projects"
    }
    ordinary = ProjectService(examples_db).create_project(
        title="ordinary", summary="must remain untouched", actor="tester"
    )
    ordinary_before = examples_db.fetch_one("SELECT * FROM projects WHERE id=?", (ordinary["id"],))

    ExampleProjectSeeder(examples_db).seed()

    assert _canonical_graph(examples_db) == canonical_before
    assert _ids(
        examples_db, "solution_candidates", "project_example_inventory_alert"
    ) == canonical_solution_ids
    assert _ids(
        examples_db, "document_versions", "project_example_inventory_alert"
    ) == canonical_version_ids
    assert {
        table: _rows_for_project(examples_db, table, child_id)
        for table in child_before
    } == child_before
    assert examples_db.fetch_one("SELECT * FROM projects WHERE id=?", (ordinary["id"],)) == ordinary_before


def test_full_copy_keeps_independent_selected_solution_and_handoff_readiness(examples_db):
    from app.services.handoff import HandoffService

    copied = ExampleCopyService(examples_db).copy(CANONICAL_ID, actor="tour_user")
    child_id = copied["id"]
    child_candidate_ids = _ids(examples_db, "solution_candidates", child_id)
    parent_candidate_ids = _ids(examples_db, "solution_candidates", CANONICAL_ID)

    assert len(child_candidate_ids) == 3
    assert child_candidate_ids.isdisjoint(parent_candidate_ids)
    child_decision = _rows_for_project(examples_db, "project_decisions", child_id)[-1]
    assert child_decision["selected_option_id"] in child_candidate_ids
    assert child_decision["selected_option_id"] not in parent_candidate_ids
    assert HandoffService(examples_db).readiness(child_id)["ready"] is True


def test_child_edits_do_not_change_any_canonical_example_rows(examples_db):
    service = ExampleCopyService(examples_db)
    canonical_before = _canonical_graph(examples_db)
    copied = service.copy(CANONICAL_ID, actor="tour_user")
    child_id = copied["id"]

    canvas = examples_db.get_canvas(child_id)
    ProjectService(examples_db).update_canvas(
        child_id,
        problem="Only the editable copy changes.",
        target_users=canvas["target_users"],
        goals=canvas["goals"],
        non_goals=canvas["non_goals"],
        success_metrics=canvas["success_metrics"],
        constraints=canvas["constraints"],
        actor="tour_user",
    )
    child_source_id = next(iter(_ids(examples_db, "sources", child_id)))
    examples_db.execute("UPDATE sources SET title='edited child source' WHERE id=?", (child_source_id,))
    child_version_id = next(iter(_ids(examples_db, "document_versions", child_id)))
    examples_db.execute("UPDATE document_versions SET content='edited child doc' WHERE id=?", (child_version_id,))

    assert _canonical_graph(examples_db) == canonical_before


def test_copy_rejects_noncanonical_projects_and_blank_actors(examples_db):
    service = ExampleCopyService(examples_db)

    with pytest.raises(KeyError, match="canonical example not found"):
        service.copy("project_insightforge_demo", actor="tour_user")
    with pytest.raises(ValueError, match="actor is required"):
        service.copy(CANONICAL_ID, actor="   ")


def test_copy_rolls_back_every_row_when_the_final_audit_write_fails(examples_db, monkeypatch):
    service = ExampleCopyService(examples_db)

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(examples_db, "insert_audit_tx", fail_audit)
    with pytest.raises(RuntimeError, match="injected audit failure"):
        service.copy(CANONICAL_ID, actor="tour_user")

    assert examples_db.fetch_one(
        "SELECT COUNT(*) AS count FROM project_relations WHERE parent_project_id=?",
        (CANONICAL_ID,),
    )["count"] == 0
    assert examples_db.fetch_one(
        "SELECT COUNT(*) AS count FROM projects WHERE status='active'"
    )["count"] == 0


def test_examples_api_lists_only_canonical_examples_and_copies_with_header_actor(examples_db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    application = create_app(database_path=examples_db.path, seed=False)
    with TestClient(application) as client:
        listed = client.get("/api/examples")
        copied = client.post(
            f"/api/examples/{CANONICAL_ID}/copies",
            headers={"X-Actor": "api_tour_user"},
        )

    assert listed.status_code == 200
    assert {row["id"] for row in listed.json()} == {
        "project_example_inventory_alert",
        "project_example_procurement_workflow",
    }
    assert all(row["status"] == "example" for row in listed.json())
    assert copied.status_code == 201
    assert copied.json()["parent_project_id"] == CANONICAL_ID
    assert examples_db.fetch_one(
        """SELECT actor FROM audit_events
           WHERE action='canonical_example_copied' AND entity_id=?""",
        (copied.json()["id"],),
    )["actor"] == "api_tour_user"
