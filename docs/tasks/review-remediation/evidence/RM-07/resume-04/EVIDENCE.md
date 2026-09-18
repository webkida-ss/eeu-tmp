# RM-07 actual-workflow harness correction

September 13, 2026 06:30 continuation. Baseline/HEAD
`3c4fae5d2c03e6592ebd1f51debf5c798294a476`. SHA256SUMS binds the cumulative diff
and eleven source paths. Compare resume-03 for this test-only increment.
Implementer `/root/rm07_regressions`, Terra/high, released ownership.

Only backend/test_exact_plan_cli.py changed in this correction. Its SHA-256 is
`27143ee41b17d94672d75048c63b1df24d5590a65887e3b2fcb47a9fd55befde`.
The implementer reports that the harness now parses actual jobs.apply.steps via
PyYAML, substitutes a bounded fixture-expression map, preserves run bodies, step
environment and working-directory, and executes from assert-record through the
actual Terraform apply arguments. Fake S3 no longer creates download directories.
Negative cases assert the expected rejection reason and absent apply sentinel.
Mutation cases cover removed version arguments, omitted verification and changed
ordering. These reports have not yet received independent follow-up review.

Parent and implementer whitespace checks passed; current manifests verified.
All canonical runtime checks remain NOT RUN due Docker access denial. No host
runtime, credentials, providers, external writes or commits. No task acceptance.

Next: narrow independent Astra follow-up against resume-03/REVIEW.md, focused on
the actual-workflow harness and its reliable fixtures/drift checks. Prior source
findings 1–3 already have static correction confirmation in that review; do not
repeat the whole baseline audit absent new drift. Runtime evidence remains an
independent requirement even if the source follow-up is clean.
