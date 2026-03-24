"""
normalize.py
------------
Transforms raw Etherscan API responses into a clean,
consistent pandas DataFrame.

Raw fields needing transformation:
  value      → Wei string  → ETH float  (divide by 10^18)
  timeStamp  → Unix string → datetime
  isError    → "0"/"1"     → bool
  gas/gasPrice              → fee in ETH
  from/to                  → determine direction + counterparty

Key derived field: is_new_address
  True if we have never transacted with this counterparty before.
  Computed by maintaining a running set across all transactions
  sorted chronologically — this is why fetch uses sort=asc.
"""

import logging
from datetime import datetime

import pandas as pd

from config import WALLETS, APPROVED_DESTINATIONS

logger = logging.getLogger(__name__)

# Build set of our own addresses in lowercase once at import time
OWN_ADDRESSES = {addr.lower() for addr in WALLETS.values()}

# Wei → ETH conversion constant
WEI_PER_ETH = 10 ** 18


def normalize_transaction(raw_tx: dict, wallet_tier: str) -> dict:
    """
    Normalize one raw Etherscan transaction dict to a clean schema.

    Raises KeyError if required fields are missing — caller should
    catch and skip, logging the bad record.
    """
    # ── Amount ───────────────────────────────────────────────────
    amount_eth = int(raw_tx["value"]) / WEI_PER_ETH

    # ── Timestamp ────────────────────────────────────────────────
    tx_time = datetime.fromtimestamp(int(raw_tx["timeStamp"]))

    # ── Fee: gas_used × gas_price, converted from Wei to ETH ─────
    gas_used  = int(raw_tx.get("gasUsed", raw_tx.get("gas", 0)))
    gas_price = int(raw_tx.get("gasPrice", 0))
    fee_eth   = (gas_used * gas_price) / WEI_PER_ETH

    # ── Direction ────────────────────────────────────────────────
    # Compare from/to (lowercased) against our known wallet addresses.
    from_addr = raw_tx["from"].lower()
    to_addr   = raw_tx.get("to", "").lower()

    if from_addr in OWN_ADDRESSES:
        direction    = "OUTGOING"
        counterparty = to_addr
    else:
        direction    = "INCOMING"
        counterparty = from_addr

    # ── Success ──────────────────────────────────────────────────
    success = raw_tx.get("isError", "0") == "0"

    return {
        "tx_hash":        raw_tx["hash"],
        "wallet_tier":    wallet_tier,
        "wallet_address": from_addr if direction == "OUTGOING" else to_addr,
        "tx_timestamp":   tx_time,
        "direction":      direction,
        "counterparty":   counterparty,
        "amount_eth":     round(amount_eth, 8),
        "fee_eth":        round(fee_eth, 8),
        "success":        success,
        "block_number":   int(raw_tx["blockNumber"]),
        "gas_price_gwei": round(gas_price / 1e9, 2),
    }


def normalize_all_wallets(all_raw: dict) -> pd.DataFrame:
    """
    Normalize all raw transactions across all wallet tiers into
    a single clean DataFrame, sorted chronologically, with the
    is_new_address flag computed.

    Args:
        all_raw: dict mapping tier → list of raw tx dicts

    Returns:
        pd.DataFrame with all normalized transactions.
        Empty DataFrame if no transactions found.
    """
    records = []

    for tier, raw_txns in all_raw.items():
        for raw_tx in raw_txns:
            try:
                records.append(normalize_transaction(raw_tx, tier))
            except (KeyError, ValueError, ZeroDivisionError) as exc:
                # One bad record never stops the pipeline
                logger.warning(
                    "Skipping malformed tx %s: %s",
                    raw_tx.get("hash", "unknown")[:16],
                    exc,
                )

    if not records:
        logger.info("No transactions to normalize.")
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.sort_values("tx_timestamp").reset_index(drop=True)

    # ── Compute is_new_address ────────────────────────────────────
    # For each transaction in chronological order:
    # - If the counterparty has never appeared before → True
    # - Add to seen set regardless (only alert once per address)
    # Pre-seed with our own wallets + known safe addresses.
    seen: set = OWN_ADDRESSES | APPROVED_DESTINATIONS
    is_new_flags = []

    for cp in df["counterparty"]:
        cp_lower = cp.lower() if cp else ""
        is_new_flags.append(bool(cp_lower and cp_lower not in seen))
        if cp_lower:
            seen.add(cp_lower)

    df["is_new_address"] = is_new_flags

    logger.info(
        "Normalized %d transactions across %d wallets.",
        len(df),
        len(all_raw),
    )
    return df
