# RM-03 independent security review

Reviewer `rm03_review`, Astra/high; implementer `rm03_implementation`, Terra/high.
Base/HEAD `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Verified diff SHA-256
`0b6e65fbf0eb822d3c1b01e6755b8bc07304b6f59f04355bdd26185535a6ef07`.
Disposition: changes requested. No acceptance or release approval.

## Required corrections

1. High: late account A restoration is relabeled as account B.
   `content.js:426` sends GET_PRELOAD_STATUS before capturing auth scope;
   `panel-ui.js:1371` accepts late status into cachedActivePreload, and hydration
   at `panel-ui.js:1716` uses the then-current scope. Capture before requests and
   propagate through response/cache/hydration/mounting; background getPreloadStatus
   (`background.js:269`) must also reject scope changes. Pause A's response,
   sign B in, release it, and prove no A record/render under B on either surface.
2. High: storage completion resurrects private UI after logout clears it.
   `settings.js:538` checks scope only before awaiting a write; `content.js:977`
   then renders unconditionally. `getReadingSession` (`settings.js:528`) and
   panel mount (`panel-ui.js:646`) have similar read/readiness windows and an
   unowned-session fallback. Recheck after awaited storage/readiness and before
   visible mutations; keep initiating scope. Delay these operations, deliver
   auth-change clearing, then resolve and prove state remains cleared.
3. Medium: worker restore captures nonce after fetching data (`background.js:497`),
   binding replacement documents to older work. Receiver `content.js:394` handles
   active/cache restoration before supplied-envelope validation. Capture original
   document before network work, verify before delivery, and validate supplied
   envelopes before all mutations. Test actual RESTORE_PAGE_READING_SESSION with
   same-URL replacement and a stale envelope alongside valid local cache.
4. Medium: generation read/increment/write (`settings.js:448`) collides for
   concurrent same-user logins. Use a cryptographically fresh session identifier
   atomically stored with each auth session, or serialize transitions. Interleave
   logins and prove distinct scopes reject the replaced login's delayed work.

Also require page_url in stored-preload validation (`settings.js:500`) to satisfy
the matching-URL contract. Line references identify the frozen resume-01 source.

## Evidence and remaining work

Private article/chat state crosses server, worker, content/panel and extension
storage boundaries. Source review used no runtime, providers, secrets or writes.
Parent whitespace evidence passed. All canonical unit/lint/format/package/smoke
checks remain NOT RUN. Required managed-Chromium and panel-switch integration
regressions remain NOT AUTHORED; add the four race regressions above as well.
Fix source, freeze a new checkpoint, then obtain independent re-review and
canonical container evidence. Parent persisted this independent report.
