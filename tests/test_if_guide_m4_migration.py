from __future__ import annotations


def _columns(db, table: str) -> set[str]:
    with db.connect() as connection:
        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }


def test_m4_schema_contains_experiment_session_and_annotation_contracts(db):
    expected = {
        "m4_experiments": {
            "experiment_id",
            "account_id",
            "spec_version",
            "source_commit",
            "deployment_id",
            "condition_definitions_json",
            "assignment_rule",
            "metric_versions_json",
            "rubric_versions_json",
            "threshold_policy_json",
            "operator_assistance_policy_json",
            "state",
            "revision",
            "created_at",
            "updated_at",
            "frozen_at",
        },
        "m4_participants": {
            "participant_id",
            "experiment_id",
            "account_id",
            "purpose",
            "prior_ai_familiarity",
            "prior_product_experience",
            "task_category",
            "state",
            "withdrawal_reason",
            "created_at",
            "updated_at",
        },
        "m4_sessions": {
            "session_id",
            "experiment_id",
            "participant_id",
            "account_id",
            "project_id",
            "condition",
            "assignment_rule_version",
            "condition_version",
            "source_commit",
            "deployment_id",
            "state",
            "version_split",
            "version_split_reason",
            "revision",
            "created_at",
            "updated_at",
        },
        "m4_requirement_gold_items": {
            "gold_item_id",
            "session_id",
            "participant_id",
            "project_id",
            "requirement_id",
            "canonical_text",
            "importance",
            "source",
            "confirmed_by",
            "participant_confirmed",
            "revision",
            "created_at",
        },
        "m4_quality_annotations": {
            "annotation_id",
            "session_id",
            "project_id",
            "artifact_ref",
            "annotation_type",
            "target_id",
            "label",
            "evaluator_role",
            "adjudication_status",
            "evidence_hash",
            "evidence_ref_json",
            "revision",
            "created_at",
        },
    }
    tables = db.table_names()
    assert set(expected) <= tables
    for table, fields in expected.items():
        assert fields <= _columns(db, table)


def test_m4_schema_has_safe_lifecycle_and_no_raw_content_columns(db):
    forbidden = {"raw_idea", "transcript", "private_content", "body", "content"}
    with db.connect() as connection:
        for table in (
            "m4_experiments",
            "m4_participants",
            "m4_sessions",
            "m4_requirement_gold_items",
            "m4_quality_annotations",
        ):
            columns = {
                str(row["name"])
                for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
            }
            assert not columns & forbidden

        experiment_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='m4_experiments'"
        ).fetchone()[0]
        session_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='m4_sessions'"
        ).fetchone()[0]
    assert "FROZEN" in experiment_sql
    assert "VERSION_SPLIT" in experiment_sql
    assert "INSIGHTFORGE_STATEFUL" in session_sql
    assert "GENERAL_AI" in session_sql
    assert "STATIC_TEMPLATE" in session_sql


def test_m4_schema_enforces_uniqueness_and_gold_set_confirmation_contract(db):
    with db.connect() as connection:
        experiment_indexes = connection.execute(
            "PRAGMA index_list(m4_experiments)"
        ).fetchall()
        session_indexes = connection.execute("PRAGMA index_list(m4_sessions)").fetchall()
        gold_sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='m4_requirement_gold_items'"
        ).fetchone()[0]
    assert experiment_indexes
    assert session_indexes
    assert "idea_provider" in gold_sql
    assert "CRITICAL" in gold_sql
    assert "SECONDARY" in gold_sql
