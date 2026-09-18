# RM-11B shared source corrections

Three released production files are frozen against B-shared-01. This source-only
packet has no new runtime receipt. Expanded adapter tests and preload integration
are still in progress.

Dynamo shadow reclaim now uses conditional expiry, evidence version and execution
ownership checks for preparation and settlement. Outcome validation and terminal
replay checks precede acknowledgment. Pending decisions seal further dispatch and
completion evidence: late reports fail explicitly before acknowledgment instead
of being accepted and later discarded. The chosen compatibility tradeoff is
that a prepared conservative decision cannot be revised by a later report.

Independent source review and canonical runtime remain required for acceptance.
