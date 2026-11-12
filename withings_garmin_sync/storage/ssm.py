"""AWS Systems Manager (SSM) Parameter Store storage provider."""

import base64
import gzip
import json
import logging
from typing import Any, Dict, List, Literal, Optional

from withings_garmin_sync.storage.base import StorageProvider

logger = logging.getLogger(__name__)


class SSMStorage(StorageProvider):
    """Stores config, tokens, and ledger in AWS SSM Parameter Store as SecureString parameters."""

    def __init__(
        self,
        prefix: str = "/withings-sync",
        ssm_client: Any = None,
        region_name: Optional[str] = None,
    ):
        self.prefix = prefix.rstrip("/")
        if ssm_client is None:
            import boto3

            if region_name:
                self.ssm = boto3.client("ssm", region_name=region_name)
            else:
                self.ssm = boto3.client("ssm")
        else:
            self.ssm = ssm_client

        self._cache: Dict[str, Any] = {}

    def _param_name(self, key: str) -> str:
        return f"{self.prefix}/{key}"

    def _get_param(self, key: str, default_val: Any) -> Any:
        param_name = self._param_name(key)
        if key in self._cache:
            return self._cache[key]

        try:
            resp = self.ssm.get_parameter(Name=param_name, WithDecryption=True)
            raw_val = resp["Parameter"]["Value"]
            if isinstance(raw_val, str) and raw_val.startswith("GZ:"):
                decompressed = gzip.decompress(base64.b64decode(raw_val[3:])).decode("utf-8")
                data = json.loads(decompressed)
            else:
                data = json.loads(raw_val)
            self._cache[key] = data
            return data
        except self.ssm.exceptions.ParameterNotFound:
            logger.info("SSM parameter %s not found. Using default.", param_name)
            return default_val
        except Exception as e:
            # Handle client errors or JSON decode errors gracefully
            if getattr(e, "response", {}).get("Error", {}).get("Code") == "ParameterNotFound":
                return default_val
            logger.warning("Error reading parameter %s from SSM: %s", param_name, e)
            return default_val

    def _put_param(
        self,
        key: str,
        data: Any,
        param_type: Literal["SecureString", "String", "StringList"] = "SecureString",
    ) -> None:
        param_name = self._param_name(key)
        raw_val = json.dumps(data, default=str)
        # Transparently compress if payload exceeds 3,000 chars to strictly stay within
        # the 4,096 char limit of AWS SSM Parameter Store Standard Tier ($0.00).
        if len(raw_val) > 3000:
            compressed = base64.b64encode(gzip.compress(raw_val.encode("utf-8"))).decode("ascii")
            raw_val = f"GZ:{compressed}"
            logger.debug("Compressed SSM parameter %s to %d bytes", param_name, len(raw_val))

        try:
            self.ssm.put_parameter(
                Name=param_name,
                Value=raw_val,
                Type=param_type,
                Overwrite=True,
                Tier="Standard",
            )
            self._cache[key] = data
            logger.debug("Saved parameter %s to SSM.", param_name)
        except Exception as e:
            logger.error("Failed to write parameter %s to SSM: %s", param_name, e)
            raise

    def get_credentials(self) -> Dict[str, Any]:
        data = self._get_param("credentials", {})
        return data if isinstance(data, dict) else {}

    def save_credentials(self, credentials: Dict[str, Any]) -> None:
        self._put_param("credentials", credentials, param_type="SecureString")

    def get_tokens(self) -> Dict[str, Any]:
        data = self._get_param("tokens", {})
        return data if isinstance(data, dict) else {}

    def save_tokens(self, tokens: Dict[str, Any]) -> None:
        self._put_param("tokens", tokens, param_type="SecureString")

    def get_ledger(self) -> List[Dict[str, Any]]:
        data = self._get_param("ledger", [])
        return data if isinstance(data, list) else []

    def save_ledger(self, ledger: List[Dict[str, Any]]) -> None:
        self._put_param("ledger", ledger, param_type="SecureString")

    def get_state(self) -> Dict[str, Any]:
        data = self._get_param("state", {})
        return data if isinstance(data, dict) else {}

    def save_state(self, state: Dict[str, Any]) -> None:
        self._put_param("state", state, param_type="SecureString")
