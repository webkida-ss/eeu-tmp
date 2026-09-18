# Final service-free gate preparation

Parent decision during the September 15 continuation: the existing runtime stays
credential-free, network-denied and mount-free. `task check` also verifies all four
committed Terraform provider lock platforms. The owned mirror currently contains
only hashicorp/aws 6.55.0 linux_arm64, so prepare the three missing public packages
(darwin_arm64, darwin_amd64, linux_amd64) separately from runtime execution.

Fetch the exact version from HashiCorp's public release host into the task's host
temporary directory, verify every ZIP SHA-256 belongs to the existing committed
lock, then copy only verified files into the owned container mirror. No version
upgrade, lock edit, credentials, provider API, external write or deployment is
part of this preparation. Runtime will use the existing explicit filesystem
mirror and pinned Lambda wheelhouse, with network still disconnected.

This document records preparation authorization under the user's continued local
implementation/testing request; it is not a passing runtime receipt.

## Frozen evidence and the local lint gate

The working tree contains 304 historical Python snapshots under the remediation
evidence directory, including deliberately failing pre-fix checkpoints. Ruff's
root discovery would format/lint those immutable snapshots as active source.
Parent adds only `docs/tasks/review-remediation/evidence` to Ruff's existing
exclusions. Active backend source, tests, scripts and configuration stay checked.
This keeps evidence immutable and makes the same canonical local gate applicable
to the delivered tree. Independent review and runtime verification are required.

## Source and secret-scan coverage

The temporary container has an isolated Git repository with an initially empty
index. Before the final gate, populate only that container index with the host's
564 committed repository paths plus explicitly selected new remediation source
and test paths. This makes the canonical tracked-file secret scan meaningful.
The only committed environment-named file is the public `.env.example` template;
no private environment file, credential store, local data or Git history is
transferred. The host Git index remains untouched. Synchronize and hash the exact
source set, including workflow YAML, Lambda shell build code and example AWS
policies required by the gate. Historical evidence remains outside active source.
