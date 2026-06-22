from __future__ import annotations

from importlib.resources import files
from typing import Any

from langchain_core.tools import BaseTool


def load_system_prompt() -> str:
    return files("data_agent_agent.prompts").joinpath("system.md").read_text(encoding="utf-8")


def openai_model_name(model: str) -> str:
    return model if model.startswith("openai:") else f"openai:{model}"


def create_data_agent(
    *,
    model: str,
    tools: list[BaseTool],
    system_prompt: str | None = None,
) -> Any:
    from deepagents import create_deep_agent

    return create_deep_agent(
        model=openai_model_name(model),
        tools=tools,
        system_prompt=system_prompt or load_system_prompt(),
    )
