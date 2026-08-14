"""Every fact quoted in the benchmark CSV must exist in the demo database.

A benchmark that asserts a price or an item id the agent cannot possibly find is
worse than no benchmark, because it teaches the optimizer to hallucinate. These
tests fail loudly if the two files drift apart.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from retail_support import store

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "retail_order_benchmark.csv"

ORDER_RE = re.compile(r"#W\d{7}")
ITEM_RE = re.compile(r"\b(?:item id |item )(\d{10})\b")
PAYMENT_RE = re.compile(r"\b((?:gift_card|credit_card|paypal)_\d+)\b")
AMOUNT_RE = re.compile(r"\$(\d+\.\d{2})")

# The one order id that is deliberately absent, used by the unknown-order sample.
KNOWN_MISSING = {"#W1111111"}


def rows() -> list[dict[str, str]]:
    with BENCHMARK.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_rows_are_well_formed():
    seen = set()
    for row in rows():
        # DictReader parks surplus fields under None, which is what an unquoted
        # comma inside a rubric looks like.
        assert None not in row, f"{row['sample_id']} has an unquoted comma: {row[None]}"
        assert row["sample_id"], "every sample needs an id"
        assert row["sample_id"] not in seen, f"duplicate sample id {row['sample_id']}"
        seen.add(row["sample_id"])
        for column in ("input", "expected_behavior", "rubric"):
            assert row[column].strip(), f"{row['sample_id']} has an empty {column}"
    assert len(seen) >= 15, "the benchmark should be substantial enough to show a score spread"


def test_referenced_orders_exist():
    for row in rows():
        text = " ".join(row.values())
        for order_id in ORDER_RE.findall(text):
            if order_id in KNOWN_MISSING:
                assert store.get_order(order_id) is None, f"{order_id} should not exist"
                continue
            assert store.get_order(order_id) is not None, f"{row['sample_id']} cites missing {order_id}"


def test_referenced_items_belong_to_the_cited_order():
    for row in rows():
        text = " ".join(row.values())
        order_ids = [oid for oid in ORDER_RE.findall(text) if oid not in KNOWN_MISSING]
        item_ids = ITEM_RE.findall(text)
        if not item_ids or not order_ids:
            continue
        owned = {
            item["item_id"]
            for oid in order_ids
            for item in (store.get_order(oid) or {"items": []})["items"]
        }
        for item_id in item_ids:
            assert item_id in owned, f"{row['sample_id']} cites item {item_id} not in {order_ids}"


def test_referenced_payment_methods_belong_to_the_cited_customer():
    for row in rows():
        text = " ".join(row.values())
        methods = PAYMENT_RE.findall(text)
        order_ids = [oid for oid in ORDER_RE.findall(text) if oid not in KNOWN_MISSING]
        if not methods or not order_ids:
            continue
        allowed: set[str] = set()
        for oid in order_ids:
            order = store.get_order(oid)
            user = store.get_user(order["user_id"]) if order else None
            if user:
                allowed |= set(user["payment_methods"])
        for method in methods:
            assert method in allowed, f"{row['sample_id']} cites {method}, not owned by the customer"


def test_quoted_amounts_match_a_real_item_price():
    for row in rows():
        text = " ".join(row.values())
        order_ids = [oid for oid in ORDER_RE.findall(text) if oid not in KNOWN_MISSING]
        amounts = AMOUNT_RE.findall(text)
        if not amounts or not order_ids:
            continue
        prices = set()
        for oid in order_ids:
            order = store.get_order(oid)
            if not order:
                continue
            prices |= {f"{item['price']:.2f}" for item in order["items"]}
            prices |= {
                f"{entry['amount']:.2f}"
                for entry in order["payment_history"]
                if entry["transaction_type"] == "payment"
            }
        for amount in amounts:
            assert amount in prices, f"{row['sample_id']} quotes ${amount}, not a price in {order_ids}"


def test_customer_names_and_zips_resolve():
    """Each sample that opens with an identity must name a customer who exists."""
    pattern = re.compile(r"(?:I am|This is)\s+([A-Z][a-z]+)\s+([A-Z][a-z]+),\s*zip\s*(\d{5})")
    matched = 0
    for row in rows():
        found = pattern.search(row["input"])
        if not found:
            continue
        first, last, zip_code = found.groups()
        assert store.match_user(first, last, zip_code) is not None, (
            f"{row['sample_id']} identifies {first} {last}/{zip_code}, who is not in the database"
        )
        matched += 1
    assert matched >= 10, "most samples should exercise the identification step"
