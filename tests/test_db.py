def test_seed_contains_project_canvas_and_sources(db):
    assert len(db.fetch_all("SELECT * FROM projects")) == 1
    assert len(db.fetch_all("SELECT * FROM project_canvas")) == 1
    assert len(db.fetch_all("SELECT * FROM sources")) >= 4
    assert len(db.fetch_all("SELECT * FROM source_chunks")) >= 4
    assert len(db.fetch_all("SELECT * FROM project_canvas_versions")) == 1


def test_seed_is_idempotent(db):
    db.seed_demo_data()
    db.seed_demo_data()
    assert len(db.fetch_all("SELECT * FROM projects")) == 1
    assert len(db.fetch_all("SELECT * FROM sources")) == 4


def test_seed_retains_source_types_and_authority(db):
    rows = db.fetch_all("SELECT source_type, authority FROM sources ORDER BY id")
    assert {row["source_type"] for row in rows} >= {
        "user_input", "simulated_research", "public_source", "implementation_evidence"
    }
    assert all(0 <= row["authority"] <= 1 for row in rows)
