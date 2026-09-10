from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class Settings:
    app_name: str = "InsightForge"
    app_version: str = "3.0.0"
    data_root: Path = Path(".")
    database_path: Path = Path("data/insightforge.sqlite3")
    max_loop_rounds: int = 2
    default_top_k: int = 8
    openai_model: str = "gpt-5.6"
    access_username: str | None = None
    access_password: str | None = None
    beta_mode: bool = False
    beta_managed_mode: bool = False
    managed_qwen_model: str = "qwen3.7-flash"
    managed_qwen_api_key: str | None = None
    managed_bailian_api_key: str | None = None
    managed_pilot_default_model: str = "qwen3.7-flash"
    managed_qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    beta_release_id: str = "insightforge_closed_beta_20260830_v1"
    beta_participant_id: str | None = None
    beta_consent_version: int = 1
    beta_session_idle_timeout_minutes: int = 30
    beta_session_cookie_secure: bool = False
    beta_timezone: str = "Asia/Shanghai"
    daily_user_limits_enabled: bool = False
    runtime_dir: Path = Path("runtime")
    accounts_enabled: bool = False
    accounts_dir: Path = Path("data/accounts")
    safe_fixture_mode: bool = False
    safe_fixture_scenario: str = "success"

    @classmethod
    def from_env(cls) -> "Settings":
        data_root_value = os.getenv("INSIGHTFORGE_DATA_ROOT")
        data_root = Path(data_root_value) if data_root_value else Path(".")
        database_value = os.getenv("INSIGHTFORGE_DATABASE_PATH")
        runtime_value = os.getenv("RUNTIME_DIR")
        accounts_value = os.getenv("INSIGHTFORGE_ACCOUNTS_DIR")
        settings = cls(
            app_name=os.getenv("INSIGHTFORGE_APP_NAME", "InsightForge"),
            app_version=os.getenv("INSIGHTFORGE_APP_VERSION", "3.0.0"),
            data_root=data_root,
            database_path=Path(database_value) if database_value else (
                data_root / "insightforge.sqlite3" if data_root_value else Path("data/insightforge.sqlite3")
            ),
            max_loop_rounds=int(os.getenv("INSIGHTFORGE_MAX_LOOP_ROUNDS", "2")),
            default_top_k=int(os.getenv("INSIGHTFORGE_DEFAULT_TOP_K", "8")),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6"),
            access_username=os.getenv("INSIGHTFORGE_ACCESS_USERNAME") or None,
            access_password=os.getenv("INSIGHTFORGE_ACCESS_PASSWORD") or None,
            beta_mode=os.getenv("BETA_MODE", "false").strip().lower() in {"1", "true", "yes"},
            beta_managed_mode=os.getenv("BETA_MANAGED_MODE", "false").strip().lower() in {"1", "true", "yes"},
            managed_qwen_model=os.getenv("MANAGED_QWEN_MODEL", "qwen3.7-flash"),
            managed_qwen_api_key=os.getenv("MANAGED_QWEN_API_KEY") or None,
            managed_bailian_api_key=(os.getenv("MANAGED_BAILIAN_API_KEY") or os.getenv("MANAGED_QWEN_API_KEY") or None),
            managed_pilot_default_model=os.getenv("MANAGED_PILOT_DEFAULT_MODEL", "qwen3.7-flash"),
            managed_qwen_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            beta_release_id=os.getenv("BETA_RELEASE_ID", "insightforge_closed_beta_20260830_v1"),
            beta_participant_id=os.getenv("BETA_PARTICIPANT_ID") or None,
            beta_consent_version=int(os.getenv("BETA_CONSENT_VERSION", "1")),
            beta_session_idle_timeout_minutes=int(os.getenv("BETA_SESSION_IDLE_TIMEOUT_MINUTES", "30")),
            beta_session_cookie_secure=os.getenv("BETA_SESSION_COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes"},
            beta_timezone=os.getenv("BETA_TIMEZONE", "Asia/Shanghai"),
            daily_user_limits_enabled=os.getenv("INSIGHTFORGE_DAILY_USER_LIMITS_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            runtime_dir=Path(runtime_value) if runtime_value else (
                data_root / "runtime" if data_root_value else Path("runtime")
            ),
            accounts_enabled=os.getenv("INSIGHTFORGE_ACCOUNTS_ENABLED", "false").lower() == "true",
            accounts_dir=Path(accounts_value) if accounts_value else (
                data_root / "accounts" if data_root_value else Path("data/accounts")
            ),
            safe_fixture_mode=os.getenv("INSIGHTFORGE_SAFE_FIXTURE_MODE", "false").strip().lower() in {"1", "true", "yes"},
            safe_fixture_scenario=os.getenv("INSIGHTFORGE_SAFE_FIXTURE_SCENARIO", "success").strip(),
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
        if settings.safe_fixture_scenario not in {"success", "solution_generation_fail_once"}:
            raise ValueError("INSIGHTFORGE_SAFE_FIXTURE_SCENARIO is unsupported")
        try:
            ZoneInfo(settings.beta_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("BETA_TIMEZONE must name an installed IANA timezone") from exc
        return settings
