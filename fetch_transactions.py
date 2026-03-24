"""
fetch_transactions.py
---------------------
Calls the Etherscan Sepolia API for each wallet address
and returns the raw JSON transaction list.

Etherscan txlist endpoint returns:
  hash, from, to, value (Wei), timeStamp (Unix),
  isError ("0"/"1"), gas, gasUsed, gasPrice, blockNumber

Rate limit: 5 calls/second on free tier.
We sleep 250ms between wallet fetches to stay safe.
"""

import time
import requests
import logging
from config import ETHERSCAN_BASE_URL, ETHERSCAN_API_KEY, WALLETS

logger = logging.getLogger(__name__)


def fetch_transactions_for_address(address: str, start_block: int = 0) -> list:
    """
    Fetch all transactions for a wallet address from Etherscan.

    Args:
        address:     wallet address to query
        start_block: only fetch transactions from this block onwards.
                     Use 0 for full history. Pass last known block
                     on subsequent runs to avoid re-processing.

    Returns:
        list of raw transaction dicts from Etherscan API.
        Empty list on error or no transactions found.
    """
    params = {
        "module":     "account",
        "action":     "txlist",
        "address":    address,
        "startblock": start_block,
        "endblock":   "latest",
        "sort":       "asc",          # oldest first — important for is_new_address logic
        "apikey":     ETHERSCAN_API_KEY,
    }

    try:
        response = requests.get(ETHERSCAN_BASE_URL, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data["status"] == "1":
            logger.info(
                "Fetched %d transactions for %s...",
                len(data["result"]),
                address[:12],
            )
            return data["result"]

        if data["message"] == "No transactions found":
            logger.info("No transactions for %s...", address[:12])
            return []

        logger.error("Etherscan error: %s", data.get("message", "unknown"))
        return []

    except requests.Timeout:
        logger.error("Timeout fetching %s", address[:12])
        return []
    except requests.RequestException as exc:
        logger.error("Request failed for %s: %s", address[:12], exc)
        return []


def fetch_all_wallets() -> dict:
    """
    Fetch transactions for all three wallet tiers.

    Returns:
        dict mapping tier name ("hot"/"warm"/"cold") to list of raw txns.
    """
    all_raw = {}
    for tier, address in WALLETS.items():
        logger.info("Fetching %s wallet (%s...)...", tier, address[:12])
        all_raw[tier] = fetch_transactions_for_address(address)
        time.sleep(0.25)   # stay within Etherscan 5 req/sec rate limit
    return all_raw
