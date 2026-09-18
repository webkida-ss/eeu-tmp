# RM-11B first integrated checkpoint

Seven exact formatted sources are frozen against accepted A. Canonical lint and
formatting passed, then 121 tests and 13 subtests passed with three failures.
The receipt records task exit 201. Separate B-shared-02 records the expanded
adapter suite; its passing receipt is not attributed to this integration source.

Failures cover a terminal marker-failure oracle, missing observation logging,
and ordinary API readiness. The API uses a default disabled meter, while this
initial source only enables durable shadow for callers explicitly setting the
new flag. Parent assigned preload-owned durable conversion for all new shadow
submissions, preserving true legacy in-flight fail-closed behavior and keeping
synchronous reading callers unchanged.

Independent review identified additional recovery, actual page-size validation,
handoff settlement and known-cost retention gaps. All are assigned; no R07
acceptance is claimed by this intermediate packet.
