# RM-11B expanded adapter regression checkpoint

Two exact adapter sources and the expanded regression file are frozen. Canonical
lint, formatting and 69 tests / 22 subtests passed in the isolated container.
The receipt records exit zero.

Cases cover failed-before dispatch fencing, outcome validation and terminal
replay, aggregate failure/retry, separate-instance settlement and reclaim orders,
account/month pinning and unavailable pricing with partial usage. The latter
winner-order cases are sequential, so deterministic competing preparation and
Dynamo parity for two boundary guards remain requested by independent review.
No preload integration acceptance is implied.
