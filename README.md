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

Reading exchange hack post-mortems, the failure pattern is never a broken cryptographic algorithm, it is operational failures. Keys in plaintext config files. Backups never tested. No rotation policy. No monitoring. I built this to make key management operational rather than theoretical.

## Architecture

```
Ethereum Sepolia Testnet
        ↓
Etherscan API (fetch_transactions.py)
        ↓
normalize.py  →  Unix→datetime, direction, fee, is_new_address
        ↓
detect_alerts.py  →  4 detection rules, per-tier thresholds
        ↓                      ↓
alert_sender.py         CSV export
(Slack webhook)         (Power BI source)
```

Deatiled architecture depicting what each layer does :

┌─────────────────────────────────────────────────────────────────┐
│                    ETHEREUM SEPOLIA TESTNET                     │
│              Real network · Zero financial risk                  │
│         Identical API to mainnet · Free test ETH via faucet     │
└───────────────────────────┬─────────────────────────────────────┘
                            │ on-chain transaction data
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   ETHERSCAN API  (V2)                           │
│          api.etherscan.io/v2/api  ·  chainid=11155111           │
│                                                                  │
│  module=account  action=txlist  sort=asc  startblock=0          │
│                                                                  │
│  Returns per transaction:                                        │
│    hash · from · to · value (Wei) · timeStamp (Unix)            │
│    isError · gas · gasUsed · gasPrice · blockNumber             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ raw JSON · exponential backoff retry
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│               fetch_transactions.py                             │
│                                                                  │
│  • Reads wallet addresses from config.py                        │
│  • Calls Etherscan API for HOT → WARM → COLD (250ms sleep)      │
│  • Returns dict:  { "hot": [...], "warm": [...], "cold": [...] }│
└───────────────────────────┬─────────────────────────────────────┘
                            │ raw dict per wallet tier
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    normalize.py                                  │
│                                                                  │
│  Field transformations:                                          │
│    value (Wei string)  →  amount_eth (float)  ÷ 10¹⁸           │
│    timeStamp (Unix)    →  tx_timestamp (datetime)               │
│    gas × gasPrice      →  fee_eth (float)  ÷ 10¹⁸              │
│    from / to           →  direction (OUTGOING / INCOMING)       │
│    other address       →  counterparty                          │
│    isError "0"/"1"     →  success (bool)                        │
│                                                                  │
│  Derived field:                                                  │
│    is_new_address — running set of all seen counterparties       │
│    sorted chronologically · whitelist pre-seeded with own addrs  │
│                                                                  │
│  Output: single pandas DataFrame · sorted by tx_timestamp        │
│          one malformed record never crashes the pipeline         │
└───────────────────────────┬─────────────────────────────────────┘
                            │ clean DataFrame
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                   detect_alerts.py                              │
│                  (four detection rules)                          │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ RULE 1 · NEW_DESTINATION                    [HIGH]       │   │
│  │ Outgoing tx to address never seen before                │   │
│  │ Why: compromised key first sends to attacker's address  │   │
│  │ How: is_new_address flag · whitelist checked first      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ RULE 2 · LARGE_TRANSFER                     [HIGH]       │   │
│  │ Single outgoing tx above per-tier threshold             │   │
│  │ Hot: 0.5 ETH · Warm: 0.2 ETH · Cold: 0.05 ETH          │   │
│  │ Why: per-tier avoids noise on hot, catches cold anomaly  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ RULE 3 · HIGH_VELOCITY (sliding window)     [CRITICAL]   │   │
│  │ 3+ outgoing txns within 10-minute window                │   │
│  │ Why: drain attack signature — automated script          │   │
│  │ How: sliding window catches bursts spanning clock       │   │
│  │      boundaries that fixed buckets miss  O(n²)          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ RULE 4 · FAILED_TRANSACTION                 [MEDIUM]     │   │
│  │ Any tx where isError = 1                                │   │
│  │ Why: repeated failures = unauthorized signing attempt   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Runs across all three tiers · sorted by severity · timestamp    │
└──────────────┬──────────────────────────────┬───────────────────┘
               │ alert list                   │ DataFrame
               ▼                              ▼
┌──────────────────────────┐    ┌─────────────────────────────────┐
│    alert_sender.py       │    │         CSV export              │
│                          │    │   wallet_transactions.csv       │
│  Slack Block Kit format  │    │                                 │
│  Severity emoji header   │    │  Columns:                       │
│  Full alert message      │    │    tx_hash · wallet_tier        │
│  Embedded runbook steps  │    │    direction · amount_eth       │
│  Per-run deduplication   │    │    fee_eth · success            │
│                          │    │    counterparty                 │
│  🔴 CRITICAL → PagerDuty │    │    is_new_address               │
│  🟠 HIGH     → Slack     │    │    tx_timestamp                 │
│  🟡 MEDIUM   → Slack     │    │                                 │
│  Console if no webhook   │    │  → Power BI / Excel dashboard   │
└──────────────────────────┘    └─────────────────────────────────┘

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


| Wallet lab | Problem | solution |
|-----------|---------|---------------|
| config.py thresholds | Unmanageable at 50+ vaults | Control plane DB |
| CSV storage | Breaks with multiple teams | BigQuery |
| Detect + ingest in same script | Hard to change rules independently | Separate layers |
| Slack call inside detection | Outage = lost alerts | Alerts table intermediary |
| Single chain | Fireblocks is multi-chain | Provider-agnostic schema |
