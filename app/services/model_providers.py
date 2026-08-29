"""Provider identities and protocol/base-URL resolution.

Provider identity is deliberately separate from a wire protocol: several presets
currently use OpenAI-compatible chat completions, but that must not make them one
provider in persisted profiles or audit records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProviderProtocol = Literal["openai_chat_completions", "anthropic_messages", "custom"]


class ProviderConfigurationError(ValueError):
    """A non-secret, local configuration problem."""


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    provider: str
    protocol: ProviderProtocol
    default_base_url: str | None


class ProviderRegistry:
    """Small, explicit registry of supported provider identities."""

    _PRESETS: dict[str, ProviderPreset] = {
        "qwen": ProviderPreset("qwen", "openai_chat_completions", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "kimi": ProviderPreset("kimi", "openai_chat_completions", "https://api.moonshot.cn/v1"),
        "deepseek": ProviderPreset("deepseek", "openai_chat_completions", "https://api.deepseek.com"),
        "glm": ProviderPreset("glm", "openai_chat_completions", "https://open.bigmodel.cn/api/paas/v4"),
        "openai": ProviderPreset("openai", "openai_chat_completions", "https://api.openai.com/v1"),
        "custom": ProviderPreset("custom", "custom", None),
    }
    _ADAPTER_PROTOCOLS = {"openai_chat_completions", "anthropic_messages"}
    _BAILIAN_SHARED_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @classmethod
    def get(cls, provider: str) -> ProviderPreset:
        key = str(provider).strip().casefold()
        try:
            return cls._PRESETS[key]
        except KeyError:
            raise ProviderConfigurationError("Unknown provider preset.") from None

    @classmethod
    def resolve(
        cls,
        provider: str,
        *,
        protocol: ProviderProtocol | str | None = None,
        base_url: str | None = None,
    ) -> ProviderPreset:
        """Resolve a configured provider without accepting implicit custom defaults."""
        preset = cls.get(provider)
        if preset.provider == "custom":
            selected_protocol = protocol or preset.protocol
            selected_base_url = base_url or preset.default_base_url
            if selected_protocol not in cls._ADAPTER_PROTOCOLS or not selected_base_url:
                raise ProviderConfigurationError(
                    "Custom provider requires a supported protocol and base URL."
                )
        else:
            if protocol is not None and protocol != preset.protocol:
                raise ProviderConfigurationError(
                    "Preset providers do not accept protocol overrides."
                )
            requested_url = base_url.rstrip("/") if isinstance(base_url, str) else None
            official_url = str(preset.default_base_url).rstrip("/")
            bailian_override = (
                preset.provider in {"deepseek", "glm"}
                and requested_url is not None
                and (
                    requested_url == cls._BAILIAN_SHARED_URL
                    or requested_url.endswith(".maas.aliyuncs.com/compatible-mode/v1")
                )
            )
            if requested_url is not None and requested_url != official_url and not bailian_override:
                raise ProviderConfigurationError(
                    "Preset provider base URL override is not allowed for this endpoint."
                )
            selected_protocol = preset.protocol
            selected_base_url = requested_url or preset.default_base_url
        if not isinstance(selected_base_url, str) or not selected_base_url.startswith(("https://", "http://")):
            raise ProviderConfigurationError("Provider base URL must be an HTTP(S) URL.")
        return ProviderPreset(preset.provider, selected_protocol, selected_base_url.rstrip("/"))
