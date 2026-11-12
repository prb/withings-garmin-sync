# withings-garmin-sync

Lightweight, automated serverless tool to push weight and body composition data from Withings into Garmin Connect, with support for two-way deletion reconciliation.

Runs on AWS Lambda (ARM64) triggered periodically by Amazon EventBridge, with zero ongoing cost ($0.00/month within AWS Free Tier). Credentials, rotating session tokens, and the sync ledger are encrypted at rest using AWS SSM Parameter Store.

---

## Features

* **Specific Withings Profile**: Binds to a specific Withings user profile chosen during interactive authorization.
* **Full Body Composition**: Uploads binary FIT records including weight, body fat %, muscle mass, bone mass, hydration %, and BMI.
* **Deletion Reconciliation**: Automatically detects when a weigh-in is removed from Withings (within a 30–90 day sliding window) and deletes the matching record from Garmin Connect.
* **All-Time Historical Backfill**: Includes a dedicated CLI to batch-upload historical measurements (supports 10+ years of history).
* **Token Expiration Alerting**: Automatically publishes an actionable alert to an Amazon SNS email topic if tokens are ever revoked, with 24-hour deduplication.
* **Zero Infrastructure Cost**: Standard AWS SSM Parameter Store + Lambda + EventBridge fits entirely in the AWS Free Tier.

---

## Quick Start

### 1. Install Dependencies
```bash
uv sync
```

### 2. One-Time Local Bootstrap
Because Garmin Connect challenges datacenter IPs with MFA and Withings requires a browser consent redirect, run the bootstrap CLI once on your local computer:

```bash
uv run python -m withings_garmin_sync.cli.bootstrap --target ssm --prefix /withings-sync --region us-east-1
```
* **Withings**: Opens your browser to authorize your Withings account and select your user profile. Paste the returned code into the terminal.
* **Garmin**: Prompts for your Garmin Connect credentials and handles MFA in the terminal.
* Automatically uploads both authenticated session token sets into AWS SSM Parameter Store.

### 3. Deploy Infrastructure via Pulumi
```bash
cd infra
pulumi stack init prod
pulumi config set aws:region us-east-1
pulumi config set alertEmail "your-email@example.com"  # Optional: for token expiration alerts
pulumi up
```

### 4. (Optional) Backfill Historical Data
To import your complete historical Withings weigh-in history into Garmin Connect:
```bash
# Preview what will be uploaded:
uv run python -m withings_garmin_sync.cli.backfill --dry-run

# Run the backfill:
uv run python -m withings_garmin_sync.cli.backfill
```

---

## Architecture

```
                  ┌─────────────────────────────┐
                  │    Amazon EventBridge Cron  │
                  │       (e.g. hourly)         │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │     AWS Lambda (ARM64)      │
                  │    withings-garmin-sync     │
                  └──────┬───────────────▲──────┘
  1. Read/Write Tokens   │               │  2. Sync data
     & Sync Ledger       ▼               │
                  ┌─────────────┐        │
                  │   AWS SSM   │        │
                  └─────────────┘        │
                                         │
             ┌───────────────────────────┴───────────────────────────┐
             ▼                                                       ▼
  ┌───────────────────────┐                               ┌───────────────────────┐
  │      Withings API     │                               │   Garmin Connect API  │
  │  - Refresh OAuth      │                               │  - Session restore    │
  │  - Fetch measurements │                               │  - Upload FIT weights │
  │                       │                               │  - Delete weigh-ins   │
  └───────────────────────┘                               └───────────────────────┘
```

---

## Acknowledgments & Credits

This project is inspired by and builds upon the pioneering work of [jaroslawhartman/withings-sync](https://github.com/jaroslawhartman/withings-sync) (and its contributors Masayuki Hamasaki, Steffen Vogel, and Jarek Hartman). 

This repository adapts the core Withings OAuth integration and binary FIT protocol encoding into a standalone, cloud-native serverless architecture with two-way deletion reconciliation, Pulumi IaC, and AWS SSM token management.

---

## License

[MIT](LICENSE)
