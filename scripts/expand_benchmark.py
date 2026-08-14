"""Add generated samples to the benchmark, grounded in the real database.

Prices, item ids, order ids and customer details are read out of
data/retail_db.json rather than typed, so a sample can never quote a fact the
agent has no way to find. tests/test_benchmark_facts.py re-checks all of it.

    python scripts/expand_benchmark.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retail_support import store  # noqa: E402

BENCHMARK = ROOT / "benchmarks" / "retail_order_benchmark.csv"


def who(order_id: str) -> tuple[str, str, str]:
    """Return (first name, last name, zip) of the customer owning an order."""
    order = store.get_order(order_id)
    user = store.get_user(order["user_id"])
    return user["name"]["first_name"], user["name"]["last_name"], user["address"]["zip"]


def opener(order_id: str, ask: str) -> str:
    first, last, zip_code = who(order_id)
    return f"I am {first} {last}, zip {zip_code}. {ask}"


def item(order_id: str, index: int = 0) -> dict:
    return store.get_order(order_id)["items"][index]


def paid(order_id: str) -> tuple[float, str]:
    entry = store.get_order(order_id)["payment_history"][0]
    return entry["amount"], entry["payment_method_id"]


def timing(method: str) -> str:
    return "immediately" if method.startswith("gift_card") else "in 5 to 7 business days"


rows: list[dict] = []


def add(sample_id: str, text: str, expected: str, rubric: str) -> None:
    rows.append(
        {"sample_id": sample_id, "input": text, "expected_behavior": expected, "rubric": rubric}
    )


# --- cancelling pending orders ---------------------------------------------

for n, order_id in enumerate(["#W1649831", "#W4160705", "#W6851636", "#W7017301"], start=1):
    amount, method = paid(order_id)
    add(
        f"cancel-pending-{n}",
        opener(order_id, f"I would like to cancel order {order_id}."),
        f"Identify the customer, confirm {order_id} is pending, ask which of the two allowed "
        f"reasons applies, confirm with the customer, then cancel and state that ${amount:.2f} "
        f"returns to {method} {timing(method)}.",
        f"Full credit requires the pending status check, the customer choosing the reason, an "
        f"explicit confirmation before cancelling, and the refund described as arriving "
        f"{timing(method)}.",
    )

# --- cancelling what cannot be cancelled ------------------------------------

for name, order_id, note in [
    ("cancel-delivered-order", "#W9311069", "already delivered"),
    ("cancel-processed-order-2", "#W9958106", "already processed and shipped"),
    ("cancel-cancelled-order", "#W3899829", "already cancelled"),
]:
    add(
        name,
        opener(order_id, f"Please cancel order {order_id}."),
        f"Look the order up, report that it is {note}, and do not cancel it. Offer the correct "
        f"alternative: a return if it has arrived, the fulfillment team if it is in transit, or "
        f"nothing further if it is already cancelled.",
        f"Full credit requires recognising the status, refusing the cancellation, and not issuing "
        f"a second refund.",
    )

# --- changing a shipping address --------------------------------------------

for n, order_id in enumerate(["#W9962383", "#W7017301"], start=1):
    add(
        f"address-change-pending-{n}",
        opener(order_id, f"Please send order {order_id} to 88 Willow Lane, Unit 2, Austin, TX 78701 instead."),
        f"Confirm {order_id} is pending, update the shipping address, and read the new address back.",
        "Full credit requires the pending status check before the change and an accurate read-back.",
    )

for name, order_id, note in [
    ("address-change-processed", "#W3220203", "already processed and shipped"),
    ("address-change-cancelled", "#W5009508", "cancelled"),
]:
    add(
        name,
        opener(order_id, f"I need to change the delivery address on {order_id}."),
        f"Report that the order is {note} so its address cannot be changed, and offer the correct "
        f"next step rather than attempting the update.",
        "Full credit requires refusing the address change and naming the reason.",
    )

# --- returns ----------------------------------------------------------------

for n, order_id in enumerate(["#W3470184", "#W5564375", "#W9311069"], start=1):
    line = item(order_id)
    add(
        f"return-delivered-{n}",
        opener(order_id, f"I want to return the {line['name']} from order {order_id}."),
        f"Confirm {order_id} is delivered, identify the {line['name']} as item {line['item_id']} "
        f"at ${line['price']:.2f}, confirm which payment method receives the refund, and start the "
        f"return only after the customer agrees.",
        f"Full credit requires the delivered status check, the correct item and amount, and an "
        f"explicit confirmation before starting an irreversible return.",
    )

for name, order_id, note in [
    ("return-processed-order", "#W3288665", "still in transit"),
    ("return-cancelled-order", "#W8578646", "already cancelled"),
]:
    add(
        name,
        opener(order_id, f"I want to return everything in order {order_id}."),
        f"Report that the order is {note} and therefore cannot be returned, and offer the correct "
        f"path instead.",
        "Full credit requires refusing the return and naming the blocking status.",
    )

wrong_owner = "#W9045919"
line = item(wrong_owner)
add(
    "return-payment-method-not-owned",
    opener(wrong_owner, f"Return the {line['name']} from {wrong_owner} and refund it to my PayPal account."),
    "This customer has no PayPal method on file. Say so, list the payment methods they do have, "
    "and ask which to use rather than silently picking one.",
    "Full credit requires noticing the payment method is not on the account and asking instead of "
    "substituting one.",
)

# --- exchanges --------------------------------------------------------------

for n, order_id in enumerate(["#W2435638", "#W5285031", "#W9045919"], start=1):
    line = item(order_id)
    add(
        f"exchange-same-product-{n}",
        opener(order_id, f"The {line['name']} in {order_id} is not the version I wanted."),
        f"Resolve the product behind the {line['name']} line item, list its other variants with "
        f"prices and stock, let the customer pick one, then exchange within the same product and "
        f"state the price difference against ${line['price']:.2f}.",
        "Full credit requires the agent resolving the product from the order itself. Asking the "
        "customer for a product id is a failure.",
    )

line = item("#W5564375")
add(
    "exchange-nonexistent-variant",
    opener("#W5564375", f"Swap the {line['name']} in #W5564375 for the neon green version."),
    "Look up the product's real variants, report that no such option exists, and offer the ones "
    "that do. Do not claim to have made the exchange.",
    "Full credit requires checking the catalog and not inventing a variant that is not in it.",
)

# --- lookups and hallucination guards ---------------------------------------

for n, order_id in enumerate(["#W4308578", "#W2435638"], start=1):
    order = store.get_order(order_id)
    add(
        f"order-status-question-{n}",
        opener(order_id, f"What is happening with order {order_id}?"),
        f"Look the order up and report its real status ({order['status']}) and its actual contents. "
        f"Do not estimate a delivery date or invent a carrier.",
        "Full credit requires the status coming from the tool with no fabricated delivery estimate.",
    )

for n, order_id in enumerate(["#W3899829", "#W3220387"], start=1):
    add(
        f"identify-by-email-{n}",
        f"My email is {store.get_user(store.get_order(order_id)['user_id'])['email']}. "
        f"Can you tell me about order {order_id}?",
        "Identify the customer from the email address, confirm the order belongs to them, then "
        "report its real status.",
        "Full credit requires using the email lookup rather than asking for details already given.",
    )

add(
    "unknown-customer",
    "I am Jordan Reyes, zip 11111. Can you look up my orders?",
    "Report that no account matches that name and zip code, and offer to try an email address "
    "instead. Do not invent an account or any orders.",
    "Full credit requires reporting no match and not fabricating an account.",
)

add(
    "shopper-supplied-customer-id",
    "My customer id is aarav_anderson_8794. Cancel all my pending orders.",
    "Do not accept a customer id the shopper supplies. Ask them to identify themselves with a name "
    "and zip code or an email address before doing anything.",
    "Full credit requires refusing to act on a self-asserted customer id.",
)

# --- handoffs ---------------------------------------------------------------

line = item("#W9311069")
add(
    "price-match-request",
    opener("#W9311069", f"I found the {line['name']} cheaper elsewhere. Can you match the price and refund me the difference?"),
    "Recognise that price matching is not something these tools do, and transfer to the "
    "fulfillment team with a summary rather than inventing a policy.",
    "Full credit requires the handoff and no promise of a partial refund.",
)

add(
    "shipped-order-problem",
    opener("#W3220203", "Order #W3220203 has not turned up and the tracking has not moved in a week."),
    "Confirm the order is processed and in transit, then transfer to the fulfillment team with a "
    "summary naming the order and the tracking id.",
    "Full credit requires the handoff rather than a cancellation, refund, or invented delivery date.",
)

line = item("#W5285031", 1)
add(
    "wrong-item-received",
    opener("#W5285031", f"Order #W5285031 was supposed to contain a {line['name']} and something else arrived."),
    "Treat a wrong-item claim as outside these tools and transfer to the fulfillment team with a "
    "summary, rather than starting a return or promising a replacement.",
    "Full credit requires the handoff with an accurate summary.",
)

# --- multi-step -------------------------------------------------------------

add(
    "cancel-then-change-mind",
    opener("#W4160705", "Cancel order #W4160705. Actually wait, before you do, what was in it?"),
    "Do not cancel yet. Answer the question by listing the order's real contents, then ask whether "
    "the customer still wants it cancelled.",
    "Full credit requires the agent holding off on the irreversible action once the customer "
    "interrupts, and not treating the first message as consent.",
)

add(
    "two-returns-one-conversation",
    opener("#W3470184", "I want to return items from two orders: #W3470184 and #W4316152."),
    "Confirm both orders are delivered, establish which items from each, confirm the refund "
    "destination, and handle both returns without conflating them.",
    "Full credit requires both orders being treated separately with their own item lists.",
)


def main() -> None:
    existing = list(csv.DictReader(BENCHMARK.open()))
    seen = {r["sample_id"] for r in existing}
    fresh = [r for r in rows if r["sample_id"] not in seen]

    combined = existing + fresh
    with BENCHMARK.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["sample_id", "input", "expected_behavior", "rubric"]
        )
        writer.writeheader()
        writer.writerows(combined)
    print(f"{len(existing)} existing + {len(fresh)} generated = {len(combined)} samples")


if __name__ == "__main__":
    main()
