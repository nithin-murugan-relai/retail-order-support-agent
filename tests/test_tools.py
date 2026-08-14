"""The policy rules, exercised directly against the tools. No model calls."""

from __future__ import annotations

import json

import pytest
from agents.tool_context import ToolContext

from retail_support import agent, store


@pytest.fixture(autouse=True)
def fresh_store():
    """Each test starts from the shipped database, since the tools mutate in place."""
    store.reset()
    yield
    store.reset()


async def call(tool, **kwargs) -> str:
    """Invoke a @function_tool the way the Agents SDK does."""
    context = ToolContext(
        context=None,
        tool_name=tool.name,
        tool_call_id="test",
        tool_arguments="{}",
        run_config=None,
    )
    return await tool.on_invoke_tool(context, json.dumps(kwargs))


# --- lookups ----------------------------------------------------------------


async def test_customer_lookup_by_name_and_zip():
    out = await call(
        agent.find_customer_by_name_zip, first_name="Aarav", last_name="Anderson", zip_code="19031"
    )
    assert "aarav_anderson_8794" in out


async def test_customer_lookup_rejects_wrong_zip():
    out = await call(
        agent.find_customer_by_name_zip, first_name="Aarav", last_name="Anderson", zip_code="00000"
    )
    assert "No customer matched" in out


async def test_order_lookup_tolerates_a_missing_hash():
    with_hash = await call(agent.get_order_details, order_id="#W9300146")
    without_hash = await call(agent.get_order_details, order_id="W9300146")
    assert with_hash == without_hash
    assert "status: pending" in with_hash


async def test_unknown_order_is_reported_not_invented():
    out = await call(agent.get_order_details, order_id="#W1111111")
    assert out == "No such order."


# --- cancellation -----------------------------------------------------------


async def test_cancel_pending_order_refunds_to_gift_card_immediately():
    out = await call(agent.cancel_pending_order, order_id="#W9300146", reason="ordered by mistake")
    assert "cancelled" in out
    assert "immediately" in out
    order = store.get_order("#W9300146")
    assert order["status"] == "cancelled"
    assert any(e["transaction_type"] == "refund" for e in order["payment_history"])


async def test_cancel_rejects_a_reason_outside_the_two_allowed():
    out = await call(agent.cancel_pending_order, order_id="#W9300146", reason="seller was rude")
    assert "no longer needed" in out and "ordered by mistake" in out
    assert store.get_order("#W9300146")["status"] == "pending", "the order must be untouched"


async def test_cancel_refuses_a_processed_order():
    out = await call(agent.cancel_pending_order, order_id="#W3288665", reason="no longer needed")
    assert "processed" in out
    assert store.get_order("#W3288665")["status"] == "processed"


# --- address ----------------------------------------------------------------


async def test_address_change_on_a_pending_order():
    out = await call(
        agent.modify_pending_order_address,
        order_id="#W4308578",
        address1="42 Pine Street",
        address2="Apt 3",
        city="Philadelphia",
        state="PA",
        zip_code="19104",
    )
    assert "42 Pine Street" in out
    assert store.get_order("#W4308578")["address"]["zip"] == "19104"


async def test_address_change_refused_once_delivered():
    before = store.get_order("#W5285031")["address"]["zip"]
    out = await call(
        agent.modify_pending_order_address,
        order_id="#W5285031",
        address1="1 New Road",
        address2="",
        city="Orlando",
        state="FL",
        zip_code="32801",
    )
    assert "delivered" in out
    assert store.get_order("#W5285031")["address"]["zip"] == before


# --- returns ----------------------------------------------------------------


async def test_return_delivered_item_refunds_the_item_price():
    out = await call(
        agent.return_delivered_order_items,
        order_id="#W9045919",
        item_ids=["1719127154"],
        refund_payment_method_id="credit_card_1982124",
    )
    assert "206.26" in out
    assert store.get_order("#W9045919")["status"] == "return requested"


async def test_return_refuses_a_payment_method_the_customer_does_not_own():
    out = await call(
        agent.return_delivered_order_items,
        order_id="#W9045919",
        item_ids=["1719127154"],
        refund_payment_method_id="gift_card_7245904",  # belongs to a different customer
    )
    assert "does not belong" in out
    assert store.get_order("#W9045919")["status"] == "delivered"


async def test_return_refuses_an_item_from_another_order():
    out = await call(
        agent.return_delivered_order_items,
        order_id="#W9045919",
        item_ids=["9190635437"],
        refund_payment_method_id="credit_card_1982124",
    )
    assert "not part of" in out


async def test_return_refuses_a_pending_order():
    out = await call(
        agent.return_delivered_order_items,
        order_id="#W1649831",
        item_ids=["4422467033"],
        refund_payment_method_id="credit_card_1982124",
    )
    assert "pending" in out


# --- exchanges --------------------------------------------------------------


async def test_exchange_must_stay_within_the_same_product():
    # A Water Bottle variant swapped in for Wireless Earbuds is a different product.
    out = await call(
        agent.exchange_delivered_order_items,
        order_id="#W3470184",
        item_ids=["6452271382"],
        new_item_ids=["2366567022"],
        payment_method_id="gift_card_7245904",
    )
    assert "different product" in out
    assert store.get_order("#W3470184")["status"] == "delivered"


async def test_exchange_within_the_same_product_reports_the_price_difference():
    product = store.find_product_of_item("6452271382")
    alternative = next(
        item_id
        for item_id, variant in product["variants"].items()
        if item_id != "6452271382" and variant["available"]
    )
    out = await call(
        agent.exchange_delivered_order_items,
        order_id="#W3470184",
        item_ids=["6452271382"],
        new_item_ids=[alternative],
        payment_method_id="gift_card_7245904",
    )
    assert "Exchange started" in out
    assert "charged" in out or "refunded" in out or "no price difference" in out
    assert store.get_order("#W3470184")["status"] == "exchange requested"


async def test_exchange_requires_matching_counts():
    out = await call(
        agent.exchange_delivered_order_items,
        order_id="#W3470184",
        item_ids=["6452271382", "2366567022"],
        new_item_ids=["6452271382"],
        payment_method_id="gift_card_7245904",
    )
    assert "one replacement item" in out


# --- handoff ----------------------------------------------------------------


async def test_handoff_echoes_the_summary():
    out = await call(
        agent.transfer_to_fulfillment_team,
        order_id="#W2435638",
        summary="Espresso machine arrived cracked",
    )
    assert "fulfillment team" in out
    assert "cracked" in out


def test_the_agent_exposes_every_tool():
    assert len(agent.TOOLS) == 10
    names = {tool.name for tool in agent.TOOLS}
    assert "transfer_to_fulfillment_team" in names
