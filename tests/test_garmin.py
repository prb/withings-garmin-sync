"""Unit tests for Garmin Connect client."""

import unittest
from unittest.mock import MagicMock, patch

from garminconnect.exceptions import GarminConnectAuthenticationError

from withings_garmin_sync.garmin.client import (
    GarminAuthError,
    GarminClient,
)


class TestGarminClient(unittest.TestCase):
    @patch("withings_garmin_sync.garmin.client.Garmin")
    def test_auth_failure_raises_garmin_auth_error(self, mock_garmin_cls):
        mock_garmin = MagicMock()
        mock_garmin.login.side_effect = GarminConnectAuthenticationError("Invalid credentials")
        mock_garmin_cls.return_value = mock_garmin

        with self.assertRaises(GarminAuthError):
            GarminClient(tokens={"di_token": "expired_token"})

    @patch("withings_garmin_sync.garmin.client.Garmin")
    def test_successful_login_and_token_dump(self, mock_garmin_cls):
        mock_garmin = MagicMock()
        mock_garmin.client.dumps.return_value = '{"di_token": "valid_token", "di_client_id": "cid"}'
        mock_garmin_cls.return_value = mock_garmin

        client = GarminClient(tokens={"di_token": "valid_token"})
        tokens = client.get_session_tokens()

        self.assertEqual(tokens.get("di_token"), "valid_token")
        self.assertEqual(tokens.get("di_client_id"), "cid")

    @patch("withings_garmin_sync.garmin.client.Garmin")
    def test_delete_weigh_in(self, mock_garmin_cls):
        mock_garmin = MagicMock()
        mock_garmin_cls.return_value = mock_garmin

        client = GarminClient(tokens={"di_token": "valid_token"})
        result = client.delete_weigh_in(sample_pk=12345, cdate="2026-11-10")

        self.assertTrue(result)
        mock_garmin.delete_weigh_in.assert_called_once_with("12345", "2026-11-10")


if __name__ == "__main__":
    unittest.main()
