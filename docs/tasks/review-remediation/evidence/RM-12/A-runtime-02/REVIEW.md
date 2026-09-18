# Independent Astra review: corrections required

Reviewer rm03_security_rereview verified all ten source hashes and the increment.
Reservation-winner reconciliation and atomic shadow-only cap retention close the
prior findings. Complete positive operation caps must not require a plan lookup;
complete saved preload caps must remain usable when the old plan is unavailable.
The new repository parity test also uses the wrong dataclass replacement field.
Acceptance requires these corrections and a passing exact-source runtime receipt.
Review was read-only; the parent executed the isolated canonical checks.
