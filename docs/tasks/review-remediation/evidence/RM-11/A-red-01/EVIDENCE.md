# RM-11A initial regression checkpoint

Parent ran the new fourteen-case test file against accepted RM-10 production in
the credential-free, network-denied container using canonical test:backend:unit
with PYTEST_ADDOPTS=test_usage_evidence_recovery.py. Two existing marker-write
failure guards passed; twelve tests failed. Concrete old behavior includes
releasing incurred usage after private-result deletion in JSON and fake Dynamo,
and allowing a synchronous retry after private response expiry. Other failures
assert the new durable evidence metadata or its stricter authorization contract,
which the baseline does not implement yet.

The exact test source is frozen from the container. This is pre-implementation
evidence only; no RM-11 acceptance is implied. Production remains owned by the
implementation agent until its explicit checkpoint release.
