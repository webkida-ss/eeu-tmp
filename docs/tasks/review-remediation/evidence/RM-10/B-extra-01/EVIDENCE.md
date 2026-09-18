# RM-10B additional workflow fixture checkpoint

The frozen eleven-case workflow test ran against B-runtime-02 production using
canonical test:backend:unit with a focused PYTEST_ADDOPTS override in the
credential-free, network-denied container. Nine tests / two subtests passed;
two assertions are invalid test oracles, not additional production findings.

Shadow submission intentionally does not reserve a disabled or durable usage
operation before RM-11B. The test must assert absence and no release, not a
reserved operation. A handoff's failed_pending_release status already persists
cleanup recovery; content_retirement_pending is the worker terminal protocol.
The handoff test must verify successful retry and retirement without requiring
that additional internal flag. Worker-terminal cleanup flag assertions remain.
Corrections are assigned; no acceptance is implied.
