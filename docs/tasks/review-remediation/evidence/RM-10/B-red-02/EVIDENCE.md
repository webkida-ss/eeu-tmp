# RM-10B corrected fixture against accepted A

Canonical focused test:backend:unit ran in the credential-free network-denied
container with accepted A production and the frozen new test. Seven failures:
six exercise absent B handoff/retirement paths or the stale superseded worker
overwrite (running becomes failed). The conflict test's expected exception class
is a faulty oracle: the public service already returns an entitlement conflict
with status 409. That oracle is being corrected, not counted as a production bug.

This packet is pre-integration evidence only. Test source comes from the executed
container; no successful gate or implementation acceptance is implied.
