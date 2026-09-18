# RM-09C review: one cancellation race remains

Independent Astra verified three source hashes and increment. The supplied
provider-create, post-result/pre-activation-read and activation-CAS cancellation
cases are addressed, as is the worker fixture syntax correction.

Medium: cancellation can commit after post-provider read but before created-state
CAS. The failed CAS leaves the old operation attempted with no saved session.
Retry skips the saved-session guard and resets activation_fence_revision to the
canceled current revision, allowing that old operation to activate. Preserve the
original attempt fence and detect superseding cancellation before redispatch or
rebasing; add a controlled cancellation-before-created-CAS regression.

Parent runtime receipt is valid: 906 passed, 6 skipped, 47 subtests; canonical
lint/format passed, exit 0. It does not close the remaining race. C is unaccepted.
Reviewer executed no runtime, edits or provider calls. No release approval.
