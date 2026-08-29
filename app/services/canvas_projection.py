from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CanvasProjection:
    problem: str
    target_users: str
    goals: list[str]
    non_goals: list[str]
    success_metrics: list[str]
    constraints: list[str]


class CanvasProjectionService:
    """Deterministically projects a confirmed Snapshot into the legacy Canvas contract."""

    def project(self, snapshot_payload: dict[str, Any]) -> CanvasProjection:
        target = snapshot_payload.get("target_user") or {}
        problem = snapshot_payload.get("problem") or {}
        mvp = snapshot_payload.get("mvp") or {}
        solution = snapshot_payload.get("solution") or {}
        technical = snapshot_payload.get("technical_plan") or {}
        unknowns = snapshot_payload.get("unknowns") or []
        return CanvasProjection(
            target_users=str(target.get("primary") or ""),
            problem=str(problem.get("statement") or ""),
            goals=[str(item) for item in (mvp.get("outcomes") or [])],
            non_goals=[str(item) for item in (solution.get("explicit_non_goals") or [])],
            success_metrics=[str(item) for item in (mvp.get("acceptance_criteria") or [])],
            constraints=[
                *[str(item) for item in unknowns],
                *[str(item) for item in (technical.get("constraints") or [])],
            ],
        )
