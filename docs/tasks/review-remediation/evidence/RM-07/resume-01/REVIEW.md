# RM-07 independent security review

Reviewer: Astra/high, independent read-only security reviewer.
Baseline/HEAD: `3c4fae5d2c03e6592ebd1f51debf5c798294a476`.
Frozen diff SHA-256: `f8cc7755083ef9b4424714d21bb9c3e25e1a843ee91a3f3b86e0760b4eae0157`.
Verdict: **Changes required; runtime acceptance blocked.**

The reviewer compared RM-06 evidence to isolate RM-07, and inspected the plan,
resumption contract, baseline Terraform paths, and storage policies. Trust
boundaries are the protected plan job, private versioned S3/KMS storage, and the
separately approved apply runner. Record binding, canonical destination, byte
hashing, both Lambda hash comparisons, and role separation are present.

## Findings

1. **High: package transfer exceeds documented object permissions.** The sibling
   package key at `scripts/exact_plan_policy.py:706` cannot be transferred using
   existing templates. Both plan-role templates at lines 174/198 permit only
   `/tfplan` for S3 PUT and KMS context. Both apply-plan-read templates at lines
   11/23 similarly restrict versioned GET/decrypt. Add explicit plan/package
   object allowlists and matching KMS contexts, validators, and denial tests;
   preserve environment separation and version-only reads. Parent subsequently
   recorded precise source-only correction ownership in RESUME. No live IAM
   change is authorized or performed.
2. **Medium: workflow ordering regression necessarily fails.**
   `backend/test_exact_plan_cli.py:687` searches the entire workflow for the first
   Terraform init, which is in the earlier plan job. Scope ordering assertions to
   apply steps and check both strict-validation locations.
3. **Medium: GET validation misses the explicit evidence contract.**
   `scripts/exact_plan_policy.py:1523` checks only GET VersionId, ignoring GET
   encryption, KMS key, and identity metadata. The successful fixture at test
   line 408 lacks those fields. Require matching GET evidence and negative cases.
   HEAD validation and byte hashing limit substitution risk; this is a contract
   gap, not a demonstrated AWS integrity bypass.
4. **Material test gap:** the end-to-end fixture creates the package directly at
   its destination (test line 283), without actual fake-storage restoration into
   an empty apply workspace. Missing-binding coverage (line 749) removes an option
   but leaves its value, demonstrating argparse rejection instead of strict
   binding enforcement. Cover actual workflow restore with local fake storage,
   an apply sentinel, missing/corrupt ZIP and metadata, omitted/partial bindings,
   missing upload evidence, and mismatch in either Lambda hash.

## Evidence limits

Static inspection only. All seven canonical commands in EVIDENCE remain NOT RUN
because Docker access was denied. No reviewer runtime execution, imports, edits,
provider calls, secret access, or external writes occurred. Corrections require
independent re-review and credential-free container execution evidence. No
release or deployment approval is granted.
