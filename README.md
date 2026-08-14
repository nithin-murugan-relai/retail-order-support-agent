# Northwind Retail Support Agent

A small retail order-support agent, built as a worked example for optimizing an
agent with [RELAI](https://relai.ai).

It does what an e-commerce back office actually does: look a customer up, cancel
an order that has not shipped, change a shipping address, start a return or an
exchange on a delivered order, and hand anything else to the human fulfillment
team.

It is deliberately small. `src/retail_support/agent.py` is the whole agent:
ten tools and one instruction block.

## Two commands

```sh
git clone https://github.com/nithin-murugan-relai/retail-order-support-agent
cd retail-order-support-agent && ./start.sh
```

`start.sh` installs everything, asks for an `OPENAI_API_KEY` or
`ANTHROPIC_API_KEY` if it needs one, and drops you into a chat. Try:

```
I am Aarav Anderson, zip 19031. I want to cancel order #W9300146.
```

Type `exit` to leave. Every conversation is saved to `logs/`.

## See where it breaks

```sh
./start.sh --check
```

This runs the agent through 11 scripted customers and grades each one on what it
actually did: which tools it called, and what state the order database ended up
in. No judge model, so it is deterministic and costs about a cent.

On `gpt-4o` the agent scores **10 out of 11**, the same check failing on every
run:

> **`exchange-with-variant-lookup`** - a customer says the Tea Kettle they
> received is the wrong one and asks to see the other versions. The agent calls
> `get_product_details("Tea Kettle")`, gets back "No such product", and then asks
> the customer to supply a product ID. No real customer knows their product ID.

The cause is not the wording of the instructions. `get_order_details` prints item
ids but never product ids, so there is no path from "the Tea Kettle in my order"
to the product the agent needs to look up. The agent is being asked to do
something its tools do not let it do. That is what makes it a good optimization
target rather than a prompt tweak.

Every check writes its conversation to `logs/check-*.jsonl`, pass or fail. Those
transcripts are the material RELAI learns from.

A note on the checks themselves, since it cost real time to learn: grade agent
behaviour on **state and tool calls**, not on keywords in the reply. Early
versions of these checks searched the text and produced three false failures in a
row, because a correct refusal quotes the thing it is refusing ("I'm unable to
offer the requested 20% discount" contains "20%"), and models write "5–7" with an
en dash and "couldn't" with a curly apostrophe. The verifiers in
`scripts/check_agent.py` assert against the order database wherever they can.

## What is in here

| Path | Role |
|---|---|
| `src/retail_support/agent.py` | The agent: ten tools and its instructions. This is what RELAI optimizes. |
| `src/retail_support/store.py` | The order database and the rules for changing it. The fixed part of the problem. |
| `src/retail_support/main.py` | Terminal chat loop. Writes `logs/*.jsonl`. |
| `scripts/check_agent.py` | The 11 scripted checks behind `--check`. |
| `data/retail_db.json` | 8 customers, 22 orders, 33 products. |
| `benchmarks/retail_order_benchmark.csv` | 18 benchmark samples covering the policy rules. |
| `tests/` | 24 tests, no model calls. |

The rules the agent is meant to follow, all enforced by the tools and checked by
the tests:

- Identify the customer before touching any order, and never accept a customer id
  the shopper supplies.
- Pending orders can be cancelled or readdressed. Delivered orders can be returned
  or exchanged. Processed orders have shipped. Cancelled orders are final.
- An exchange stays within one product. A different product is a return.
- Cancellations accept two reasons only: `no longer needed` or `ordered by mistake`.
- Gift card refunds are immediate; card and PayPal take 5 to 7 business days.
- Anything else goes to the fulfillment team, not to improvisation.

## The benchmark, and how it relates to the checks

`benchmarks/retail_order_benchmark.csv` holds **18 samples** in the standard
four-column RELAI shape (`sample_id,input,expected_behavior,rubric`), so it can be
registered directly:

```sh
relai benchmark register --csv benchmarks/retail_order_benchmark.csv
```

The 11 scripted checks behind `./start.sh --check` are a **subset** of it. Every
check has a benchmark row with the same `sample_id`. The difference is how they
are graded:

- The **checks** grade deterministically, on tool calls and on the final state of
  the order database. Free to judge, no RELAI account, same answer every time.
  They only cover cases where a machine can tell right from wrong outright.
- The **benchmark** grades against the `rubric` column, which covers the other
  seven cases where the right answer is a judgement call, such as whether the
  agent asked which of the two cancellation reasons applied before choosing one.

Use the checks for a fast local signal and the benchmark for the full picture.

## Point RELAI at it

From the repository root:

```sh
relai init
```

`relai init` reads the repo, works out how to drive the agent, and sets up
learning environments. The failing conversations in `logs/` are the material it
learns from: you can simulate against them, register
`benchmarks/retail_order_benchmark.csv` as a benchmark, and then optimize the
instructions and tools in `agent.py` and re-run `./start.sh --check` to see
whether the score moved.

## Tests

```sh
uv run pytest
```

24 tests, no model calls, about a second. They check the policy rules directly
against the tools, and they check that every order id, price, item id, payment
method and customer name in the benchmark actually resolves against the database,
so a test case can never ask the agent for something it has no way to find.

## Which model it runs

Built on the [OpenAI Agents SDK](https://github.com/openai/openai-agents-python).
`src/retail_support/models.py` picks the provider from whichever key is set:

| Key | Model |
|---|---|
| `OPENAI_API_KEY` | `gpt-4o` (the SDK default) |
| `ANTHROPIC_API_KEY` | `claude-sonnet-5` via LiteLLM |

OpenAI wins if both are set. You pay your own provider. A chat is a fraction of a
cent and a full `--check` run is about a cent.

## Data provenance

The customers, orders, and products are a subset of the retail domain of
[tau2-bench](https://github.com/sierra-research/tau2-bench) by Sierra Research,
used under the MIT licence. `scripts/build_demo_db.py` regenerates the subset from
a tau2-bench checkout. The agent, its tools, the policy, the checks, and the
benchmark here are our own. tau2-bench is not a dependency and you do not need it
to run anything in this repository.

## Licence

MIT. See `LICENSE`.
