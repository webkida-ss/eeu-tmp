# RM-03 independent security re-review

Reviewer: `/root/rm03_security_rereview`, Astra/high, read-only.
Baseline/HEAD: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Verified diff SHA-256: `4b0c8ecfc8c646d6b1a1b67fa9801baf6a10df2b3fc78a44cb59b754319e1c0d`
and all twelve source hashes. Scope includes RM-02 shared-helper changes.
Verdict: **Changes requested; runtime validation separately blocked.**

Boundaries reviewed: private article/session data across accounts, worker
responses, extension storage, content isolated worlds and panel UI. Account
transitions, delayed responses, document replacement, page storage and malformed
records are untrusted inputs.

## High: A's preload can still be hydrated as B

`extension/panel-ui.js:1555` awaits preloadMatchesCurrentLearnerProfile after its
last account-scope check. Switch to B during the storage read and let the auth
listener clear A's UI. Completion caches A's preload at 1562 and calls sync at
1563 without authScope. syncReadingViewUi reads B's current scope at 1783 and
can persist A's record under B.

Recheck original scope after the learner-profile await and propagate it through
every downstream sync, including 1591. Bind cachedActivePreload to its originating
scope: 1782–1783 retains an unowned candidate across an async scope read, exposing
another relabeling window when callers omit scope. Regress the actual
existing-preload flow paused at learner-profile storage.

## Medium: browser race tests have incorrect wiring

In extension/test/smoke.mjs:

- 726–728, 778–780, 816–821 send runtime messages from the worker itself; its own
  registered listener does not receive them. Use panel/another extension context.
- 732, 825, 868 read an isolated content-world variable from page main world.
  Use the existing worker-to-content PING mechanism. The main-world activePreload
  assertion at 828 is ineffective for the same reason.
- Line 72 returns HTTP 200 for POST /pages/preload; the generated contract expects
  202, so the worker rejects it before polling.
- 718 and 770 compare root page.url() with its trailing slash against normalized
  extraction/polling URLs without it. Normalize both gate operands.
- Bound gate waits, release in finally, and assert the intended operation rather
  than incidental panel refresh reached each gate.

## Medium: required race coverage remains incomplete

- content-parsing.test.mjs 287/352 mutate the backing auth object directly;
  dom-harness.mjs 222 discards storage listeners. Deliver actual auth-change
  clearing events while read/write completion is held.
- smoke 847–855 delays server status only, not panel storage hydration, API
  readiness or mounting. Cover those waits, refreshPreloadStatus, and the
  existing-preload branch identified above.
- Forged page storage is tested by direct restoration and invalid schema by
  getReadingSession only. Add receiver-path cases and otherwise-valid fixtures
  that independently omit or mismatch page_url.
- Distinct concurrent login IDs alone do not prove late work from the replaced
  same-user login is rejected. Add that completion scenario.

## Prior findings and evidence

Original account scope is partially corrected; the High issue above remains.
Scoped storage checks and mount guards exist, but clearing/readiness/mount tests
are insufficient. Restoration nonce captured before network and envelope checked
before cache/active restoration are statically corrected. Atomic cryptographic
loginId and required stored page_url are also statically corrected.

No tests/imports/scripts/secrets/providers/network/writes occurred. All canonical
unit, smoke, lint, format and package checks are NOT RUN due supplied Docker
denial. Implementer owns corrections. Parent must provide a new frozen checkpoint
and canonical container evidence for independent review. No acceptance or release
approval.
