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
        )
        if not 1 <= settings.max_loop_rounds <= 5:
            raise ValueError("INSIGHTFORGE_MAX_LOOP_ROUNDS must be in [1, 5]")
        if not 1 <= settings.default_top_k <= 30:
            raise ValueError("INSIGHTFORGE_DEFAULT_TOP_K must be in [1, 30]")
        if bool(settings.access_username) != bool(settings.access_password):
            raise ValueError(
                "INSIGHTFORGE_ACCESS_USERNAME and INSIGHTFORGE_ACCESS_PASSWORD must be set together"
            )
        return settings
