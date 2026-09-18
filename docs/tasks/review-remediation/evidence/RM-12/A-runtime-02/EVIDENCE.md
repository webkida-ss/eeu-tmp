# RM-12A second integrated checkpoint

Ten exact formatted sources are frozen against accepted RM-11B. Canonical lint
and formatting passed; unit tests reported 1022 passed, eight failed, six skipped
and 73 subtests. The full receipt is retained here. The public enforced and
shadow allowance workflow regressions pass at this checkpoint.

The failures include four inherited copies of an invalid PlanCatalog test access,
two adapter subcases with an invalid dataclass replacement field, a race fixture
using the wrong accounting month, and an actual pinned-plan fallback defect.
No R08 acceptance is claimed. Runtime ran in the existing network-denied,
mount-free owned container with mocked providers and JSON storage.
