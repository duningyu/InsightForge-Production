"""Closed-beta participant runtime boundary and safe path derivation."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

PARTICIPANT_RE = re.compile(r"^(?:beta_[0-9]{3}|user_[a-f0-9]{32})$")
APPROVED_RAILWAY_STAGE_PARTICIPANTS = frozenset({"railway_stage_a", "railway_stage_b"})


def validate_participant_id(value: str) -> str:
    if not isinstance(value, str) or (
        value not in APPROVED_RAILWAY_STAGE_PARTICIPANTS and not PARTICIPANT_RE.fullmatch(value)
    ):
        raise ValueError(
            "participant_id must match beta_[0-9]{3}, be one of the approved Railway stage identities, "
            "or be a server account identity"
        )
    return value


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    root: Path
    temp: Path
    exports: Path
    uploads: Path
    handoff: Path

    @classmethod
    def from_root(cls, root: str | Path) -> "RuntimePaths":
        base = Path(root).expanduser().resolve()
        paths = cls(base, base / "tmp", base / "exports", base / "uploads", base / "handoff")
        for path in (paths.root, paths.temp, paths.exports, paths.uploads, paths.handoff):
            path.mkdir(parents=True, exist_ok=True)
        return paths

    def child(self, relative_name: str, *, area: str = "temp") -> Path:
        if not isinstance(relative_name, str) or not relative_name:
            raise ValueError("runtime child name is required")
        root = getattr(self, area, None)
        if not isinstance(root, Path):
            raise ValueError("unknown runtime area")
        # Treat Windows separators as separators even when acceptance tests run
        # on POSIX.  Reject drive-qualified/absolute Windows paths before the
        # native resolve check so the boundary is platform-independent.
        windows_name = PureWindowsPath(relative_name)
        if windows_name.is_absolute() or windows_name.drive:
            raise ValueError("runtime child name must be relative")
        candidate = (root / relative_name.replace("\\", "/")).resolve()
        if root.resolve() != candidate and root.resolve() not in candidate.parents:
            raise ValueError("runtime path escapes participant root")
        return candidate


@dataclass(frozen=True, slots=True)
class BetaInstanceContext:
    participant_id: str | None
    database_path: Path
    runtime: RuntimePaths
    beta_mode: bool
    release_id: str

    @classmethod
    def from_settings(cls, settings) -> "BetaInstanceContext":
        participant = validate_participant_id(settings.beta_participant_id) if settings.beta_participant_id else None
        return cls(participant, Path(settings.database_path).expanduser().resolve(), RuntimePaths.from_root(settings.runtime_dir), settings.beta_mode, settings.beta_release_id)
