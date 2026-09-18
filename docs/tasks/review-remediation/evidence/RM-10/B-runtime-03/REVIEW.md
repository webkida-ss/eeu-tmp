# RM-10B independent correction review

Astra verified all seven source hashes and increment hash. Prior sequential
shadow identity and cleanup findings are closed, but three medium cases remain:

- Concurrent same-ID shadow creation between ID lookup and page lookup can
  return a different-payload winner without validating the actual candidate.
- A released reservation with an abandoned running preload returns before
  expired-lease reclaim, leaving its private filesystem content indefinitely.
- Superseded cleanup uses a stale preclaim processing observation, allowing a
  caller to reclaim a competitor's expired dispatched lease and release its cost.

Parent assigned production corrections and bounded interleaving regressions.
Actual claim state or durable execution recovery must authorize release; a caller
snapshot is insufficient. Runtime and source acceptance are not granted.
