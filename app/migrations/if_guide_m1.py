"""M1 purpose and deterministic first-action storage."""

from __future__ import annotations

import sqlite3


VERSION = 1


def apply(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS if_guide_m1_schema_meta (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            version INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS project_intents (
            intent_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            owner_actor TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK(revision > 0),
            purpose TEXT NOT NULL CHECK(purpose IN ('LEARNING', 'PERSONAL_USE', 'FOR_OTHERS', 'UNSPECIFIED')),
            raw_idea TEXT NOT NULL,
            confirmed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, revision)
        );

        CREATE INDEX IF NOT EXISTS idx_project_intents_project_revision
            ON project_intents(project_id, revision DESC);

        CREATE TABLE IF NOT EXISTS first_action_cards (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            intent_revision INTEGER NOT NULL,
            template_version TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('DRAFT', 'READY', 'NEEDS_REVISION')),
            goal TEXT NOT NULL,
            why_now TEXT NOT NULL,
            inputs_json TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            expected_artifact TEXT NOT NULL,
            checks_json TEXT NOT NULL,
            branches_json TEXT NOT NULL,
            stop_condition TEXT NOT NULL,
            prohibited_actions_json TEXT NOT NULL,
            card_revision INTEGER NOT NULL DEFAULT 1 CHECK(card_revision > 0),
            confirmed INTEGER NOT NULL DEFAULT 0 CHECK(confirmed IN (0, 1)),
            confirmed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, intent_revision, template_version),
            FOREIGN KEY(project_id, intent_revision)
                REFERENCES project_intents(project_id, revision)
        );

        CREATE INDEX IF NOT EXISTS idx_first_action_cards_project_revision
            ON first_action_cards(project_id, intent_revision DESC);

        INSERT OR IGNORE INTO if_guide_m1_schema_meta(singleton, version)
        VALUES (1, 1);
        """
    )
