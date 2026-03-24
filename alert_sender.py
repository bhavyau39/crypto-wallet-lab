"""
alert_sender.py
---------------
Sends formatted alerts to Slack via webhook.
Falls back to console output if no webhook is configured.

Each alert includes an embedded runbook so the person
receiving it at 2am does not need to go find documentation.
"""

import json
import logging

import requests

from config import SLACK_WEBHOOK_URL

logger = logging.getLogger(__name__)

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🔵",
}

RUNBOOKS = {
    "NEW_DESTINATION": (
        "1. Verify YOU authorized this transaction\n"
        "2. Check the destination address — is it expected?\n"
        "3. If unauthorized → treat key as compromised\n"
        "4. Stop all signing · begin key rotation procedure"
    ),
    "HIGH_VELOCITY": (
        "1. Check every transaction in this burst\n"
        "2. If any were NOT authorized → drain attack likely\n"
        "3. Stop all signing from this wallet immediately\n"
        "4. Rotate key using governance.md procedure"
    ),
    "LARGE_TRANSFER": (
        "1. Confirm you authorized this transfer\n"
        "2. Verify destination address is expected\n"
        "3. Document authorization evidence\n"
        "4. If unauthorized → begin incident response"
    ),
    "FAILED_TRANSACTION": (
        "1. Check the transaction details on Etherscan\n"
        "2. Did YOU initiate this transaction?\n"
        "3. Multiple failures in short window = investigate\n"
        "4. Possible unauthorized signing attempt"
    ),
}


def _format_slack_blocks(alert: dict) -> dict:
    """Build a Slack Block Kit message for one alert."""
    emoji   = SEVERITY_EMOJI.get(alert["severity"], "⚪")
    runbook = RUNBOOKS.get(alert["alert_type"], "Investigate and escalate.")

    return {
        "text": f"{emoji} {alert['severity']} — {alert['alert_type']}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {alert['severity']} — {alert['alert_type']}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": alert.get("message", "No message"),
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Wallet:*\n{alert.get('wallet_tier', 'N/A').upper()}"},
                    {"type": "mrkdwn", "text": f"*Amount:*\n{alert.get('amount_eth', 'N/A')} ETH"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Response steps:*\n{runbook}",
                },
            },
        ],
    }


def send_slack_alert(alert: dict) -> None:
    """Send one alert to Slack. Falls back to console if no webhook."""
    if not SLACK_WEBHOOK_URL:
        # Console fallback — useful for demo / no Slack configured
        emoji = SEVERITY_EMOJI.get(alert["severity"], "⚪")
        print(f"\n{emoji} [{alert['severity']}] {alert['alert_type']}")
        print(f"   {alert['message']}")
        return

    payload = _format_slack_blocks(alert)
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code != 200:
            logger.error("Slack returned %d: %s", resp.status_code, resp.text)
        else:
            logger.info("Slack alert sent: %s", alert["alert_type"])
    except requests.RequestException as exc:
        # Never crash the pipeline because Slack is down
        logger.error("Slack send failed: %s", exc)


def send_all_alerts(alerts: list) -> None:
    """
    Send all alerts with simple deduplication.

    Dedup key: (alert_type, wallet_tier) — send at most one
    alert per type per wallet per pipeline run.
    """
    sent: set = set()

    for alert in alerts:
        key = (alert["alert_type"], alert.get("wallet_tier"))
        if key not in sent:
            send_slack_alert(alert)
            sent.add(key)
        else:
            logger.debug("Suppressed duplicate: %s %s", *key)
