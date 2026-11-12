"""Unit tests for Withings models and client."""

import unittest
from unittest.mock import MagicMock, patch

from withings_garmin_sync.withings.client import (
    WithingsAuthError,
    WithingsClient,
)
from withings_garmin_sync.withings.models import (
    WithingsMeasure,
    WithingsMeasureGroup,
)


class TestWithingsModels(unittest.TestCase):
    def test_withings_measure_value(self):
        # 75500 with unit -3 -> 75.5 kg
        m = WithingsMeasure({"type": 1, "value": 75500, "unit": -3})
        self.assertAlmostEqual(m.get_value(), 75.5)

    def test_withings_measure_group(self):
        raw_grp = {
            "grpid": 1001,
            "date": 1700000000,
            "category": 1,
            "measures": [
                {"type": 1, "value": 76000, "unit": -3},  # weight: 76.0
                {"type": 6, "value": 1850, "unit": -2},  # fat ratio: 18.5
                {"type": 76, "value": 35200, "unit": -3},  # muscle mass: 35.2
                {"type": 77, "value": 42000, "unit": -3},  # hydration: 42.0
                {"type": 88, "value": 3100, "unit": -3},  # bone mass: 3.1
            ],
        }
        grp = WithingsMeasureGroup(raw_grp)
        self.assertEqual(grp.grpid, 1001)
        self.assertEqual(grp.get_weight(), 76.0)
        self.assertEqual(grp.get_fat_ratio(), 18.5)
        self.assertEqual(grp.get_muscle_mass(), 35.2)
        self.assertEqual(grp.get_hydration(), 42.0)
        self.assertEqual(grp.get_bone_mass(), 3.1)


class TestWithingsClient(unittest.TestCase):
    def setUp(self):
        self.creds = {"client_id": "cid_123", "consumer_secret": "sec_456"}
        self.tokens = {
            "access_token": "acc_tok",
            "refresh_token": "ref_tok",
            "userid": 9999,
            "expires_at": 2000000000,
        }

    def test_missing_credentials_raises_auth_error(self):
        with self.assertRaises(WithingsAuthError):
            WithingsClient(credentials={}, tokens=self.tokens)

    def test_missing_refresh_token_raises_auth_error(self):
        with self.assertRaises(WithingsAuthError):
            WithingsClient(credentials=self.creds, tokens={})

    @patch("requests.post")
    def test_refresh_token_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 0,
            "body": {
                "access_token": "new_access",
                "refresh_token": "new_refresh",
                "userid": 9999,
                "expires_in": 10800,
            },
        }
        mock_post.return_value = mock_resp

        client = WithingsClient(credentials=self.creds, tokens=self.tokens)
        new_tokens = client.refresh_access_token()

        self.assertEqual(new_tokens["access_token"], "new_access")
        self.assertEqual(new_tokens["refresh_token"], "new_refresh")
        self.assertTrue(client.tokens_mutated)

    @patch("requests.post")
    def test_refresh_token_failure_raises_auth_error(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": 401,
            "error": "Invalid refresh token",
        }
        mock_post.return_value = mock_resp

        client = WithingsClient(credentials=self.creds, tokens=self.tokens)
        with self.assertRaises(WithingsAuthError):
            client.refresh_access_token()


if __name__ == "__main__":
    unittest.main()
