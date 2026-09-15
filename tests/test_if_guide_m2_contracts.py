from __future__ import annotations


def test_m2_build_slice_and_prototype_task_store_contract_fields(db):
    expected = {
        "build_slices": {
            "slice_id", "project_id", "owner_actor", "intent_revision", "snapshot_id",
            "purpose", "confirmed_constraints", "in_scope_json", "out_of_scope_json",
            "minimal_flow_json", "acceptance_criteria_json", "revision", "status",
        },
        "prototype_tasks": {
            "task_id", "project_id", "owner_actor", "slice_id", "slice_revision",
            "snapshot_id", "purpose", "scope_json", "inputs_json", "outputs_json",
            "existing_behaviors_json", "non_goals_json", "known_context_json",
            "unknown_dependencies_json", "implementation_tasks_json", "acceptance_steps_json",
            "failure_recovery_json", "required_evidence_json", "permission_risk_json",
            "revision", "status",
        },
    }
    with db.connect() as connection:
        for table, fields in expected.items():
            columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
            assert fields <= columns
