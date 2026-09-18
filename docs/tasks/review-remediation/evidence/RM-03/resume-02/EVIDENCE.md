# RM-03 correction checkpoint

Saved September 13, 2026 during the 01:00 JST continuation.
Implementer: `/root/rm03_implementation`, Terra/high. Parent: Astra.
Baseline/HEAD: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Diff SHA-256: `4018a7dfdb9ddff32e070739a9cecd2b2d76ff4147809b7f90b1dfb51d812a56`.
Full diff against HEAD includes RM-02. Compare resume-01 for this correction;
SHA256SUMS binds all twelve current extension paths. No untracked source files.

The implementer reports corrections for all four prior security findings:
cryptographic loginId atomically stored with authSession, originating account
scope captured and checked across asynchronous worker/content/panel/storage
paths, document identity captured before delivery/restoration, early receiver
envelope validation, and cleanup after a scope change during panel mounting.
Stored preload validation now requires page_url. These claims have not yet
received independent re-review.

Authored tests cover worker navigation/logout races, same-URL document nonce
replacement, forged page storage, invalid schema, account isolation, stale restore
envelopes, and login IDs. Managed-Chromium smoke adds a stale-envelope case and
panel account switching. The implementer explicitly reports these required
regressions still unauthored: actively gated cross-origin navigation during
submission/polling, logout during worker completion, same-URL reload during live
restoration, and deferred storage get/set completion races. The next implementer
must also match the exact delayed status/hydration/mount scenarios in the prior
REVIEW rather than assume a nearby smoke assertion proves them.

Parent and implementer `git diff --check`: PASS.
NOT RUN: `test:extension:unit`, `lint:extension`, `format:extension:check`,
`test:extension:package`, `test:extension:smoke`. Docker listing failed once in
this window; no host runtime fallback. No independent review of this checkpoint.
No acceptance, release approval, external writes, credentials, or commits.

Ownership released. Finish missing regressions, freeze a new checkpoint, and
obtain independent Astra security re-review before dependent RM-04 preparation.
