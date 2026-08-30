from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "InsightForge"
    app_version: str = "3.0.0"
    database_path: Path = Path("data/insightforge.sqlite3")
    max_loop_rounds: int = 2
    default_top_k: int = 8
    openai_model: str = "gpt-5.6"
    access_username: str | None = None
    access_password: str | None = None
    beta_mode: bool = False
    beta_release_id: str = "insightforge_closed_beta_20260830_v1"
    beta_participant_id: str | None = None
    beta_consent_version: int = 1
    beta_session_idle_timeout_minutes: int = 30
    beta_session_cookie_secure: bool = False
    runtime_dir: Path = Path("runtime")

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            app_name=os.getenv("INSIGHTFORGE_APP_NAME", "InsightForge"),
            app_version=os.getenv("INSIGHTFORGE_APP_VERSION", "3.0.0"),
            database_path=Path(os.getenv("INSIGHTFORGE_DATABASE_PATH", "data/insightforge.sqlite3")),
            max_loop_rounds=int(os.getenv("INSIGHTFORGE_MAX_LOOP_ROUNDS", "2")),
            default_top_k=int(os.getenv("INSIGHTFORGE_DEFAULT_TOP_K", "8")),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
            access_username=os.getenv("INSIGHTFORGE_ACCESS_USERNAME") or None,
            access_password=os.getenv("INSIGHTFORGE_ACCESS_PASSWORD") or None,
            beta_mode=os.getenv("BETA_MODE", "false").strip().lower() in {"1", "true", "yes"},
            beta_release_id=os.getenv("BETA_RELEASE_ID", "insightforge_closed_beta_20260830_v1"),
            beta_participant_id=os.getenv("BETA_PARTICIPANT_ID") or None,
            beta_consent_version=int(os.getenv("BETA_CONSENT_VERSION", "1")),
            beta_session_idle_timeout_minutes=int(os.getenv("BETA_SESSION_IDLE_TIMEOUT_MINUTES", "30")),
            beta_session_cookie_secure=os.getenv("BETA_SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"},
            runtime_dir=Path(os.getenv("RUNTIME_DIR", "runtime")),
        )
        if not 1 <= settings.max_loop_rounds <= 5:
            raise ValueError("INSIGHTFORGE_MAX_LOOP_ROUNDS must be in [1, 5]")
        if not 1 <= settings.default_top_k <= 30:
            raise ValueError("INSIGHTFORGE_DEFAULT_TOP_K must be in [1, 30]")
        if bool(settings.access_username) != bool(settings.access_password):
            raise ValueError(
                "INSIGHTFORGE_ACCESS_USERNAME and INSIGHTFORGE_ACCESS_PASSWORD must be set together"
            )
        if settings.beta_consent_version < 1:
            raise ValueError("BETA_CONSENT_VERSION must be positive")
        if settings.beta_session_idle_timeout_minutes != 30:
            raise ValueError("BETA_SESSION_IDLE_TIMEOUT_MINUTES must remain 30")
        return settings
