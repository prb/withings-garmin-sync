"""Unit tests for storage providers."""

import tempfile
import unittest
from unittest.mock import MagicMock

from withings_garmin_sync.storage.local import LocalStorage
from withings_garmin_sync.storage.ssm import SSMStorage


class TestLocalStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = LocalStorage(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_empty_defaults(self):
        self.assertEqual(self.storage.get_credentials(), {})
        self.assertEqual(self.storage.get_tokens(), {})
        self.assertEqual(self.storage.get_ledger(), [])
        self.assertEqual(self.storage.get_state(), {})

    def test_save_and_retrieve(self):
        creds = {"client_id": "test_id", "consumer_secret": "test_secret"}
        self.storage.save_credentials(creds)
        self.assertEqual(self.storage.get_credentials(), creds)

        tokens = {"withings": {"access_token": "abc"}, "garmin": {"di_token": "xyz"}}
        self.storage.save_tokens(tokens)
        self.assertEqual(self.storage.get_tokens(), tokens)

        ledger = [{"grpid": 123, "date_time": "2026-11-10T08:00:00", "weight": 75.0}]
        self.storage.save_ledger(ledger)
        self.assertEqual(self.storage.get_ledger(), ledger)

        state = {"last_sync": 1700000000}
        self.storage.save_state(state)
        self.assertEqual(self.storage.get_state(), state)


class TestSSMStorage(unittest.TestCase):
    def setUp(self):
        self.mock_ssm = MagicMock()
        self.storage = SSMStorage(prefix="/test-sync", ssm_client=self.mock_ssm)

    def test_get_param_found(self):
        self.mock_ssm.get_parameter.return_value = {
            "Parameter": {"Value": '{"client_id": "ssm_id"}'}
        }
        creds = self.storage.get_credentials()
        self.assertEqual(creds, {"client_id": "ssm_id"})
        self.mock_ssm.get_parameter.assert_called_once_with(
            Name="/test-sync/credentials", WithDecryption=True
        )

    def test_save_param(self):
        self.storage.save_tokens({"access_token": "token123"})
        self.mock_ssm.put_parameter.assert_called_once_with(
            Name="/test-sync/tokens",
            Value='{"access_token": "token123"}',
            Type="SecureString",
            Overwrite=True,
            Tier="Standard",
        )


if __name__ == "__main__":
    unittest.main()
