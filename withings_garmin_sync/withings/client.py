"""Withings API client with automatic token rotation and profile verification."""

import logging
import time
from typing import Any, Dict, List, Optional

import requests

from withings_garmin_sync.withings.models import (
    WeightRecord,
    WithingsMeasure,
    WithingsMeasureGroup,
)

logger = logging.getLogger(__name__)

TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
GETMEAS_URL = "https://wbsapi.withings.net/measure"


class WithingsException(Exception):
    """Base exception for Withings API operations."""


class WithingsAuthError(WithingsException):
    """Raised when Withings authentication fails or tokens cannot be refreshed."""


class WithingsClient:
    """Client for interacting with Withings API."""

    def __init__(
        self,
        credentials: Dict[str, Any],
        tokens: Dict[str, Any],
        timeout: int = 30,
    ):
        self.client_id = credentials.get("client_id")
        self.consumer_secret = credentials.get("consumer_secret")
        self.tokens = dict(tokens)
        self.timeout = timeout
        self.tokens_mutated = False

        if not self.client_id or not self.consumer_secret:
            raise WithingsAuthError("Missing Withings client_id or consumer_secret in credentials.")

        if not self.tokens.get("refresh_token"):
            raise WithingsAuthError("Missing Withings refresh_token. Run bootstrap CLI first.")

    def get_userid(self) -> Optional[int]:
        return self.tokens.get("userid")

    def refresh_access_token(self) -> Dict[str, Any]:
        """Exchange the refresh token for a new access token and rotated refresh token."""
        logger.info("Refreshing Withings access token...")
        params = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.consumer_secret,
            "refresh_token": self.tokens["refresh_token"],
        }

        try:
            resp = requests.post(TOKEN_URL, data=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as err:
            raise WithingsException(f"Network error during Withings token refresh: {err}") from err
        except ValueError as err:
            raise WithingsException(f"Invalid JSON from Withings token endpoint: {err}") from err

        status = data.get("status")
        body = data.get("body", {})

        if status != 0:
            error_msg = data.get("error", body.get("error", "Unknown error"))
            logger.error("Withings token refresh failed with status %s: %s", status, error_msg)
            raise WithingsAuthError(
                f"Withings rejected token refresh (status {status}): {error_msg}. "
                "Interactive re-authentication required."
            )

        new_access = body.get("access_token")
        new_refresh = body.get("refresh_token")
        userid = body.get("userid", self.tokens.get("userid"))
        expires_in = body.get("expires_in", 10800)

        if not new_access or not new_refresh:
            raise WithingsAuthError("Withings response missing access_token or refresh_token.")

        self.tokens.update(
            {
                "access_token": new_access,
                "refresh_token": new_refresh,
                "userid": userid,
                "expires_at": int(time.time()) + expires_in,
            }
        )
        self.tokens_mutated = True
        logger.info("Withings access token successfully refreshed for userid: %s", userid)
        return self.tokens

    def _ensure_valid_token(self) -> None:
        """Ensure the access token is fresh before making API requests."""
        now = int(time.time())
        expires_at = self.tokens.get("expires_at", 0)
        # Refresh if token expired or expiring within 5 minutes, or if no access token
        if not self.tokens.get("access_token") or now >= (expires_at - 300):
            self.refresh_access_token()

    def _post_measure(
        self, params: Dict[str, Any], retry_on_auth_fail: bool = True
    ) -> Dict[str, Any]:
        self._ensure_valid_token()
        headers = {
            "Authorization": f"Bearer {self.tokens['access_token']}",
        }
        data = dict(params)
        data.setdefault("action", "getmeas")

        try:
            resp = requests.post(GETMEAS_URL, data=data, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            res = resp.json()
        except requests.RequestException as err:
            raise WithingsException(f"Withings request error: {err}") from err

        status = res.get("status")
        if status != 0:
            # Status 401 or similar auth error
            if status in (401, 100, 2555) and retry_on_auth_fail:
                logger.warning(
                    "Withings returned status %s. Retrying after token refresh...", status
                )
                self.refresh_access_token()
                return self._post_measure(params, retry_on_auth_fail=False)

            error_msg = res.get("error", "Unknown error")
            raise WithingsException(f"Withings API error (status {status}): {error_msg}")

        return res if isinstance(res, dict) else {}

    def get_height(self) -> Optional[float]:
        """Fetch the most recent height for the user to compute accurate BMI."""
        params = {
            "category": 1,
            "meastype": WithingsMeasure.TYPE_HEIGHT,
        }
        try:
            res = self._post_measure(params)
        except WithingsException as e:
            logger.warning("Could not fetch user height: %s", e)
            return None

        measuregrps = res.get("body", {}).get("measuregrps", [])
        if not measuregrps:
            return None

        latest_height = None
        latest_time = None
        for grp in measuregrps:
            mg = WithingsMeasureGroup(grp)
            h = mg.get_height()
            if h is not None:
                dt = mg.get_datetime()
                if latest_time is None or dt > latest_time:
                    latest_height = h
                    latest_time = dt

        return latest_height

    def get_weight_records(self, start_date: int, end_date: int) -> List[WeightRecord]:
        """Fetch all weight and body composition records in epoch range, with pagination."""
        height = self.get_height()
        measuregrps: List[Dict[str, Any]] = []
        offset = 0

        while True:
            params: Dict[str, Any] = {
                "category": 1,
                "startdate": start_date,
                "enddate": end_date,
            }
            if offset:
                params["offset"] = offset

            res = self._post_measure(params)
            body = res.get("body", {})
            groups = body.get("measuregrps", [])
            if not groups:
                break

            measuregrps.extend(groups)
            if not body.get("more"):
                break
            offset = body.get("offset")

        records: List[WeightRecord] = []
        for raw_grp in measuregrps:
            grp = WithingsMeasureGroup(raw_grp)
            weight = grp.get_weight()
            if weight is None:
                continue

            dt = grp.get_datetime()
            fat_ratio = grp.get_fat_ratio()
            muscle_mass = grp.get_muscle_mass()
            bone_mass = grp.get_bone_mass()
            hydration = grp.get_hydration()

            percent_hydration = None
            if hydration and weight > 0:
                percent_hydration = round(hydration * 100.0 / weight, 2)

            bmi = None
            if height and height > 0:
                bmi = round(weight / (height * height), 1)

            records.append(
                WeightRecord(
                    grpid=grp.grpid,
                    date_time=dt,
                    weight=weight,
                    fat_ratio=fat_ratio,
                    muscle_mass=muscle_mass,
                    bone_mass=bone_mass,
                    hydration=hydration,
                    percent_hydration=percent_hydration,
                    bmi=bmi,
                )
            )

        # Sort chronologically
        records.sort(key=lambda r: r.date_time)
        return records
