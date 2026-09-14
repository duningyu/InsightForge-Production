from app.db import Database


def test_real_idea_schema_is_versioned_and_isolated(tmp_path):
    db = Database(tmp_path / "evaluation.sqlite")
    db.init_schema()
    assert db.schema_version() >= 1
    assert db.table_names() >= {
        "real_idea_batches", "real_idea_samples",
        "real_idea_budget_allocations", "real_idea_transport_reservations",
        "real_idea_feedback", "real_idea_annotations",
    }
    assert db.public_project_schema_has_no_evaluation_identity_input()
