# RM-11B independently authored crash-window regressions

The new frozen test file ran against B-runtime-01's preload source and fixture,
with B-shared-02's corrected adapters. The isolated canonical task reported six
failures and two passes, exit 201.

Failures reproduce the reviewed stuck recovery after a dispatch marker or
completed result, private-result expiry, missing content after dispatch, and a
preparation failure before commit. Existing durable evidence conflicts with the
incorrect pre-dispatch outcome, or settlement is retried without preparation.
These are behavioral failures, separate from B-red-01's missing API failures.

The corrected integration must pass these tests without allowing provider replay
or relaxing successful-result and accounting assertions.
