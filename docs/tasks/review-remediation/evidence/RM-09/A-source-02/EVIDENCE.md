# RM-09A correction checkpoint

Base 3c4fae5d2c03e6592ebd1f51debf5c798294a476. Nine frozen files and an
incremental diff follow the five independent findings in A-source-01/REVIEW.md.
Original Terra implementer released ownership. No B/C implementation.

The correction preserves current pending records across legacy writes, validates
explicit CAS transitions, retains immutable email/provider parameters, reconciles
exact-operation terminal proof before replacement, preserves all Stripe identity
signals, and conditionally handles legacy Dynamo customer-index documents.

New tests cover all-adapter stale-writer interleavings, original-email retries,
terminal/missing-history recovery, SDK-shaped paginated discovery and identity
conflicts, and exact legacy-index upgrade/remap conditions in the fake store.

Parent and implementer git diff --check passed. Runtime, lint and formatting are
pending: Docker engine API remains unresponsive. No host execution workaround or
provider calls. A-source-01's 857-test receipt cannot validate these corrections.
Independent Astra static review is required, followed by exact-source canonical
container checks before A acceptance or B dispatch. No release approval.
