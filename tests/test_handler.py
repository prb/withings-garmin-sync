"""Unit tests for the Lambda handler and SNS alerting mechanism."""

import unittest
from unittest.mock import MagicMock, patch

from withings_garmin_sync.handler import lambda_handler, send_alert_if_needed


class TestLambdaHandler(unittest.TestCase):
    @patch("boto3.client")
    def test_send_alert_publishing_and_throttling(self, mock_boto):
        mock_sns = MagicMock()
        mock_boto.return_value = mock_sns

        mock_storage = MagicMock()
        mock_storage.get_state.return_value = {}

        # 1. First alert should publish
        send_alert_if_needed(
            error_type="Test Failure",
            error_message="Test details",
            storage=mock_storage,
            sns_topic_arn="arn:aws:sns:us-east-1:123456789:alert-topic",
        )
        mock_sns.publish.assert_called_once()
        mock_storage.save_state.assert_called_once()

        # 2. Second alert immediately after should be throttled
        mock_storage.get_state.return_value = {"last_alert_sent_at": 10000000000}
        mock_sns.reset_mock()
        send_alert_if_needed(
            error_type="Test Failure 2",
            error_message="Test details 2",
            storage=mock_storage,
            sns_topic_arn="arn:aws:sns:us-east-1:123456789:alert-topic",
        )
        mock_sns.publish.assert_not_called()

    @patch("withings_garmin_sync.handler.SSMStorage")
    @patch("withings_garmin_sync.handler.WithingsClient")
    @patch("withings_garmin_sync.handler.GarminClient")
    @patch("withings_garmin_sync.handler.SyncEngine")
    def test_lambda_handler_success(
        self,
        mock_engine_cls,
        mock_garmin_cls,
        mock_withings_cls,
        mock_storage_cls,
    ):
        mock_storage = MagicMock()
        mock_storage.get_credentials.return_value = {"client_id": "cid", "consumer_secret": "sec"}
        mock_storage.get_tokens.return_value = {
            "withings": {"refresh_token": "w_ref"},
            "garmin": {"di_token": "g_tok"},
        }
        mock_storage_cls.return_value = mock_storage

        mock_engine = MagicMock()
        mock_result = MagicMock()
        mock_result.is_successful = True
        mock_result.synced_count = 2
        mock_result.deleted_count = 0
        mock_result.skipped_count = 1
        mock_engine.reconcile.return_value = mock_result
        mock_engine_cls.return_value = mock_engine

        resp = lambda_handler({}, None)
        self.assertEqual(resp["statusCode"], 200)
        self.assertEqual(resp["body"]["synced"], 2)
        self.assertEqual(resp["body"]["status"], "success")

    @patch("withings_garmin_sync.handler.SSMStorage")
    @patch("withings_garmin_sync.handler.send_alert_if_needed")
    def test_lambda_handler_missing_tokens_raises(
        self,
        mock_send_alert,
        mock_storage_cls,
    ):
        mock_storage = MagicMock()
        mock_storage.get_tokens.return_value = {}
        mock_storage_cls.return_value = mock_storage

        with self.assertRaises(RuntimeError):
            lambda_handler({}, None)

        mock_send_alert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
