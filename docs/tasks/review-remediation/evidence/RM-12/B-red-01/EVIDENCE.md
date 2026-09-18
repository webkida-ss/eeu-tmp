# RM-12B behavioral reproduction

Frozen accepted-A pipeline and new provider-stub regression source reproduce
three actual failures: Max 300 loses the last 50 of 250 sentences through the
one-shot, agent tool and mechanical fallback paths. One lower-plan/default test
and two subtests pass. Canonical test:backend:unit ran in the network-denied
container, with only this file selected; command exit 201 reflects test failure.
