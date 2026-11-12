"""Garmin Connect client for uploading FIT body composition and deleting weigh-ins."""

import json
import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict, List, Optional, Union

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

logger = logging.getLogger(__name__)


class GarminException(Exception):
    """Base exception for Garmin Connect operations."""


class GarminAuthError(GarminException):
    """Raised when Garmin authentication fails or saved session tokens are rejected."""


class GarminClient:
    """Client for authenticating with Garmin Connect and managing weigh-ins."""

    def __init__(
        self,
        tokens: Optional[Union[Dict[str, Any], str]] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        prompt_mfa: Optional[Any] = None,
    ):
        self.username = username
        self.password = password
        self.prompt_mfa = prompt_mfa
        self.garmin: Optional[Garmin] = None
        self._initial_tokenstore = tokens

        self._login()

    def _login(self) -> None:
        """Authenticate using saved tokenstore or credentials."""
        tokenstore_str = None
        if self._initial_tokenstore:
            if isinstance(self._initial_tokenstore, dict):
                tokenstore_str = json.dumps(self._initial_tokenstore)
            elif isinstance(self._initial_tokenstore, str):
                tokenstore_str = self._initial_tokenstore

        try:
            self.garmin = Garmin(
                email=self.username,
                password=self.password,
                prompt_mfa=self.prompt_mfa,
            )
            logger.info("Attempting Garmin authentication...")
            self.garmin.login(tokenstore=tokenstore_str)
            logger.info("Garmin authentication successful.")
        except GarminConnectAuthenticationError as e:
            logger.error("Garmin authentication failed: %s", e)
            raise GarminAuthError(
                f"Garmin Connect authentication failed: {e}. "
                "Interactive re-authentication via bootstrap CLI required."
            ) from e
        except GarminConnectTooManyRequestsError as e:
            logger.error("Garmin rate limit / 429: %s", e)
            raise GarminException("Garmin rate limited the login request.") from e
        except GarminConnectConnectionError as e:
            logger.error("Garmin connection error: %s", e)
            raise GarminException(f"Network error connecting to Garmin: {e}") from e
        except Exception as e:
            logger.error("Unexpected error during Garmin login: %s", e)
            raise GarminException(f"Unexpected error authenticating with Garmin: {e}") from e

    def get_session_tokens(self) -> Dict[str, Any]:
        """Serialize active session tokens to a dictionary for persistence in SSM."""
        if not self.garmin or not self.garmin.client:
            return {}
        raw = self.garmin.client.dumps()
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    def upload_fit_bytes(self, fit_bytes: bytes) -> bool:
        """Upload a binary FIT payload directly to Garmin Connect."""
        if not self.garmin:
            raise GarminException("Garmin client is not authenticated")

        logger.info("Uploading FIT weight data to Garmin Connect (%d bytes)...", len(fit_bytes))

        # First try uploading in-memory via client.post
        try:
            url = self.garmin.garmin_connect_upload
            files = {"file": ("weight_scale.fit", BytesIO(fit_bytes))}
            resp = self.garmin.client.post("connectapi", url, files=files, api=True)
            logger.info("Garmin FIT upload succeeded: %s", resp)
            return True
        except Exception as e:
            logger.warning("In-memory upload failed (%s), falling back to tempfile upload...", e)

        # Fallback to upload_activity with a temporary file
        with tempfile.NamedTemporaryFile(suffix=".fit", delete=False) as tmp:
            tmp.write(fit_bytes)
            tmp_path = tmp.name

        try:
            self.garmin.upload_activity(tmp_path)
            logger.info("Garmin upload via temporary file succeeded.")
            return True
        except Exception as ex:
            logger.error("Failed to upload FIT file to Garmin: %ex", ex)
            raise GarminException(f"Garmin upload failed: {ex}") from ex
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def get_daily_weigh_ins(self, cdate: str) -> List[Dict[str, Any]]:
        """Retrieve all weigh-in records on a given date (cdate in 'YYYY-MM-DD' format)."""
        if not self.garmin:
            raise GarminException("Garmin client is not authenticated")

        try:
            res = self.garmin.get_daily_weigh_ins(cdate)
            items = res.get("dateWeightList", [])
            return list(items) if isinstance(items, list) else []
        except Exception as e:
            logger.warning("Failed to fetch weigh-ins for date %s: %s", cdate, e)
            return []

    def delete_weigh_in(self, sample_pk: Union[int, str], cdate: str) -> bool:
        """Delete a specific weigh-in record in Garmin Connect."""
        if not self.garmin:
            raise GarminException("Garmin client is not authenticated")

        logger.info("Deleting weigh-in %s for date %s from Garmin Connect...", sample_pk, cdate)
        try:
            self.garmin.delete_weigh_in(str(sample_pk), cdate)
            logger.info("Weigh-in %s deleted successfully.", sample_pk)
            return True
        except Exception as e:
            logger.error("Failed to delete weigh-in %s on %s: %s", sample_pk, cdate, e)
            raise GarminException(f"Failed to delete weigh-in from Garmin: {e}") from e
