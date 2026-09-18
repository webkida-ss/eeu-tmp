# RM-11A intermediate lint failure

Canonical validation stopped before tests on four test-import errors: Callable
was imported from typing, Mock was unused, and usage_operation_sk and replace
were missing. The parent corrected these imports in released test files and
reran validation. This historical packet is not an acceptance checkpoint.
