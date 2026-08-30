from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db import Database
from app.errors import BetaDailyLimitReached


DEFAULT_BETA_LIMITS = {
    "solution_generation": 10,
    "document_generation": 10,
    "evidence_analysis": 20,
}


@dataclass(frozen=True, slots=True)
class UsageDecision:
    allowed: bool
    counted: bool
    operation: str
    limit: int | None
    used: int
    reset_at: str | None


class BetaUsageService:
    """Atomically consume participant-scoped daily real-provider allowances."""

    def __init__(
        self,
        db: Database,
        *,
        participant_id: str | None,
        beta_mode: bool,
        timezone_name: str = "Asia/Shanghai",
        limits: Mapping[str, int] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        try:
            self.timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown beta timezone: {timezone_name}") from exc
        configured = dict(DEFAULT_BETA_LIMITS)
        if limits:
            configured.update(limits)
        if set(configured) != set(DEFAULT_BETA_LIMITS):
            unknown = set(configured) - set(DEFAULT_BETA_LIMITS)
            raise ValueError(f"unsupported beta usage operations: {sorted(unknown)}")
        if any(not isinstance(value, int) or value < 1 for value in configured.values()):
            raise ValueError("beta usage limits must be positive integers")
        self.db = db
        self.participant_id = participant_id
        self.beta_mode = beta_mode
        self.limits = configured
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _local_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("beta usage clock must return a timezone-aware datetime")
        return value.astimezone(self.timezone)

    def consume(self, operation: str) -> UsageDecision:
        if operation not in DEFAULT_BETA_LIMITS:
            raise ValueError(f"unsupported beta usage operation: {operation}")
        if not self.beta_mode:
            return UsageDecision(True, False, operation, None, 0, None)
        if not self.participant_id:
            raise RuntimeError("beta usage requires a participant_id")

        local_now = self._local_now()
        usage_date = local_now.date().isoformat()
        reset_at = (local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
        limit = self.limits[operation]
        updated_at = local_now.astimezone(timezone.utc).isoformat(timespec="microseconds")

        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_count FROM beta_daily_usage
                WHERE participant_id=? AND usage_date=? AND operation_type=?
                """,
                (self.participant_id, usage_date, operation),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used >= limit:
                raise BetaDailyLimitReached(
                    operation=operation,
                    limit=limit,
                    used=used,
                    reset_at=reset_at,
                )
            used += 1
            connection.execute(
                """
                INSERT INTO beta_daily_usage(
                    participant_id, usage_date, operation_type, request_count, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(participant_id, usage_date, operation_type)
                DO UPDATE SET request_count=excluded.request_count, updated_at=excluded.updated_at
                """,
                (self.participant_id, usage_date, operation, used, updated_at),
            )
        return UsageDecision(True, True, operation, limit, used, reset_at)
