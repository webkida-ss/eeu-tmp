# RM-07 independent correction review

Reviewer: `/root/rm07_review`, Astra/high; runtime read-only.
Baseline/HEAD: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Frozen diff SHA-256: `cb9daac5d79bb2305a6ec5a96d747e40f977727d9c7482a8c3b11c909ea936c1`.
Compared resume-01 and resume-02, excluding unrelated remediation.

**Static verdict: findings 1–3 corrected; finding 4 partially open. Runtime
acceptance remains blocked.**

All four policy templates now enumerate exactly the plan/package object patterns
and matching environment-specific KMS contexts. Version-only apply reads,
SSE-KMS conditions and denies remain intact. The validator checks those lists.
Ordering assertions select the apply block. Both plan/package GET responses now
require matching version, encryption, KMS key, and metadata. Record binding,
canonical destination, byte hashing and both Lambda hash checks remain present.

## Required correction

**Medium: behavioral harness does not execute the reviewed workflow.**
`backend/test_exact_plan_cli.py:945` reconstructs verification arguments and
`:1002` hand-writes restoration. It omits pre-AWS assert-record and changes actual
Terraform arguments (`:1013`, `:1020`). Removing --version-id from the real
download step or altering its verification arguments could leave tests passing.
Fake S3 creates destination directories itself (`:308`), masking workflow mkdir
regressions. Load actual selected apply steps, substitute only fixture context
values, honor their working directories, and execute unchanged bodies against
restricted fake executables. Include pre-AWS validation and actual apply. Assert
the expected rejection reason and absent apply sentinel, and leave directory
creation to the workflow.

Separate empty workspace, version-aware fake storage, missing/corrupt ZIP, GET
metadata failures, either Lambda hash mismatch, complete/partial omitted bindings,
and missing package upload evidence are now authored. They improve helper coverage
but do not close the workflow execution gap.

## Evidence limits

Read-only static inspection only; no tests/imports/writes/network/secrets/providers.
All eight canonical checks in EVIDENCE remain NOT RUN due denied Docker access.
Parent/implementer owns the bounded harness correction and container evidence;
independent follow-up review is required. No live IAM, release acceptance or
deployment approval.
