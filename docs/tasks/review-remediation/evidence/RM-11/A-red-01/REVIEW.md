# RM-11A independent regression-design review

Astra reviewed only this frozen test packet, without runtime or changing source.
Two race oracles were too permissive: successful dispatch promotion could still
end released, and successful completion at cost 17 could settle at cost 13.
The owner must correlate each observed winner with its exact accounting result,
require one reclaim/terminal event, and fence the losing transition.

Start barriers alone do not force both critical orders. Add controlled
interleavings, timeouts on synchronization and an outer terminating boundary
for deadlock probes; a future timeout does not bound executor shutdown.
Privacy coverage must inject nested private usage fields and assert strict
accounting whitelists. Add actual JSON TTL/sweeper coverage alongside manual
deletion and fake Dynamo native TTL deletion.

Callback failure and unknown/partial usage cases are useful. Parent assigned the
corrections before integrated acceptance; this packet does not pass review yet.
