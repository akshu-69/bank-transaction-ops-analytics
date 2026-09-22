"""
Synthetic bank transaction operations dataset generator.

Creates a realistic-but-entirely-fake transactions dataset that mimics the
shape of transaction-level operational reporting data used in bank ops teams.
No real customer data — all values are generated from seeded RNGs.

Usage:
    python generate_data.py               # writes full dataset (~50k rows) to data/transactions.csv
    python generate_data.py --rows 50000  # custom row count
"""

import argparse
import hashlib
from datetime import date, timedelta

import numpy as np
import pandas as pd

SEED = 42
FULL_ROWS = 50_000
SAMPLE_ROWS = 2_000

TRANSACTION_TYPES = ["ACH", "Wire", "Check", "Card", "Zelle/P2P", "Bill Pay"]
CHANNELS = ["Online", "Branch", "Mobile", "ATM", "Call Center", "API"]
REGIONS = ["Northeast", "Southeast", "Midwest", "Southwest", "West"]
STATUSES = ["processed", "pending", "failed", "exception"]
EXCEPTION_REASONS = [
    "Insufficient funds",
    "Duplicate submission",
    "Account number mismatch",
    "Hold / compliance review",
    "Stale dated",
    "Amount exceeds limit",
]


def _hash_id(prefix: str, n: int) -> str:
    """Deterministic fake identifier (SHA-256 of the index, truncated)."""
    return f"{prefix}-" + hashlib.sha256(str(n).encode()).hexdigest()[:12].upper()


def generate(n_rows: int = FULL_ROWS, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    # Business-day weighted dates over the last 90 days (more volume on weekdays).
    start = date(2026, 6, 24)
    days = np.array([start + timedelta(days=i) for i in range(90)])
    weekday_weight = np.array([1.0 if d.weekday() < 5 else 0.25 for d in days])
    day_idx = rng.choice(len(days), size=n_rows, p=weekday_weight / weekday_weight.sum())
    dates = days[day_idx]

    # Type drives channel: Cards skew to Mobile/Online, Checks to Branch, Wires to Call Center.
    ttype = rng.choice(TRANSACTION_TYPES, size=n_rows, p=[0.28, 0.07, 0.12, 0.30, 0.13, 0.10])
    channel = np.empty(n_rows, dtype=object)
    channel_by_type = {
        "ACH": (["Online", "API", "Branch", "Mobile"], [0.35, 0.30, 0.15, 0.20]),
        "Wire": (["Call Center", "Branch", "Online"], [0.55, 0.25, 0.20]),
        "Check": (["Branch", "Mobile", "ATM"], [0.55, 0.25, 0.20]),
        "Card": (["Mobile", "Online", "ATM"], [0.45, 0.40, 0.15]),
        "Zelle/P2P": (["Mobile", "Online"], [0.75, 0.25]),
        "Bill Pay": (["Online", "Mobile", "Call Center"], [0.50, 0.35, 0.15]),
    }
    for t, (chs, p) in channel_by_type.items():
        mask = ttype == t
        channel[mask] = rng.choice(chs, size=mask.sum(), p=p)

    # Amounts: lognormal, scaled by transaction type.
    scale = {"ACH": 3_500, "Wire": 25_000, "Check": 4_500, "Card": 120,
             "Zelle/P2P": 450, "Bill Pay": 900}
    amount = np.array([rng.lognormal(np.log(scale[t]), 1.1) for t in ttype]).round(2)

    region = rng.choice(REGIONS, size=n_rows, p=[0.22, 0.24, 0.20, 0.16, 0.18])

    # Exception probability rises for Wires/Checks and during a known "spike week"
    # (days 60-66, mimicking a vendor incident) so the analysis has something to find.
    base_exc = {"ACH": 0.015, "Wire": 0.06, "Check": 0.05,
                "Card": 0.01, "Zelle/P2P": 0.02, "Bill Pay": 0.025}
    exc_p = np.array([base_exc[t] for t in ttype])
    spike_mask = (day_idx >= 60) & (day_idx < 67)
    exc_p[spike_mask] *= 3.0

    roll = rng.random(n_rows)
    status = np.where(roll < exc_p, "exception",
             np.where(roll < exc_p + 0.02, "failed",
             np.where(roll < exc_p + 0.05, "pending", "processed")))

    exception_reason = np.where(
        status == "exception",
        rng.choice(EXCEPTION_REASONS, size=n_rows),
        None,
    )

    # Processing time (minutes): slower for exceptions/wires, right-skewed.
    proc = rng.lognormal(1.2, 0.9, n_rows)
    proc = np.where(ttype == "Wire", proc * 2.5, proc)
    proc = np.where(np.isin(status, ["exception", "failed"]), proc * 3.0, proc)
    processing_time_mins = np.round(proc, 1)

    # ~1% injected duplicates to make duplicate detection meaningful.
    txn_id = np.array([_hash_id("TXN", i) for i in range(n_rows)])
    dup_idx = rng.choice(n_rows, size=int(n_rows * 0.01), replace=False)
    txn_id[dup_idx] = rng.choice(txn_id, size=len(dup_idx))

    # ~0.5% missing region to exercise null handling.
    region = region.astype(object)
    region[rng.random(n_rows) < 0.005] = None

    df = pd.DataFrame({
        "transaction_id": txn_id,
        "date": dates,
        "account_id": [_hash_id("ACCT", i) for i in range(n_rows)],
        "transaction_type": ttype,
        "channel": channel,
        "amount": amount,
        "status": status,
        "exception_reason": exception_reason,
        "region": region,
        "processing_time_mins": processing_time_mins,
    })
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=FULL_ROWS)
    ap.add_argument("--out", default="data/transactions.csv")
    args = ap.parse_args()

    df = generate(n_rows=args.rows)
    df.to_csv(args.out, index=False)
    print(f"Wrote {len(df):,} rows -> {args.out}")

    sample = df.sample(SAMPLE_ROWS, random_state=SEED)
    sample.to_csv("data/sample_transactions.csv", index=False)
    print(f"Wrote {len(sample):,} row sample -> data/sample_transactions.csv")


if __name__ == "__main__":
    main()
