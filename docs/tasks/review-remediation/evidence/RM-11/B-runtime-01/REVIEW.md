# RM-11B independent integrated review

Astra verified the integrated manifest and B-shared-02 regression evidence.
Acceptance is withheld for these findings in frozen preloading.py:

- Lines 1125–1169 can retry provider work after durable dispatch/completion but
  before outcome preparation, then become stuck when the marker and pre-dispatch
  failure decision both correctly conflict. Recover evidence before provider work.
- Lines 1069–1078 and 1277–1294 cannot recover a pending page when preparation
  failed before committing its durable decision. Retained validated results must
  permit safe preparation on retry without another provider call.
- Lines 905–951 settle success before the actual Dynamo page-size validation.
  Validate and retain the complete pending publication before success preparation;
  test the page adapter boundary, not only private-result storage rejection.
- Handoff cleanup at lines 181–204 and 693 treats shadow as unreserved and bypasses
  its durable failure settlement. Complete accounting before terminal cleanup.
- Incomplete tally conversion at lines 1219 and 1244 can replace higher known
  cost with a lower estimate. Preserve the maximum together with known tokens.

The parent additionally assigned default-meter integration and observation logging.
Shared tests cover failure atomicity and execution fences, but competing outcome
preparation still needs deterministic interleaving and two guards need Dynamo
parity. Sequential settlement/reclaim orders alone do not prove concurrency.

Integrated runtime: 121 passed, three failed. Shared runtime: 69 passed and 22
subtests. Neither supports integrated acceptance before these corrections.
