"""In-memory retail store backing the agent's tools.

The database is loaded from ``data/retail_db.json`` once per process and mutated
in place. Nothing is written back to disk, so every run of the agent (and every
benchmark sample) starts from the same known state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def db_path() -> Path:
    override = os.environ.get("RETAIL_SUPPORT_DB")
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[2] / "data" / "retail_db.json"


_DB: dict[str, Any] | None = None


def db() -> dict[str, Any]:
    """Return the live database, loading it on first use."""
    global _DB
    if _DB is None:
        _DB = json.loads(db_path().read_text())
    return _DB


def reset() -> None:
    """Drop all in-process mutations. Used by the tests and the benchmark runner."""
    global _DB
    _DB = None


# --- lookups ----------------------------------------------------------------


def get_user(user_id: str) -> dict[str, Any] | None:
    return db()["users"].get(user_id.strip())


def get_order(order_id: str) -> dict[str, Any] | None:
    order_id = order_id.strip().upper()
    if not order_id.startswith("#"):
        order_id = f"#{order_id}"
    return db()["orders"].get(order_id)


def get_product(product_id: str) -> dict[str, Any] | None:
    return db()["products"].get(product_id.strip())


def find_product_of_item(item_id: str) -> dict[str, Any] | None:
    """Find the product that owns a given variant."""
    for product in db()["products"].values():
        if item_id.strip() in product["variants"]:
            return product
    return None


def match_user(first_name: str, last_name: str, zip_code: str) -> dict[str, Any] | None:
    for user in db()["users"].values():
        name = user["name"]
        if (
            name["first_name"].lower() == first_name.strip().lower()
            and name["last_name"].lower() == last_name.strip().lower()
            and user["address"]["zip"] == zip_code.strip()
        ):
            return user
    return None


def match_user_by_email(email: str) -> dict[str, Any] | None:
    for user in db()["users"].values():
        if user["email"].lower() == email.strip().lower():
            return user
    return None


# --- formatting -------------------------------------------------------------


def format_address(address: dict[str, str]) -> str:
    parts = [address["address1"]]
    if address.get("address2"):
        parts.append(address["address2"])
    parts.append(f"{address['city']}, {address['state']} {address['zip']}")
    return ", ".join(parts)


def format_order(order: dict[str, Any]) -> str:
    lines = [
        f"Order {order['order_id']} for user {order['user_id']} - status: {order['status']}",
        f"Ship to: {format_address(order['address'])}",
        "Items:",
    ]
    for item in order["items"]:
        options = ", ".join(f"{k}: {v}" for k, v in item["options"].items())
        lines.append(f"  - {item['name']} (item {item['item_id']}) ${item['price']:.2f} [{options}]")
    total = sum(entry["amount"] for entry in order["payment_history"] if entry["transaction_type"] == "payment")
    lines.append(f"Total paid: ${total:.2f}")
    for entry in order["payment_history"]:
        if entry["transaction_type"] == "refund":
            lines.append(f"Refunded ${entry['amount']:.2f} to {entry['payment_method_id']}")
    for fulfillment in order.get("fulfillments", []):
        lines.append(f"Tracking: {', '.join(fulfillment['tracking_id'])}")
    return "\n".join(lines)


def format_user(user: dict[str, Any]) -> str:
    methods = ", ".join(user["payment_methods"])
    return (
        f"{user['name']['first_name']} {user['name']['last_name']} ({user['user_id']})\n"
        f"Email: {user['email']}\n"
        f"Address: {format_address(user['address'])}\n"
        f"Payment methods: {methods}\n"
        f"Orders: {', '.join(user['orders'])}"
    )


def format_product(product: dict[str, Any]) -> str:
    lines = [f"{product['name']} (product {product['product_id']})"]
    for item_id, variant in product["variants"].items():
        options = ", ".join(f"{k}: {v}" for k, v in variant["options"].items())
        stock = "in stock" if variant["available"] else "out of stock"
        lines.append(f"  - item {item_id}: ${variant['price']:.2f} [{options}] {stock}")
    return "\n".join(lines)


# --- mutations --------------------------------------------------------------


def refund_total(order: dict[str, Any], item_ids: list[str]) -> float:
    return sum(item["price"] for item in order["items"] if item["item_id"] in item_ids)


def record_refund(order: dict[str, Any], amount: float, payment_method_id: str) -> None:
    order["payment_history"].append(
        {
            "transaction_type": "refund",
            "amount": round(amount, 2),
            "payment_method_id": payment_method_id,
        }
    )
