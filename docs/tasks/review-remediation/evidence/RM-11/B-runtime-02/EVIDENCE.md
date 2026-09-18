# RM-11B corrected recovery runtime checkpoint

Ten exact formatted files are frozen from the isolated container. Canonical lint
and formatting passed, followed by 222 tests / 37 subtests and six failures.
The remaining failures are a stale execution-clock fixture, two legacy runner
signatures, and three old shadow-handoff expectations. Corrections preserve
no-redispatch, ownership and exact accounting assertions.

This checkpoint used the interim service-side size guard. The subsequent
adapter-owned validation source and independent review are recorded separately
in B-review-03. Neither the later source nor later fixture changes are claimed
as tested by this receipt. R07 remains unaccepted.
