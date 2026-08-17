from __future__ import annotations

import os
from typing import Any

from relai import (
    AgentTarget,
    FixedInput,
    FixedTurn,
    LLMJudgeEvaluator,
    ModelSpec,
    RELAIBenchmark,
    RELAIEnvironment,
    StoredBenchmarkCsv,
)


BENCHMARK_ID = "retail-train"
BENCHMARK_NAME = "retail-train"
DATASET_ID = "36ad3224-d949-42f4-82c9-5a6020532846"
REQUIRED_COLUMNS = ["sample_id", "input", "expected_behavior", "rubric"]


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _row_field(row_fields: Any, key: str) -> str:
    if isinstance(row_fields, dict):
        return _coerce_text(row_fields.get(key))

    try:
        value = row_fields[key]
    except Exception:
        return ""
    return _coerce_text(value)


def _sample_name(sample_id: str) -> str:
    words = [part for part in sample_id.replace("_", "-").split("-") if part]
    if not words:
        return "Retail support policy check"
    return " ".join(word.capitalize() for word in words)


def _judge_model() -> ModelSpec:
    if os.environ.get("OPENAI_API_KEY"):
        return ModelSpec(name="gpt-4o")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ModelSpec(name="litellm/anthropic/claude-sonnet-5")
    return ModelSpec(name="gpt-4o")


def _build_judge(row_fields: Any) -> LLMJudgeEvaluator:
    sample_id = _row_field(row_fields, "sample_id") or "retail-support-sample"
    user_input = _row_field(row_fields, "input")
    expected_behavior = _row_field(row_fields, "expected_behavior")
    rubric = _row_field(row_fields, "rubric")

    instructions = f"""
You are grading the first assistant response for a single-turn Northwind Retail support scenario.

Evaluate only whether the response takes the correct next action for this row. Treat later steps that
would require another user reply as out of scope unless the assistant improperly performed them now.
Accept semantically equivalent wording and concise phrasing; do not require exact text.

Row sample id: {sample_id}
Customer input:
{user_input}

Expected behavior:
{expected_behavior}

Rubric:
{rubric}

Scoring guidance:
- Give full credit only if the response materially satisfies the expected behavior and rubric.
- Deduct for any disallowed action, fabricated fact, missing required question, missing handoff, or
  policy mistake that changes the business outcome or the next action.
- If the response mixes correct and incorrect behavior, deduct based on the decisive failure.
- Focus on the first assistant response only.

Feedback requirements:
- If the score is below full credit, identify the failed criterion or rubric dimension.
- State the observed issue that caused the deduction.
- State what full-credit behavior required for this specific row.
- Keep feedback concise and concrete.
""".strip()

    return LLMJudgeEvaluator(
        id=f"{sample_id}-judge",
        description="Grades the first assistant response against the row's expected retail support behavior.",
        instructions=instructions,
        model=_judge_model(),
    )


def build_environment(row_fields, sample_index):
    sample_id = _row_field(row_fields, "sample_id") or f"sample-{sample_index}"
    user_input = _row_field(row_fields, "input")
    expected_behavior = _row_field(row_fields, "expected_behavior")
    rubric = _row_field(row_fields, "rubric")

    if not user_input:
        raise ValueError(f"benchmark row {sample_id} is missing a non-empty input value")
    if not expected_behavior:
        raise ValueError(f"benchmark row {sample_id} is missing a non-empty expected_behavior value")
    if not rubric:
        raise ValueError(f"benchmark row {sample_id} is missing a non-empty rubric value")

    return RELAIEnvironment(
        id=sample_id,
        name=_sample_name(sample_id),
        description=expected_behavior,
        tags=["end-to-end"],
        target=AgentTarget(agent_target="name"),
        input=FixedInput(turns=[FixedTurn(content=user_input)]),
        evaluators=[_build_judge(row_fields)],
    )


benchmark = RELAIBenchmark(
    schema_version="relai.benchmark.v1",
    id=BENCHMARK_ID,
    name=BENCHMARK_NAME,
    description=(
        "Single-turn Northwind Retail support benchmark that expands each live CSV row into an "
        "end-to-end agent environment and grades the first assistant response against the row rubric."
    ),
    dataset_ref=StoredBenchmarkCsv(id=DATASET_ID),
    required_columns=REQUIRED_COLUMNS,
    agent_target="name",
    build_environment=build_environment,
)
