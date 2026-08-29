from __future__ import annotations

import json
import os
from typing import Any

from app.tools import ToolRegistry


class OpenAIToolCallingAgent:
    """Optional cloud-model loop that cannot bypass ToolRegistry policy gates."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        model: str = "gpt-5.6",
        max_tool_rounds: int = 4,
    ):
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for the optional OpenAI adapter")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError('Install optional dependencies with: pip install -e ".[llm]"') from exc
        if max_tool_rounds < 1 or max_tool_rounds > 8:
            raise ValueError("max_tool_rounds must be in [1, 8]")
        self.client = OpenAI()
        self.registry = registry
        self.model = model
        self.max_tool_rounds = max_tool_rounds

    def run(self, user_message: str, *, actor: str = "llm_assistant") -> str:
        messages: list[Any] = [
            {
                "role": "system",
                "content": (
                    "You are a project evidence assistant. Retrieve before asserting. "
                    "Always preserve source_type and citations. simulated_research and "
                    "model_hypothesis are not verified findings. Never approve, publish, "
                    "delete, or overwrite artifacts."
                ),
            },
            {"role": "user", "content": user_message},
        ]
        for _round in range(self.max_tool_rounds):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.registry.schemas(),
            )
            message = response.choices[0].message
            messages.append(message)
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return message.content or ""
            for call in tool_calls:
                try:
                    arguments = json.loads(call.function.arguments)
                    output = self.registry.execute(
                        call.function.name,
                        arguments,
                        actor=actor,
                        human_confirmed=False,
                    )
                except Exception as exc:
                    output = {"error": type(exc).__name__, "message": str(exc)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(output, ensure_ascii=False),
                    }
                )
        return "工具调用达到上限，系统已停止并转人工处理。"
