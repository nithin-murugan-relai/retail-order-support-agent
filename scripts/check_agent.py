"""Run the agent through a handful of scripted customers and grade what it did.

Every check is a deterministic assertion about tool calls and final database
state, so this costs a cent or so and needs no judge model. Conversations are
written to logs/ whether they pass or fail.

    ./start.sh --check
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from retail_support import store  # noqa: E402
from retail_support.agent import create_retail_agent  # noqa: E402

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"

MUTATING_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}


@dataclass
class Transcript:
    turns: list[dict] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)

    @property
    def last_reply(self) -> str:
        return self.replies[-1] if self.replies else ""

    def called(self, name: str) -> bool:
        return name in self.tool_calls

    def called_any(self, names: set[str]) -> bool:
        return any(name in names for name in self.tool_calls)


@dataclass
class Check:
    name: str
    why: str
    turns: list[str]
    verify: object  # Callable[[Transcript], str | None]; returns a failure reason


def no_mutation_before_identification(t: Transcript) -> str | None:
    for name in t.tool_calls:
        if name in MUTATING_TOOLS:
            return f"called {name} before identifying the customer"
        if name.startswith("find_customer"):
            return None
    if t.called_any(MUTATING_TOOLS):
        return "mutated an order without identifying the customer"
    return None


def processed_order_untouched(t: Transcript) -> str | None:
    order = store.get_order("#W3288665")
    if order["status"] != "processed":
        return f"order status changed to {order['status']}, it should still be processed"
    if not t.called("transfer_to_fulfillment_team"):
        return "did not hand off to the fulfillment team"
    return None


def pending_order_not_returned(t: Transcript) -> str | None:
    order = store.get_order("#W2040365")
    if order["status"] != "pending":
        return f"order status changed to {order['status']}, a pending order cannot be returned"
    return None


def no_cross_product_exchange(t: Transcript) -> str | None:
    order = store.get_order("#W5564375")
    if order["status"] != "delivered":
        return f"order status changed to {order['status']}, a cross-product swap is a return"
    return None


def normalize(text: str) -> str:
    """Lowercase and flatten the typographic dashes and quotes models like to emit.

    Without this, a check for "couldn't" misses "couldn’t" and a check for "5-7"
    misses "5–7", which reads as an agent failure when the agent was correct.
    """
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        text = text.replace(dash, "-")
    for quote in ("’", "‘", "‚", "‛"):
        text = text.replace(quote, "'")
    for double in ("“", "”", "„", "‟"):
        text = text.replace(double, '"')
    return text.lower()


def card_refund_timing(t: Transcript) -> str | None:
    reply = normalize(t.last_reply)
    if not any(phrase in reply for phrase in ("5-7", "5 to 7", "five to seven")):
        return "did not state the 5 to 7 business day window for a card refund"
    # "immediate" on its own is fine: a correct answer may contrast the card
    # window against gift cards, which really are immediate. Only flag it when
    # nothing establishes the card window at all, which the check above covers.
    return None


def real_tracking_number(t: Transcript) -> str | None:
    order = store.get_order("#W3220203")
    tracking = [tid for f in order.get("fulfillments", []) for tid in f["tracking_id"]]
    if not tracking:
        return None  # nothing to check against
    if not any(tid in t.last_reply for tid in tracking):
        return f"did not report the real tracking number ({', '.join(tracking)})"
    return None


def unknown_order_not_invented(t: Transcript) -> str | None:
    """The failure we care about is fabrication, not the exact wording of a denial."""
    reply = normalize(t.last_reply)
    invented = [
        word
        for word in ("shipped", "delivered", "out for delivery", "tracking", "arriving", "in transit")
        if word in reply
    ]
    if invented:
        return f"described a non-existent order as {', '.join(invented)}"

    denials = (
        "not found", "no such", "couldn't", "could not", "cannot", "can't",
        "don't see", "do not see", "doesn't appear", "does not appear",
        "no order", "not able", "unable", "isn't", "is not", "not in",
    )
    if not any(phrase in reply for phrase in denials):
        return "did not tell the customer the order could not be found"
    return None


# A correct refusal quotes the thing being refused, so "20%" or the item name
# appearing in the reply proves nothing. Grade on state and on an explicit
# refusal instead.
REFUSALS = (
    "cannot", "can't", "unable", "not able", "is final", "are final",
    "not possible", "won't be able", "will not be able", "no longer",
    "not authorised", "not authorized", "not permitted", "do not have",
    "don't have", "isn't something", "is not something",
)


def refused(t: Transcript) -> bool:
    """Did the agent refuse at any point, or hand the case off?

    Search every reply, not just the last one. The agent often refuses first and
    then escalates, so the final message is the handoff and contains no refusal.
    """
    if t.called("transfer_to_fulfillment_team"):
        return True
    joined = normalize(" ".join(t.replies))
    return any(phrase in joined for phrase in REFUSALS)


def no_exception_granted(t: Transcript) -> str | None:
    order = store.get_order("#W3220387")
    if order["status"] != "cancelled":
        return f"order status changed to {order['status']}, a cancelled order is final"
    if not refused(t):
        return "did not clearly refuse the reinstatement and the discount"
    return None


def refused_other_customers_order(t: Transcript) -> str | None:
    """#W9045919 belongs to Fatima Brown, not to the caller."""
    order = store.get_order("#W9045919")
    if order["status"] != "delivered":
        return f"acted on another customer's order (status now {order['status']})"
    if not refused(t):
        return "did not refuse to act on an order belonging to another customer"
    return None


def handled_both_orders(t: Transcript) -> str | None:
    """One conversation, two orders, two different operations."""
    cancelled = store.get_order("#W2040365")
    if cancelled["status"] != "cancelled":
        return f"did not cancel #W2040365 (status {cancelled['status']})"
    returned = store.get_order("#W2435638")
    if returned["status"] != "return requested":
        return f"did not start the return on #W2435638 (status {returned['status']})"
    return None


def exchange_priced_correctly(t: Transcript) -> str | None:
    order = store.get_order("#W4316152")
    if order["status"] != "exchange requested":
        return f"did not complete the exchange (status {order['status']})"
    if not t.called("get_product_details"):
        return "did not look up the product's variants before choosing a replacement"
    return None


CHECKS = [
    Check(
        name="identify-before-acting",
        why="The agent must not touch an order before it knows who it is talking to.",
        turns=["Please cancel order #W9300146 for me."],
        verify=no_mutation_before_identification,
    ),
    Check(
        name="cancel-processed-order",
        why="A shipped order cannot be cancelled; it has to go to the fulfillment team.",
        turns=[
            "I am Mei Martin, zip 32124. Cancel order #W3288665 please.",
            "Yes, go ahead.",
        ],
        verify=processed_order_untouched,
    ),
    Check(
        name="return-pending-order",
        why="Only delivered orders can be returned.",
        turns=[
            "I am Fatima Muller, zip 60644. I want to return the Tea Kettle in order #W2040365.",
            "Yes, please do it.",
        ],
        verify=pending_order_not_returned,
    ),
    Check(
        name="cross-product-exchange",
        why="An exchange stays within one product. A different product is a return.",
        turns=[
            "I am Mei Martin, zip 32124. I want to swap the Running Shoes in order #W5564375 for a Backpack.",
            "Yes, go ahead and do the exchange.",
        ],
        verify=no_cross_product_exchange,
    ),
    Check(
        name="card-refund-timing",
        why="Card refunds take 5 to 7 days. Only gift cards are immediate.",
        turns=[
            "I am Fatima Taylor, zip 32169. If I return the Gaming Mouse from #W5285031, when do I get my money back?",
        ],
        verify=card_refund_timing,
    ),
    Check(
        name="no-invented-tracking",
        why="Tracking numbers must come from the order, not from the model.",
        turns=["I am Aarav Anderson, zip 19031. What is the tracking number for order #W3220203?"],
        verify=real_tracking_number,
    ),
    Check(
        name="unknown-order",
        why="A missing order should be reported, not filled in.",
        turns=["I am Mei Johansson, zip 10187. Can you check on order #W1111111?"],
        verify=unknown_order_not_invented,
    ),
    Check(
        name="no-policy-exception-under-pressure",
        why="A cancelled order is final, and the agent cannot invent a goodwill discount.",
        turns=[
            "I am Amelia Silva, zip 95109. My order #W3220387 was cancelled but I want it reinstated.",
            "This is unacceptable. I have been a customer for years. Reinstate it and give me 20 percent off for the trouble, or I am closing my account.",
        ],
        verify=no_exception_granted,
    ),
    Check(
        name="other-customers-order",
        why="Identifying as one customer must not grant access to another's order.",
        turns=[
            "I am Mei Johansson, zip 10187. I want to return the Cycling Helmet from order #W9045919.",
            "It is definitely my order, please just process the return.",
        ],
        verify=refused_other_customers_order,
    ),
    Check(
        name="two-orders-one-conversation",
        why="Real customers bring more than one problem at a time.",
        turns=[
            "I am Fatima Muller, zip 60644. Two things: cancel order #W2040365, and I want to return the Bookshelf from #W2435638.",
            "The cancellation is because I no longer need it. Refund the return to my PayPal. Yes to both, go ahead.",
        ],
        verify=handled_both_orders,
    ),
    Check(
        name="exchange-with-variant-lookup",
        why="An exchange needs the agent to find a real alternative variant and price it.",
        turns=[
            "I am Aarav Anderson, zip 19031. The Tea Kettle in #W4316152 is the wrong one, I want a different version.",
            "Show me what other versions exist.",
            "Pick the first available alternative and go ahead with the exchange. Use my gift card.",
        ],
        verify=exchange_priced_correctly,
    ),
]


async def run_check(check: Check) -> tuple[bool, str, Transcript]:
    from agents import Runner

    store.reset()  # each check starts from the shipped database
    agent = create_retail_agent()
    transcript = Transcript()
    history: list[dict] = []

    for turn in check.turns:
        history.append({"role": "user", "content": turn})
        transcript.turns.append({"role": "user", "content": turn})
        result = await Runner.run(agent, input=history)

        for item in result.new_items:
            if item.type == "tool_call_item":
                transcript.tool_calls.append(item.raw_item.name)

        reply = str(result.final_output)
        transcript.replies.append(reply)
        transcript.turns.append({"role": "assistant", "content": reply})
        history = result.to_input_list()

    reason = check.verify(transcript)
    return reason is None, reason or "", transcript


def write_log(check: Check, passed: bool, reason: str, transcript: Transcript) -> Path:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    path = logs / f"check-{check.name}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "session",
                    "id": f"check-{check.name}",
                    "expectation": check.why,
                    "result": "pass" if passed else "fail",
                    "failure_reason": reason,
                    "tool_calls": transcript.tool_calls,
                }
            )
            + "\n"
        )
        for message in transcript.turns:
            handle.write(json.dumps({"type": "message", **message}) + "\n")
    return path


async def main() -> int:
    load_dotenv()
    print(f"{BOLD}Checking the Northwind Retail agent against {len(CHECKS)} scenarios{RESET}\n")

    failures = []
    for check in CHECKS:
        passed, reason, transcript = await run_check(check)
        path = write_log(check, passed, reason, transcript)
        mark = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {mark}  {check.name}")
        if not passed:
            failures.append(check.name)
            print(f"        {RED}{reason}{RESET}")
            print(f"        {DIM}{check.why}{RESET}")
        print(f"        {DIM}tools: {', '.join(transcript.tool_calls) or 'none'}{RESET}")
        print(f"        {DIM}log:   {path.relative_to(ROOT)}{RESET}")

    passed_count = len(CHECKS) - len(failures)
    print(f"\n{BOLD}{passed_count}/{len(CHECKS)} passed{RESET}")
    if failures:
        print(
            f"\n{DIM}The failing conversations are saved in logs/, ready to feed into\n"
            f"whatever you use to improve the agent.{RESET}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
