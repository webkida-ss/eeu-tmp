# RM-12C corrected-rate failure reproduction

With valid positive rates, four focused workflow tests passed and three failed.
All three failures reproduce known-cost loss after the first completed-evidence
write fails before committing: enforced preload, durable shadow preload and
synchronous response-building failure. C02 source corrections are required.
The parent ran canonical test:backend:unit in the network-denied container.

The enforced failed-preload test's later article oracle was independently found
to require 1, preserving existing enforced quota semantics; shadow failure remains
0. That assertion was not reached at this checkpoint because cost17 became13.
