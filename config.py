"""
config.py
---------
Central configuration for the wallet monitoring lab.
All thresholds and wallet addresses in one place.

In production: thresholds would live in a control plane
database so changes require no code deployment.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Wallet addresses ────────────────────────────────────────────
WALLETS = {
    "hot":  os.getenv("HOT_WALLET_ADDRESS",  "0x0000000000000000000000000000000000000001"),
    "warm": os.getenv("WARM_WALLET_ADDRESS", "0x0000000000000000000000000000000000000002"),
    "cold": os.getenv("COLD_WALLET_ADDRESS", "0x0000000000000000000000000000000000000003"),
}

# ── API credentials ─────────────────────────────────────────────
ETHERSCAN_API_KEY  = os.getenv("ETHERSCAN_API_KEY", "")
ETHERSCAN_BASE_URL = "https://api-sepolia.etherscan.io/api"

SLACK_WEBHOOK_URL  = os.getenv("SLACK_WEBHOOK_URL", "")

# ── Alert thresholds — per wallet tier ──────────────────────────
# Why per-tier: hot wallet legitimately moves large amounts.
# Cold wallet almost never should. One global threshold either
# drowns hot wallet in false positives or misses cold anomalies.
THRESHOLDS = {
    "hot": {
        "large_transfer_eth":      0.5,   # alert if single tx > 0.5 ETH
        "velocity_window_minutes": 10,    # sliding window duration
        "velocity_tx_count":       3,     # max outgoing txns in window
        "rotation_sla_days":       90,    # key rotation requirement
    },
    "warm": {
        "large_transfer_eth":      0.2,
        "velocity_window_minutes": 10,
        "velocity_tx_count":       2,
        "rotation_sla_days":       180,
    },
    "cold": {
        "large_transfer_eth":      0.05,  # anything significant on cold
        "velocity_window_minutes": 60,
        "velocity_tx_count":       2,
        "rotation_sla_days":       365,
    },
}

# ── Known safe addresses ─────────────────────────────────────────
# These never trigger new destination alerts.
# Pre-populated with our own wallets and known counterparties.
APPROVED_DESTINATIONS = {
    addr.lower() for addr in WALLETS.values()
} | {
    "0xfaucet0000000000000000000000000000000001",  # testnet faucet
}

# ── Output ───────────────────────────────────────────────────────
OUTPUT_CSV = "wallet_transactions.csv"
