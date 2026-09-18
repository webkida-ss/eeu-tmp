# RM-10B corrected provenance and recovery checkpoint

Eight sources frozen from the formatted test container. Increment compares
B-runtime-03 and adds the activity fixture's distinct-operation correction.
Canonical lint/format passed, followed by 959 backend unit tests (6 skipped,
53 subtests) and 102 admin tests. Final exit status 0. All execution used the
credential-free, network-denied owned container and mock/fake providers.

Canonical creation explicitly records worker_execution_started=false; claim
sets it true and returns transient never-started predecessor evidence under the
same atomic boundary. The service strips that evidence before subsequent writes.
Legacy unknown and previously claimed work cannot use superseded release.
Expired running records with released usage are conditionally claimed for
cleanup; active workers remain protected. Shadow fast-path candidates are
validated after concurrent lookups. New tests cover those interleavings and
returned-to-processing dispatch recovery.

Exact sources and runtime receipt are hashed. Independent final source/runtime
review remains required before RM-10B and R05 acceptance.
