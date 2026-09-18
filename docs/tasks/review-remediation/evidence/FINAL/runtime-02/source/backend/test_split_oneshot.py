import json
import types
import unittest
from unittest import mock

import core.pipeline as main
from core.pipeline import _split_article_chunk_with_ai

_SENTENCES = [
    "Many large cities have started to rethink how their streets are used.",
    "Planners argue that roads designed only for cars waste valuable public space.",
    "Some neighborhoods have replaced parking lots with small parks and cafes.",
    "Residents who once drove everywhere now walk or cycle for short trips.",
    "Local shops report that foot traffic has increased since the changes began.",
    "City officials say careful design can balance these competing needs.",
]
_CONTENT = "\n\n".join(_SENTENCES)


def _fake_client_returning(payload: dict):
    def create(**kwargs):
        message = types.SimpleNamespace(content=json.dumps(payload))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))


class OneShotSplitTests(unittest.TestCase):
    def setUp(self):
        self.rate_env = mock.patch.dict(
            "os.environ",
            {
                "OPENAI_MODEL": main.OPENAI_MODEL,
                "OPENAI_RATE_CARD_VERSION": "test",
                "OPENAI_MODEL_INPUT_MICRO_USD_PER_MILLION": "1",
                "OPENAI_MODEL_OUTPUT_MICRO_USD_PER_MILLION": "1",
            },
        )
        self.rate_env.start()
        self.addCleanup(self.rate_env.stop)

    def test_one_shot_result_is_used_without_the_agent(self):
        client = _fake_client_returning({"sentences": _SENTENCES})
        agent = mock.Mock(side_effect=AssertionError("agent must not run on the fast path"))

        with (
            mock.patch.object(main, "_client", lambda: client),
            mock.patch.object(main, "_run_sentence_split_agent", agent),
        ):
            result = _split_article_chunk_with_ai(_CONTENT, page_title="T", max_sentences=50)

        self.assertEqual(result, _SENTENCES)
        agent.assert_not_called()

    def test_hallucinated_output_falls_back_to_the_agent(self):
        # None of these are substrings of the chunk, so the finalizer drops
        # them all and the fallback threshold trips.
        client = _fake_client_returning(
            {"sentences": ["A completely invented sentence that is not in the article at all."]}
        )
        agent = mock.Mock(return_value=_SENTENCES)

        with (
            mock.patch.object(main, "_client", lambda: client),
            mock.patch.object(main, "_run_sentence_split_agent", agent),
        ):
            result = _split_article_chunk_with_ai(_CONTENT, page_title=None, max_sentences=50)

        self.assertEqual(result, _SENTENCES)
        agent.assert_called_once()

    def test_non_list_payload_falls_back_to_the_agent(self):
        client = _fake_client_returning({"sentences": "not a list"})
        agent = mock.Mock(return_value=_SENTENCES)

        with (
            mock.patch.object(main, "_client", lambda: client),
            mock.patch.object(main, "_run_sentence_split_agent", agent),
        ):
            result = _split_article_chunk_with_ai(_CONTENT, page_title=None, max_sentences=50)

        self.assertEqual(result, _SENTENCES)
        agent.assert_called_once()

    def test_api_failure_falls_back_to_the_agent(self):
        def create(**kwargs):
            raise RuntimeError("api down")

        client = types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create))
        )
        agent = mock.Mock(return_value=_SENTENCES)

        with (
            mock.patch.object(main, "_client", lambda: client),
            mock.patch.object(main, "_run_sentence_split_agent", agent),
        ):
            result = _split_article_chunk_with_ai(_CONTENT, page_title=None, max_sentences=50)

        self.assertEqual(result, _SENTENCES)
        agent.assert_called_once()


if __name__ == "__main__":
    unittest.main()
