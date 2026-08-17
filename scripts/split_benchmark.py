"""Split the benchmark into a train half and a held-out half.

The optimizer only ever sees the train split. The holdout exists to answer the
question anyone will ask about an optimization result: did the agent learn the
rule, or did it learn these particular samples?

The split is by RULE, not random. Every behaviour the agent has to learn appears
on both sides, using different orders and different customers, so an improvement
that only shows up on train is visibly memorisation.

    python scripts/split_benchmark.py
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "benchmarks" / "retail_order_benchmark.csv"

# Held out. Each of these has at least one sibling in train that exercises the
# same rule against a different order, so the rule is learnable from train alone.
HOLDOUT = {
    # a shipped order cannot be cancelled  (train: cancel-processed-order)
    "cancel-processed-order-2",
    # a shipped order's problem goes to the fulfillment team  (train: damaged-item-handoff)
    "shipped-order-problem",
    # refund timing  (train: card-refund-timing)
    "return-payment-method-not-owned",
    # exchanges must resolve the product from the order  (train: exchange-with-variant-lookup)
    "exchange-same-product-2",
    "exchange-same-product-3",
    # only delivered orders can be returned  (train: return-pending-order)
    "return-processed-order",
    "return-cancelled-order",
    # identify before acting  (train: identify-before-acting)
    "shopper-supplied-customer-id",
    # a cancelled order is final  (train: cancel-already-cancelled)
    "cancel-cancelled-order",
    # address changes only on pending  (train: address-change-delivered)
    "address-change-cancelled",
    # escalate what the tools do not cover  (train: price-match-request)
    "wrong-item-received",
    # happy paths, to catch regressions rather than measure learning
    "cancel-pending-3",
    "cancel-pending-4",
    "return-delivered-3",
    "address-change-pending-2",
    "identify-by-email-2",
    "order-status-question-2",
}


def main() -> None:
    rows = list(csv.DictReader(BENCHMARK.open()))
    fields = ["sample_id", "input", "expected_behavior", "rubric"]

    unknown = HOLDOUT - {r["sample_id"] for r in rows}
    if unknown:
        raise SystemExit(f"holdout names not in the benchmark: {sorted(unknown)}")

    train = [r for r in rows if r["sample_id"] not in HOLDOUT]
    holdout = [r for r in rows if r["sample_id"] in HOLDOUT]

    for name, subset in (("train", train), ("holdout", holdout)):
        path = BENCHMARK.parent / f"retail_order_{name}.csv"
        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(subset)
        print(f"{path.name}: {len(subset)} samples")


if __name__ == "__main__":
    main()
