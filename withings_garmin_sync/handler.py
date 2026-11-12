"""AWS Lambda handler entry point triggered by Amazon EventBridge."""

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import boto3

from withings_garmin_sync.engine.reconcile import SyncEngine, SyncResult
from withings_garmin_sync.garmin.client import GarminAuthError, GarminClient
from withings_garmin_sync.storage.ssm import SSMStorage
from withings_garmin_sync.withings.client import WithingsAuthError, WithingsClient

# Configure root logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

SSM_PREFIX = os.environ.get("SSM_PREFIX", "/withings-sync")
SNS_TOPIC_ARN = os.environ.get("ALERT_SNS_TOPIC_ARN")
WINDOW_DAYS = int(os.environ.get("SYNC_WINDOW_DAYS", "30"))
ALERT_COOLDOWN_SECONDS = 86400  # 24 hours between duplicate alert emails


def send_alert_if_needed(
    error_type: str,
    error_message: str,
    storage: SSMStorage,
    sns_topic_arn: Optional[str] = SNS_TOPIC_ARN,
) -> None:
    """Send an actionable SNS email alert when authentication expires, throttled to 24h."""
    if not sns_topic_arn:
        logger.warning("No ALERT_SNS_TOPIC_ARN configured; skipping email alert.")
        return

    state = storage.get_state()
    now = int(time.time())
    last_sent = state.get("last_alert_sent_at", 0)

    if (now - last_sent) < ALERT_COOLDOWN_SECONDS:
        logger.info(
            "Alert throttled (last sent %d seconds ago, cooldown %d seconds).",
            now - last_sent,
            ALERT_COOLDOWN_SECONDS,
        )
        return

    subject = f"[Withings-Garmin Sync Alert] {error_type}"
    body = (
        f"Withings-to-Garmin sync encountered an authentication failure.\n\n"
        f"Failure: {error_type}\n"
        f"Details: {error_message}\n\n"
        f"Action Required:\n"
        f"Please re-authenticate on your computer by running:\n"
        f"  uv run python -m withings_garmin_sync.cli.bootstrap "
        f"--target ssm --prefix {storage.prefix}\n\n"
        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(now))}\n"
    )

    try:
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=sns_topic_arn,
            Subject=subject,
            Message=body,
        )
        state["last_alert_sent_at"] = now
        storage.save_state(state)
        logger.info("Sent authentication failure alert to SNS topic %s.", sns_topic_arn)
    except Exception as e:
        logger.error("Failed to publish alert to SNS topic %s: %s", sns_topic_arn, e)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Lambda function handler."""
    logger.info("Withings-to-Garmin sync triggered. Event: %s", json.dumps(event))

    storage = SSMStorage(prefix=SSM_PREFIX)
    credentials = storage.get_credentials()
    tokens = storage.get_tokens()

    withings_tokens = tokens.get("withings", {})
    garmin_tokens = tokens.get("garmin", {})

    # Validate essential token presence
    if not withings_tokens.get("refresh_token"):
        error_msg = "Missing Withings refresh token in SSM. Run bootstrap CLI first."
        send_alert_if_needed("Withings Tokens Missing", error_msg, storage)
        raise RuntimeError(error_msg)

    if not garmin_tokens:
        error_msg = "Missing Garmin session tokens in SSM. Run bootstrap CLI first."
        send_alert_if_needed("Garmin Tokens Missing", error_msg, storage)
        raise RuntimeError(error_msg)

    # Initialize clients with auth failure handling
    try:
        withings_client = WithingsClient(
            credentials=credentials,
            tokens=withings_tokens,
        )
    except WithingsAuthError as e:
        send_alert_if_needed("Withings Authentication Expired", str(e), storage)
        raise

    try:
        garmin_client = GarminClient(
            tokens=garmin_tokens,
            username=credentials.get("garmin_username"),
            password=credentials.get("garmin_password"),
        )
    except GarminAuthError as e:
        send_alert_if_needed("Garmin Authentication Expired", str(e), storage)
        raise

    # Execute reconciliation
    engine = SyncEngine(
        storage=storage,
        withings_client=withings_client,
        garmin_client=garmin_client,
        window_days=WINDOW_DAYS,
    )

    result: SyncResult = engine.reconcile()

    if not result.is_successful:
        logger.error("Sync completed with errors: %s", result.errors)
        # Raise to let CloudWatch register an error metric if desired
        raise RuntimeError(f"Sync completed with errors: {result.errors}")

    response = {
        "statusCode": 200,
        "body": {
            "synced": result.synced_count,
            "deleted": result.deleted_count,
            "skipped": result.skipped_count,
            "status": "success",
        },
    }
    logger.info("Sync finished successfully: %s", response)
    return response
