"""Explicit, quota-consuming provider capability checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from app.services.provider_adapters import ModelAdapter


CapabilityStatus = Literal["supported", "unsupported", "unknown"]


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    basic_chat: CapabilityStatus
    structured_json: CapabilityStatus
    function_calling: CapabilityStatus
    streaming: CapabilityStatus
    checked_at: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "basic_chat": self.basic_chat,
            "structured_json": self.structured_json,
            "function_calling": self.function_calling,
            "streaming": self.streaming,
            "checked_at": self.checked_at.isoformat(),
        }


class CapabilityProbe:
    """Runs only when a caller explicitly invokes :meth:`probe`.

    Function calling and streaming are left unknown until a future, dedicated
    probe is requested; model names and preset identities are never used as proof.
    """

    def __init__(self, adapter: "ModelAdapter") -> None:
        self._adapter = adapter

    def probe(self) -> CapabilityReport:
        return CapabilityReport(
            basic_chat=self._adapter._probe_basic_chat(),
            structured_json=self._adapter._probe_structured_json(),
            function_calling="unknown",
            streaming="unknown",
            checked_at=datetime.now(timezone.utc),
        )
