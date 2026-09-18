# RM-11B initial API regression checkpoint

Four new tests ran against the accepted A source in the isolated container.
All failed because UsageMeter does not yet accept durable_shadow. This confirms
the new API is absent; it is not behavioral evidence for all failure windows.
Task returned 201 after pytest failed. No B production source was tested here.

The final suite must additionally observe settlement at the actual ready write,
recover from nonterminal work after result expiry, and settle a same-account
operation across a month boundary. The initial terminal-replay tests alone do
not establish those stronger guarantees. Parent requested those additions.
