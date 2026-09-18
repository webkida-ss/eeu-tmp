# RM-04 runtime correction checkpoint

Four frozen files and increment relative to independently reviewed source-02.
Base 3c4fae5d2c03e6592ebd1f51debf5c798294a476. The new unit fixture uses a
configurable WebCrypto property instead of assigning a getter-only jsdom property.

Real browser execution exposed local selection storage echoes that reset audio
position. The producer tracks bounded scoped UI fingerprints before persistence;
the panel excludes matching local echoes, while differing external selection is
still handled. Persistence refuses a different same-page preload. New regression
assertions exercise local-write recognition and stale-preload protection.

The audio fixture uses the reading view and real keyboard input. Its unchanged
advance/stop oracles passed. A later dropdown fixture timed out after its real
language change handler hid the settings control. The final smoke waits for the
persisted language, change count and closed control, then returns to settings and
waits for visibility. It does not force clicks or remove the original oracles.

Canonical unit/package receipt: 190 unit tests and 8 package tests/14 subtests
passed. That combined log retains the earlier dropdown smoke failure explicitly.
Only smoke.mjs changed afterward; format.log confirms the production files and
unit fixture were unchanged. The final smoke then passed twice, and final lint
and formatting checks passed (exit 0). The extra smoke run checks the previously
intermittent fixture failure rather than substituting repeated unit runs.

All tests ran in the owned credential-free, network-disconnected container.
No host application execution or external provider calls. Frozen hashes and
unchanged-source receipts are supplied for independent Astra review of the echo
boundary and fixture corrections. RM-04 acceptance remains pending that review.
