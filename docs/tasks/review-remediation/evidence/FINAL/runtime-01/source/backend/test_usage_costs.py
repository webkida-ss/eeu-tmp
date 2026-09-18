import unittest
from unittest.mock import patch

import core.usage_costs as usage_costs
from core.usage_costs import (
    ModelRate,
    UnknownModelRateError,
    calculate_cost_micro_usd,
    estimate_cost_micro_usd,
    load_model_rate,
)


class UsageCostCalculationTests(unittest.TestCase):
    def setUp(self):
        self.rate = ModelRate(
            model="test-model",
            input_micro_usd_per_million=2_000_000,
            output_micro_usd_per_million=3_000_000,
            version="2026-07-17",
        )

    def test_input_and_output_components_round_up_independently(self):
        fractional_rate = ModelRate(
            model="test-model",
            input_micro_usd_per_million=1,
            output_micro_usd_per_million=1,
            version="2026-07-17",
        )
        self.assertEqual(calculate_cost_micro_usd(1, 1, fractional_rate), 2)

    def test_cost_uses_integer_micro_usd_arithmetic(self):
        self.assertEqual(calculate_cost_micro_usd(3, 4, self.rate), 18)

    def test_estimate_uses_maximum_output_tokens(self):
        self.assertEqual(estimate_cost_micro_usd(3, 7, self.rate), 27)

    def test_cost_rejects_values_outside_dynamodb_integer_range(self):
        huge_rate = ModelRate(
            model="test-model",
            input_micro_usd_per_million=usage_costs.DYNAMODB_MAX_INTEGER,
            output_micro_usd_per_million=1,
            version="2026-07-17",
        )
        with self.assertRaises(OverflowError):
            calculate_cost_micro_usd(usage_costs.DYNAMODB_MAX_INTEGER, 0, huge_rate)


class ModelRateLoadingTests(unittest.TestCase):
    def test_loads_configured_model_rate_and_version(self):
        env = {
            "OPENAI_MODEL": "configured-model",
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "11",
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "22",
            "OPENAI_RATE_CARD_VERSION": "rates-v1",
        }
        with patch.dict("os.environ", env, clear=True):
            rate = load_model_rate("configured-model")

        self.assertEqual(
            rate,
            ModelRate(
                model="configured-model",
                input_micro_usd_per_million=11,
                output_micro_usd_per_million=22,
                version="rates-v1",
            ),
        )

    def test_unknown_model_fails_closed(self):
        env = {
            "OPENAI_MODEL": "configured-model",
            "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "11",
            "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "22",
            "OPENAI_RATE_CARD_VERSION": "rates-v1",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(UnknownModelRateError):
                load_model_rate("unknown-model")

    def test_missing_pricing_fails_closed(self):
        with patch.dict("os.environ", {"OPENAI_MODEL": "configured-model"}, clear=True):
            with self.assertRaises(UnknownModelRateError):
                load_model_rate()


if __name__ == "__main__":
    unittest.main()
