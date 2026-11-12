"""Local filesystem-backed storage provider for local runs and testing."""

import json
from pathlib import Path
from typing import Any, Dict, List

from withings_garmin_sync.storage.base import StorageProvider


class LocalStorage(StorageProvider):
    """Stores config, tokens, and ledger in local JSON files."""

    def __init__(self, base_dir: str = ".withings_garmin_data"):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.credentials_file = self.base_dir / "credentials.json"
        self.tokens_file = self.base_dir / "tokens.json"
        self.ledger_file = self.base_dir / "ledger.json"
        self.state_file = self.base_dir / "state.json"

    def _read_json(self, path: Path, default_val: Any) -> Any:
        if not path.exists():
            return default_val
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default_val

    def _write_json(self, path: Path, data: Any) -> None:
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        temp_path.replace(path)

    def get_credentials(self) -> Dict[str, Any]:
        data = self._read_json(self.credentials_file, {})
        return data if isinstance(data, dict) else {}

    def save_credentials(self, credentials: Dict[str, Any]) -> None:
        self._write_json(self.credentials_file, credentials)

    def get_tokens(self) -> Dict[str, Any]:
        data = self._read_json(self.tokens_file, {})
        return data if isinstance(data, dict) else {}

    def save_tokens(self, tokens: Dict[str, Any]) -> None:
        self._write_json(self.tokens_file, tokens)

    def get_ledger(self) -> List[Dict[str, Any]]:
        data = self._read_json(self.ledger_file, [])
        return data if isinstance(data, list) else []

    def save_ledger(self, ledger: List[Dict[str, Any]]) -> None:
        self._write_json(self.ledger_file, ledger)

    def get_state(self) -> Dict[str, Any]:
        data = self._read_json(self.state_file, {})
        return data if isinstance(data, dict) else {}

    def save_state(self, state: Dict[str, Any]) -> None:
        self._write_json(self.state_file, state)
