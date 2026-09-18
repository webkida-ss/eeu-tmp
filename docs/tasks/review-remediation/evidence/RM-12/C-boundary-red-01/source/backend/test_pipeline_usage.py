import concurrent.futures
import importlib.metadata
import json
import types
import unittest
from pathlib import Path
from unittest import mock

import core.pipeline as pipeline
from core.plans import get_plan_limits
from core.usage_costs import ModelRate, UnknownModelRateError
from services.reading_support import _settlement_usage


class _WordEncoding:
    def encode(self, text):
        return text.split()


class _BoundaryEncoding(_WordEncoding):
    def encode(self, text):
        tokens = super().encode(text)
        return tokens + (["boundary-expansion"] if "\n\n" in text and text != "\n\n" else [])


class _SpecialAwareEncoding:
    def encode(self, text):
        raise ValueError("special token rejected")

    def encode_ordinary(self, text):
        return list(text)


def _response(*, model="priced-model", usage=None):
    return types.SimpleNamespace(model=model, usage=usage)


class TokenEstimatorTests(unittest.TestCase):
    def test_special_token_literals_are_treated_as_ordinary_text(self):
        with mock.patch.object(pipeline, "_token_encoding", return_value=_SpecialAwareEncoding()):
            self.assertEqual(
                pipeline.estimate_tokens("before <|endoftext|> after"),
                len("before <|endoftext|> after"),
            )

    def test_configured_encoding_is_deterministic(self):
        with (
            mock.patch.dict("os.environ", {"OPENAI_TOKEN_ENCODING": "test-encoding"}),
            mock.patch.object(
                pipeline.tiktoken, "get_encoding", return_value=_WordEncoding()
            ) as get_encoding,
        ):
            self.assertEqual(pipeline.estimate_tokens("one two three"), 3)
            self.assertEqual(pipeline.estimate_tokens("one two three"), 3)
        get_encoding.assert_called_with("test-encoding")

    def test_invalid_encoding_fails_closed(self):
        with (
            mock.patch.dict("os.environ", {"OPENAI_TOKEN_ENCODING": "not-real"}),
            mock.patch.object(pipeline.tiktoken, "get_encoding", side_effect=KeyError("not-real")),
        ):
            with self.assertRaises(pipeline.PipelineError) as raised:
                pipeline.estimate_tokens("text")
        self.assertEqual(raised.exception.status_code, 500)

    def test_tested_tiktoken_minimum_is_installed_and_declared(self):
        installed = tuple(
            int(part) for part in importlib.metadata.version("tiktoken").split(".")[:3]
        )
        self.assertGreaterEqual(installed, pipeline.MIN_TIKTOKEN_VERSION)
        requirements = Path(__file__).with_name("requirements.in").read_text()
        minimum = ".".join(str(part) for part in pipeline.MIN_TIKTOKEN_VERSION)
        self.assertIn(f"tiktoken>={minimum}", requirements)


class UsageTallyTests(unittest.TestCase):
    def setUp(self):
        self.rate = ModelRate("priced-model", 2_000_000, 3_000_000, "2026-07")

    def test_tallies_legacy_and_new_usage_fields_with_integer_cost(self):
        tally = pipeline.UsageTally()
        tally.add_response(
            _response(
                usage=types.SimpleNamespace(prompt_tokens=2, completion_tokens=3, total_tokens=5)
            )
        )
        tally.add_response(
            _response(usage=types.SimpleNamespace(input_tokens=4, output_tokens=5, total_tokens=9))
        )

        with mock.patch.object(pipeline, "load_model_rate", return_value=self.rate):
            snapshot = tally.snapshot()

        self.assertEqual(snapshot.model, "priced-model")
        self.assertEqual(snapshot.rate_card_version, "2026-07")
        self.assertEqual(snapshot.input_tokens, 6)
        self.assertEqual(snapshot.output_tokens, 8)
        self.assertEqual(snapshot.total_tokens, 14)
        self.assertEqual(snapshot.cost_micro_usd, 36)
        self.assertFalse(snapshot.missing_usage)

    def test_charges_pinned_billing_model_and_audits_provider_snapshot(self):
        tally = pipeline.UsageTally(rate=self.rate)
        tally.add_response(
            _response(
                model="priced-model-2026-07-15",
                usage=types.SimpleNamespace(input_tokens=2, output_tokens=3, total_tokens=5),
            )
        )

        snapshot = tally.snapshot()

        self.assertEqual(snapshot.model, "priced-model")
        self.assertEqual(snapshot.provider_model, "priced-model-2026-07-15")
        self.assertEqual(snapshot.cost_micro_usd, 13)

    def test_parallel_accumulation_is_thread_safe(self):
        tally = pipeline.UsageTally()
        usage = types.SimpleNamespace(input_tokens=1, output_tokens=2, total_tokens=3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: tally.add_response(_response(usage=usage)), range(100)))

        with mock.patch.object(pipeline, "load_model_rate", return_value=self.rate):
            snapshot = tally.snapshot()
        self.assertEqual(
            (snapshot.input_tokens, snapshot.output_tokens, snapshot.total_tokens), (100, 200, 300)
        )

    def test_incurred_call_uncertainty_is_sticky_across_concurrent_responses(self):
        tally = pipeline.UsageTally(rate=self.rate)
        client = mock.Mock()
        client.chat.completions.create.side_effect = TimeoutError("provider timeout")

        with self.assertRaises(pipeline.PipelineError):
            pipeline._create_chat_completion_at_dispatch_boundary(
                client,
                tally=tally,
                model="priced-model",
                messages=[],
            )

        usage = types.SimpleNamespace(input_tokens=1, output_tokens=2, total_tokens=3)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: tally.add_response(_response(usage=usage)), range(100)))

        snapshot = tally.snapshot()
        settlement = _settlement_usage(
            tally,
            types.SimpleNamespace(reserved_cost_micro_usd=13),
        )

        self.assertTrue(snapshot.incurred_call_uncertainty)
        self.assertTrue(snapshot.missing_usage)
        self.assertEqual(
            (snapshot.input_tokens, snapshot.output_tokens, snapshot.total_tokens),
            (100, 200, 300),
        )
        self.assertFalse(settlement["usage_complete"])
        self.assertEqual(settlement["actual_cost_micro_usd"], 800)

    def test_uncertain_settlement_keeps_the_reservation_floor_without_losing_tokens(self):
        tally = pipeline.UsageTally(rate=self.rate)
        tally.add_response(
            _response(
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=0, total_tokens=1)
            )
        )
        tally.mark_incurred_call_uncertainty()

        settlement = _settlement_usage(
            tally,
            types.SimpleNamespace(reserved_cost_micro_usd=13),
        )

        self.assertFalse(settlement["usage_complete"])
        self.assertEqual(
            (
                settlement["input_tokens"],
                settlement["output_tokens"],
                settlement["total_tokens"],
                settlement["actual_cost_micro_usd"],
            ),
            (1, 0, 1, 13),
        )

    def test_complete_settlement_keeps_exact_cost_below_the_reservation_floor(self):
        tally = pipeline.UsageTally(rate=self.rate)
        tally.add_response(
            _response(
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=0, total_tokens=1)
            )
        )

        settlement = _settlement_usage(
            tally,
            types.SimpleNamespace(reserved_cost_micro_usd=13),
        )

        self.assertTrue(settlement["usage_complete"])
        self.assertEqual(settlement["actual_cost_micro_usd"], 2)

    def test_rejects_inconsistent_response_models(self):
        tally = pipeline.UsageTally()
        usage = types.SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2)
        tally.add_response(_response(model="priced-model", usage=usage))
        with self.assertRaises(pipeline.PipelineError) as raised:
            tally.add_response(_response(model="other-model", usage=usage))
        self.assertEqual(raised.exception.status_code, 502)

    def test_missing_usage_is_explicit_in_snapshot(self):
        tally = pipeline.UsageTally()
        tally.add_response(_response(usage=None))
        with mock.patch.object(pipeline, "load_model_rate", return_value=self.rate):
            snapshot = tally.snapshot()
        self.assertTrue(snapshot.missing_usage)
        self.assertEqual(snapshot.total_tokens, 0)

    def test_missing_input_token_fields_marks_usage_incomplete(self):
        tally = pipeline.UsageTally()
        tally.add_response(_response(usage=types.SimpleNamespace(output_tokens=3, total_tokens=3)))
        with mock.patch.object(pipeline, "load_model_rate", return_value=self.rate):
            snapshot = tally.snapshot()
        self.assertTrue(snapshot.missing_usage)
        self.assertEqual(snapshot.output_tokens, 3)

    def test_missing_output_token_fields_marks_usage_incomplete(self):
        tally = pipeline.UsageTally()
        tally.add_response(_response(usage=types.SimpleNamespace(input_tokens=2, total_tokens=2)))
        with mock.patch.object(pipeline, "load_model_rate", return_value=self.rate):
            snapshot = tally.snapshot()
        self.assertTrue(snapshot.missing_usage)
        self.assertEqual(snapshot.input_tokens, 2)

    def test_unknown_model_pricing_fails_when_cost_snapshot_is_requested(self):
        tally = pipeline.UsageTally()
        tally.add_response(
            _response(usage=types.SimpleNamespace(input_tokens=1, output_tokens=1, total_tokens=2))
        )
        with mock.patch.object(
            pipeline, "load_model_rate", side_effect=UnknownModelRateError("unknown")
        ):
            with self.assertRaises(UnknownModelRateError):
                tally.snapshot()


class SourceCapTests(unittest.TestCase):
    def test_prepare_tokenizes_each_sentence_once_without_growing_prefixes(self):
        sentences = [f"Sentence {index}." for index in range(200)]
        content = "\n\n".join(sentences)
        calls: list[str] = []

        def count_tokens(value):
            text = str(value)
            calls.append(text)
            return len(text.split())

        with (
            mock.patch.object(
                pipeline,
                "_coarse_split_sentences",
                return_value=sentences,
            ),
            mock.patch.object(pipeline, "estimate_tokens", side_effect=count_tokens),
        ):
            prepared = pipeline._prepare_article_content(
                content,
                sentence_limit=200,
                source_token_limit=10_000,
            )

        self.assertEqual(len(prepared.sentences), 200)
        self.assertLessEqual(len(calls), len(sentences) + 3)
        self.assertFalse(
            any(value != "\n\n" and "\n\n" in value for value in calls[1:]),
            "after the full-content count, accumulated prefixes must not be re-tokenized",
        )

    def _prepare(self, content, *, sentence_limit, token_limit):
        with mock.patch.object(pipeline, "_token_encoding", return_value=_WordEncoding()):
            return pipeline._prepare_article_content(
                content,
                sentence_limit=sentence_limit,
                source_token_limit=token_limit,
            )

    def test_earlier_sentence_cap_wins(self):
        prepared = self._prepare(
            "First useful sentence has four words. Second useful sentence has four words. Third useful sentence has four words.",
            sentence_limit=2,
            token_limit=100,
        )
        self.assertEqual(prepared.sentences_detected, 3)
        self.assertEqual(len(prepared.sentences), 2)
        self.assertEqual(prepared.source_tokens_detected, 18)
        self.assertEqual(prepared.source_tokens_analyzed, 12)
        self.assertEqual(prepared.source_token_limit, 100)

    def test_earlier_source_token_cap_wins_at_sentence_boundary(self):
        prepared = self._prepare(
            "First useful sentence has four words. Second useful sentence has four words. Third useful sentence has four words.",
            sentence_limit=3,
            token_limit=6,
        )
        self.assertEqual(prepared.sentences, ("First useful sentence has four words.",))
        self.assertLessEqual(prepared.source_tokens_analyzed, 6)

    def test_oversized_sentence_is_omitted_and_never_exceeds_limit(self):
        with self.assertRaises(pipeline.PipelineError) as raised:
            self._prepare(
                "Unicode " + "非常に長い " * 30 + "sentence.",
                sentence_limit=10,
                token_limit=5,
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_long_unicode_article_reports_all_detected_sentences(self):
        content = " ".join(
            f"Unicode sentence {index} includes café 東京 context." for index in range(250)
        )
        prepared = self._prepare(content, sentence_limit=230, token_limit=100_000)
        self.assertEqual(prepared.sentences_detected, 250)
        self.assertEqual(len(prepared.sentences), 230)

    def test_final_serialized_content_never_exceeds_source_limit(self):
        with mock.patch.object(pipeline, "_token_encoding", return_value=_BoundaryEncoding()):
            prepared = pipeline._prepare_article_content(
                "First useful sentence here. Second useful sentence here.",
                sentence_limit=2,
                source_token_limit=8,
            )
        self.assertLessEqual(prepared.source_tokens_analyzed, 8)


class PreflightTests(unittest.TestCase):
    def test_shadow_mode_without_pricing_continues_and_reports_unpriced_usage(self):
        response = types.SimpleNamespace(
            model="test-model",
            usage=types.SimpleNamespace(input_tokens=4, output_tokens=2, total_tokens=6),
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="reply"))],
        )
        client = mock.Mock()
        client.chat.completions.create.return_value = response
        tally = pipeline.UsageTally()
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "USAGE_RESERVATION_ENABLED": "false",
                    "OPENAI_MODEL": "test-model",
                    "OPENAI_RATE_CARD_VERSION": "",
                    "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "",
                    "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "",
                },
                clear=True,
            ),
            mock.patch.object(pipeline, "_client", return_value=client),
            self.assertLogs("untangle.backend", level="INFO") as captured,
        ):
            reply = pipeline._call_openai_chat(
                [{"role": "user", "content": "hello"}],
                max_completion_tokens=10,
                tally=tally,
            )

        self.assertEqual(reply, "reply")
        self.assertTrue(tally.any_dispatch_attempted)
        event = next(
            json.loads(line.split(":", 2)[-1].strip())
            for line in captured.output
            if "usage_shadow_observed" in line
        )
        self.assertFalse(event["pricing_available"])
        self.assertNotIn("cost_micro_usd", event)

    def test_enforcement_without_pricing_fails_before_provider(self):
        client = mock.Mock()
        with (
            mock.patch.dict(
                "os.environ",
                {
                    "USAGE_RESERVATION_ENABLED": "true",
                    "OPENAI_MODEL": "test-model",
                    "OPENAI_RATE_CARD_VERSION": "",
                    "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "",
                    "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "",
                },
                clear=True,
            ),
            mock.patch.object(pipeline, "_client", return_value=client),
            self.assertRaises(UnknownModelRateError),
        ):
            pipeline._call_openai_chat(
                [{"role": "user", "content": "hello"}],
                max_completion_tokens=10,
                tally=pipeline.UsageTally(),
            )
        client.chat.completions.create.assert_not_called()

    def test_split_agent_validates_client_before_dispatch_boundary(self):
        tally = pipeline.UsageTally()
        dispatch_callback = mock.Mock()
        tally.set_dispatch_callback(dispatch_callback)
        with (
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "test"),
            ),
            mock.patch.object(
                pipeline,
                "_client",
                side_effect=RuntimeError("client construction failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "client construction failed"):
                pipeline._run_sentence_split_agent(
                    "A complete article sentence.",
                    page_title="Title",
                    max_sentences=5,
                    tally=tally,
                )

        dispatch_callback.assert_not_called()
        self.assertFalse(tally.any_dispatch_attempted)
        self.assertFalse(tally.snapshot().incurred_call_uncertainty)

    def test_dispatch_marker_failure_does_not_mark_incurred_call_uncertainty(self):
        tally = pipeline.UsageTally(
            rate=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "test")
        )
        tally.set_dispatch_callback(mock.Mock(side_effect=RuntimeError("marker failed")))
        client = mock.Mock()

        with self.assertRaisesRegex(RuntimeError, "marker failed"):
            pipeline._create_chat_completion_at_dispatch_boundary(
                client,
                tally=tally,
                model=pipeline.OPENAI_MODEL,
                messages=[],
            )

        client.chat.completions.create.assert_not_called()
        self.assertFalse(tally.any_dispatch_attempted)
        self.assertFalse(tally.snapshot().incurred_call_uncertainty)

    def test_split_agent_local_post_boundary_failure_is_classified_dispatched(self):
        tally = pipeline.UsageTally()
        tool_call = types.SimpleNamespace(
            id="call-1",
            function=types.SimpleNamespace(
                name="submit_sentence_split",
                arguments="{invalid-json",
            ),
        )
        response = types.SimpleNamespace(
            model=pipeline.OPENAI_MODEL,
            usage=None,
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(content=None, tool_calls=[tool_call])
                )
            ],
        )
        client = mock.Mock()
        client.chat.completions.create.return_value = response
        with (
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "test"),
            ),
        ):
            with self.assertRaises(pipeline.PipelineError) as raised:
                pipeline._run_sentence_split_agent(
                    "A complete article sentence.",
                    page_title="Title",
                    max_sentences=5,
                    tally=tally,
                )

        self.assertTrue(raised.exception.dispatch_attempted)
        self.assertTrue(tally.any_dispatch_attempted)
        client.chat.completions.create.assert_called_once()

    def test_billing_rate_is_pinned_before_provider_dispatch(self):
        rate = ModelRate(pipeline.OPENAI_MODEL, 2, 3, "test")
        tally = pipeline.UsageTally()
        client = mock.Mock()
        client.chat.completions.create.side_effect = RuntimeError("offline")
        with (
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(pipeline, "load_model_rate", return_value=rate),
        ):
            with self.assertRaises(pipeline.PipelineError):
                pipeline._call_openai_json(
                    "safe prompt",
                    max_completion_tokens=3,
                    tally=tally,
                )

        with mock.patch.object(
            pipeline,
            "load_model_rate",
            side_effect=AssertionError("must use pinned rate"),
        ):
            self.assertEqual(tally.snapshot().model, pipeline.OPENAI_MODEL)

    def test_tool_schema_overhead_is_included_near_boundary(self):
        tools = [{"type": "function", "function": {"name": "split"}}]
        with (
            mock.patch.object(pipeline, "estimate_tokens", side_effect=[8, 3]),
            mock.patch.dict(
                "os.environ",
                {"OPENAI_MAX_INPUT_TOKENS_PER_CALL": "20"},
            ),
        ):
            with self.assertRaises(pipeline.PipelineError):
                pipeline._preflight_openai_input(
                    [{"role": "user", "content": "prompt"}],
                    max_output_tokens=5,
                    tools=tools,
                )

    def test_unknown_model_rate_rejects_before_provider_dispatch(self):
        client = mock.Mock()
        with (
            mock.patch.dict(
                "os.environ",
                {"USAGE_RESERVATION_ENABLED": "true"},
            ),
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                side_effect=UnknownModelRateError("unknown"),
            ),
        ):
            with self.assertRaises(UnknownModelRateError):
                pipeline._call_openai_json("safe prompt", max_completion_tokens=3)
        client.chat.completions.create.assert_not_called()

    def test_preflight_rejects_before_provider_dispatch(self):
        client = mock.Mock()
        tally = pipeline.UsageTally()
        with (
            mock.patch.object(pipeline, "_client", return_value=client),
            mock.patch.object(pipeline, "estimate_tokens", return_value=10),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(pipeline.OPENAI_MODEL, 1, 1, "test"),
            ),
            mock.patch.dict("os.environ", {"OPENAI_MAX_INPUT_TOKENS_PER_CALL": "12"}),
        ):
            with self.assertRaises(pipeline.PipelineError) as raised:
                pipeline._call_openai_json(
                    "large prompt",
                    max_completion_tokens=3,
                    tally=tally,
                )
        self.assertEqual(raised.exception.status_code, pipeline.INPUT_TOKEN_LIMIT_STATUS_CODE)
        client.chat.completions.create.assert_not_called()
        self.assertFalse(tally.snapshot().incurred_call_uncertainty)

    def test_batch_envelope_accepts_exact_limit(self):
        with (
            mock.patch.object(pipeline, "estimate_tokens", return_value=4),
            mock.patch.dict("os.environ", {"OPENAI_MAX_INPUT_TOKENS_PER_CALL": "15"}),
        ):
            pipeline._preflight_openai_input(
                [{"role": "user", "content": "prompt"}], max_output_tokens=3
            )

    def test_input_envelope_rejects_impractical_maximum(self):
        with mock.patch.dict(
            "os.environ",
            {"OPENAI_MAX_INPUT_TOKENS_PER_CALL": str(pipeline.MAX_OPENAI_INPUT_TOKEN_ENVELOPE + 1)},
        ):
            with self.assertRaises(pipeline.PipelineError):
                pipeline._max_input_tokens_per_call()


class CostEstimateTests(unittest.TestCase):
    def test_basic_article_estimate_fits_default_monthly_ceiling(self):
        prepared = pipeline.PreparedArticle(
            content="\n\n".join(
                f"Sentence {index} contains useful learner content." for index in range(50)
            ),
            sentences=tuple(
                f"Sentence {index} contains useful learner content." for index in range(50)
            ),
            sentences_detected=50,
            sentence_limit=50,
            source_tokens_detected=600,
            source_tokens_analyzed=600,
            source_token_limit=12_000,
        )
        with (
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(
                    pipeline.OPENAI_MODEL,
                    10_000,
                    40_000,
                    "test",
                ),
            ),
            mock.patch.object(
                pipeline, "estimate_tokens", side_effect=lambda value: len(str(value).split())
            ),
        ):
            estimate = pipeline.estimate_article_cost_micro_usd(
                prepared,
                page_title="Title",
                vocabulary_coverage_percent=8,
            )

        self.assertGreater(estimate, 0)
        self.assertLess(
            estimate,
            get_plan_limits("basic").cost_micro_usd_per_month,
        )

    def test_article_reservation_covers_every_configured_runtime_turn_at_max_output(self):
        prepared = pipeline.PreparedArticle(
            content="A useful sentence.",
            sentences=("A useful sentence.",),
            sentences_detected=1,
            sentence_limit=1,
            source_tokens_detected=4,
            source_tokens_analyzed=4,
            source_token_limit=12_000,
        )
        output_limits: list[int] = []

        def capture_cost(input_tokens, output_tokens, rate):
            output_limits.append(output_tokens)
            return input_tokens + output_tokens

        with (
            mock.patch.dict("os.environ", {"MAX_SENTENCE_SPLIT_AGENT_TURNS": "8"}),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(pipeline.OPENAI_MODEL, 10, 20, "test"),
            ),
            mock.patch.object(pipeline, "estimate_tokens", return_value=100),
            mock.patch.object(
                pipeline,
                "estimate_cost_micro_usd",
                side_effect=capture_cost,
            ),
        ):
            pipeline.estimate_article_cost_micro_usd(
                prepared,
                page_title="Title",
                vocabulary_coverage_percent=8,
            )

        self.assertEqual(output_limits.count(4000), 9)
        self.assertEqual(output_limits.count(6000), 1)

    def test_article_reservation_covers_ai_split_sentence_expansion_batches(self):
        prepared = pipeline.PreparedArticle(
            content="One coarse sentence that the AI may split further.",
            sentences=("One coarse sentence that the AI may split further.",),
            sentences_detected=1,
            sentence_limit=50,
            source_tokens_detected=10,
            source_tokens_analyzed=10,
            source_token_limit=12_000,
        )
        output_limits: list[int] = []

        def capture_cost(input_tokens, output_tokens, rate):
            output_limits.append(output_tokens)
            return input_tokens + output_tokens

        with (
            mock.patch.dict("os.environ", {"MAX_SENTENCE_SPLIT_AGENT_TURNS": "2"}),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(pipeline.OPENAI_MODEL, 10, 20, "test"),
            ),
            mock.patch.object(pipeline, "estimate_tokens", return_value=100),
            mock.patch.object(
                pipeline,
                "estimate_cost_micro_usd",
                side_effect=capture_cost,
            ),
        ):
            pipeline.estimate_article_cost_micro_usd(
                prepared,
                page_title="Title",
                vocabulary_coverage_percent=8,
            )

        expected_batches = (
            prepared.sentence_limit + pipeline.SENTENCE_BATCH_SIZE - 1
        ) // pipeline.SENTENCE_BATCH_SIZE
        self.assertEqual(output_limits.count(6000), expected_batches)

    def test_plan_sentence_limit_above_global_default_drives_analysis_reservation(self):
        prepared = pipeline.PreparedArticle(
            content="Bounded article content.",
            sentences=("Bounded article content.",),
            sentences_detected=1,
            sentence_limit=400,
            source_tokens_detected=4,
            source_tokens_analyzed=4,
            source_token_limit=96_000,
        )
        output_limits: list[int] = []

        def capture_cost(input_tokens, output_tokens, rate):
            output_limits.append(output_tokens)
            return input_tokens + output_tokens

        with (
            mock.patch.object(pipeline, "MAX_SENTENCES", 200),
            mock.patch.dict("os.environ", {"MAX_SENTENCE_SPLIT_AGENT_TURNS": "2"}),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate(pipeline.OPENAI_MODEL, 10, 20, "test"),
            ),
            mock.patch.object(pipeline, "estimate_tokens", return_value=100),
            mock.patch.object(
                pipeline,
                "estimate_cost_micro_usd",
                side_effect=capture_cost,
            ),
        ):
            pipeline.estimate_article_cost_micro_usd(
                prepared,
                page_title="Title",
                vocabulary_coverage_percent=8,
            )

        expected_batches = (400 + pipeline.SENTENCE_BATCH_SIZE - 1) // pipeline.SENTENCE_BATCH_SIZE
        self.assertEqual(output_limits.count(6000), expected_batches)

    def test_agent_turn_limit_rejects_impractical_maximum(self):
        with mock.patch.dict(
            "os.environ",
            {
                "MAX_SENTENCE_SPLIT_AGENT_TURNS": str(
                    pipeline.MAX_CONFIGURED_SENTENCE_SPLIT_AGENT_TURNS + 1
                )
            },
        ):
            with self.assertRaises(pipeline.PipelineError):
                pipeline._configured_sentence_split_agent_turns()

    def test_agent_turn_limit_uses_configuration(self):
        with mock.patch.dict("os.environ", {"MAX_SENTENCE_SPLIT_AGENT_TURNS": "3"}):
            self.assertEqual(pipeline._configured_sentence_split_agent_turns(), 3)

    def test_call_estimate_includes_input_and_max_output(self):
        rate = ModelRate("priced-model", 2_000_000, 3_000_000, "2026-07")
        with (
            mock.patch.object(pipeline, "estimate_tokens", return_value=4),
            mock.patch.object(pipeline, "load_model_rate", return_value=rate),
        ):
            cost = pipeline.estimate_openai_call_cost_micro_usd(
                [{"role": "user", "content": "prompt"}], max_output_tokens=5
            )
        self.assertEqual(cost, 37)

    def test_analysis_estimate_counts_each_known_batch(self):
        rate = ModelRate("priced-model", 1_000_000, 1_000_000, "2026-07")
        sentences = [f"Sentence {index} has useful content." for index in range(25)]
        with (
            mock.patch.object(pipeline, "estimate_tokens", return_value=10),
            mock.patch.object(pipeline, "load_model_rate", return_value=rate),
        ):
            cost = pipeline.estimate_analysis_cost_micro_usd(
                sentences,
                page_title="Title",
                vocabulary_coverage_percent=8.0,
            )
        self.assertEqual(cost, 3 * (10 + 7 + 6000))

    def test_article_estimate_applies_bounded_fallback_and_safety_margin(self):
        prepared = pipeline.PreparedArticle(
            content="First article chunk.\n\nSecond article chunk.",
            sentences=tuple(f"Sentence {index} has useful content." for index in range(25)),
            sentences_detected=25,
            sentence_limit=25,
            source_tokens_detected=100,
            source_tokens_analyzed=80,
            source_token_limit=100,
        )
        with (
            mock.patch.object(
                pipeline, "_group_paragraph_chunks", return_value=["chunk one", "chunk two"]
            ),
            mock.patch.object(
                pipeline,
                "load_model_rate",
                return_value=ModelRate("priced-model", 1_000_000, 1_000_000, "2026-07"),
            ),
            mock.patch.object(pipeline, "estimate_tokens", return_value=100),
            mock.patch.dict("os.environ", {"MAX_SENTENCE_SPLIT_AGENT_TURNS": "8"}),
        ):
            cost = pipeline.estimate_article_cost_micro_usd(
                prepared,
                page_title="Title",
                vocabulary_coverage_percent=8.0,
            )
        self.assertEqual(pipeline.ARTICLE_ESTIMATE_SAFETY_BPS, 12_500)
        self.assertGreater(cost, 5 * (100 + 256))


if __name__ == "__main__":
    unittest.main()
