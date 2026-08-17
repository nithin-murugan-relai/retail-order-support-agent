from relai import AgentTarget, FixedInput, FixedTurn, RELAIEnvironment

environment = RELAIEnvironment(
    id="relai-init-smoke",
    name="RELAI init smoke",
    description="Runs one representative Northwind Retail customer request through the simulator.",
    target=AgentTarget(),
    input=FixedInput(
        turns=[
            FixedTurn(
                content="I am Aarav Anderson, zip 19031. I want to cancel order #W9300146."
            ),
        ],
    ),
    mocks={},
    evaluators=[],
)
