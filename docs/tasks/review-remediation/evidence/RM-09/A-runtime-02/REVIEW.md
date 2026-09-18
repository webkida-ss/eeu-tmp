# Independent exact-session correction review

Reviewer rm03_security_rereview, Astra/high, read-only. Changes required.
Two frozen sources, diff and runtime receipt verified. Increment SHA-256:
8a6004d028f6e15bcb89ce1918d954456374ebbcebe706447755384e67a71ef3.
Canonical lint/format and 869 tests passed, 6 skipped, 33 subtests; exit 0.

Legacy adoption identity is corrected, but replacing relevant history with
matching_sessions at billing_flow.py:158 hides other same-user purchases before
multiple-open/subscription safety validation. Saved open S1 alongside open S2 or
completed/active S2 returns S1 instead of reconciliation-required. Keep the full
relevant history and validate exact session/optional operation identity separately.
Add competing-session regressions, including a terminal saved session that must
not authorize replacement while another unsafe purchase remains.

Parent assigned the narrow flow/test correction to Terra. No B/C dispatch,
reviewer execution/mutation/provider calls or release approval.
