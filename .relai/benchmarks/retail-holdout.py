import os

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


BENCHMARK_ID = "retail-holdout"
BENCHMARK_NAME = "retail-holdout"
DATASET_REF_ID = "3ee5745f-8140-41ad-8a5f-2fa59e6b80c2"
REQUIRED_COLUMNS = ["sample_id", "input", "expected_behavior", "rubric"]


def _row_text(row_fields, key):
    if not isinstance(row_fields, dict):
        return ""
    value = row_fields.get(key)
    if value is None:
        return ""
    return str(value).strip()


def _sample_id(row_fields, sample_index):
    sample_id = _row_text(row_fields, "sample_id")
    if sample_id:
        return sample_id
    return f"sample-{sample_index}"


def _sample_name(sample_id):
    words = [word for word in sample_id.replace("_", "-").split("-") if word]
    if not words:
        return "Retail support scenario"
    return " ".join(word.capitalize() for word in words)


def _judge_model():
    if os.environ.get("OPENAI_API_KEY"):
        return ModelSpec(name="gpt-4o")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ModelSpec(name="litellm/anthropic/claude-sonnet-5", provider="litellm")
    return ModelSpec(name="gpt-4o")


def _judge_instructions(row_fields):
    sample_id = _sample_id(row_fields, sample_index="row")
    customer_input = _row_text(row_fields, "input")
    expected_behavior = _row_text(row_fields, "expected_behavior")
    rubric = _row_text(row_fields, "rubric")
    return (
        "Score only the assistant's first reply to the customer's first message in this "
        "environment. Use the benchmark row below as the source of truth.\n\n"
        f"Sample id: {sample_id}\n"
        f"Customer message: {customer_input}\n"
        f"Expected behavior: {expected_behavior}\n"
        f"Rubric: {rubric}\n\n"
        "Grading rules:\n"
        "- Judge first-turn behavior only. Do not assume a later follow-up unless one is "
        "explicitly present in the environment input.\n"
        "- Do not require exact wording when the meaning is correct.\n"
        "- Give full credit when the reply takes the correct policy path, states or requests "
        "the decisive facts needed at this turn, and avoids disallowed actions or invented facts.\n"
        "- Give partial credit when the reply is directionally correct but misses a decisive "
        "required detail from the expected behavior or rubric.\n"
        "- Deduct heavily when the reply takes the wrong operational path, fabricates facts, "
        "acts without required identification, accepts a self-asserted customer id, skips a "
        "required refusal or transfer, or performs an irreversible step that should wait for "
        "customer choice or confirmation.\n"
        "- When the row expects a later customer choice or confirmation, full credit on the "
        "first turn means the assistant correctly asks for that choice or confirmation now "
        "instead of pretending it already has it.\n"
        "- If score is below full credit, feedback must name the failed criterion or rule, "
        "describe the observed issue that caused the deduction, and state what full-credit "
        "behavior required."
    )


def build_environment(row_fields, sample_index):
    sample_id = _sample_id(row_fields, sample_index)
    customer_input = _row_text(row_fields, "input")
    expected_behavior = _row_text(row_fields, "expected_behavior")

    return RELAIEnvironment(
        id=sample_id,
        name=_sample_name(sample_id),
        description=(
            expected_behavior
            or "Judge whether the retail support agent handles the customer request correctly."
        ),
        tags=["end-to-end"],
        target=AgentTarget(),
        input=FixedInput(turns=[FixedTurn(content=customer_input)]),
        evaluators=[
            LLMJudgeEvaluator(
                id=f"{sample_id}-judge",
                description="Grades the first-turn retail support behavior for this benchmark row.",
                instructions=_judge_instructions(row_fields),
                model=_judge_model(),
            )
        ],
    )


benchmark = RELAIBenchmark(
    schema_version="relai.benchmark.v1",
    id=BENCHMARK_ID,
    name=BENCHMARK_NAME,
    description="Holdout benchmark for end-to-end retail order-support policy and workflow behavior.",
    dataset_ref=StoredBenchmarkCsv(id=DATASET_REF_ID),
    required_columns=REQUIRED_COLUMNS,
    build_environment=build_environment,
)
