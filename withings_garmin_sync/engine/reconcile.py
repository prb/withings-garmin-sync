"""Synchronization and deletion reconciliation engine."""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from withings_garmin_sync.engine.ledger import SyncLedger
from withings_garmin_sync.garmin.client import GarminClient
from withings_garmin_sync.garmin.encoder import encode_weight_records
from withings_garmin_sync.storage.base import StorageProvider
from withings_garmin_sync.withings.client import WithingsClient
from withings_garmin_sync.withings.models import WeightRecord

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Summary of reconciliation results."""

    synced_count: int = 0
    deleted_count: int = 0
    skipped_count: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def is_successful(self) -> bool:
        return len(self.errors) == 0


class SyncEngine:
    """Orchestrates forward sync and deletion reconciliation between Withings and Garmin."""

    def __init__(
        self,
        storage: StorageProvider,
        withings_client: WithingsClient,
        garmin_client: GarminClient,
        window_days: int = 30,
    ):
        self.storage = storage
        self.withings = withings_client
        self.garmin = garmin_client
        self.window_days = window_days
        self.ledger = SyncLedger(self.storage.get_ledger())

    def _match_garmin_sample(
        self,
        garmin_items: List[Dict[str, Any]],
        target_weight_kg: float,
        target_dt: datetime,
    ) -> Optional[int]:
        """Find the Garmin weigh-in samplePk that matches the target weight and timestamp."""
        best_match_pk = None
        min_weight_diff = 0.5  # Tolerance: 0.5 kg

        for item in garmin_items:
            raw_weight = item.get("weight")
            sample_pk = item.get("samplePk")
            if raw_weight is None or sample_pk is None:
                continue

            # Garmin API may report weight in grams (e.g. 76500) or kg (e.g. 76.5)
            weight_kg = raw_weight / 1000.0 if raw_weight > 500 else raw_weight
            diff = abs(weight_kg - target_weight_kg)

            if diff < min_weight_diff:
                min_weight_diff = diff
                best_match_pk = int(sample_pk)

        return best_match_pk

    def reconcile(self) -> SyncResult:
        """Run reconciliation: execute deletions on Garmin first, then upload new records."""
        result = SyncResult()
        now = datetime.now()
        start_dt = now - timedelta(days=self.window_days)

        start_epoch = int(start_dt.timestamp())
        end_epoch = int(now.timestamp())

        logger.info(
            "Starting reconciliation window: %s to %s (%d days)",
            start_dt.strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
            self.window_days,
        )

        # 1. Fetch active records from Withings
        try:
            active_withings_records = self.withings.get_weight_records(start_epoch, end_epoch)
            active_grpids = {r.grpid: r for r in active_withings_records}
            logger.info("Retrieved %d active measurements from Withings.", len(active_grpids))
        except Exception as e:
            error_msg = f"Failed to fetch Withings measurements: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            return result

        # 2. Deletion reconciliation:
        # Check all records we previously synced in this window
        ledger_entries_in_window = self.ledger.get_entries_in_window(start_dt, now)
        logger.info(
            "Found %d previously synced entries in the current window.",
            len(ledger_entries_in_window),
        )

        for entry in ledger_entries_in_window:
            grpid = entry["withings_grpid"]
            if grpid not in active_grpids:
                # This record was present in our ledger but has vanished from Withings!
                cdate = entry.get("cdate")
                weight_kg = entry.get("weight", 0.0)
                dt_str = entry.get("date_time", "")
                try:
                    target_dt = datetime.fromisoformat(dt_str)
                except ValueError:
                    target_dt = now

                logger.warning(
                    "Measurement grpid=%d (weight=%.2f kg on %s) was deleted from Withings.",
                    grpid,
                    weight_kg,
                    cdate,
                )

                if cdate:
                    try:
                        garmin_daily = self.garmin.get_daily_weigh_ins(cdate)
                        match_pk = self._match_garmin_sample(garmin_daily, weight_kg, target_dt)
                        if match_pk:
                            self.garmin.delete_weigh_in(match_pk, cdate)
                            logger.info(
                                "Deleted weigh-in samplePk=%d from Garmin for date %s.",
                                match_pk,
                                cdate,
                            )
                        else:
                            logger.info(
                                "No matching weigh-in found in Garmin for %s to delete.", cdate
                            )
                    except Exception as e:
                        logger.error("Error deleting weigh-in from Garmin: %s", e)
                        result.errors.append(f"Failed deleting weigh-in on {cdate}: {e}")

                self.ledger.remove_entry(grpid)
                result.deleted_count += 1

        # 3. Forward sync:
        # Upload any active Withings records that have not yet been synced
        new_records: List[WeightRecord] = []
        for r in active_withings_records:
            if not self.ledger.is_synced(r.grpid):
                new_records.append(r)
            else:
                result.skipped_count += 1

        if new_records:
            logger.info("Found %d new measurements to upload to Garmin.", len(new_records))
            try:
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
                        for rec in new_records
                    ]
                )
                self.garmin.upload_fit_bytes(fit_payload)

                # Record successful syncs in the ledger
                for rec in new_records:
                    self.ledger.record_synced(rec)
                    result.synced_count += 1
                logger.info("Successfully uploaded and recorded %d measurements.", len(new_records))
            except Exception as e:
                error_msg = f"Failed to upload new records to Garmin: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)
        else:
            logger.info("No new measurements to sync.")

        # 4. Persist updated tokens and state
        self._persist_state()

        return result

    def _persist_state(self) -> None:
        """Persist updated tokens, pruned ledger, and operational state to storage."""
        # 1. Save Withings tokens if updated
        if self.withings.tokens_mutated:
            tokens_dict = self.storage.get_tokens()
            tokens_dict["withings"] = self.withings.tokens
            self.storage.save_tokens(tokens_dict)
            logger.debug("Persisted updated Withings tokens to storage.")

        # 2. Save Garmin session tokens if active
        garmin_tokens = self.garmin.get_session_tokens()
        if garmin_tokens:
            tokens_dict = self.storage.get_tokens()
            tokens_dict["garmin"] = garmin_tokens
            self.storage.save_tokens(tokens_dict)
            logger.debug("Persisted updated Garmin session tokens to storage.")

        # 3. Prune old ledger entries (>180 days) and persist
        self.ledger.prune_older_than(days=180)
        self.storage.save_ledger(self.ledger.to_list())

        # 4. Update operational state
        state = self.storage.get_state()
        state["last_sync_timestamp"] = int(time.time())
        state["last_sync_datetime"] = datetime.now().isoformat()
        self.storage.save_state(state)
