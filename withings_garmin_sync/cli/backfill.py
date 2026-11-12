"""Deliberate historical backfill CLI tool.

Safely batches and synchronizes all-time historical measurements from Withings
to Garmin Connect without impacting the steady-state Lambda budget.
"""

import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from typing import List

from withings_garmin_sync.engine.ledger import SyncLedger
from withings_garmin_sync.garmin.client import GarminClient
from withings_garmin_sync.garmin.encoder import encode_weight_records
from withings_garmin_sync.storage.base import StorageProvider
from withings_garmin_sync.storage.local import LocalStorage
from withings_garmin_sync.storage.ssm import SSMStorage
from withings_garmin_sync.withings.client import WithingsClient
from withings_garmin_sync.withings.models import WeightRecord

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("backfill")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill all historical Withings weight data into Garmin Connect."
    )
    parser.add_argument(
        "--target",
        choices=["ssm", "local"],
        default="ssm",
        help="Storage target (default: ssm).",
    )
    parser.add_argument(
        "--prefix",
        default="/withings-sync",
        help="SSM Parameter Store prefix (default: /withings-sync).",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")),
        help="AWS region (default: us-east-1).",
    )
    parser.add_argument(
        "--local-dir",
        default=".withings_garmin_data",
        help="Local directory if --target local is used.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Number of weight records per FIT file upload (default: 200).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect historical records without uploading to Garmin.",
    )
    return parser.parse_args()


def run_backfill(
    storage: StorageProvider,
    batch_size: int = 200,
    dry_run: bool = False,
) -> None:
    credentials = storage.get_credentials()
    tokens = storage.get_tokens()

    withings_tokens = tokens.get("withings", {})
    garmin_tokens = tokens.get("garmin", {})

    if not withings_tokens.get("refresh_token"):
        raise RuntimeError("Missing Withings tokens in storage. Run bootstrap CLI first.")
    if not garmin_tokens:
        raise RuntimeError("Missing Garmin tokens in storage. Run bootstrap CLI first.")

    withings_client = WithingsClient(
        credentials=credentials,
        tokens=withings_tokens,
    )

    garmin_client = None
    if not dry_run:
        garmin_client = GarminClient(
            tokens=garmin_tokens,
            username=credentials.get("garmin_username"),
            password=credentials.get("garmin_password"),
        )

    ledger = SyncLedger(storage.get_ledger())
    state = storage.get_state()
    checkpoint_str = state.get("backfill_checkpoint_dt")
    checkpoint_dt = None
    if checkpoint_str:
        try:
            checkpoint_dt = datetime.fromisoformat(checkpoint_str)
            print(f"Resuming from backfill checkpoint: {checkpoint_str}")
        except ValueError:
            pass

    now = int(time.time())
    print("\nFetching all-time historical measurements from Withings (startdate=0)...")
    all_records = withings_client.get_weight_records(start_date=0, end_date=now)
    print(f"Retrieved {len(all_records)} total weight measurements from Withings.")

    # Filter out records already in the ledger or prior to checkpoint
    unsynced: List[WeightRecord] = [
        r
        for r in all_records
        if not ledger.is_synced(r.grpid) and (checkpoint_dt is None or r.date_time > checkpoint_dt)
    ]
    print(
        f"Records already synced: {len(all_records) - len(unsynced)} | "
        f"Records needing backfill: {len(unsynced)}"
    )

    if not unsynced:
        print("All historical records are already synchronized! Nothing to do.\n")
        return

    earliest = unsynced[0].date_time.strftime("%Y-%m-%d")
    latest = unsynced[-1].date_time.strftime("%Y-%m-%d")
    print(f"Unsynced date range: {earliest} to {latest}")

    num_batches = (len(unsynced) + batch_size - 1) // batch_size
    print(f"Split into {num_batches} batches of up to {batch_size} records each.")

    if dry_run:
        print("\n[DRY RUN] No records were uploaded to Garmin. Exiting.\n")
        return

    print("\nStarting backfill upload to Garmin Connect...")
    total_uploaded = 0
    window_cutoff = datetime.now() - timedelta(days=90)

    for i in range(num_batches):
        batch = unsynced[i * batch_size : (i + 1) * batch_size]
        batch_start = batch[0].date_time.strftime("%Y-%m-%d")
        batch_end = batch[-1].date_time.strftime("%Y-%m-%d")

        print(
            f"Batch {i + 1}/{num_batches}: Encoding {len(batch)} records "
            f"({batch_start} to {batch_end})..."
        )

        fit_payload = encode_weight_records(
            [
                {
                    "date_time": rec.date_time,
                    "weight": rec.weight,
                    "fat_ratio": rec.fat_ratio,
                    "muscle_mass": rec.muscle_mass,
                    "bone_mass": rec.bone_mass,
                    "percent_hydration": rec.percent_hydration,
                    "bmi": rec.bmi,
                }
                for rec in batch
            ]
        )

        assert garmin_client is not None
        garmin_client.upload_fit_bytes(fit_payload)

        # Only retain records from the active reconciliation window (last 90 days)
        # in the SSM ledger to prevent exceeding the 32 KB SSM parameter limit.
        for rec in batch:
            if rec.date_time >= window_cutoff:
                ledger.record_synced(rec)

        ledger.prune_older_than(days=90)
        storage.save_ledger(ledger.to_list())

        # Update checkpoint in state
        state["backfill_checkpoint_dt"] = batch[-1].date_time.isoformat()
        storage.save_state(state)

        total_uploaded += len(batch)
        print(
            f"Batch {i + 1}/{num_batches} uploaded successfully ({total_uploaded}/{len(unsynced)})."
        )

        # Small pause between batches
        if i < num_batches - 1:
            time.sleep(2)

    # Persist updated tokens if mutated
    if withings_client.tokens_mutated:
        tokens_dict = storage.get_tokens()
        tokens_dict["withings"] = withings_client.tokens
        storage.save_tokens(tokens_dict)

    if garmin_client:
        gtok = garmin_client.get_session_tokens()
        if gtok:
            tokens_dict = storage.get_tokens()
            tokens_dict["garmin"] = gtok
            storage.save_tokens(tokens_dict)

    print(f"\nSUCCESS! Backfilled {total_uploaded} historical measurements into Garmin Connect.")
    print("All records have been recorded in the sync ledger.\n")


def main() -> None:
    args = parse_args()

    storage: StorageProvider
    if args.target == "ssm":
        storage = SSMStorage(prefix=args.prefix, region_name=args.region)
    else:
        storage = LocalStorage(base_dir=args.local_dir)

    run_backfill(
        storage=storage,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
