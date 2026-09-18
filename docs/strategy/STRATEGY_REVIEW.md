# Codebase and monetization strategy review

Date: 2026-09-09. Baseline: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Scope: static inspection of product, billing, usage and release documents;
primary-source market research accessed on September 9. No runtime, production, account or
secret inspection. “Not found” is limited to inspected repository surfaces.

The findings below describe the September 9 strategy review. The
[September 15 checkpoint](IMPLEMENTATION_STATUS.md) records accepted code fixes;
commercial acceptance criteria remain open.

## Existing assets worth preserving

The product already combines inline explanation, contextual chat, vocabulary,
TTS and localized UI. `backend/core/plans.py` defines finite quota tiers;
`backend/accounts/billing/stripe_billing.py` and the billing flow provide
provider-backed checkout/portal/webhook structure. `extension/panel-ui.js`
contains usage warnings and purchase controls. Release packaging exists in
`extension/scripts/build_release.py`. Operational activity exists in
`backend/services/admin_activity.py` and is called from reading/preloading.
These assets support a focused pilot without inventing a new product platform.
Their presence is code evidence, not proof of production readiness.

## Findings and recommended dispositions

| Severity | Finding and evidence | Business impact | Resolution in proposal |
| --- | --- | --- | --- |
| High | `docs/MONETIZATION.md` treats cross-article vocabulary as the retention pillar, but `extension/panel-ui.js:244` filters by current preload/page and line 274 renders that filtered book | Accumulation is not accessible as promised in normal article context | M04 adds explicit all-article navigation; do not advertise this as complete |
| High | Habit metric is at least 3 preloads/week while Basic in `backend/core/plans.py` allows 3/month | Free engagement is structurally misclassified | Track cached reading and revisit days separately from paid new analyses |
| High | Pricing design rounds Max cost share to 30%; exact original calculation is 30.22%, revised Billing allowance gives 30.46% | Existing hard-profit-rule claim is false | M01, freeze Max sales approval until exact recalibration; no silent deployed change |
| High | Max stress workload of articles and chats is JPY 1,080 vs JPY 1,050 ceiling; uncached selections also cost money | Visible allowances can outlast hidden budget | Measure joint demand and premature blocks; honest limits and verified protection before scale |
| High | Existing materials say instrumentation absent, but terminal article/chat outcomes now exist; full acquisition/render/checkout funnel was not found in inspected paths | Rebuilding everything wastes effort; server success alone overstates first value | Reuse admin activity, add only missing product events and verified payment attribution |
| High | Public disclosure/support documents and account deletion flow not found in inspected docs, accounts and main routes | Public paid release gate remains unproven | M06/M07 inventory and evidence; external state is unknown, not asserted absent |
| Medium | Generic multi-language/heavy-reader segments do not establish reachable buyers or willingness to pay | Broad acquisition burns effort without learning | First cohort focused on public technical reading; test willingness to pay |
| Medium | Default configuration/model does not prove enabled cost enforcement or measured rates | Margins could be overstated | Require calibrated enforced-mode evidence and failure workload measurement |
| Medium | Prior strategy suggests annual discount when monthly churn exceeds 5% | Longer contracts could conceal a weak recurring job | Require mature retained cohorts first |
| Medium | July release design describes packaging as missing; a reproducible builder now exists | Stale roadmap can duplicate completed work | Revalidate gates from current artifacts rather than reuse historical status |

## Counterarguments and falsification

1. Technical professionals may only want translated meaning, or already use
   general chat. Ask them to demonstrate an actual difficult paragraph and
   compare the workflow; stop this positioning if explanation does not matter.
2. A competing reading tool can provide inexpensive contextual explanations.
   Do not claim uniqueness. Test whether integration quality and revisit value
   justify the actual recurring price.
3. Three free articles may be too little to evaluate long-term value. First
   provide a cached demonstration and frictionless revisits; only then consider
   a bounded allowance experiment with a cost model.
4. Cross-article vocabulary repair may not increase retention. It corrects a
   specific product promise; further study features require observed demand.
5. Ten interviews and five payers are selected small samples. They permit the
   next cohort, not a confident conversion estimate or product-market-fit claim.
6. One engineer may not finish trust/deletion work in the optimistic schedule.
   Prioritize safe paid delivery and move the date, rather than expand features.

## Review conclusion

Recommended direction: a narrow Pro-first paid pilot with reliable first value,
revisitable material and measured contribution. The proposal is suitable for
turning into small implementation specifications; public launch and scale are
not approved. Live costs, actual customer demand, operational readiness and
renewal remain missing evidence. No pricing change has been applied.

## Independent review and disposition

A separate correctness reviewer inspected the frozen four-document packet
against the baseline above. It did not edit files, run tests, or independently
repeat the web research. Its findings were resolved by the parent:

| Finding | Severity | Applied correction |
| --- | --- | --- |
| Seven renewals could pass even with 100 eligible subscribers; cancellations could disappear from denominator | High | Require at least 10 matured first-renewal opportunities and a 70% rate; include advance cancellations; fix seven-day settlement window and separate first/second renewals |
| Funnel numerators did not explicitly share denominator maturity criteria | Medium | Restrict every numerator to its denominator cohort; fix 24-hour checkout observation and report late settlement separately |
| Post-rejection explanation does not make hidden service limits an honest offer | Medium | Add pre-purchase allowance validation or understandable additional restrictions as a paid-pilot gate and M05 acceptance criterion |

At the September 9 checkpoint, the parent checked these edits against the
findings without a second independent pass. The corrected packet and current
implementation reconciliation are now submitted for that pass; the
[dated independent review](evidence/2026-09-15/REVIEW.md) records its disposition. Remaining uncertainties are customer demand,
real costs, production readiness and capacity, not claimed resolved by review.
Documentation validation: relative links resolve, pricing formulas recomputed,
and whitespace checks pass. No application tests ran for this docs-only change.
The review grants no deployment, billing-change or release approval.
