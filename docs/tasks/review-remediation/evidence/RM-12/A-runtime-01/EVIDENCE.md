# RM-12A first integrated checkpoint

Five formatted sources are frozen against accepted RM-11B. Canonical lint and
formatting passed; unit tests reported 1012 passed, seven failed, six skipped
and 73 subtests. Four failures are inherited copies of the old lower-than-current
pinned-cap display expectation. Three new integration cases require a local rate
fixture or valid minimum-length HTML before exercising their intended assertions.

Independent review additionally found concurrent canonical-reservation mismatch,
missing shadow processing-cap retention, and zero-cap legacy replay. These require
source corrections and regressions; passing the existing tests alone is
insufficient. No R08 acceptance is claimed.
