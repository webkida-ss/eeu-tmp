"""Regression coverage for explicit sentence allowances inside pipeline splitting."""

from __future__ import annotations

import json
import types
import unittest
from unittest import mock

import core.pipeline as pipeline


def _sentences() -> list[str]:
    return [
        f"Unit {index:03d} carries a unique study point."
        for index in range(250)
    ]


_SENTENCES = _sentences()
_CONTENT = "\n\n".join(_SENTENCES)


def _json_response(payload: dict) -> object:
    message = types.SimpleNamespace(content=json.dumps(payload), tool_calls=None)
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


def _tool_response(name: str, arguments: dict, *, call_id: str) -> object:
    tool_call = types.SimpleNamespace(
        id=call_id,
        type="function",
        function=types.SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )
    message = types.SimpleNamespace(content=None, tool_calls=[tool_call])
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])


class _SequencedClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(create=self.create),
        )

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("The provider stub received an unexpected extra call.")
        return self._responses.pop(0)


class SentenceAllowanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._rate_environment = mock.patch.dict(
            "os.environ",
            {
                "OPENAI_MODEL": pipeline.OPENAI_MODEL,
                "OPENAI_RATE_CARD_VERSION": "sentence-allowance-test",
                "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
            },
        )
        self._rate_environment.start()
        self.addCleanup(self._rate_environment.stop)

    def test_max_allowance_keeps_250_unique_verbatim_one_shot_sentences(self) -> None:
        client = _SequencedClient([_json_response({"sentences": _SENTENCES + [_SENTENCES[0]]})])

        with mock.patch.object(pipeline, "_client", lambda: client):
            result = pipeline._split_sentences(_CONTENT, page_title="Allowance", max_sentences=300)

        self.assertLess(len(_CONTENT), pipeline.SENTENCE_SPLIT_SINGLE_CALL_MAX_CHARS)
        self.assertEqual(result, _SENTENCES)
        self.assertEqual(len(set(result)), 250)
        self.assertTrue(all(sentence in _CONTENT for sentence in result))
        self.assertEqual(len(client.calls), 1)

    def test_max_allowance_keeps_250_sentences_through_agent_tool_fallback(self) -> None:
        client = _SequencedClient(
            [
                _json_response({"sentences": []}),
                _tool_response("get_coarse_sentence_split", {}, call_id="coarse"),
                _tool_response(
                    "submit_sentence_split",
                    {"sentences": _SENTENCES + [_SENTENCES[0]]},
                    call_id="submit",
                ),
            ]
        )

        with mock.patch.object(pipeline, "_client", lambda: client):
            result = pipeline._split_sentences(_CONTENT, page_title="Allowance", max_sentences=300)

        self.assertEqual(result, _SENTENCES)
        self.assertEqual(len(set(result)), 250)
        self.assertTrue(all(sentence in _CONTENT for sentence in result))
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[1]["tools"], pipeline.SENTENCE_SPLIT_TOOLS)
        self.assertEqual(client.calls[2]["tools"], pipeline.SENTENCE_SPLIT_TOOLS)

    def test_max_allowance_keeps_250_sentences_through_mechanical_fallback(self) -> None:
        with mock.patch.object(
            pipeline,
            "_client",
            side_effect=RuntimeError("provider unavailable"),
        ):
            result = pipeline._split_sentences(_CONTENT, page_title="Allowance", max_sentences=300)

        self.assertEqual(result, _SENTENCES)
        self.assertEqual(len(set(result)), 250)
        self.assertTrue(all(sentence in _CONTENT for sentence in result))

    def test_basic_pro_and_unmetered_limits_remain_bounded(self) -> None:
        for allowance in (50, 150):
            with self.subTest(allowance=allowance):
                client = _SequencedClient([_json_response({"sentences": _SENTENCES})])
                with mock.patch.object(pipeline, "_client", lambda: client):
                    result = pipeline._split_sentences(
                        _CONTENT,
                        page_title="Allowance",
                        max_sentences=allowance,
                    )
                self.assertEqual(result, _SENTENCES[:allowance])

        client = _SequencedClient([_json_response({"sentences": _SENTENCES})])
        with mock.patch.object(pipeline, "_client", lambda: client):
            default_result = pipeline._split_sentences(_CONTENT, page_title="Allowance")
        self.assertEqual(default_result, _SENTENCES[: pipeline.MAX_SENTENCES])


if __name__ == "__main__":
    unittest.main()
