# RM-09B initial source checkpoint

Eight frozen files implement authoritative lifecycle retrieval, event dedup and
revision CAS under the B contract. accounts/container.py passes the configured
plan catalog through the existing dependency-injection boundary. Related account
and manual-contract tests update synthetic provider fixtures; no public contract
was changed. A's subscription adapters remain unchanged.

Before runtime, parent inspection and implementer confirmation identified three
compatibility gaps: adding subscription_data changes A's saved same-key request;
strict fetched user metadata rejects legitimate legacy customer-index ownership;
requiring finite periods for terminal snapshots prevents authoritative revocation.
These are open corrections, not accepted behavior. Capture regressions and fix
them before independent B review. No C changes or runtime evidence yet.
