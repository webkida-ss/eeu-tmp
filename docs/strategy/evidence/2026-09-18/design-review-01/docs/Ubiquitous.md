# Ubiquitous Language

Shared vocabulary for the project. Add or refine a term whenever a domain
concept or naming decision is introduced or changed.

## Follow-up question (追加質問) / context chat

The free-form Q&A the learner can have with the AI about a specific piece of
text. It exists in three surfaces: a sentence in the reading panel, a study
item (word) in the word book, and an in-page text selection popup. Sent to the
backend `/chat` endpoint, which attaches page and analysis context.

## Quick action

A one-tap button in a context chat that sends a predefined message immediately
(instead of the learner typing it). Two kinds:

- **Built-in preset** — fixed quick actions shipped with the extension
  (`syntax`, `paraphrase`), with labels and prompt text defined per locale in
  `i18n.js`. Not user-editable.
- **Custom chat prompt** — a user-registered quick action, stored as
  `{ id, label, message }` in `chrome.storage.local` (`customChatPrompts`,
  max 20). Managed in the side-panel settings view and shown, after the
  built-in presets, in every context chat surface. See ADR 0002.

`label` is the button text; `message` is the prompt text sent to the AI.

## Terminal activity outcome

The final success, failure, or quota rejection of an article or context-chat
operation, together with its available usage evidence. Unknown usage is distinct
from a measured zero; this outcome is not itself a persisted activity record.

## Activity event

A persisted learner article/chat outcome with sanitized operational metadata.
Its opaque entity ID identifies the record; its source identity deduplicates
repeated recording of the same operation and terminal status within one account.
The persistence identity is `(user_id, source_id)`; another account may retain its
own event with the same source identity.

## Account control

The active or suspended access state assigned to a learner account through
administration. It is separate from the learner's paid-plan entitlement.

## Admin audit event

A record of an administrator's account-control decision, including the actor,
target, reason, and transition. It is not a learner activity event.

## Reserved usage operation

An idempotent article, chat, or analysis operation with a pinned quota and cost
snapshot. A completed result may be replayed without another provider call or
another charge.

## Reading activation

The first own-article explanation rendered for a newly signed-in reader.
A cached demonstration alone is not activation. The strategy measures this
within 24 hours of sign-in; server completion is a separate activity outcome.

## Returning reader

A reader who renders an explanation on multiple distinct days, including
cached revisits. Returning does not require consuming a new article allowance
and is not evidence by itself of improved language proficiency.

## Pending checkout operation

An account-owned purchase attempt persisted before contacting the billing
provider. Its immutable request and idempotency identity survive retries and
ambiguous failures. It does not itself grant paid entitlement.

## Checkout reconciliation

Read-only verification of provider checkout and subscription state against the
account's persisted purchase identity. A historical checkout may be identified
by its exact provider session ID when it predates operation metadata. Unknown,
conflicting or incomplete evidence cannot authorize a second purchase.

## Terminal checkout proof

Authoritative evidence that a prior purchase no longer prevents a new checkout:
an expired checkout without an attached subscription, or a subscription in a
validated terminal state. Local time expiry alone is not terminal proof.

## Entitlement provenance

The billing source that established a stored paid-plan entitlement. A local mock
activation is honored only while the application explicitly uses mock billing.
Real-provider entitlement requires a known paid plan, validated live status and
a finite period with bounded renewal grace. The stored marker alone cannot
override the application's configured billing provider.

## Content handoff ownership

The temporary right of one preload submission to publish its extracted article
content and make the operation runnable. Its operation identity, token and bounded
lease distinguish a current owner from a delayed or retried submission.

## Retired content tombstone

A small nonprivate marker replacing consumed or terminally abandoned extracted
content. It prevents a delayed conditional write from recreating content while
the marker remains. A tombstone is unavailable content, never a reusable article.

## Durable accounting evidence

Minimal account-owned operation metadata that survives private-response expiry.
It records whether provider dispatch occurred and the measured or conservative
usage needed for settlement, without retaining article text, prompts or replies.
Unknown historical dispatch state differs from explicit evidence of no dispatch.

## Pending settlement

Persisted accounting work awaiting an idempotent aggregate update. A result's
availability and the durability of its accounting are separate states; recovery
must complete the pending settlement without repeating provider execution or
counting the operation twice.

## Effective processing allowance

The sentence and source-token caps selected for one account and accounting month.
New work uses the higher of current-plan caps and retained monthly caps. Existing
operations keep their pinned month and caps. This allowance does not grant paid
entitlement or replace article, chat or cost admission rules.

## Incurred-call uncertainty

A provider invocation was attempted and raised before reporting complete usage.
The operation retains this uncertainty even when later fallback calls succeed.
Known tokens and cost remain available; conservative settlement uses the larger
of known measured cost and the pinned reservation floor, never their sum.
Client setup, preflight and dispatch-authorization failures before invocation do
not create this uncertainty.

## Proposed monetization implementation terms

These terms describe the September 18 design; their records and workflows are
not yet implemented. See [the development design](strategy/MONETIZATION_DEVELOPMENT_DESIGN.md).

| Term | Meaning |
| --- | --- |
| Product event | An allowlisted, account-scoped observation of a product interaction; it is not a billing or usage ledger entry. |
| Analytics enrollment | A trusted server record of cohort eligibility and observation start, distinguishing new, existing and unknown accounts. |
| Renewal opportunity | One expected subscription-period renewal, retained in the denominator even after advance cancellation. |
| Cost scenario | Versioned synthetic workload and explicit model, fee and FX assumptions; a simulation is not measured provider spend. |
| Deletion job | The durable progress record coordinating access blocking, confirmed cancellation and resumable erasure across stores. |
| Deletion fence | A minimal persisted guard preventing delayed sign-in, billing or worker writes from recreating data during/after deletion. |
