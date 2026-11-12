"""Unit and property-based tests for the sync ledger and reconciliation engine."""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from hypothesis import given
from hypothesis import strategies as st

from withings_garmin_sync.engine.ledger import SyncLedger
from withings_garmin_sync.engine.reconcile import SyncEngine
from withings_garmin_sync.withings.models import WeightRecord


class TestSyncLedger(unittest.TestCase):
    def test_record_and_retrieve(self):
        ledger = SyncLedger()
        rec = WeightRecord(
            grpid=5001,
            date_time=datetime(2026, 11, 10, 8, 0, 0),
            weight=75.5,
            fat_ratio=18.0,
        )
        ledger.record_synced(rec)

        self.assertTrue(ledger.is_synced(5001))
        self.assertFalse(ledger.is_synced(5002))

        entry = ledger.get_entry(5001)
        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry["cdate"], "2026-11-10")
        self.assertEqual(entry["weight"], 75.5)

    def test_window_filtering(self):
        ledger = SyncLedger()
        rec1 = WeightRecord(grpid=1, date_time=datetime(2026, 11, 1, 8, 0, 0), weight=75.0)
        rec2 = WeightRecord(grpid=2, date_time=datetime(2026, 11, 10, 8, 0, 0), weight=75.5)
        ledger.record_synced(rec1)
        ledger.record_synced(rec2)

        window_entries = ledger.get_entries_in_window(
            start_dt=datetime(2026, 11, 5, 0, 0, 0),
            end_dt=datetime(2026, 11, 15, 0, 0, 0),
        )
        self.assertEqual(len(window_entries), 1)
        self.assertEqual(window_entries[0]["withings_grpid"], 2)

    @given(days_ago_list=st.lists(st.integers(min_value=1, max_value=300), min_size=5, max_size=50))
    def test_ledger_pruning_property(self, days_ago_list):
        """Property: After pruning, remaining entries are strictly newer than cutoff."""
        now = datetime.now()
        ledger = SyncLedger()
        for idx, days in enumerate(days_ago_list):
            dt = now - timedelta(days=days)
            rec = WeightRecord(grpid=1000 + idx, date_time=dt, weight=70.0)
            ledger.record_synced(rec)

        prune_days = 90
        cutoff = now - timedelta(days=prune_days)
        ledger.prune_older_than(days=prune_days)

        for entry in ledger.to_list():
            dt_str = entry.get("dt") or entry.get("date_time")
            assert dt_str is not None
            entry_dt = datetime.fromisoformat(dt_str)
            self.assertGreaterEqual(entry_dt, cutoff)


class TestSyncEngine(unittest.TestCase):
    def setUp(self):
        self.mock_storage = MagicMock()
        self.mock_storage.get_ledger.return_value = []
        self.mock_storage.get_tokens.return_value = {}
        self.mock_storage.get_state.return_value = {}

        self.mock_withings = MagicMock()
        self.mock_withings.tokens_mutated = False

        self.mock_garmin = MagicMock()
        self.mock_garmin.get_session_tokens.return_value = {"di_token": "valid"}

    def test_forward_sync_new_records(self):
        rec1 = WeightRecord(
            grpid=101,
            date_time=datetime(2026, 11, 10, 7, 0, 0),
            weight=76.2,
            fat_ratio=18.0,
            muscle_mass=35.0,
            percent_hydration=55.0,
            bmi=23.4,
        )
        self.mock_withings.get_weight_records.return_value = [rec1]

        engine = SyncEngine(
            storage=self.mock_storage,
            withings_client=self.mock_withings,
            garmin_client=self.mock_garmin,
            window_days=30,
        )
        result = engine.reconcile()

        self.assertEqual(result.synced_count, 1)
        self.assertEqual(result.deleted_count, 0)
        self.assertEqual(result.skipped_count, 0)
        self.assertTrue(result.is_successful)

        self.mock_garmin.upload_fit_bytes.assert_called_once()
        self.mock_storage.save_ledger.assert_called_once()

    def test_idempotent_skip_already_synced(self):
        rec1 = WeightRecord(grpid=101, date_time=datetime(2026, 11, 10, 7, 0, 0), weight=76.2)
        # Prepopulate ledger with rec1
        self.mock_storage.get_ledger.return_value = [
            {
                "withings_grpid": 101,
                "date_time": "2026-11-10T07:00:00",
                "cdate": "2026-11-10",
                "weight": 76.2,
            }
        ]
        self.mock_withings.get_weight_records.return_value = [rec1]

        engine = SyncEngine(
            storage=self.mock_storage,
            withings_client=self.mock_withings,
            garmin_client=self.mock_garmin,
            window_days=30,
        )
        result = engine.reconcile()

        self.assertEqual(result.synced_count, 0)
        self.assertEqual(result.skipped_count, 1)
        self.assertEqual(result.deleted_count, 0)
        self.mock_garmin.upload_fit_bytes.assert_not_called()

    def test_deletion_reconciliation(self):
        # Ledger has an entry from 5 days ago, but Withings returns [] (user deleted it)
        past_dt = datetime.now() - timedelta(days=5)
        cdate = past_dt.strftime("%Y-%m-%d")
        self.mock_storage.get_ledger.return_value = [
            {
                "withings_grpid": 202,
                "date_time": past_dt.isoformat(),
                "cdate": cdate,
                "weight": 75.8,
            }
        ]
        self.mock_withings.get_weight_records.return_value = []

        # Garmin has matching weigh-in on that date
        self.mock_garmin.get_daily_weigh_ins.return_value = [
            {"samplePk": 88888, "weight": 75800.0, "date": int(past_dt.timestamp() * 1000)}
        ]

        engine = SyncEngine(
            storage=self.mock_storage,
            withings_client=self.mock_withings,
            garmin_client=self.mock_garmin,
            window_days=30,
        )
        result = engine.reconcile()

        self.assertEqual(result.deleted_count, 1)
        self.assertEqual(result.synced_count, 0)
        self.mock_garmin.delete_weigh_in.assert_called_once_with(88888, cdate)


if __name__ == "__main__":
    unittest.main()
