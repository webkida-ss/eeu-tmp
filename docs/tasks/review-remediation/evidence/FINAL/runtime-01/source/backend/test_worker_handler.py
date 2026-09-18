import importlib
import unittest
from types import SimpleNamespace
from unittest import mock

from storage import dynamodb_store

_dynamodb_resource_factory = dynamodb_store.create_dynamodb_resource
_dynamodb_client_factory = dynamodb_store.create_dynamodb_client

worker_handler = importlib.import_module("worker_handler")


class WorkerHandlerTests(unittest.TestCase):
    def test_worker_lambda_entrypoint_keeps_both_dynamodb_factories(self):
        self.assertIs(dynamodb_store.create_dynamodb_resource, _dynamodb_resource_factory)
        self.assertIs(dynamodb_store.create_dynamodb_client, _dynamodb_client_factory)

    @mock.patch.object(worker_handler, "get_preload_content_store")
    @mock.patch.object(worker_handler, "get_usage_repository")
    @mock.patch.object(worker_handler, "get_subscription_repository")
    @mock.patch.object(worker_handler, "get_page_preload_repository")
    @mock.patch.object(worker_handler, "run_preload_job")
    def test_legacy_message_without_identity_is_acknowledged(
        self,
        run_preload_job,
        _get_repository,
        _get_subscription_repository,
        _get_usage_repository,
        _get_content_store,
    ):
        result = worker_handler.handler(
            {
                "Records": [
                    {
                        "messageId": "legacy-message",
                        "body": '{"user_id":"u1","page_url":"https://example.com/article"}',
                    }
                ]
            },
            None,
        )

        self.assertEqual(result, {"batchItemFailures": []})
        run_preload_job.assert_not_called()

    @mock.patch.object(worker_handler, "get_preload_content_store")
    @mock.patch.object(worker_handler, "get_usage_repository")
    @mock.patch.object(worker_handler, "get_subscription_repository")
    @mock.patch.object(worker_handler, "get_page_preload_repository")
    @mock.patch.object(
        worker_handler, "run_preload_job", side_effect=RuntimeError("settlement uncertain")
    )
    def test_settlement_failure_is_not_acknowledged(
        self,
        run_preload_job,
        _get_repository,
        _get_subscription_repository,
        _get_usage_repository,
        _get_content_store,
    ):
        usage_context = {
            "operation_id": "019b63f8-f600-7000-8000-000000000030",
            "usage_month": "2026-07",
        }
        result = worker_handler.handler(
            {
                "Records": [
                    {
                        "messageId": "message-1",
                        "body": (
                            '{"user_id":"u1","page_url":"https://example.com/article",'
                            '"preload_id":"preload","learner_profile_fingerprint":"profile",'
                            '"usage_context":{"operation_id":"019b63f8-f600-7000-8000-000000000030",'
                            '"usage_month":"2026-07"}}'
                        ),
                    }
                ]
            },
            None,
        )

        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "message-1"}]})
        self.assertEqual(run_preload_job.call_args.args[-1], usage_context)

    def test_worker_passes_the_configured_billing_mode_to_preload_entitlement_checks(self):
        accounts = SimpleNamespace(settings=SimpleNamespace(billing_provider="stripe"))
        with (
            mock.patch.object(worker_handler, "get_accounts", return_value=accounts),
            mock.patch.object(worker_handler, "get_page_preload_repository"),
            mock.patch.object(worker_handler, "get_subscription_repository"),
            mock.patch.object(worker_handler, "get_usage_repository"),
            mock.patch.object(worker_handler, "get_preload_content_store"),
            mock.patch.object(worker_handler, "run_preload_job") as run_preload_job,
        ):
            result = worker_handler.handler(
                {
                    "Records": [
                        {
                            "messageId": "message-1",
                            "body": (
                                '{"user_id":"u1","page_url":"https://example.com/article",'
                                '"preload_id":"preload","learner_profile_fingerprint":"profile"}'
                            ),
                        }
                    ]
                },
                None,
            )

        self.assertEqual(result, {"batchItemFailures": []})
        self.assertEqual(run_preload_job.call_args.kwargs["billing_provider_mode"], "stripe")


if __name__ == "__main__":
    unittest.main()
