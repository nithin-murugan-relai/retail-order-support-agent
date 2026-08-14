"""Carve a small, self-contained demo database out of the public tau2-bench retail domain.

Source: https://github.com/sierra-research/tau2-bench (MIT, Copyright (c) 2025 Sierra Research)
        data/tau2/domains/retail/db.json  -- 500 users / 1000 orders / 50 products

The full database is far too large to read, and shipping it would make this repo
feel like a benchmark harness rather than a worked example. We keep a coherent
slice: a set of users whose orders cover every status the agent has to reason
about (pending, processed, delivered, cancelled), plus every product those
orders reference.

Run this only to regenerate data/retail_db.json. Nothing at runtime needs it.

    python scripts/build_demo_db.py --tau2 ../benchmarking/tau2-bench
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# Fixed so the demo database is stable across regenerations. Chosen for status
# coverage, not cherry-picked for agent difficulty.
TARGET_STATUSES = ("pending", "processed", "delivered", "cancelled")
USERS_PER_STATUS = 3


def pick_users(users: dict, orders: dict) -> list[str]:
    """Pick users so that every order status is represented, deterministically.

    Candidates are sampled at an even stride rather than taken from the front of
    the sorted list, otherwise every demo customer's name starts with an "A".
    """
    picked: list[str] = []
    for status in TARGET_STATUSES:
        matches = sorted(
            uid
            for uid, user in users.items()
            if any(orders[oid]["status"] == status for oid in user["orders"] if oid in orders)
        )
        stride = max(1, len(matches) // USERS_PER_STATUS)
        for uid in matches[::stride]:
            if uid in picked:
                continue
            picked.append(uid)
            if sum(1 for p in picked if p in matches) >= USERS_PER_STATUS:
                break
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tau2",
        type=Path,
        required=True,
        help="Path to a tau2-bench checkout",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data" / "retail_db.json",
    )
    args = parser.parse_args()

    source = args.tau2 / "data" / "tau2" / "domains" / "retail" / "db.json"
    db = json.loads(source.read_text())
    users, orders, products = db["users"], db["orders"], db["products"]

    user_ids = pick_users(users, orders)
    kept_users = {uid: users[uid] for uid in user_ids}

    order_ids = [oid for uid in user_ids for oid in users[uid]["orders"] if oid in orders]
    kept_orders = {oid: orders[oid] for oid in sorted(order_ids)}

    # Every product any kept order references, so the catalog is never a dead end.
    product_ids = sorted({item["product_id"] for o in kept_orders.values() for item in o["items"]})
    kept_products = {pid: products[pid] for pid in product_ids if pid in products}

    out = {
        "_source": "tau2-bench retail domain (MIT, Sierra Research) -- demo subset",
        "products": kept_products,
        "users": kept_users,
        "orders": kept_orders,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n")

    statuses = sorted({o["status"] for o in kept_orders.values()})
    print(
        f"wrote {args.out}: {len(kept_users)} users, {len(kept_orders)} orders "
        f"({', '.join(statuses)}), {len(kept_products)} products"
    )


if __name__ == "__main__":
    main()
