from __future__ import annotations

from typing import Any, Protocol

from relai import AdapterRuntime, AgentTurnResult, ToolCallRecord, ToolResultRecord


class AgentAdapter(Protocol):
    capabilities: frozenset[str]

    def run_turn(self, user_input: Any, runtime: AdapterRuntime) -> AgentTurnResult | Any: ...


__all__ = ["AgentAdapter", "AgentTurnResult", "AdapterRuntime", "ToolCallRecord", "ToolResultRecord"]
