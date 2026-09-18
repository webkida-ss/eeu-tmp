# RM-12A independent initial review

Astra verified five source hashes and the increment. Three corrections remain:

- Preparation can retain a local allowance after another submitter wins the
  same operation with different pinned caps or month. Reconcile before content
  handoff and test a winning reservation paused before page creation.
- Shadow creation/settlement currently leaves monthly processing caps unset.
  Preserve processing-only retained caps atomically without quota admission,
  reserved counters or paid entitlement effects; cover public shadow downgrade.
- Missing legacy operation caps deserialize as zero and can fail preparation
  before an existing ready result is replayed. Use trusted pinned context or
  bypass preparation for canonical terminal replay without adopting a new plan.

The public tests initially cover enforced reservations only. No further concrete
paid-entitlement boundary finding was identified. Acceptance awaits source
corrections, relevant regressions and a passing canonical receipt.
