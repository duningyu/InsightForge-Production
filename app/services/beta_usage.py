from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import uuid
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
    reservation_id: str | None = None
    usage_date: str | None = None


class BetaUsageService:
    """Record operation reservations independently of optional daily admission caps."""

    def __init__(
        self,
        db: Database,
        *,
        participant_id: str | None,
        beta_mode: bool,
        timezone_name: str = "Asia/Shanghai",
        limits: Mapping[str, int] | None = None,
        clock: Callable[[], datetime] | None = None,
        daily_limits_enabled: bool = False,
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
        self.daily_limits_enabled = daily_limits_enabled
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
        limit = self.limits[operation] if self.daily_limits_enabled else None
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
            if limit is not None and used >= limit:
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
            reservation_id = f"quota_res_{uuid.uuid4().hex}"
            connection.execute(
                """INSERT INTO beta_quota_reservations(
                    reservation_id, participant_id, usage_date, operation_type,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'RESERVED', ?, ?)""",
                (reservation_id, self.participant_id, usage_date, operation, updated_at, updated_at),
            )
        return UsageDecision(True, True, operation, limit, used, reset_at, reservation_id, usage_date)

    def policy(self) -> dict:
        """Fresh operation-scoped accounting; null means unbounded, never zero uses."""
        day = self._local_now().date().isoformat()
        rows = self.db.fetch_all(
            "SELECT operation_type, request_count FROM beta_daily_usage WHERE participant_id=? AND usage_date=?",
            (self.participant_id, day),
        )
        counts = {row["operation_type"]: int(row["request_count"]) for row in rows}
        enabled = self.beta_mode and self.daily_limits_enabled
        return {
            "daily_user_limits_enabled": enabled,
            "usage_date": day,
            "timezone": str(self.timezone),
            "operations": {
                op: {"used": counts.get(op, 0), "limit": cap if enabled else None,
                     "remaining": max(0, cap - counts.get(op, 0)) if enabled else None}
                for op, cap in self.limits.items()
            },
            "accounting": "reserved_then_committed_or_released",
        }

    def commit(self, decision: UsageDecision) -> None:
        """Commit a successful user-visible operation exactly once."""
        if not self.beta_mode or not decision.counted or not decision.reservation_id:
            return
        now = self._local_now().astimezone(timezone.utc).isoformat(timespec="microseconds")
        with self.db.connect() as connection:
            connection.execute(
                """UPDATE beta_quota_reservations
                   SET state='COMMITTED', updated_at=?
                   WHERE reservation_id=? AND state='RESERVED'""",
                (now, decision.reservation_id),
            )

    def release(self, decision: UsageDecision) -> None:
        """Release a reservation when the provider did not deliver a result."""
        if not self.beta_mode or not decision.counted or not self.participant_id:
            return
        local_now = self._local_now()
        usage_date = decision.usage_date or local_now.date().isoformat()
        updated_at = local_now.astimezone(timezone.utc).isoformat(timespec="microseconds")
        with self.db.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if decision.reservation_id:
                reservation = connection.execute(
                    "SELECT state FROM beta_quota_reservations WHERE reservation_id=?",
                    (decision.reservation_id,),
                ).fetchone()
                if reservation is None or reservation[0] != "RESERVED":
                    return
            row = connection.execute(
                "SELECT request_count FROM beta_daily_usage WHERE participant_id=? AND usage_date=? AND operation_type=?",
                (self.participant_id, usage_date, decision.operation),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used <= 1:
                connection.execute(
                    "DELETE FROM beta_daily_usage WHERE participant_id=? AND usage_date=? AND operation_type=?",
                    (self.participant_id, usage_date, decision.operation),
                )
            else:
                connection.execute(
                    "UPDATE beta_daily_usage SET request_count=?, updated_at=? WHERE participant_id=? AND usage_date=? AND operation_type=?",
                    (used - 1, updated_at, self.participant_id, usage_date, decision.operation),
                )
            if decision.reservation_id:
                connection.execute(
                    """UPDATE beta_quota_reservations
                       SET state='RELEASED', updated_at=?
                       WHERE reservation_id=? AND state='RESERVED'""",
                    (updated_at, decision.reservation_id),
                )
