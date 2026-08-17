from __future__ import annotations

from agents import Runner
from relai_simulator.adapter_contract import AdapterRuntime, AgentAdapter

from retail_support import store
from retail_support.agent import create_retail_agent


class ProjectAgentAdapter:
    capabilities = frozenset({"run_turn"})

    def __init__(self) -> None:
        store.reset()
        self._agent = create_retail_agent()
        self.agent_or_tools = self._agent
        self._history: list[dict[str, str]] = []

    async def run_turn(self, user_input: object, runtime: AdapterRuntime):
        if not isinstance(user_input, str):
            raise TypeError(
                "retail_support simulator expects each turn input to be a raw string."
            )

        self._history.append({"role": "user", "content": user_input})
        result = await Runner.run(self._agent, input=self._history)
        self._history = result.to_input_list()
        assistant_message = (
            None if result.final_output is None else str(result.final_output)
        )
        return {"assistant_message": assistant_message}


def build_agent_adapter(
    agent_target: str | None = None,
    runtime: AdapterRuntime | None = None,
) -> AgentAdapter:
    if agent_target not in (None, "name"):
        raise ValueError(
            "retail_support supports only the default agent target and the legacy 'name' alias."
        )
    return ProjectAgentAdapter()
