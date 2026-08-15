from __future__ import annotations

from agents import Runner
from dotenv import load_dotenv
from relai_simulator.adapter_contract import AdapterRuntime, AgentAdapter

from retail_support import store
from retail_support.agent import create_retail_agent


class ProjectAgentAdapter:
    capabilities = frozenset({"run_turn"})

    def __init__(self) -> None:
        load_dotenv()
        store.reset()
        self._agent = create_retail_agent()
        self._history: list[dict[str, object]] = []

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
    if agent_target is not None:
        raise ValueError("retail_support exposes no named agent targets.")
    return ProjectAgentAdapter()
