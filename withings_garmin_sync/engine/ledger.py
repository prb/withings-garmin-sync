"""Sync ledger for tracking measurements synchronized between Withings and Garmin."""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from withings_garmin_sync.withings.models import WeightRecord

logger = logging.getLogger(__name__)


class SyncLedger:
    """Manages an audit ledger of synchronized measurements for active window reconciliation."""

    def __init__(self, raw_entries: Optional[List[Dict[str, Any]]] = None):
        self._entries: Dict[int, Dict[str, Any]] = {}
        if raw_entries:
            for entry in raw_entries:
                grpid = entry.get("id", entry.get("withings_grpid"))
                if grpid is not None:
                    gid = int(grpid)
                    self._entries[gid] = {
                        "id": gid,
                        "dt": entry.get("dt", entry.get("date_time", "")),
                        "cd": entry.get("cd", entry.get("cdate", "")),
                        "w": float(entry.get("w", entry.get("weight", 0.0))),
                    }

    def is_synced(self, grpid: int) -> bool:
        """Check if a measurement with the given Withings grpid has already been synced."""
        return grpid in self._entries

    def get_entry(self, grpid: int) -> Optional[Dict[str, Any]]:
        entry = self._entries.get(grpid)
        if not entry:
            return None
        return {
            "withings_grpid": entry["id"],
            "date_time": entry["dt"],
            "cdate": entry["cd"],
            "weight": entry["w"],
        }

    def record_synced(self, record: WeightRecord) -> None:
        """Record a newly synchronized measurement in compact format."""
        cdate = record.date_time.strftime("%Y-%m-%d")
        self._entries[record.grpid] = {
            "id": record.grpid,
            "dt": record.date_time.isoformat(),
            "cd": cdate,
            "w": record.weight,
        }

    def remove_entry(self, grpid: int) -> Optional[Dict[str, Any]]:
        """Remove an entry that was deleted."""
        popped = self._entries.pop(grpid, None)
        if not popped:
            return None
        return {
            "withings_grpid": popped["id"],
            "date_time": popped["dt"],
            "cdate": popped["cd"],
            "weight": popped["w"],
        }

    def get_entries_in_window(self, start_dt: datetime, end_dt: datetime) -> List[Dict[str, Any]]:
        """Get all ledger entries whose date_time falls within the given window."""
        results: List[Dict[str, Any]] = []
        for entry in self._entries.values():
            dt_str = entry.get("dt") or ""
            if not dt_str:
                continue
            try:
                dt = datetime.fromisoformat(dt_str)
                if start_dt <= dt <= end_dt:
                    results.append(
                        {
                            "withings_grpid": entry["id"],
                            "date_time": dt_str,
                            "cdate": entry["cd"],
                            "weight": entry["w"],
                        }
                    )
            except ValueError:
                continue
        return results

    def prune_older_than(self, days: int = 90) -> int:
        """Prune records older than the active reconciliation window (default 90 days)."""
        cutoff = datetime.now() - timedelta(days=days)
        to_remove: Set[int] = set()

        for grpid, entry in self._entries.items():
            dt_str = entry.get("dt", "")
            if not dt_str:
                continue
            try:
                dt = datetime.fromisoformat(dt_str)
                if dt < cutoff:
                    to_remove.add(grpid)
            except ValueError:
                continue

        for grpid in to_remove:
            self._entries.pop(grpid, None)

        if to_remove:
            logger.info("Pruned %d ledger entries older than %d days.", len(to_remove), days)
        return len(to_remove)

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialize the ledger to compact dicts for SSM storage."""
        return list(self._entries.values())
