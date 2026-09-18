# RM-09A follow-up correction checkpoint

Base 3c4fae5d2c03e6592ebd1f51debf5c798294a476. Original Terra implementer
completed the five findings in A-source-02/REVIEW.md and released ownership.
Nine full frozen files and an incremental diff preserve the exact source state.

Corrections: Dynamo aliases are conditional and the fake rejects unused names;
saved price crosses the provider boundary; adopted sessions retain original
provider operation/session identity for terminal reconciliation; expired sessions
with attached subscriptions require fetched terminal state; post-retention tests
advance mocked time and explicitly control discovery instead of stale upserts.

Focused regressions include fresh/legacy/remapped customer indexes, SDK request
arguments across price drift, adopted terminal recovery/missing evidence, attached
active/unknown subscriptions, and retention timing. B/C remain untouched.

Parent and implementer git diff --check passed. No runtime, lint or formatting
checks ran for this checkpoint because Docker remains unresponsive. No provider
calls or host application execution. Independent review is pending. To avoid
repeated incomplete source-only review cycles, the next continuation should run
canonical backend checks first, resolve concrete failures, freeze final sources,
then request a narrow Astra follow-up against A-source-02's findings. Acceptance
and B dispatch still require both runtime evidence and independent review.

The historical 857-test result belongs to A-source-01 and is not evidence for
source-03. No source, migration, purchase or release approval is implied.
