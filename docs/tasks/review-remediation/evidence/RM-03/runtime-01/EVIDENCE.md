# RM-03 current privacy correction

Base3c4fae5d2c03e6592ebd1f51debf5c798294a476, frozen cumulative diff/source SHA256SUMS. Terra/high authored corrections; parent owns final canonical formatting and key-helper wiring. Independent review requested against resume-03 findings only, plus new runtime-discovered cleanup race.

Cached preload retains originating auth/login scope and post-profile checks preserve it. Regression browser routing now uses panel-origin worker messages, isolated content PING,202 POST,normalized URLs and bounded gates. Post-hydration account switch cleanup uses existing settings.js readingSessionStorageKey, verifies owner and preload identity, and removes only the initiating scoped key in finally. Capture occurs before the post-hydration scope check. Smoke proves replacement B state survives. Scope-matched navigation poll counting excludes independent destination readiness polls.

Historical runtime: 187 extension units passed and package checks passed. Smoke reached final assertions and exposed the account-switch persistence race now corrected. Canonical final lint/format/unit/package/smoke is running in network-disconnected credential-free container with repository Chromium. Parent will add separate hashed results after completion; do not infer runtime acceptance before that receipt.
