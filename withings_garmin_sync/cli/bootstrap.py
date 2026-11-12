"""Interactive bootstrap CLI to perform initial Withings OAuth and Garmin MFA logins.

Serializes authenticated session tokens into AWS SSM Parameter Store (or LocalStorage).
"""

import argparse
import getpass
import logging
import os
import time
import urllib.parse
import webbrowser
from typing import Any, Dict, Optional

import requests

from withings_garmin_sync.garmin.client import GarminClient
from withings_garmin_sync.storage.base import StorageProvider
from withings_garmin_sync.storage.local import LocalStorage
from withings_garmin_sync.storage.ssm import SSMStorage

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("bootstrap")

DEFAULT_CLIENT_ID = "183e03e1f363110b3551f96765c98c10e8f1aa647a37067a1cb64bbbaf491626"
DEFAULT_CONSUMER_SECRET = "a75d655c985d9e6391df1514c16719ef7bd69fa7c5d3fd0eac2e2b0ed48f1765"
DEFAULT_CALLBACK_URL = "https://jaroslawhartman.github.io/withings-sync/contrib/withings.html"

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"


def authenticate_withings(
    client_id: str,
    consumer_secret: str,
    callback_url: str = DEFAULT_CALLBACK_URL,
) -> Dict[str, Any]:
    """Perform the Withings interactive authorization code flow."""
    params = {
        "response_type": "code",
        "client_id": client_id,
        "state": "OK",
        "scope": "user.metrics",
        "redirect_uri": callback_url,
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    print("\n" + "=" * 70)
    print("STEP 1: WITHINGS AUTHORIZATION")
    print("=" * 70)
    print("Opening your browser to log in to Withings and authorize your profile...")
    print(f"URL: {url}\n")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    auth_code = input(
        "Paste the authorization code from the callback page (expires in 30s): "
    ).strip()
    if not auth_code:
        raise ValueError("Authorization code cannot be empty.")

    print("Exchanging authorization code for OAuth tokens...")
    token_params = {
        "action": "requesttoken",
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": consumer_secret,
        "code": auth_code,
        "redirect_uri": callback_url,
    }

    resp = requests.post(TOKEN_URL, data=token_params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != 0:
        error_msg = data.get("error", "Failed to retrieve tokens")
        raise RuntimeError(f"Withings token exchange failed: {error_msg}")

    body = data.get("body", {})
    tokens = {
        "access_token": body.get("access_token"),
        "refresh_token": body.get("refresh_token"),
        "userid": body.get("userid"),
        "expires_at": int(time.time()) + body.get("expires_in", 10800),
    }

    print(f"Withings authentication successful! Authorized Profile User ID: {tokens['userid']}")
    return tokens


def authenticate_garmin(
    username: Optional[str] = None,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform interactive Garmin authentication with MFA prompt handling."""
    print("\n" + "=" * 70)
    print("STEP 2: GARMIN CONNECT AUTHENTICATION")
    print("=" * 70)

    if not username:
        username = input("Garmin Connect email address: ").strip()
    if not password:
        password = getpass.getpass("Garmin Connect password: ").strip()

    def mfa_prompt() -> str:
        return input("Enter Garmin MFA / verification code: ").strip()

    print("Authenticating with Garmin Connect (handling MFA if challenged)...")
    client = GarminClient(
        username=username,
        password=password,
        prompt_mfa=mfa_prompt,
    )
    tokens = client.get_session_tokens()
    print("Garmin authentication successful! Session tokens acquired.")
    return tokens


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bootstrap Withings-to-Garmin credentials and tokens."
    )
    parser.add_argument(
        "--target",
        choices=["ssm", "local"],
        default="ssm",
        help="Where to store tokens (default: ssm).",
    )
    parser.add_argument(
        "--prefix",
        default="/withings-sync",
        help="SSM Parameter Store prefix (default: /withings-sync).",
    )
    parser.add_argument(
        "--local-dir",
        default=".withings_garmin_data",
        help="Local directory path when --target local is used.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")),
        help="AWS region for SSM Parameter Store (default: us-east-1).",
    )
    parser.add_argument(
        "--withings-client-id",
        default=os.environ.get("WITHINGS_CLIENT_ID", DEFAULT_CLIENT_ID),
        help="Withings API Client ID.",
    )
    parser.add_argument(
        "--withings-consumer-secret",
        default=os.environ.get("WITHINGS_CONSUMER_SECRET", DEFAULT_CONSUMER_SECRET),
        help="Withings API Consumer Secret.",
    )
    parser.add_argument(
        "--garmin-username",
        default=os.environ.get("GARMIN_USERNAME"),
        help="Garmin username / email.",
    )
    parser.add_argument(
        "--garmin-password",
        default=os.environ.get("GARMIN_PASSWORD"),
        help="Garmin password.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # 1. Select storage provider
    storage: StorageProvider
    if args.target == "ssm":
        storage = SSMStorage(prefix=args.prefix, region_name=args.region)
        print(f"Target: AWS SSM Parameter Store at {args.prefix} ({args.region})")
    else:
        storage = LocalStorage(base_dir=args.local_dir)
        print(f"Target: Local filesystem at {args.local_dir}")

    # 2. Authenticate Withings
    withings_tokens = authenticate_withings(
        client_id=args.withings_client_id,
        consumer_secret=args.withings_consumer_secret,
    )

    # 3. Authenticate Garmin
    garmin_tokens = authenticate_garmin(
        username=args.garmin_username,
        password=args.garmin_password,
    )

    # 4. Save credentials and tokens
    print("\n" + "=" * 70)
    print("STEP 3: PERSISTING CONFIGURATION & TOKENS")
    print("=" * 70)

    credentials = {
        "client_id": args.withings_client_id,
        "consumer_secret": args.withings_consumer_secret,
    }
    storage.save_credentials(credentials)

    all_tokens = {
        "withings": withings_tokens,
        "garmin": garmin_tokens,
    }
    storage.save_tokens(all_tokens)

    # Initialize empty ledger and state if not present
    if not storage.get_ledger():
        storage.save_ledger([])
    if not storage.get_state():
        storage.save_state({"created_at": time.time()})

    print(f"\nSUCCESS! Tokens and credentials have been securely stored in {args.target.upper()}.")
    print("Scheduled serverless Lambda can now run unattended without further login prompts.\n")


if __name__ == "__main__":
    main()
