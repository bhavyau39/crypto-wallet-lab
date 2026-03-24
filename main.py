"""
main.py
-------
Orchestrates the full pipeline:
  1. Fetch raw transactions from Etherscan API
  2. Normalize to clean DataFrame
  3. Run detection rules → generate alerts
  4. Send alerts to Slack (or console)
  5. Export to CSV for Power BI dashboard

Run manually or on a schedule (cron / Lambda).
For demo data without an API key: run demo.py instead.
"""

import logging
import sys

from fetch_transactions import fetch_all_wallets
from normalize import normalize_all_wallets
from detect_alerts import run_all_detection
from alert_sender import send_all_alerts
from config import OUTPUT_CSV

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline():
    logger.info("═══ Pipeline run starting ═══")

    # 1 — Fetch
    logger.info("Step 1/5: Fetching transactions...")
    raw = fetch_all_wallets()
    total = sum(len(v) for v in raw.values())
    logger.info("Fetched %d total transactions across all wallets.", total)

    if total == 0:
        logger.info("No transactions found. Exiting.")
        return None, []

    # 2 — Normalize
    logger.info("Step 2/5: Normalizing...")
    df = normalize_all_wallets(raw)

    # 3 — Detect
    logger.info("Step 3/5: Running detection rules...")
    alerts = run_all_detection(df)

    # 4 — Alert
    logger.info("Step 4/5: Sending alerts...")
    if alerts:
        send_all_alerts(alerts)
    else:
        logger.info("No alerts — all clear.")

    # 5 — Export
    logger.info("Step 5/5: Exporting to %s...", OUTPUT_CSV)
    df.to_csv(OUTPUT_CSV, index=False)
    logger.info("Export complete.")

    logger.info("═══ Pipeline complete. %d alerts. ═══", len(alerts))
    return df, alerts


if __name__ == "__main__":
    df, alerts = run_pipeline()
    sys.exit(0)
