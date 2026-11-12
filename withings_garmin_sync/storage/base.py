"""Abstract storage provider interface."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class StorageProvider(ABC):
    """Abstract interface for storing configuration, session tokens, and sync state."""

    @abstractmethod
    def get_credentials(self) -> Dict[str, Any]:
        """Retrieve static credentials (Withings client_id/secret, Garmin credentials, etc.)."""
        pass

    @abstractmethod
    def save_credentials(self, credentials: Dict[str, Any]) -> None:
        """Save static credentials."""
        pass

    @abstractmethod
    def get_tokens(self) -> Dict[str, Any]:
        """Retrieve dynamic session tokens (Withings tokens, Garmin session dictionary)."""
        pass

    @abstractmethod
    def save_tokens(self, tokens: Dict[str, Any]) -> None:
        """Save dynamic session tokens."""
        pass

    @abstractmethod
    def get_ledger(self) -> List[Dict[str, Any]]:
        """Retrieve the sync ledger tracking active synced measurements."""
        pass

    @abstractmethod
    def save_ledger(self, ledger: List[Dict[str, Any]]) -> None:
        """Save the sync ledger."""
        pass

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """Retrieve operational state (e.g., last_sync timestamp, last_alert_sent_at)."""
        pass

    @abstractmethod
    def save_state(self, state: Dict[str, Any]) -> None:
        """Save operational state."""
        pass
