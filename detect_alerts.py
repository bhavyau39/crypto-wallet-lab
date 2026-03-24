"""
detect_alerts.py
----------------
Four detection rules that run against the normalized DataFrame.
Each rule returns a list of alert dicts.

Rules:
  1. NEW_DESTINATION   — outgoing tx to never-seen-before address
  2. LARGE_TRANSFER    — single outgoing tx above tier threshold
  3. HIGH_VELOCITY     — burst of outgoing txns in sliding window
  4. FAILED_TRANSACTION — any tx with isError=1

Design decisions:
  - Per-tier thresholds (not global) to reduce false positives
  - Sliding window (not fixed bucket) to catch boundary-spanning bursts
  - Whitelist checked before new-address check
  - Dedup: HIGH_VELOCITY fires once per burst, not per transaction
"""

import logging
from datetime import timedelta

import pandas as pd

from config import THRESHOLDS, APPROVED_DESTINATIONS

logger = logging.getLogger(__name__)


# ── Rule 1: New destination address ─────────────────────────────
def detect_new_destination(df: pd.DataFrame, wallet_tier: str) -> list:
    """
    Alert when an outgoing successful transaction goes to an
    address we have never transacted with before.

    Why this is the highest-signal rule:
    When a private key is compromised, the attacker's first action
    is sending funds to their own address. By definition that
    address is new — not in our transaction history.

    The is_new_address flag was already computed in normalize.py.
    We respect the whitelist (APPROVED_DESTINATIONS) which was
    also pre-seeded during normalization.
    """
    alerts = []

    outgoing_new = df[
        (df["wallet_tier"]    == wallet_tier)
        & (df["direction"]    == "OUTGOING")
        & (df["success"]      == True)
        & (df["is_new_address"] == True)
    ]

    for _, tx in outgoing_new.iterrows():
        cp = tx["counterparty"]
        # Double-check whitelist (belt and suspenders)
        if cp.lower() in APPROVED_DESTINATIONS:
            continue

        alerts.append({
            "alert_type":  "NEW_DESTINATION",
            "severity":    "HIGH",
            "wallet_tier": wallet_tier,
            "tx_hash":     tx["tx_hash"],
            "amount_eth":  tx["amount_eth"],
            "counterparty":cp,
            "timestamp":   tx["tx_timestamp"],
            "message": (
                f"[{wallet_tier.upper()}] Outgoing {tx['amount_eth']:.4f} ETH "
                f"to address never seen before: {cp[:18]}..."
            ),
        })

    return alerts


# ── Rule 2: Large transfer ───────────────────────────────────────
def detect_large_transfer(df: pd.DataFrame, wallet_tier: str) -> list:
    """
    Alert when a single outgoing transaction exceeds the
    tier-specific threshold.

    Why per-tier thresholds matter:
    Hot wallet regularly moves 0.5+ ETH for operational reasons.
    Cold wallet should almost never move anything significant.
    A global threshold creates noise on hot or misses cold anomalies.
    """
    alerts  = []
    thresh  = THRESHOLDS[wallet_tier]["large_transfer_eth"]

    large = df[
        (df["wallet_tier"] == wallet_tier)
        & (df["direction"] == "OUTGOING")
        & (df["success"]   == True)
        & (df["amount_eth"] > thresh)
    ]

    for _, tx in large.iterrows():
        alerts.append({
            "alert_type":  "LARGE_TRANSFER",
            "severity":    "HIGH",
            "wallet_tier": wallet_tier,
            "tx_hash":     tx["tx_hash"],
            "amount_eth":  tx["amount_eth"],
            "threshold":   thresh,
            "counterparty":tx["counterparty"],
            "timestamp":   tx["tx_timestamp"],
            "message": (
                f"[{wallet_tier.upper()}] Large transfer: "
                f"{tx['amount_eth']:.4f} ETH "
                f"(threshold: {thresh} ETH)"
            ),
        })

    return alerts


# ── Rule 3: High velocity (sliding window) ───────────────────────
def detect_high_velocity(df: pd.DataFrame, wallet_tier: str) -> list:
    """
    Alert when too many outgoing transactions occur within a
    short sliding window.

    Why sliding window over fixed time bucket:
    Fixed hourly buckets miss bursts spanning clock boundaries.
    Three transactions at :55, :58, :02 look like 2+1 in fixed
    hourly buckets but are correctly caught as one 3-transaction
    burst by a sliding window.

    This is the drain attack signature:
    An automated script sends many small transactions rapidly,
    staying below the large_transfer threshold per transaction
    while exfiltrating significant value in aggregate.

    Time complexity: O(n²) worst case.
    Acceptable at custody operation volumes (hundreds/day).
    For high-frequency environments: use deque-based O(n) approach.
    """
    alerts  = []
    config  = THRESHOLDS[wallet_tier]
    window  = timedelta(minutes=config["velocity_window_minutes"])
    thresh  = config["velocity_tx_count"]

    outgoing = df[
        (df["wallet_tier"] == wallet_tier)
        & (df["direction"] == "OUTGOING")
        & (df["success"]   == True)
    ].sort_values("tx_timestamp").reset_index(drop=True)

    if len(outgoing) < thresh:
        return alerts

    for i in range(len(outgoing)):
        window_txns = []

        for j in range(i, len(outgoing)):
            time_diff = (
                outgoing.loc[j, "tx_timestamp"] -
                outgoing.loc[i, "tx_timestamp"]
            )
            if time_diff <= window:
                window_txns.append(outgoing.loc[j])
            else:
                break   # sorted, so no point looking further

        if len(window_txns) >= thresh:
            total_eth = sum(t["amount_eth"] for t in window_txns)
            alerts.append({
                "alert_type":  "HIGH_VELOCITY",
                "severity":    "CRITICAL",
                "wallet_tier": wallet_tier,
                "tx_count":    len(window_txns),
                "total_eth":   round(total_eth, 4),
                "window_min":  config["velocity_window_minutes"],
                "timestamp":   outgoing.loc[i, "tx_timestamp"],
                "message": (
                    f"[{wallet_tier.upper()}] HIGH VELOCITY: "
                    f"{len(window_txns)} outgoing transactions "
                    f"({total_eth:.4f} ETH total) "
                    f"in {config['velocity_window_minutes']} minutes"
                ),
            })
            break   # Alert once per burst, not per transaction

    return alerts


# ── Rule 4: Failed transactions ──────────────────────────────────
def detect_failed_transactions(df: pd.DataFrame, wallet_tier: str) -> list:
    """
    Alert on failed transactions (isError = 1).

    A single failure: probably a gas issue or wrong nonce.
    Multiple failures in a short window: possible unauthorized
    party attempting to sign without proper credentials or balance.

    Severity MEDIUM because single failures are common operational
    events. The pattern across failures is the signal.
    """
    alerts = []

    failed = df[
        (df["wallet_tier"] == wallet_tier)
        & (df["success"]   == False)
    ]

    for _, tx in failed.iterrows():
        alerts.append({
            "alert_type":  "FAILED_TRANSACTION",
            "severity":    "MEDIUM",
            "wallet_tier": wallet_tier,
            "tx_hash":     tx["tx_hash"],
            "counterparty":tx["counterparty"],
            "timestamp":   tx["tx_timestamp"],
            "message": (
                f"[{wallet_tier.upper()}] Failed transaction: "
                f"{tx['tx_hash'][:18]}..."
            ),
        })

    return alerts


# ── Run all rules ────────────────────────────────────────────────
def run_all_detection(df: pd.DataFrame) -> list:
    """
    Run all four rules across all three wallet tiers.
    Returns combined alert list sorted by severity then timestamp.
    """
    if df.empty:
        logger.info("No data to run detection on.")
        return []

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    all_alerts = []

    for tier in ["hot", "warm", "cold"]:
        all_alerts.extend(detect_new_destination(df, tier))
        all_alerts.extend(detect_large_transfer(df, tier))
        all_alerts.extend(detect_high_velocity(df, tier))
        all_alerts.extend(detect_failed_transactions(df, tier))

    all_alerts.sort(
        key=lambda a: (
            severity_order.get(a.get("severity", "LOW"), 99),
            a.get("timestamp", ""),
        )
    )

    logger.info("Detection complete. %d alerts generated.", len(all_alerts))
    return all_alerts
