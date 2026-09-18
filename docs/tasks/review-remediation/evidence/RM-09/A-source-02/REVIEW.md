# Independent correction review

Reviewer rm03_security_rereview, Astra/high, runtime read-only. Changes required.
Verified all nine frozen sources and incremental SHA-256
08895ab7edc83c8ee8d7662a618aa185fb481ec8284e3542c6771e5d19f707d5.

Previous stale-writer preservation, immutable/monotonic CAS, separate ownership
signals, operation metadata and immutable email findings are closed statically.
Terminal replacement and legacy index handling remain incomplete:

1. Medium: Dynamo index put/delete helpers always declare #document even when
   the expression has no legacy clause. Real Dynamo rejects unused aliases on
   fresh mappings/remaps. Build names with their clauses and validate aliases in
   the fake, alongside fresh and legacy index cases.
2. Medium: saved price does not cross the provider call boundary. Stripe resolves
   the current configuration again, changing line_items under the old key after
   configuration drift. Pass the immutable price and test actual SDK arguments.
3. Medium: adopted sessions bypass terminal reconciliation. Retain the original
   historical session/operation identity; the new local adoption operation ID
   alone cannot prove which old checkout was reconciled.
4. Medium: expired sessions with subscription_status=None are treated as terminal
   without checking their attached subscription ID. The normalizer fetches status
   only for completed sessions. Require no subscription for bare expired proof,
   or retrieve and validate authoritative terminal subscription state. Add an
   SDK-shaped expired-with-attached-subscription negative fixture.
5. Medium: the post-retention regression edits its attempt timestamp via upsert,
   which now intentionally preserves it. Advance the mocked clock instead and
   explicitly return empty discovery, asserting discovery without another create.

Parent assigned all five corrections to the original Terra implementer. No B/C
work, runtime execution, provider call, mutation or release approval by reviewer.
The old 857-test receipt does not validate this checkpoint. Canonical exact-source
container checks remain required after Docker recovery.
