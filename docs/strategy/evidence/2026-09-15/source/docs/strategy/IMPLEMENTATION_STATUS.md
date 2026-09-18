# Monetization implementation checkpoint

Date: 2026-09-15. Local remediation accepted; commercial validation remains open.
This checkpoint reconciles the September 9 strategy with the completed code-review
work. It does not change prices, quotas, market assumptions or release authority.
The market research and fee/FX scenarios remain dated September 9; they have not
been refreshed or established as actual account costs.

## Completed foundation

All 27 retained code-review findings are accepted across RM-01 through RM-14.
See [the task status](../tasks/review-remediation/STATUS.md) and
[final independent acceptance](../tasks/review-remediation/evidence/FINAL/runtime-02/REVIEW.md).

| Foundation | Accepted work | Consequence for the commercial roadmap |
| --- | --- | --- |
| Purchase and entitlement consistency | RM-09: idempotent checkout, authoritative subscription reconciliation, finite provider-aware entitlement | M05 can build on these behaviors; customer-facing plan comparison and honest limit disclosure still need their own evidence |
| Cost and workload accounting | RM-10 through RM-12: handoff ownership, durable dispatch evidence, recoverable shadow outcomes, retained processing allowance, sentence capacity and incurred-call uncertainty | M01 should measure and calibrate the corrected system; these fixes do not establish real provider rates, monthly demand or the Max margin rule |
| Account and local persistence | RM-03, RM-04, RM-13 and RM-14: ownership, session/account persistence, account-scoped activity and serialized phrase saves | M02 can reuse operational outcomes; M04 still needs cross-article navigation and M06 still needs deletion/retention design |
| Configuration and release safeguards | RM-01, RM-02 and RM-05 through RM-08: isolated defaults, credential-chain/TTL wiring and deployment/configuration safeguards | M07 should reuse the validated build and policy workflow; live sign-in, checkout, cancellation, store installation and release approval remain separate evidence |

Canonical local checks passed: 1057 backend tests / 99 subtests, 102 admin tests,
190 extension tests, extension packaging, Lambda packaging, indexed secret scan,
four-platform provider locks, development/production Terraform validation and
managed Chromium smoke. Six default-mode skips are not passes. DynamoDB Local,
live providers and the user's normal Chrome profile were not tested. Changes
remain local and uncommitted; acceptance is not a production rollout.

## Remaining strategy work

The M01–M10 backlog remains proposed. Completion of RM-01–RM-14 does not complete
any whole M-unit: their commercial/product acceptance criteria are different.
Do not count the remediation tests as acquisition, activation, renewal or measured
contribution evidence. Do not start a second copy of the completed RM backlog.

| Next unit | First bounded deliverable | Evidence needed before subsequent work |
| --- | --- | --- |
| M01 | A cost-audit specification using versioned plan/model/rate inputs and a synthetic joint workload of article, chat, uncached, retry and failed calls | Exact formulas, known-versus-unknown cost handling and workload reproducibility; distinguish simulation from provider invoices. Record a proposed Max remedy before any price/allowance change |
| M02 | An event/cohort specification tied to existing account-scoped terminal activity, with a minimal client-render event contract | Same-cohort maturity and exclusions, account-scoped deduplication, no content/URL/credential collection, and analytics failures that do not break reading |
| M03–M05 | Separate first-value, cross-article revisit and honest purchase-flow specifications, after M01/M02 definitions | Own-article value distinguished from sample/demo, free cached revisits, both article scopes accessible, and understandable pre-purchase limits |
| M06–M07 | Inventory deletion, retention, cancellation, support and store-release evidence; reuse accepted tooling | Authenticated idempotent deletion across actual stores, explicit retained records, accurate disclosures and verified release/payment flows before paid launch |
| M08–M10 | Remain conditional on observed return use, mature renewals and measured contribution | Customer evidence and bounded experiment budgets; no automatic speculative feature expansion |

The existing roadmap estimates and dependency ordering remain provisional. They
have not been re-estimated from the remediation duration. Start a new commercial
work packet from the accepted source checkpoint instead of reopening resolved
reliability findings. A future live measurement, customer outreach, price change
or release needs authorization for that specific external action.

## Review and continuation

This reconciliation and the corrected strategy packet are submitted for a second
independent documentation review. See the dated review packet under
[evidence](evidence/2026-09-15/REVIEW.md) for the final disposition.
The completed RM backlog needs no scheduled continuation. The user's conditional
05:00 continuation applies only if this follow-up remains unfinished; completion
before then does not create a recurring or empty task.
