# RM-11B corrected integration source review

Astra verified twelve frozen source files and the increment. Earlier gaps in
default durable composition, legacy handling, evidence recovery, preparation
retry, handoff settlement and initial adapter-owned size validation are addressed.
Two source corrections remain before acceptance:

- The new cost helper applies the estimate floor even to complete measured
  priced usage. Preserve exact measured cost; use the floor only for uncertain
  usage. The named incomplete-usage test currently supplies a complete tally and
  must exercise an actual missing response as well as measured-below-estimate.
- Recovery metadata can enlarge a previously valid publication beyond Dynamo's
  size ceiling. Normalize transient metadata consistently and validate recovery
  before choosing success. Test a near-ceiling result with preparation failure,
  and bounded unavailable-result publication after an already canonical success.

The crash-window tests meaningfully cover previously missing recovery boundaries.
No final passing runtime receipt covers this composition yet.
