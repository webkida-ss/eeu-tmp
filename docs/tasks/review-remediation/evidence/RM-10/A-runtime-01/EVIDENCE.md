# RM-10A persistence primitive checkpoint

Four frozen files cover three adapters and a new focused test module. Increment
uses the accepted pre-RM10 baseline in /private/tmp/untangle-remediation-20260914/
rm10-base, with the new test compared against /dev/null. Submission integration
is intentionally unchanged until ordered B. R05 is not yet accepted.

Canonical formatting/lint passed. Backend unit result: 931 passed, 2 failed,
6 skipped, 47 subtests; exit 201. Both failures are the existing Dynamo lease
fake Store.get_document missing the new consistent_read keyword. Parent authorized
a narrow compatibility update to that fixture in test_preload_jobs.py; preserve
existing lease/completion oracles. No production fallback for incomplete fakes.

All runtime used the credential-free network-denied owned container, fake Dynamo
and fake S3. No host application tests or external calls. Independent review
and successful canonical checks remain required before A integration acceptance.
