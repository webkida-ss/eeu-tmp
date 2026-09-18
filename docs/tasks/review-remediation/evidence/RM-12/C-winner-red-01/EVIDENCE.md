# RM-12C canonical-winner retry-loop reproduction

Parent temporarily selected the frozen C02 preload service with the new workflow
regression inside the network-denied container. Prepared and finalized winner
subcases both remain failed_pending_usage instead of terminalizing; the canonical
test task failed with two subcase failures (one enclosing test passed, eight
other tests deselected). Both exact selected sources are frozen. Shared production
sources retain the C03 checkpoint; only the preload service was reverted for this
bounded reproduction. The current service is restored before the final gate.
