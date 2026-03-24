"""
demo.py
-------
Runs the full monitoring pipeline with realistic synthetic
transaction data — no Etherscan API key required.

The demo data is designed to trigger all four detection rules
so you can see the complete system working end to end.

Scenario:
  - Hot wallet: normal operations + one suspicious drain sequence
  - Warm wallet: one large transfer + a transfer to a new address
  - Cold wallet: one failed transaction + unexpected small movement

Run with:
    python demo.py
"""

import logging
import sys
from datetime import datetime, timedelta

import pandas as pd

from detect_alerts import run_all_detection
from alert_sender import send_all_alerts
from config import OUTPUT_CSV, WALLETS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── Wallet addresses (shortened for display) ────────────────────
HOT  = WALLETS["hot"].lower()
WARM = WALLETS["warm"].lower()
COLD = WALLETS["cold"].lower()

# ── Known safe counterparties ───────────────────────────────────
BITSTAMP    = "0xbitstamp000000000000000000000000000001"
COINBASE    = "0xcoinbase000000000000000000000000000001"
INTERNAL_OP = "0xinternal000000000000000000000000000001"

# ── Reference time ──────────────────────────────────────────────
NOW = datetime(2026, 3, 30, 14, 0, 0)


def build_demo_data() -> pd.DataFrame:
    """
    Build a realistic synthetic transaction dataset that exercises
    all four detection rules.

    Returns a normalized DataFrame (same schema as normalize.py output).
    """
    rows = []

    # ────────────────────────────────────────────────────────────
    # HOT WALLET — normal operations over 3 days
    # ────────────────────────────────────────────────────────────

    # Normal incoming funding
    rows.append({
        "tx_hash":        "0xhot_in_001",
        "wallet_tier":    "hot",
        "wallet_address": HOT,
        "tx_timestamp":   NOW - timedelta(days=3),
        "direction":      "INCOMING",
        "counterparty":   COINBASE,
        "amount_eth":     2.0,
        "fee_eth":        0.0008,
        "success":        True,
        "block_number":   5000001,
        "gas_price_gwei": 12.0,
        "is_new_address": True,   # first time seeing Coinbase
    })

    # Normal outgoing to known exchange
    rows.append({
        "tx_hash":        "0xhot_out_001",
        "wallet_tier":    "hot",
        "wallet_address": HOT,
        "tx_timestamp":   NOW - timedelta(days=2, hours=6),
        "direction":      "OUTGOING",
        "counterparty":   BITSTAMP,
        "amount_eth":     0.3,
        "fee_eth":        0.0005,
        "success":        True,
        "block_number":   5001200,
        "gas_price_gwei": 10.0,
        "is_new_address": True,   # first time sending to Bitstamp
    })

    # Normal outgoing again — Bitstamp now known
    rows.append({
        "tx_hash":        "0xhot_out_002",
        "wallet_tier":    "hot",
        "wallet_address": HOT,
        "tx_timestamp":   NOW - timedelta(days=1, hours=4),
        "direction":      "OUTGOING",
        "counterparty":   BITSTAMP,
        "amount_eth":     0.25,
        "fee_eth":        0.0005,
        "success":        True,
        "block_number":   5002400,
        "gas_price_gwei": 10.0,
        "is_new_address": False,  # Bitstamp seen before
    })

    # ── TRIGGER: HIGH_VELOCITY + NEW_DESTINATION ─────────────────
    # Three rapid transactions in 8 minutes to a NEW address
    # Simulates: attacker draining via automated script
    attacker = "0xattacker_addr_000000000000000000000001"
    for i in range(3):
        rows.append({
            "tx_hash":        f"0xhot_drain_{i:03d}",
            "wallet_tier":    "hot",
            "wallet_address": HOT,
            "tx_timestamp":   NOW - timedelta(minutes=30) + timedelta(minutes=i * 3),
            "direction":      "OUTGOING",
            "counterparty":   attacker,
            "amount_eth":     0.45,   # just under large_transfer threshold
            "fee_eth":        0.001,
            "success":        True,
            "block_number":   5010000 + i,
            "gas_price_gwei": 25.0,
            "is_new_address": i == 0,  # new on first, seen after
        })

    # ────────────────────────────────────────────────────────────
    # WARM WALLET — one large transfer + new destination
    # ────────────────────────────────────────────────────────────

    # Incoming funding
    rows.append({
        "tx_hash":        "0xwarm_in_001",
        "wallet_tier":    "warm",
        "wallet_address": WARM,
        "tx_timestamp":   NOW - timedelta(days=5),
        "direction":      "INCOMING",
        "counterparty":   HOT,
        "amount_eth":     1.0,
        "fee_eth":        0.0004,
        "success":        True,
        "block_number":   4990000,
        "gas_price_gwei": 9.0,
        "is_new_address": False,  # hot wallet is our own — pre-approved
    })

    # ── TRIGGER: LARGE_TRANSFER (warm threshold: 0.2 ETH) ────────
    rows.append({
        "tx_hash":        "0xwarm_large_001",
        "wallet_tier":    "warm",
        "wallet_address": WARM,
        "tx_timestamp":   NOW - timedelta(hours=2),
        "direction":      "OUTGOING",
        "counterparty":   INTERNAL_OP,
        "amount_eth":     0.65,   # above 0.2 ETH warm threshold
        "fee_eth":        0.0006,
        "success":        True,
        "block_number":   5008000,
        "gas_price_gwei": 15.0,
        "is_new_address": True,   # ← also triggers NEW_DESTINATION
    })

    # ────────────────────────────────────────────────────────────
    # COLD WALLET — failed tx + unexpected movement
    # ────────────────────────────────────────────────────────────

    # ── TRIGGER: FAILED_TRANSACTION ──────────────────────────────
    rows.append({
        "tx_hash":        "0xcold_fail_001",
        "wallet_tier":    "cold",
        "wallet_address": COLD,
        "tx_timestamp":   NOW - timedelta(hours=1, minutes=15),
        "direction":      "OUTGOING",
        "counterparty":   "0xunknown_cold_dest_000000000000000001",
        "amount_eth":     0.0,
        "fee_eth":        0.002,  # gas burned on failed tx
        "success":        False,  # ← isError = 1
        "block_number":   5009500,
        "gas_price_gwei": 30.0,
        "is_new_address": True,
    })

    # ── TRIGGER: NEW_DESTINATION on cold vault ───────────────────
    rows.append({
        "tx_hash":        "0xcold_new_001",
        "wallet_tier":    "cold",
        "wallet_address": COLD,
        "tx_timestamp":   NOW - timedelta(minutes=45),
        "direction":      "OUTGOING",
        "counterparty":   "0xsuspicious_cold_000000000000000000001",
        "amount_eth":     0.08,   # above 0.05 cold threshold → LARGE_TRANSFER too
        "fee_eth":        0.0008,
        "success":        True,
        "block_number":   5009800,
        "gas_price_gwei": 20.0,
        "is_new_address": True,
    })

    df = pd.DataFrame(rows)
    df = df.sort_values("tx_timestamp").reset_index(drop=True)
    return df


def print_summary(df: pd.DataFrame, alerts: list) -> None:
    """Print a clean summary to the console."""
    print("\n" + "═" * 60)
    print("  WALLET MONITORING LAB — DEMO RESULTS")
    print("═" * 60)

    print(f"\n  Transactions processed: {len(df)}")
    print(f"  Wallets monitored:      {df['wallet_tier'].nunique()}")
    print(f"  Alerts generated:       {len(alerts)}")

    print("\n  TRANSACTION BREAKDOWN:")
    summary = (
        df.groupby(["wallet_tier", "direction"])["amount_eth"]
        .agg(count="count", total="sum")
        .reset_index()
    )
    for _, row in summary.iterrows():
        print(
            f"    {row['wallet_tier'].upper():6s} {row['direction']:10s}  "
            f"{int(row['count']):3d} txns  {row['total']:.4f} ETH"
        )

    print("\n  ALERTS FIRED:")
    print(f"  {'Severity':<12} {'Type':<25} {'Wallet':<8} Message")
    print("  " + "-" * 70)

    severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡"}
    for a in alerts:
        emoji = severity_emoji.get(a["severity"], "⚪")
        tier  = a.get("wallet_tier", "N/A").upper()
        sev   = a["severity"]
        atype = a["alert_type"]
        msg   = a["message"][:55] + "..." if len(a["message"]) > 55 else a["message"]
        print(f"  {emoji} {sev:<10} {atype:<25} {tier:<8} {msg}")

    print("\n  DETECTION RULES TRIGGERED:")
    fired = {a["alert_type"] for a in alerts}
    all_rules = ["NEW_DESTINATION", "LARGE_TRANSFER", "HIGH_VELOCITY", "FAILED_TRANSACTION"]
    for rule in all_rules:
        status = "✅ FIRED" if rule in fired else "  clear"
        print(f"    {status}  {rule}")

    print(f"\n  CSV exported to: {OUTPUT_CSV}")
    print("  Open in Power BI or Excel to see the dashboard.\n")
    print("═" * 60 + "\n")


def run_demo():
    print("\n  Running crypto wallet monitoring lab with demo data...")
    print("  (No API key required — using synthetic transactions)\n")

    logger.info("Building demo transaction data...")
    df = build_demo_data()
    logger.info("Demo data: %d transactions across %d wallets", len(df), df["wallet_tier"].nunique())

    logger.info("Running detection rules...")
    alerts = run_all_detection(df)

    logger.info("Sending alerts (console output — no Slack configured)...")
    send_all_alerts(alerts)

    logger.info("Exporting CSV to %s...", OUTPUT_CSV)
    df.to_csv(OUTPUT_CSV, index=False)

    print_summary(df, alerts)
    return df, alerts


if __name__ == "__main__":
    df, alerts = run_demo()
    sys.exit(0)
