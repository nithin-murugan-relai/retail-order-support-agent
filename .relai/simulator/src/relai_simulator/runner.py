from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import time
from pathlib import Path
from typing import Any

import relai
from relai_simulator.adapter_contract import AdapterRuntime, AgentTurnResult

_RESERVED_METADATA_KEYS = {
    "arguments",
    "call_id",
    "content",
    "error",
    "name",
    "result",
    "turn_index",
}


async def run_loaded_environment(
    *,
    project_root: Path,
    learning_environment: relai.RELAIEnvironment,
    result_json_path: Path | None = None,
) -> relai.SimulationResult:
    with relai.TranscriptWriter.from_environment(
        learning_environment,
        base_dir=project_root,
    ) as transcript:
        if isinstance(learning_environment.target, relai.ComponentTarget):
            simulation_result = await _run_component_environment(
                learning_environment,
                transcript,
            )
        else:
            simulation_result = await _run_agent_environment(
                learning_environment=learning_environment,
                transcript=transcript,
            )

        global_evaluators = relai.filter_global_evaluators_for_environment(
            relai.load_global_evaluators(project_root),
            learning_environment,
            project_root=project_root,
        )
        combined_evaluators = relai.combine_evaluators(
            learning_environment.evaluators,
            global_evaluators,
        )
        await relai.run_evaluators(
            combined_evaluators,
            simulation_result,
            transcript_writer=transcript,
            continue_on_error=True,
        )
        simulation_result = transcript.to_simulation_result(
            final_output=simulation_result.final_output,
            stop_reason=simulation_result.stop_reason,
            metadata=simulation_result.metadata,
            timings=simulation_result.timings,
        )

    if result_json_path is not None:
        relai.write_simulation_result_json(simulation_result, result_json_path)

    return simulation_result


async def run_environment_file(
    *,
    project_root: Path,
    learning_env_path: Path,
    result_json_path: Path | None = None,
) -> relai.SimulationResult:
    learning_environment = relai.load_learning_environment(learning_env_path)
    return await run_loaded_environment(
        project_root=project_root,
        learning_environment=learning_environment,
        result_json_path=result_json_path,
    )


async def _run_agent_environment(
    *,
    learning_environment: relai.RELAIEnvironment,
    transcript: relai.TranscriptWriter,
) -> relai.SimulationResult:
    input_driver = relai.build_input_driver(learning_environment.input)
    final_output: object | None = None
    stop_reason: str | None = None
    turn_index = 0
    total_duration_ms = 0

    transcript.run_start(
        input_type=learning_environment.input.type,
        target_type="agent",
        target=_target_label(learning_environment),
    )

    with relai.MockApplication(learning_environment.mocks):
        runtime = AdapterRuntime(
            tool_overrides=relai.tool_name_mocks(learning_environment.mocks)
        )
        adapter = _build_agent_adapter(_agent_target_id(learning_environment), runtime)
        capabilities = relai.validate_adapter_capabilities(adapter)
        await _run_adapter_self_check(adapter, runtime, capabilities)
        recorded_runtime_calls = len(runtime.mock_calls)
        agent_message: str | None = None

        while True:
            next_turn = await input_driver.next_turn(agent_message)
            if next_turn.should_stop:
                stop_reason = next_turn.reason or "input driver stopped"
                transcript.run_end(reason=stop_reason)
                break

            transcript.user_message(
                next_turn.content,
                turn_index=turn_index,
                **_safe_metadata(next_turn.metadata),
            )

            try:
                started_at = time.perf_counter_ns()
                turn_result = await _run_adapter_turn(
                    adapter,
                    next_turn.content,
                    runtime,
                )
                total_duration_ms += max(
                    0, (time.perf_counter_ns() - started_at) // 1_000_000
                )
            except Exception as error:
                recorded_runtime_calls = _record_runtime_mock_calls(
                    runtime,
                    transcript,
                    recorded_runtime_calls,
                    turn_index,
                )
                transcript.error(error, turn_index=turn_index)
                transcript.run_end(reason="agent error")
                raise

            for tool_call in turn_result.tool_calls:
                transcript.tool_call(
                    tool_call.name,
                    tool_call.arguments,
                    turn_index=turn_index,
                    call_id=tool_call.call_id,
                    **_safe_metadata(tool_call.metadata),
                )
            for tool_result in turn_result.tool_results:
                transcript.tool_result(
                    tool_result.name,
                    result=tool_result.result,
                    error=tool_result.error,
                    turn_index=turn_index,
                    call_id=tool_result.call_id,
                    **_safe_metadata(tool_result.metadata),
                )

            agent_message = turn_result.assistant_message
            final_output = agent_message
            transcript.agent_message(
                agent_message,
                turn_index=turn_index,
                **_safe_metadata(turn_result.metadata),
            )

            recorded_runtime_calls = _record_runtime_mock_calls(
                runtime,
                transcript,
                recorded_runtime_calls,
                turn_index,
            )
            turn_index += 1

    return transcript.to_simulation_result(
        final_output=final_output,
        stop_reason=stop_reason,
        metadata={
            "target": _target_label(learning_environment),
            **(
                {"agent_target": _agent_target_id(learning_environment)}
                if _agent_target_id(learning_environment) is not None
                else {}
            ),
        },
        timings=relai.SimulationTimings(total_duration_ms=total_duration_ms),
    )


async def _run_component_environment(
    learning_environment: relai.RELAIEnvironment,
    transcript: relai.TranscriptWriter,
) -> relai.SimulationResult:
    runtime = AdapterRuntime(
        tool_overrides=relai.tool_name_mocks(learning_environment.mocks)
    )
    adapter = _build_agent_adapter(None, runtime)
    capabilities = relai.validate_adapter_capabilities(adapter)
    await _run_adapter_self_check(adapter, runtime, capabilities)
    recorded_runtime_calls = len(runtime.mock_calls)
    component_runner = None
    if "run_component" in capabilities:
        run_component = getattr(adapter, "run_component", None)
        if not callable(run_component):
            raise TypeError("run_component capability requires adapter.run_component")

        async def component_runner(target, call):
            nonlocal recorded_runtime_calls
            try:
                result = run_component(target, call, runtime)
                return await result if inspect.isawaitable(result) else result
            finally:
                recorded_runtime_calls = _record_runtime_mock_calls(
                    runtime,
                    transcript,
                    recorded_runtime_calls,
                    0,
                )

    return await relai.run_component_environment(
        learning_environment,
        transcript,
        component_runner=component_runner,
    )


def _record_runtime_mock_calls(
    runtime: AdapterRuntime,
    transcript: relai.TranscriptWriter,
    start_index: int,
    turn_index: int,
) -> int:
    for mock_call in runtime.mock_calls[start_index:]:
        transcript.mock_call(mock_call, turn_index=turn_index)
    return len(runtime.mock_calls)


def _build_agent_adapter(agent_target: str | None, runtime: AdapterRuntime) -> Any:
    module = importlib.import_module("relai_simulator.adapter")
    if agent_target is None:
        return module.build_agent_adapter(runtime=runtime)
    return module.build_agent_adapter(agent_target=agent_target, runtime=runtime)


async def _run_adapter_turn(
    adapter: Any,
    user_input: Any,
    runtime: AdapterRuntime,
) -> AgentTurnResult:
    result = adapter.run_turn(user_input, runtime)
    if inspect.isawaitable(result):
        result = await result
    if isinstance(result, AgentTurnResult):
        return result
    if isinstance(result, str) or result is None:
        return AgentTurnResult(assistant_message=result)
    if isinstance(result, dict):
        return AgentTurnResult(
            assistant_message=_optional_string(
                result.get("assistant_message", result.get("final_output"))
            ),
            metadata=_object_dict(result.get("metadata")),
        )
    assistant_message = getattr(
        result,
        "assistant_message",
        getattr(result, "final_output", None),
    )
    metadata = _object_dict(getattr(result, "metadata", None))
    return AgentTurnResult(
        assistant_message=_optional_string(assistant_message),
        metadata=metadata,
    )


async def _run_adapter_self_check(
    adapter: Any,
    runtime: AdapterRuntime,
    capabilities: frozenset[str],
) -> None:
    optional = capabilities - {"run_turn"}
    if not optional:
        return
    self_check = getattr(adapter, "self_check", None)
    if not callable(self_check):
        raise TypeError(
            "adapters with optional capabilities must implement self_check(runtime)"
        )
    results = self_check(runtime)
    if inspect.isawaitable(results):
        results = await results
    relai.validate_adapter_self_check(capabilities, results)


def _target_label(learning_environment: relai.RELAIEnvironment) -> str:
    target = learning_environment.target
    if target is None:
        return "agent"
    agent_target = _agent_target_id(learning_environment)
    if agent_target is not None:
        return f"agent:{agent_target}"
    import_path = getattr(target, "import_path", None)
    if isinstance(import_path, str) and import_path:
        return import_path
    return getattr(target, "type", "agent")


def _agent_target_id(learning_environment: relai.RELAIEnvironment) -> str | None:
    target = learning_environment.target
    if isinstance(target, relai.AgentTarget):
        return target.agent_target
    return None


def _safe_metadata(metadata: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    reserved: dict[str, object] = {}
    for key, value in metadata.items():
        safe_key = str(key)
        if safe_key in _RESERVED_METADATA_KEYS:
            reserved[safe_key] = _json_safe(value)
        else:
            safe[safe_key] = _json_safe(value)
    existing_metadata = safe.pop("metadata", None)
    if existing_metadata is not None:
        if isinstance(existing_metadata, dict):
            reserved = {**_object_dict(existing_metadata), **reserved}
        else:
            reserved = {"value": existing_metadata, **reserved}
    if reserved:
        safe["metadata"] = reserved
    return safe


def _json_safe(value: object) -> object:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        pass

    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_safe(model_dump(mode="json"))
    return {"type": type(value).__name__, "repr": repr(value)}


def _object_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the RELAI simulator.")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--learning-env", required=True)
    parser.add_argument("--result-json")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    project_root = Path(args.project_root).resolve()
    learning_env_path = Path(args.learning_env).resolve()
    result_json_path = (
        Path(args.result_json).resolve() if args.result_json is not None else None
    )
    asyncio.run(
        run_environment_file(
            project_root=project_root,
            learning_env_path=learning_env_path,
            result_json_path=result_json_path,
        )
    )


if __name__ == "__main__":
    main()
