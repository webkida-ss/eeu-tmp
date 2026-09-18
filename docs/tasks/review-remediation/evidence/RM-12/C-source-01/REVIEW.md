# Independent Astra source review: corrections required

Reviewer rm03_security_rereview verified five source hashes and the increment.
Sticky uncertainty and single-snapshot arithmetic match the contract. Two findings
remain. Numeric-only completed results reach synchronous recovery's unconditional
response lookup, causing KeyError instead of bounded recovery. A before-commit
numeric-evidence write failure can discard available known 17/tokens and settle
only floor 13 in synchronous, enforced preload and durable shadow paths.

Retain known bounds through fenced finalization or retryable evidence before
shadow sealing, preserving settled winners. Add failure-before-promotion and
full-private-response finalization-retry coverage. Existing repository conflicts
already prevent replacing a full completed response with different numeric-only
content. Source review was read-only and does not grant task acceptance.
