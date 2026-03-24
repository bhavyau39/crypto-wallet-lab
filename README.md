# Crypto Wallet Monitoring Lab

A self-directed security project to build operational intuition around digital asset key management and continuous wallet monitoring — the same problems institutional custody teams solve at scale.

## What This Is

Three-tier wallet architecture (hot / warm / cold) on Ethereum Sepolia testnet with:
- Key governance documentation (signing thresholds, backup procedures, rotation triggers)
- Python pipeline pulling transaction data from the Etherscan API
- Four detection rules identifying high-risk patterns
- Slack alerting with embedded response runbooks
- CSV export feeding a Power BI dashboard

## Why I Built It

Reading exchange hack post-mortems, the failure pattern is never a broken cryptographic algorithm — it is operational failures. Keys in plaintext config files. Backups never tested. No rotation policy. No monitoring. I built this to make key management operational rather than theoretical.

## Architecture

```
Ethereum Sepolia Testnet
        ↓
Etherscan API (fetch_transactions.py)
        ↓
normalize.py  →  Wei→ETH, Unix→datetime, direction, fee, is_new_address
        ↓
detect_alerts.py  →  4 detection rules, per-tier thresholds
        ↓                      ↓
alert_sender.py         CSV export
(Slack webhook)         (Power BI source)
```

## Wallet Tiers

| Tier | Rotation | Threshold | Signing |
|------|----------|-----------|---------|
| Hot  | 90 days  | 0.5 ETH   | Single signer |
| Warm | 180 days | 0.2 ETH   | Manual confirmation |
| Cold | 365 days | 0.05 ETH  | Maximum friction |

## Detection Rules

| Rule | Severity | Why It Matters |
|------|----------|----------------|
| New destination address | HIGH | First action of a compromised key is sending to the attacker's address |
| Large single transfer | HIGH | Covers both external theft and insider misappropriation |
| High velocity (sliding window) | CRITICAL | Drain attack signature — automated script emptying a vault |
| Failed transaction | MEDIUM | Repeated failures may indicate unauthorized signing attempts |

## Quick Start

```bash
git clone https://github.com/YOURUSERNAME/crypto-wallet-lab.git
cd crypto-wallet-lab
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your wallet addresses and Etherscan API key
python main.py
```

To run with demo data (no API key needed):
```bash
python demo.py
```

## Key Design Decisions

**Per-tier thresholds** — a hot wallet legitimately moves large amounts. A cold wallet almost never should. One global threshold generates noise on hot wallets and misses real anomalies on cold wallets.

**Sliding window for velocity** — fixed time buckets miss bursts spanning clock boundaries. Three transactions at :55, :58, :02 look like 2+1 in fixed hourly buckets but one burst in a sliding window.

**is_new_address flag** — computed at normalization time by maintaining a running set of all seen counterparties in chronological order. Whitelist of own wallet addresses and known counterparties pre-populated.

**Idempotent normalization** — one malformed transaction record never crashes the pipeline. Each record normalized independently with try/except, skipped with a log entry if malformed.

## What I Would Add Next

1. Cross-wallet correlation — detect bursts spread across multiple vaults to stay below individual thresholds
2. Chainalysis KYT integration — risk-score counterparty addresses on new destination alerts
3. Proper alerts database with status tracking — measure false positive rate over time to tune thresholds
4. Lambda deployment — replace manual cron with serverless scheduled execution

## Connection to Ripple SDAO

This project is a small-scale version of what the SDAO monitoring system does at production scale. The wallet lab taught me exactly where the design needs to be different for production:

| Wallet lab | Problem | SDAO solution |
|-----------|---------|---------------|
| config.py thresholds | Unmanageable at 50+ vaults | Control plane DB |
| CSV storage | Breaks with multiple teams | BigQuery |
| Detect + ingest in same script | Hard to change rules independently | Separate layers |
| Slack call inside detection | Outage = lost alerts | Alerts table intermediary |
| Single chain | Fireblocks is multi-chain | Provider-agnostic schema |
