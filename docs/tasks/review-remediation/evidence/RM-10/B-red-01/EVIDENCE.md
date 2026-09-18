# RM-10B initial regression fixture failure

Parent ran canonical test:backend:unit with
PYTEST_ADDOPTS=test_preload_handoff_workflow.py against accepted RM-10A in the
credential-free, network-denied container. All six tests failed before reaching
their intended race because the fixture article was shorter than the extractor's
100-character minimum. This is a test-fixture failure, not proof that the new
regressions detect the intended production bugs. The owner is correcting the
fixture and race pause boundaries before another run.

The frozen source was retrieved from the tested container, not from the changing
host working tree. No production implementation is accepted by this packet.
