# Preload Performance

Design notes for the page-preload latency work (2026-07). Read this before
changing the preload pipeline or adding job queueing.

## Pipeline and where time goes

```
extract (local, ~0s)
  → split    (LLM: article chunks → learning-unit sentences)
  → analyze  (LLM: batches of 12 sentences → translation/grammar/vocabulary)
  → study_items (local parse + scoring, ~0s)
```

Only `split` and `analyze` call the LLM; they are the only phases worth
optimizing. Every preload logs per-phase timings
(`preload timing url=... split=... analyze=... total=...`) plus per-batch and
per-chunk durations — measure before optimizing further.

## Measured results (same 54-sentence article, gpt-5.4-mini)

| Phase   | Sequential (est.) | + Parallelization | + One-shot split & slim prompts |
|---------|-------------------|-------------------|--------------------------------|
| split   | ~7s               | 7.0s              | 4.1s                           |
| analyze | ~54s              | 12.3s             | 10.5s                          |
| total   | ~61s              | 19.3s             | **14.7s (~4.2x)**              |

## Implemented measures

1. **Parallel analysis batches.** Batches are independent — results are keyed
   by sentence index and only the offset-0 batch carries summary/topics — so
   they run concurrently via `ThreadPoolExecutor`. Wall time for the analyze
   phase ≈ the slowest single batch (while batch count ≤ semaphore limit).
   Split chunks run concurrently the same way; results are merged in original
   chunk order so dedup and the `MAX_SENTENCES` cap behave exactly like the
   old sequential loop.

2. **Process-wide LLM concurrency cap.** Every OpenAI call (analysis, split,
   chat, selection) acquires `_openai_call_slots`, a shared semaphore sized by
   `OPENAI_MAX_CONCURRENT_CALLS` (default 5). This keeps concurrent preloads
   inside rate limits and is deliberately queue-compatible: a future job queue
   goes IN FRONT of the pipeline (admission control), while this semaphore
   stays underneath as the rate governor. Do not remove it when adding a
   queue.

3. **One-shot sentence split with agent fallback.** The old splitter was an
   agent loop (up to 8 sequential LLM turns fetching the mechanical split via
   tools). The mechanical draft was always computed locally, so it is now
   embedded directly in a single JSON-mode prompt ("here is the chunk and a
   draft split; return the corrected final list"). Output is validated by
   `_finalize_sentence_split` (every unit must be a verbatim substring of the
   chunk); if fewer than a third of the expected units survive, the code
   falls back to the original agent automatically. Worst case = old behavior
   plus one extra call; measured quality was identical to the agent (53/53
   body sentences matched).

4. **No dead fields in analysis output.** The analysis schema used to carry
   `nuance` / `examples` / `study_tip` with prompt rules saying "always return
   empty" — the model paid input tokens for the rules and output tokens
   emitting empties for every sentence. They are gone from the prompts; stored
   records and `AnalyzeResponse` keep the fields with empty defaults, so the
   extension needed no changes. If a new per-sentence field is ever added,
   add it to the prompt only when it is actually consumed.

## Deferred: progressive ready

"Save the record after the first analyzed batch and let the user start
reading while the rest continues in the background" was planned but shelved:
after parallelization all batches finish nearly simultaneously, so on a
typical (~50-sentence) article it would only cut ~14.7s to ~10s while adding
a background job + polling + partial-render state machine.

Re-evaluate when either holds:
- Articles regularly exceed ~5 batches (~60+ sentences): batches then queue
  behind the semaphore in waves, and first-batch-early becomes valuable again.
- A job queue is introduced anyway (multi-user), which provides the async job
  seam progressive ready needs.

## Queueing (implemented)

The async preload pipeline now exists (it was the seam progressive-ready
needed, and it removes the hard 30-second ceiling below). `POST /pages/preload`
does only the fast, OpenAI-free work — extract the article text, save a
`status: "processing"` record, enqueue a job — and returns HTTP 202
immediately. The slow split + analyze runs off the request path, and the
client polls `GET /pages/preload` until the record is `ready` or `failed`.

The runner is chosen by DI (`JOB_RUNNER`), mirroring the auth/billing provider
pattern:
- `inline` (local dev): runs the job on a daemon background thread in the same
  process.
- `sqs` (AWS): the API sends `{user_id, page_url}` to SQS; a separate worker
  Lambda (`worker_handler.handler`, timeout 600s+) consumes it and runs the
  job. Visibility timeout is 6x the worker timeout; a DLQ catches messages
  that fail 3 times. See `infra/modules/reading-assistant-api`.

Parallelization and queueing stay orthogonal: the queue controls how many
preload JOBS run; the `_openai_call_slots` semaphore still controls total
in-flight LLM CALLS underneath. Split/analyze live in the framework-free
pipeline, so the worker calls the exact same code paths as the old
synchronous handler. Usage is metered in the worker (`record_article` after a
successful job), so a failed analysis never burns quota.

The 30-second API Gateway integration cap (see below / infra/README.md) no
longer constrains the analysis, because the request returns before it starts.
