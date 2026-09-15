"""Bounded, durable transport reservations for the Real Idea evaluation batch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.db import Database, utc_now


EXTENSION_ID = "REAL_IDEA_BATCH_01_EXT_01"
EXTENSION_CREDITS = 3
UNBOUND_RESTRICTED = "UNBOUND_RESTRICTED"
BOUND = "BOUND"
RELEASED = "RELEASED"
BATCH_EARMARK = 6
SAMPLE_CAP = 2
STAGE_CAPS = {"QUICKSTART": 1, "SOLUTIONS": 1}


class ReservationStateError(RuntimeError):
    """Raised when a durable reservation state transition is invalid."""


@dataclass(frozen=True, slots=True)
class BudgetAllocation:
    allocation_id: str
    batch_id: str
    authorized_total: int
    general_spendable: int
    batch_earmark: int
    sample_cap: int
    quickstart_cap: int
    solutions_cap: int


@dataclass(frozen=True, slots=True)
class DurableBudgetSnapshot:
    configured_capacity: int
    consumed: int
    durable_available: int
    bootstrap: bool


def read_durable_budget(database: Database, *, configured_capacity: int) -> DurableBudgetSnapshot:
    """Read the current durable budget from the authoritative receipt ledger.

    The configured capacity is only a bootstrap value for an empty ledger. Once
    receipts exist, consumption is authoritative and malformed accounting fails
    closed instead of silently reverting to configuration.
    """
    if configured_capacity < 0:
        raise ValueError("configured capacity must be non-negative")
    try:
        with database.connect() as connection:
            rows = connection.execute(
                "SELECT budget_consumed FROM stage_b_evaluation_receipts"
            ).fetchall()
    except Exception as exc:
        raise ValueError("unable to read durable budget accounting") from exc

    if not rows:
        return DurableBudgetSnapshot(configured_capacity, 0, configured_capacity, True)

    consumed = 0
    for row in rows:
        value = row[0]
        if not isinstance(value, int) or value not in (0, 1):
            raise ValueError("inconsistent durable budget accounting")
        consumed += value
    if consumed > configured_capacity:
        raise ValueError("inconsistent durable budget accounting")
    return DurableBudgetSnapshot(configured_capacity, consumed, configured_capacity - consumed, False)


@dataclass(frozen=True, slots=True)
class TransportReservation:
    reservation_id: str
    batch_id: str
    sample_id: str
    stage: str
    ordinal: int
    idempotency_key: str
    state: str
    dispatch_id: str | None = None
    transport_id: str | None = None


class RealIdeaBudgetService:
    """Owns restricted authorization and at-most-once transport accounting.

    The service is deliberately independent from the ordinary Provider budget.
    A reservation is cheap and reversible while RESERVED; once marked
    ATTEMPTED it is durable consumption and can never be released.
    """

    def __init__(self, database: Database, *, durable_budget: int):
        if durable_budget < 0:
            raise ValueError("durable budget must be non-negative")
        self.database = database
        self.durable_budget = durable_budget

    def activate_extension(self, extension_id: str, authorized_credits: int, *, created_by: str = "real_idea_budget_service") -> bool:
        if extension_id != EXTENSION_ID or authorized_credits != EXTENSION_CREDITS:
            raise ValueError("only the approved restricted extension may be activated")
        with self.database.connect() as connection:
            existing = connection.execute(
                "SELECT authorized_credits, state FROM real_idea_budget_extensions WHERE extension_id = ?",
                (extension_id,),
            ).fetchone()
            if existing:
                if int(existing[0]) != authorized_credits or existing[1] not in {UNBOUND_RESTRICTED, BOUND}:
                    raise ValueError("restricted extension is already incompatible")
                return False
            connection.execute(
                """
                INSERT INTO real_idea_budget_extensions(
                    extension_id, authorized_credits, state, created_at, created_by
                ) VALUES (?, ?, 'UNBOUND_RESTRICTED', ?, ?)
                """,
                (extension_id, authorized_credits, utc_now(), created_by),
            )
            return True

    def earmark_batch(self, batch_id: str, amount: int) -> BudgetAllocation:
        if amount != BATCH_EARMARK:
            raise ValueError("the Real Idea batch earmark must be exactly six transports")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT batch_id FROM real_idea_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if not batch:
                raise ValueError("batch must exist before budget earmark")
            extension = connection.execute(
                "SELECT extension_id, authorized_credits, state, bound_batch_id FROM real_idea_budget_extensions "
                "WHERE extension_id = ?",
                (EXTENSION_ID,),
            ).fetchone()
            if not extension or extension[2] not in {UNBOUND_RESTRICTED, BOUND}:
                raise ValueError("approved restricted extension is not active")
            if extension[2] == BOUND and extension[3] != batch_id:
                raise ValueError("approved restricted extension is already bound to another batch")
            existing = connection.execute(
                "SELECT * FROM real_idea_budget_allocations WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if existing:
                allocation = self._allocation(existing)
                if allocation.batch_earmark != amount or allocation.authorized_total != self.durable_budget + EXTENSION_CREDITS:
                    raise ValueError("existing batch allocation conflicts with approved budget")
                if extension[2] == UNBOUND_RESTRICTED:
                    connection.execute(
                        "UPDATE real_idea_budget_extensions SET state = 'BOUND', bound_batch_id = ? WHERE extension_id = ?",
                        (batch_id, EXTENSION_ID),
                    )
                return allocation
            allocation_id = f"allocation_{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO real_idea_budget_allocations(
                    allocation_id, batch_id, authorized_total, batch_earmark,
                    sample_cap, quickstart_cap, solutions_cap, purpose, state,
                    created_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'REAL_IDEA_BATCH_01', 'ACTIVE', ?,
                          'real_idea_budget_service')
                """,
                (
                    allocation_id, batch_id, self.durable_budget + EXTENSION_CREDITS,
                    amount, SAMPLE_CAP, STAGE_CAPS["QUICKSTART"], STAGE_CAPS["SOLUTIONS"], utc_now(),
                ),
            )
            connection.execute(
                "UPDATE real_idea_budget_extensions SET state = 'BOUND', bound_batch_id = ? WHERE extension_id = ?",
                (batch_id, EXTENSION_ID),
            )
            row = connection.execute(
                "SELECT * FROM real_idea_budget_allocations WHERE allocation_id = ?", (allocation_id,)
            ).fetchone()
            return self._allocation(row)

    def release_extension(self, extension_id: str, batch_id: str) -> None:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state, bound_batch_id FROM real_idea_budget_extensions WHERE extension_id = ?",
                (extension_id,),
            ).fetchone()
            if row is None:
                raise KeyError(extension_id)
            if row[0] == RELEASED:
                raise ReservationStateError("released")
            if row[0] != BOUND or row[1] != batch_id:
                raise ValueError("restricted extension is not bound to this batch")
            connection.execute(
                "UPDATE real_idea_budget_extensions SET state = 'RELEASED', released_at = ? WHERE extension_id = ?",
                (utc_now(), extension_id),
            )

    def inspect_extension(self, extension_id: str = EXTENSION_ID) -> dict[str, object] | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT extension_id, authorized_credits, state, bound_batch_id FROM real_idea_budget_extensions WHERE extension_id = ?",
                (extension_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "extension_id": row[0],
                "authorized_credits": int(row[1]),
                "state": row[2],
                "bound_batch_id": row[3],
            }

    def accounting_summary(self) -> dict[str, int]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT state, COALESCE(SUM(authorized_credits), 0) FROM real_idea_budget_extensions GROUP BY state"
            ).fetchall()
            totals = {str(row[0]): int(row[1]) for row in rows}
            bound_allocation = int(connection.execute(
                "SELECT COALESCE(SUM(batch_earmark), 0) FROM real_idea_budget_allocations WHERE state = 'ACTIVE'"
            ).fetchone()[0])
            authorized_total = self.durable_budget + sum(
                value for state, value in totals.items() if state != RELEASED
            )
            return {
                "authorized_total": authorized_total,
                "general_spendable": self.durable_budget,
                "restricted_unbound": totals.get(UNBOUND_RESTRICTED, 0),
                "bound_allocation": bound_allocation,
                # This is the conservative ceiling over all currently
                # authorized capacity.  It is reporting/safety metadata only;
                # ordinary spend remains capped by general_spendable and
                # restricted credits remain unavailable until batch binding.
                "safe_ceiling": max(authorized_total - 1, 0),
            }

    def reserve(self, batch_id: str, sample_id: str, stage: str, ordinal: int) -> TransportReservation:
        if stage not in STAGE_CAPS:
            raise ValueError("unsupported evaluation transport stage")
        if ordinal != 1:
            raise ValueError("transport ordinal must be one")
        idempotency_key = f"{batch_id}:{sample_id}:{stage}:{ordinal}"
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM real_idea_transport_reservations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return self._reservation(existing)
            allocation = connection.execute(
                "SELECT * FROM real_idea_budget_allocations WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if not allocation or allocation["state"] != "ACTIVE":
                raise ValueError("batch earmark is not active")
            sample = connection.execute(
                "SELECT sample_id FROM real_idea_samples WHERE batch_id = ? AND sample_id = ?",
                (batch_id, sample_id),
            ).fetchone()
            if not sample:
                raise ValueError("sample must be registered before transport reservation")
            count = connection.execute(
                "SELECT COUNT(*) FROM real_idea_transport_reservations "
                "WHERE batch_id = ? AND sample_id = ? AND state != 'RELEASED'",
                (batch_id, sample_id),
            ).fetchone()[0]
            if count >= SAMPLE_CAP:
                raise ValueError("sample transport cap exceeded")
            stage_count = connection.execute(
                "SELECT COUNT(*) FROM real_idea_transport_reservations "
                "WHERE batch_id = ? AND sample_id = ? AND stage = ? AND state != 'RELEASED'",
                (batch_id, sample_id, stage),
            ).fetchone()[0]
            if stage_count >= STAGE_CAPS[stage]:
                raise ValueError("stage transport cap exceeded")
            attempted = connection.execute(
                "SELECT COUNT(*) FROM real_idea_transport_reservations WHERE batch_id = ? AND state = 'ATTEMPTED'",
                (batch_id,),
            ).fetchone()[0]
            if attempted >= int(allocation["batch_earmark"]):
                raise ValueError("batch earmark exhausted")
            reservation_id = f"reservation_{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO real_idea_transport_reservations(
                    reservation_id, batch_id, sample_id, stage, ordinal,
                    idempotency_key, state, reserved_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, 'RESERVED', ?, 'real_idea_budget_service')
                """,
                (reservation_id, batch_id, sample_id, stage, ordinal, idempotency_key, utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM real_idea_transport_reservations WHERE reservation_id = ?", (reservation_id,)
            ).fetchone()
            return self._reservation(row)

    def mark_attempted(
        self, reservation_id: str, *, dispatch_id: str, transport_id: str
    ) -> TransportReservation:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM real_idea_transport_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise KeyError(reservation_id)
            if row["state"] != "RESERVED":
                raise ReservationStateError("only RESERVED reservations can become ATTEMPTED")
            connection.execute(
                """
                UPDATE real_idea_transport_reservations
                SET state = 'ATTEMPTED', attempted_at = ?, dispatch_id = ?, transport_id = ?
                WHERE reservation_id = ? AND state = 'RESERVED'
                """,
                (utc_now(), dispatch_id, transport_id, reservation_id),
            )
            updated = connection.execute(
                "SELECT * FROM real_idea_transport_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            return self._reservation(updated)

    def release(self, reservation_id: str) -> TransportReservation:
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM real_idea_transport_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            if not row:
                raise KeyError(reservation_id)
            if row["state"] != "RESERVED":
                raise ReservationStateError("attempted reservations can never be released")
            connection.execute(
                "UPDATE real_idea_transport_reservations SET state = 'RELEASED', released_at = ? WHERE reservation_id = ?",
                (utc_now(), reservation_id),
            )
            released = connection.execute(
                "SELECT * FROM real_idea_transport_reservations WHERE reservation_id = ?",
                (reservation_id,),
            ).fetchone()
            return self._reservation(released)

    def remaining_batch_earmark(self, batch_id: str) -> int:
        with self.database.connect() as connection:
            allocation = connection.execute(
                "SELECT batch_earmark FROM real_idea_budget_allocations WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if not allocation:
                raise KeyError(batch_id)
            attempted = connection.execute(
                "SELECT COUNT(*) FROM real_idea_transport_reservations WHERE batch_id = ? AND state = 'ATTEMPTED'",
                (batch_id,),
            ).fetchone()[0]
            return int(allocation[0]) - int(attempted)

    def reconcile_batch(self, batch_id: str) -> dict[str, int | str]:
        """Return a safe, read-only accounting summary for one batch."""
        with self.database.connect() as connection:
            allocation = connection.execute(
                "SELECT * FROM real_idea_budget_allocations WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            if not allocation:
                raise KeyError(batch_id)
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN state = 'RESERVED' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN state = 'ATTEMPTED' THEN 1 ELSE 0 END),
                    SUM(CASE WHEN state = 'RELEASED' THEN 1 ELSE 0 END)
                FROM real_idea_transport_reservations WHERE batch_id = ?
                """,
                (batch_id,),
            ).fetchone()
            reserved, attempted, released = (int(value or 0) for value in counts)
            return {
                "batch_id": batch_id,
                "authorized_total": int(allocation["authorized_total"]),
                "batch_earmark": int(allocation["batch_earmark"]),
                "reserved": reserved,
                "attempted": attempted,
                "released": released,
                "remaining": int(allocation["batch_earmark"]) - attempted,
            }

    def _allocation(self, row: Any) -> BudgetAllocation:
        return BudgetAllocation(
            allocation_id=row["allocation_id"], batch_id=row["batch_id"],
            authorized_total=int(row["authorized_total"]), general_spendable=self.durable_budget,
            batch_earmark=int(row["batch_earmark"]), sample_cap=int(row["sample_cap"]),
            quickstart_cap=int(row["quickstart_cap"]), solutions_cap=int(row["solutions_cap"]),
        )

    @staticmethod
    def _reservation(row: Any) -> TransportReservation:
        return TransportReservation(
            reservation_id=row["reservation_id"], batch_id=row["batch_id"], sample_id=row["sample_id"],
            stage=row["stage"], ordinal=int(row["ordinal"]), idempotency_key=row["idempotency_key"],
            state=row["state"], dispatch_id=row["dispatch_id"], transport_id=row["transport_id"],
        )
