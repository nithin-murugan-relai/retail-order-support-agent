"""The retail order-support agent: its tools and its instructions.

This file is the whole agent. The instructions below and the tool bodies are the
surface a RELAI optimization run is allowed to change; the store and the
benchmark are the fixed part of the problem.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable

from agents import Agent, Runner, function_tool
from openai.types.responses import ResponseTextDeltaEvent

from retail_support import store
from retail_support.models import select_model
from retail_support.sessions import ChatMessage


# --- tools ------------------------------------------------------------------


@function_tool
def find_customer_by_name_zip(first_name: str, last_name: str, zip_code: str) -> str:
    """Find a customer id from their first name, last name, and zip code."""
    user = store.match_user(first_name, last_name, zip_code)
    if user is None:
        return "No customer matched that name and zip code."
    return f"Customer id: {user['user_id']}"


@function_tool
def find_customer_by_email(email: str) -> str:
    """Find a customer id from their email address."""
    user = store.match_user_by_email(email)
    if user is None:
        return "No customer matched that email address."
    return f"Customer id: {user['user_id']}"


@function_tool
def get_customer_details(user_id: str) -> str:
    """Return a customer's contact details, payment methods, and order ids."""
    user = store.get_user(user_id)
    if user is None:
        return "No such customer."
    return store.format_user(user)


@function_tool
def get_order_details(order_id: str) -> str:
    """Return the status, items, shipping address, and payments for one order."""
    order = store.get_order(order_id)
    if order is None:
        return "No such order."
    return store.format_order(order)


@function_tool
def get_product_details(product_id: str) -> str:
    """List every variant of a product with its price and stock status."""
    product = store.get_product(product_id)
    if product is None:
        return "No such product."
    return store.format_product(product)


@function_tool
def cancel_pending_order(order_id: str, reason: str) -> str:
    """Cancel an order that has not shipped yet. Reason must be 'no longer needed' or 'ordered by mistake'."""
    order = store.get_order(order_id)
    if order is None:
        return "No such order."
    if order["status"] != "pending":
        return f"Order {order['order_id']} is {order['status']} and can no longer be cancelled."
    if reason not in {"no longer needed", "ordered by mistake"}:
        return "Reason must be exactly 'no longer needed' or 'ordered by mistake'."

    payment = order["payment_history"][0]
    store.record_refund(order, payment["amount"], payment["payment_method_id"])
    order["status"] = "cancelled"
    order["cancel_reason"] = reason
    method = payment["payment_method_id"]
    timing = "immediately" if method.startswith("gift_card") else "in 5 to 7 business days"
    return (
        f"Order {order['order_id']} is cancelled. ${payment['amount']:.2f} will be refunded "
        f"to {method} {timing}."
    )


@function_tool
def modify_pending_order_address(
    order_id: str,
    address1: str,
    address2: str,
    city: str,
    state: str,
    zip_code: str,
    country: str = "USA",
) -> str:
    """Change the shipping address of an order that has not shipped yet."""
    order = store.get_order(order_id)
    if order is None:
        return "No such order."
    if order["status"] != "pending":
        return f"Order {order['order_id']} is {order['status']} and its address can no longer be changed."

    order["address"] = {
        "address1": address1,
        "address2": address2,
        "city": city,
        "country": country,
        "state": state,
        "zip": zip_code,
    }
    return f"Shipping address for {order['order_id']} updated to {store.format_address(order['address'])}."


@function_tool
def return_delivered_order_items(order_id: str, item_ids: list[str], refund_payment_method_id: str) -> str:
    """Start a return for one or more items from a delivered order."""
    order = store.get_order(order_id)
    if order is None:
        return "No such order."
    if order["status"] != "delivered":
        return f"Order {order['order_id']} is {order['status']}. Only delivered orders can be returned."

    owned = {item["item_id"] for item in order["items"]}
    unknown = [item_id for item_id in item_ids if item_id not in owned]
    if unknown:
        return f"These items are not part of {order['order_id']}: {', '.join(unknown)}."

    user = store.get_user(order["user_id"])
    if user is None or refund_payment_method_id not in user["payment_methods"]:
        return "That payment method does not belong to this customer."

    amount = store.refund_total(order, item_ids)
    store.record_refund(order, amount, refund_payment_method_id)
    order["status"] = "return requested"
    order["return_items"] = sorted(item_ids)
    return (
        f"Return started for {order['order_id']}. ${amount:.2f} will be refunded to "
        f"{refund_payment_method_id} once the items arrive. A prepaid label has been emailed to "
        f"{user['email']}."
    )


@function_tool
def exchange_delivered_order_items(
    order_id: str,
    item_ids: list[str],
    new_item_ids: list[str],
    payment_method_id: str,
) -> str:
    """Exchange delivered items for different variants of the same product."""
    order = store.get_order(order_id)
    if order is None:
        return "No such order."
    if order["status"] != "delivered":
        return f"Order {order['order_id']} is {order['status']}. Only delivered orders can be exchanged."
    if len(item_ids) != len(new_item_ids):
        return "Provide exactly one replacement item for each item being exchanged."

    user = store.get_user(order["user_id"])
    if user is None or payment_method_id not in user["payment_methods"]:
        return "That payment method does not belong to this customer."

    difference = 0.0
    for old_id, new_id in zip(item_ids, new_item_ids):
        old_item = next((item for item in order["items"] if item["item_id"] == old_id), None)
        if old_item is None:
            return f"Item {old_id} is not part of {order['order_id']}."

        product = store.find_product_of_item(new_id)
        if product is None:
            return f"Item {new_id} does not exist."
        if product["product_id"] != old_item["product_id"]:
            return (
                f"Item {new_id} is a different product. Exchanges must stay within the same "
                f"product; use a return instead."
            )
        variant = product["variants"][new_id]
        if not variant["available"]:
            return f"Item {new_id} is out of stock."
        difference += variant["price"] - old_item["price"]

    order["status"] = "exchange requested"
    order["exchange_items"] = sorted(item_ids)
    order["exchange_new_items"] = sorted(new_item_ids)
    if difference > 0:
        settlement = f"${difference:.2f} will be charged to {payment_method_id}."
    elif difference < 0:
        settlement = f"${abs(difference):.2f} will be refunded to {payment_method_id}."
    else:
        settlement = "There is no price difference."
    return f"Exchange started for {order['order_id']}. {settlement} A prepaid label has been emailed."


@function_tool
def transfer_to_fulfillment_team(order_id: str, summary: str) -> str:
    """Hand the case to the human fulfillment team for anything these tools do not cover."""
    return (
        f"Transferred order {order_id} to the fulfillment team with this summary: {summary}. "
        f"They will reply by email within one business day."
    )


TOOLS = [
    find_customer_by_name_zip,
    find_customer_by_email,
    get_customer_details,
    get_order_details,
    get_product_details,
    cancel_pending_order,
    modify_pending_order_address,
    return_delivered_order_items,
    exchange_delivered_order_items,
    transfer_to_fulfillment_team,
]


# --- instructions -----------------------------------------------------------

# This is a first draft, on purpose. It is roughly what someone writes before
# they have watched the agent fail: a description of the job and nothing about
# the rules the business actually runs on.
#
# The rules are real. They are enforced by the tools in this file and asserted by
# benchmarks/retail_order_benchmark.csv. This agent simply does not know them yet,
# and has to learn them from the conversations where it gets them wrong. That is
# the gap an optimization pass is meant to close.
RETAIL_AGENT_INSTRUCTIONS = """
You are a customer support agent for Northwind Retail, an online store.

Help customers with questions and problems about their orders. You have tools for
looking up customers, orders, and products, and for cancelling, readdressing,
returning, and exchanging orders.

Be friendly, and keep your replies short.
""".strip()


def create_retail_agent() -> Agent:
    selection = select_model()
    model_kwargs = {"model": selection.model} if selection.model else {}
    return Agent(
        name="Northwind Retail Support",
        instructions=RETAIL_AGENT_INSTRUCTIONS,
        tools=TOOLS,
        **model_kwargs,
    )


def _messages_to_agent_input(messages: Iterable[ChatMessage]) -> list[dict[str, str]]:
    return [
        {"role": message.role, "content": message.content}
        for message in messages
        if message.role in {"user", "assistant"}
    ]


async def stream_agent_response(messages: Iterable[ChatMessage]) -> AsyncIterator[str]:
    result = Runner.run_streamed(create_retail_agent(), input=_messages_to_agent_input(messages))
    async for event in result.stream_events():
        if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
            if event.data.delta:
                yield event.data.delta
