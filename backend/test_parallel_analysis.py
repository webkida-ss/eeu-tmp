import json
import re
import threading
import time
import types
import unittest
from unittest import mock

import core.pipeline as main
from core.pipeline import SENTENCE_BATCH_SIZE, _analyze_sentences

_PROMPT_INDEX_RE = re.compile(r'^(\d+)\. "', re.MULTILINE)


class _ConcurrencyTracker:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def enter(self):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def exit(self):
        with self.lock:
            self.active -= 1


def _fake_openai_client(tracker: _ConcurrencyTracker, call_delay: float = 0.15):
    """Stands in for the OpenAI client: records call concurrency and answers
    each analysis batch with translations derived from the numbered sentences
    in its prompt."""

    def create(**kwargs):
        tracker.enter()
        try:
            time.sleep(call_delay)
            prompt = kwargs["messages"][-1]["content"]
            indexes = [int(match) for match in _PROMPT_INDEX_RE.findall(prompt)]
            payload = {
                "summary": "article summary" if 0 in indexes else "",
                "topics": ["topic"] if 0 in indexes else [],
                "sentences": [
                    {
                        "index": index,
                        "translation": f"translation-{index}",
                        "grammar": f"grammar-{index}",
                        "nuance": "",
                        "vocabulary": [],
                        "examples": [],
                        "study_tip": "",
                    }
                    for index in indexes
                ],
            }
            message = types.SimpleNamespace(content=json.dumps(payload))
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])
        finally:
            tracker.exit()

    completions = types.SimpleNamespace(create=create)
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))


class ParallelAnalysisTests(unittest.TestCase):
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

    def _run(self, sentence_count: int, semaphore_limit: int | None = None):
        sentences = [f"Sentence number {index} for analysis." for index in range(sentence_count)]
        tracker = _ConcurrencyTracker()
        client = _fake_openai_client(tracker)

        patches = [mock.patch.object(main, "_client", lambda: client)]
        if semaphore_limit is not None:
            patches.append(
                mock.patch.object(
                    main, "_openai_call_slots", threading.BoundedSemaphore(semaphore_limit)
                )
            )

        with patches[0]:
            if semaphore_limit is not None:
                with patches[1]:
                    result = _analyze_sentences(
                        sentences,
                        page_title="Title",
                        vocabulary_coverage_percent=8.0,
                    )
            else:
                result = _analyze_sentences(
                    sentences,
                    page_title="Title",
                    vocabulary_coverage_percent=8.0,
                )
        return result, tracker

    def test_batches_run_in_parallel_and_results_stay_correct(self):
        sentence_count = SENTENCE_BATCH_SIZE * 3
        (summary, topics, indexed), tracker = self._run(sentence_count)

        # Correctness: every sentence got its own analysis, in order.
        self.assertEqual(len(indexed), sentence_count)
        for index, entry in enumerate(indexed):
            self.assertEqual(entry["index"], index)
            self.assertEqual(entry["analysis"]["translation"], f"translation-{index}")

        # summary/topics come from the offset-0 batch regardless of
        # completion order.
        self.assertEqual(summary, "article summary")
        self.assertEqual(topics, ["topic"])

        # Parallelism: with 3 independent batches and the default limit (5),
        # more than one call must have been in flight at once.
        self.assertGreaterEqual(tracker.peak, 2)

    def test_shared_semaphore_caps_concurrency(self):
        sentence_count = SENTENCE_BATCH_SIZE * 4
        (_, _, indexed), tracker = self._run(sentence_count, semaphore_limit=1)

        self.assertEqual(len(indexed), sentence_count)
        self.assertEqual(tracker.peak, 1)


if __name__ == "__main__":
    unittest.main()
