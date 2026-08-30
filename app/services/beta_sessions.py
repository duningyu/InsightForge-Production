from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True, slots=True)
class SessionResolution:
    session_id: str
    created: bool


class BetaSessionService:
    def __init__(self, db, *, participant_id: str, release_id: str, idle_timeout_minutes: int = 30):
        self.db = db
        self.participant_id = participant_id
        self.release_id = release_id
        self.idle_timeout = timedelta(minutes=idle_timeout_minutes)
        self.clock = lambda: datetime.now(timezone.utc)

    def resolve(self, session_id: str | None) -> SessionResolution:
        now = self.clock()
        row = None
        if session_id:
            row = self.db.fetch_one(
                "SELECT * FROM beta_sessions WHERE id=? AND participant_id=? AND beta_release_id=?",
                (session_id, self.participant_id, self.release_id),
            )
        if row is not None:
            last = datetime.fromisoformat(row["last_activity_at"])
            if now - last <= self.idle_timeout:
                with self.db.connect() as connection:
                    connection.execute(
                        "UPDATE beta_sessions SET last_activity_at=? WHERE id=?",
                        (now.isoformat(), session_id),
                    )
                return SessionResolution(session_id=session_id or "", created=False)
        new_id = uuid.uuid4().hex
        timestamp = now.isoformat()
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO beta_sessions(id,participant_id,beta_release_id,started_at,last_activity_at) VALUES (?,?,?,?,?)",
                (new_id, self.participant_id, self.release_id, timestamp, timestamp),
            )
        return SessionResolution(session_id=new_id, created=True)
