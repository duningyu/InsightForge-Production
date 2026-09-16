from __future__ import annotations


def test_m3_schema_has_submission_review_recovery_and_decision_contracts(db):
    expected = {
        "first_action_cards": {
            "kind",
            "parent_task_id",
            "source_submission_id",
            "source_review_id",
            "execution_state",
            "execution_revision",
        },
        "action_submissions": {
            "submission_id",
            "project_id",
            "task_id",
            "task_revision",
            "submission_kind",
            "description",
            "attachment_refs_json",
            "check_results_json",
            "execution_claim_json",
            "source_identity",
            "revision",
            "submitted_by",
            "created_at",
        },
        "action_reviews": {
            "review_id",
            "project_id",
            "submission_id",
            "submission_revision",
            "task_id",
            "task_revision",
            "check_items_json",
            "overall_status",
            "known_unknowns_json",
            "evidence_level",
            "recommendation",
            "reviewer_role",
            "revision",
            "evidence_hash",
            "created_at",
        },
        "decision_records": {
            "decision_id",
            "project_id",
            "source_submission_id",
            "source_review_id",
            "decision",
            "rationale",
            "confirmed",
            "confirmed_by",
            "revision",
            "created_at",
        },
    }
    with db.connect() as connection:
        for table, fields in expected.items():
            columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert fields <= columns


def test_m3_schema_enforces_action_and_decision_enum_contracts(db):
    with db.connect() as connection:
        sql_by_table = {
            table: connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            for table in (
                "first_action_cards",
                "action_submissions",
                "action_reviews",
                "decision_records",
            )
        }

    assert "RECOVERY" in sql_by_table["first_action_cards"]
    assert "DONE" in sql_by_table["action_submissions"]
    assert "BLOCKED" in sql_by_table["action_submissions"]
    assert "AUTHORIZED_RUN" in sql_by_table["action_reviews"]
    assert "NOT_APPLICABLE" in sql_by_table["action_reviews"]
    for decision in ("CONTINUE", "NARROW", "CHANGE", "STOP", "FINISH"):
        assert decision in sql_by_table["decision_records"]
