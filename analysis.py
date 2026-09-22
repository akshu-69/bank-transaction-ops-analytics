"""
Operations analytics on the synthetic bank transactions dataset.

Computes:
  - Exception rate by channel / transaction type / region
  - Processing-time SLA analysis (15-min SLA)
  - Daily volume trends
  - Duplicate transaction detection
  - Null / data-quality checks
  - Source-to-report reconciliation summary

Prints a KPI summary and saves charts to images/.
Usage:
    python analysis.py                 # uses data/transactions.csv (50k rows)
    python analysis.py --data data/sample_transactions.csv
"""

import argparse
import os

import matplotlib
matplotlib.use("Agg")  # headless-safe rendering
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

SLA_MINUTES = 15.0

# Consistent, presentation-friendly palette.
plt.rcParams.update({"figure.dpi": 120, "font.size": 10})
COLORS = {"ok": "#2ca02c", "warn": "#ff7f0e", "bad": "#d62728", "info": "#1f77b4"}


def load(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    return df


def exception_rates(df: pd.DataFrame):
    """Exception rate (%) sliced by channel, transaction type, and region."""
    out = {}
    for col in ["channel", "transaction_type", "region"]:
        g = df.groupby(col)["status"]
        out[col] = (g.apply(lambda s: (s == "exception").mean() * 100)
                     .sort_values(ascending=False).round(2))
    return out


def sla_analysis(df: pd.DataFrame):
    """Share of transactions breaching the processing-time SLA."""
    df = df.copy()
    df["sla_breach"] = df["processing_time_mins"] > SLA_MINUTES
    by_type = (df.groupby("transaction_type")["sla_breach"]
                 .mean().mul(100).sort_values(ascending=False).round(2))
    by_status = (df.groupby("status")["sla_breach"]
                   .mean().mul(100).sort_values(ascending=False).round(2))
    overall = round(df["sla_breach"].mean() * 100, 2)
    return overall, by_type, by_status


def daily_trends(df: pd.DataFrame):
    """Daily volume and exception rate over time."""
    daily = (df.assign(is_exception=(df["status"] == "exception").astype(int))
               .groupby("date").agg(volume=("transaction_id", "size"),
                                    exceptions=("is_exception", "sum")))
    daily["exception_rate"] = (daily["exceptions"] / daily["volume"] * 100).round(2)
    return daily


def duplicate_check(df: pd.DataFrame):
    """Flag repeated transaction_ids (possible double-submissions)."""
    dup_ids = df["transaction_id"].duplicated(keep=False)
    dup_rows = df[dup_ids].sort_values("transaction_id")
    n_dup_ids = dup_rows["transaction_id"].nunique()
    return dup_rows, n_dup_ids


def data_quality(df: pd.DataFrame):
    """Null counts and negative/zero amount checks per column."""
    nulls = df.isna().sum().loc[lambda s: s > 0]
    bad_amounts = int((df["amount"] <= 0).sum())
    return nulls, bad_amounts


def reconciliation(df: pd.DataFrame):
    """Source-to-report reconciliation: row counts and amount totals tie out."""
    src = {"rows": len(df), "amount": round(df["amount"].sum(), 2)}
    # Re-aggregate from a grouped "report" view, as a downstream report would.
    report = df.groupby(["date", "channel"], as_index=False)["amount"].sum()
    rpt = {"rows": len(df), "amount": round(report["amount"].sum(), 2)}
    return src, rpt, src["rows"] == rpt["rows"] and src["amount"] == rpt["amount"]


def save_charts(df: pd.DataFrame, exc: dict, daily: pd.DataFrame,
                sla_overall: float, sla_by_type: pd.Series) -> None:
    os.makedirs("images", exist_ok=True)

    # 1. Exception rate by channel.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    exc["channel"].plot(kind="bar", ax=ax, color=COLORS["bad"])
    ax.set_title("Exception Rate by Channel (%)")
    ax.set_ylabel("Exception rate (%)"); ax.set_xlabel("")
    fig.tight_layout(); fig.savefig("images/exception_rate_by_channel.png"); plt.close(fig)

    # 2. Exception rate by transaction type.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    exc["transaction_type"].plot(kind="bar", ax=ax, color=COLORS["warn"])
    ax.set_title("Exception Rate by Transaction Type (%)")
    ax.set_ylabel("Exception rate (%)"); ax.set_xlabel("")
    fig.tight_layout(); fig.savefig("images/exception_rate_by_type.png"); plt.close(fig)

    # 3. Daily volume vs exception rate (dual axis).
    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.bar(daily.index, daily["volume"], color=COLORS["info"], alpha=0.7, label="Volume")
    ax1.set_ylabel("Daily volume")
    ax2 = ax1.twinx()
    ax2.plot(daily.index, daily["exception_rate"], color=COLORS["bad"], lw=2, label="Exception rate")
    ax2.set_ylabel("Exception rate (%)")
    ax1.set_title("Daily Volume and Exception Rate (note the spike week)")
    fig.tight_layout(); fig.savefig("images/daily_volume_exceptions.png"); plt.close(fig)

    # 4. Processing time distribution by status.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for st, c in [("processed", COLORS["ok"]), ("exception", COLORS["bad"]), ("failed", COLORS["warn"])]:
        vals = df.loc[df["status"] == st, "processing_time_mins"]
        vals = vals[vals < vals.quantile(0.99)]  # trim long tail for readability
        ax.hist(vals, bins=60, alpha=0.55, label=st, color=c)
    ax.axvline(SLA_MINUTES, color="black", ls="--", label=f"SLA ({SLA_MINUTES:.0f} min)")
    ax.set_title("Processing Time Distribution by Status")
    ax.set_xlabel("Minutes"); ax.set_ylabel("Transactions"); ax.legend()
    fig.tight_layout(); fig.savefig("images/processing_time_by_status.png"); plt.close(fig)

    # 5. SLA breach rate by transaction type.
    fig, ax = plt.subplots(figsize=(8, 4.5))
    sla_by_type.plot(kind="barh", ax=ax, color=COLORS["info"])
    ax.set_title(f"SLA Breach Rate by Transaction Type (SLA = {SLA_MINUTES:.0f} min)")
    ax.set_xlabel("Breach rate (%)")
    fig.tight_layout(); fig.savefig("images/sla_breach_by_type.png"); plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/transactions.csv")
    args = ap.parse_args()

    df = load(args.data)
    print(f"Loaded {len(df):,} rows from {args.data}\n")

    # --- KPI summary ---
    exc_rate = (df["status"] == "exception").mean() * 100
    exc = exception_rates(df)
    sla_overall, sla_by_type, sla_by_status = sla_analysis(df)
    daily = daily_trends(df)
    dup_rows, n_dup_ids = duplicate_check(df)
    nulls, bad_amounts = data_quality(df)
    src, rpt, reconciled = reconciliation(df)

    print("=" * 60)
    print("KPI SUMMARY — Bank Transaction Operations")
    print("=" * 60)
    print(f"Total transactions          : {len(df):,}")
    print(f"Total amount processed      : ${df['amount'].sum():,.2f}")
    print(f"Overall exception rate      : {exc_rate:.2f}%")
    print(f"Overall SLA breach rate     : {sla_overall:.2f}% (>{SLA_MINUTES:.0f} min)")
    print(f"Peak exception day          : {daily['exception_rate'].idxmax().date()} "
          f"({daily['exception_rate'].max():.2f}%)")
    print(f"Duplicate transaction IDs   : {n_dup_ids} IDs / {len(dup_rows):,} rows")
    print(f"Negative/zero amounts       : {bad_amounts}")
    print(f"Reconciliation tie-out      : {'PASS' if reconciled else 'FAIL'} "
          f"(source ${src['amount']:,.2f} vs report ${rpt['amount']:,.2f})")
    if len(nulls):
        print("Null values found:")
        for col, n in nulls.items():
            print(f"  - {col}: {n} ({n / len(df) * 100:.2f}%)")
    print()
    print("Exception rate by channel:")
    print(exc["channel"].to_string())
    print("\nException rate by transaction type:")
    print(exc["transaction_type"].to_string())
    print("\nTop exception reasons:")
    print(df.loc[df["status"] == "exception", "exception_reason"]
          .value_counts().head().to_string())
    print("=" * 60)

    save_charts(df, exc, daily, sla_overall, sla_by_type)
    print("\nCharts saved to images/")

    # Save the headline numbers for the README.
    summary = {
        "rows": len(df),
        "exception_rate": round(exc_rate, 2),
        "sla_breach_rate": sla_overall,
        "dup_ids": n_dup_ids,
        "reconciled": reconciled,
        "top_channel": exc["channel"].idxmax(),
        "top_type": exc["transaction_type"].idxmax(),
        "peak_day": str(daily["exception_rate"].idxmax().date()),
        "peak_rate": round(float(daily["exception_rate"].max()), 2),
    }
    pd.Series(summary).to_csv("images/kpi_summary.csv")
    print("KPI summary saved to images/kpi_summary.csv")


if __name__ == "__main__":
    main()
