# RM-04 scoped panel producer correction

Terra implementation follows source-01 Astra finding. Five frozen full files
include the new reading-panel unit test; increment.diff covers tracked deltas.
Panel UI writes/restores use scoped helpers, retain the mounted owner across
awaits and clear it on reset. Fallback mounting carries the originating owner.
Tests select through actual panel UI, persist/restore selection and check another
article remains unchanged. Existing two-panel smoke is extended at the producer.

Parent git diff --check passed. No runtime evidence exists for this checkpoint:
Docker API _ping timed out with no bytes after ten seconds, repeated after the
desktop observation tool stalled. Previous source-01's passing receipt remains
historical and cannot validate this delta. Independent static review is pending.
No host runtime workaround or user-container interruption.
