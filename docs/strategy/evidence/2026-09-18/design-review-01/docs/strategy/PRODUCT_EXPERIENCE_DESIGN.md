# Product experience design: first value, revisits, and honest purchase states

Date: 2026-09-18. Status: implementation design for M03, M04, M05, and conditional
M08. This document does not authorize a launch, price, allowance, or plan change.
It follows the proposed [roadmap](MONETIZATION_ROADMAP.md),
[strategy](MONETIZATION_STRATEGY.md), and
[implementation checkpoint](IMPLEMENTATION_STATUS.md).

## Purpose and boundaries

The panel should let a reader see an original cached example, then, after sign-in, get a
first explanation from an article they chose, find saved vocabulary without new
AI work, and understand a paid action before leaving the extension. Cached
material, the word book, and accessibility features remain available on every
plan. This design adds no price, cap, trial, or plan.

The sample is bundled, original, and read-only. Rendering it must not call an
AI, preload, vocabulary, or billing API, and it must not write article or
word-book data. After M02 is available, a signed-in view may queue its
non-blocking event. The first own-article explanation is the activation
candidate; a sample view is explicitly not.

## Current foundation and change ownership

| Area | Reuse | Change proposed |
| --- | --- | --- |
| Panel and session safety | `extension/panel-ui.js` checks auth scope, clears the active preload on logout, and returns to Settings. | Add panel-only onboarding and vocabulary state bound to the same user and login scope. |
| Own-article work | Existing preload confirmation, polling, quota messages, and usage summary. | Put a permission and allowance notice immediately before the first submitted preload; do not predict a successful analysis. |
| Vocabulary | GET /vocabulary is account-scoped, newest-first, bounded to 30 preloads/600 items; items have preload ID, title, URL, and language. | Replace its unconditional current-article filter with explicit Current article / All articles controls; add cursor paging before claiming complete access beyond that bound. |
| Return navigation | Reading sessions already sync a selected study item into the vocabulary tab. | Add an Open article action using the stored URL, followed by normal status resolution rather than assuming the old page is usable. |
| Billing | GET /billing/me returns plan, quota snapshot, used/pending/remaining allowance, reset time, sentence cap, warnings, and scheduled end. Checkout is protected from duplicate paid checkout; subscribers use the portal. | Render comparison and confirmation before checkout; disable that action in flight and refresh authoritative billing state after completion or return. |

The implementation owners are extension panel/i18n, the OpenAPI source and
generated clients, reading-query projection, entitlement presentation, and the
M02 event service. The checkout provider and reconciliation rules remain owned
by the accounts boundary.

## M03: first-run path

Persist only a versioned completion marker and current step in extension local
storage. This is device-local guidance, not activation evidence; clear or ignore
it when its owner scope differs. Never put article text, URL, email, or a
credential in this state.

~~~mermaid
stateDiagram-v2
  [*] --> Welcome
  Welcome --> Sample: View original sample
  Sample --> OwnArticle: Continue while signed in
  Sample --> SignIn: Continue while signed out
  Welcome --> SignIn: Sign in required
  SignIn --> Welcome: Authentication fails or is cancelled
  SignIn --> OwnArticle: Signed in
  OwnArticle --> Permission: Eligible HTTP(S) article selected
  Permission --> Submitting: Reader confirms allowance notice
  Submitting --> OwnValue: Explanation rendered
  Submitting --> Recover: Rejected, failed, or offline
  Recover --> Permission: Retry or choose another article
  OwnValue --> [*]
~~~

1. On a first install or new scoped session, show a compact Welcome card before
   ordinary settings. State that the chosen page's HTML is sent for extraction
   and explanation. Offer View sample and Use this article; the latter focuses
   the existing preload entry point. If sign-in is needed, explain that saving
   and analyzing a personal article requires it, then use the provider-selected
   sign-in method.
2. The sample uses the ordinary Reading presentation but says, “Original sample
   — does not use your allowance.” It has a fixed explanation and one return
   action. No sample word can appear in the word book or lead to chat/analysis.
   After M02, its completed view queues sample_viewed with source sample.
3. Before first own-article submit, show the selected page title or “current
   page,” the permission statement, current remaining articles and UTC reset
   time, and that a submitted article may consume allowance. Fetch a fresh
   billing summary; pending work is included in its remaining value. Keep the
   existing overwrite confirmation for a prior preload.
4. Complete the guide only when the panel renders an explanation from a ready
   preload owned by that auth scope. A client-render failure, server completion,
   sample view, or clicked button does not complete it.

For a non-HTTP(S), inaccessible, empty, or unextractable tab, keep the sample
available and explain how to choose a supported public article. For a limit,
keep saved material reachable and show reset/support information; never present
the sample as a substitute for own-article activation.

## M04: vocabulary scope and return path

Vocabulary opens with a visible two-option selector. Current article is default
when the active page has a ready owned preload; otherwise default to All
articles and say why. Restore the last selection only for the same auth scope,
then revalidate it against the active page and response.

- Current article filters by ready preload ID where available, otherwise by
  normalized page URL. Its empty state links to the existing article preload
  action.
- All articles renders server order without client filtering and includes title
  and article context in each item's accessible name. Identical words remain
  distinct when source article or meaning differs.
- A saved-item detail keeps its read-aloud and contextual chat. Chat remains an
  explicit user action with normal usage checks; opening a detail never sends it. Open article
  opens the stored HTTP(S) URL in a tab, says the reader may need to sign in or
  reload, and requests normal preload-status resolution. It queues
  word_revisited only after the reader opens the saved item; it does not inject,
  scrape, submit analysis, or spend allowance.
- Pagination preserves newest-first order and scope. Deduplicate only identical
  item IDs, retain expanded-item focus when possible, and expose labelled Load
  more, loading, retry, and end-of-list states.

On logout, auth failure, account switch, or generation change during a fetch,
discard its response, maps, expansion, selector state, and pending open action.
A late response must never render another account's vocabulary. Offline/error
results keep prior in-memory rows only while scope matches, label them unable to
refresh, and offer retry; they do not report an empty book.

## M05: plan, limit, and checkout path

Before purchase, Billing must show a plain comparison: plan name,
tax-inclusive price and monthly cadence from a server-authorized offer, article
and chat allowances, per-article sentence cap, reset timing, and cancellation/
manage route. Do not display provider costs or tokens, or claim a plan is
unlimited. Do not show a purchasable Max offer until M01 approves its economics
and the server identifies it as sellable.

~~~mermaid
stateDiagram-v2
  [*] --> Summary
  Summary --> Offer: Basic and a sellable offer exist
  Summary --> Manage: Paid plan active
  Offer --> Confirm: Reader chooses an offer
  Confirm --> Starting: Required comparison acknowledged
  Starting --> ExternalCheckout: Server returns checkout URL
  Starting --> Activated: Verified mock activation
  Starting --> Conflict: 409 or ownership ambiguity
  ExternalCheckout --> Summary: Panel is revisited
  Activated --> Summary: Refresh succeeds
  Conflict --> Summary: Refresh or support path
~~~

Use GET /billing/me for current allowance, warning, scheduled cancellation, and
current-versus-retained quota-plan wording. Remaining includes pending
operations, so repeat it near a blocked action. A 402/429 after a positive
summary is an honest unexpected-limit state: retain the safe server reason, say
that displayed allowance was insufficient, preserve cached revisits, and offer
reset/support guidance. Do not invent a hidden-budget explanation.

For Basic, the primary action opens a confirmation card; only its confirmed
button invokes checkout. Viewing the comparison queues upgrade_viewed; server
records checkout. Disable that button and plan selection in flight. On retry,
reuse the server's existing idempotent checkout behavior. A 409 says a
checkout or subscription already exists and directs the reader to refresh or
manage billing; never create a new purchase automatically. Paid readers see
Manage billing, not a second checkout; scheduled cancellation shows the
returned end date. Network failure leaves the card open with Retry, does not
claim checkout opened, and never changes local plan state. “Checkout opened”
means only that a URL opened; an entitlement changes only after later verified
billing summary refresh.

The server must enforce offer sellability at checkout, not just hide a button.
Keep existing paid Max entitlement and management visible even when new Max sales
are disabled. A proposed offer version identifies the exact displayed price,
cadence and restrictions. Checkout binds to that version and the configured
provider price; stale/missing acknowledgement after enforcement is enabled yields
a controlled refresh/update response, never a silent price change. Roll out the
new client and additive offer contract before enabling this server requirement.
Legacy clients must not bypass the sellability gate. The design changes no current
checkout contract or existing subscriber terms.

## M08: conditional revisit prompt

Build M08 only after M04 shows meaningful saved-material return use and M02 can
measure it. On panel open, after successful scope-safe vocabulary load, show at
most one dismissible prompt when the all-article book has a recent item from a
different article and no current preload needs attention. The prompt names no
article content until the reader opens it, links to the word book, and never
triggers AI or navigation. Dismissal queues revisit_prompt_dismissed. Store
dismissal/frequency only in scoped local state; reset on logout/account change.

Do not prompt during first-run, preload/checkout processing, error/limit state,
or when no saved material exists. It makes no progress, streak, or learning
claim and adds no email or notification channel.

## API and event deltas: proposals only

1. M02 first supplies the account-scoped, deduplicated client events
   sample_viewed, explanation_rendered, word_revisited, upgrade_viewed, and
   revisit_prompt_dismissed. For sample/explanation events, use its defined
   source values (sample or own_article) and rendering values (new or cached).
   Stable source identity, the owner/auth-generation-bound queue, its 100-event
   limit, 24-hour retry horizon, and M02 retention/deletion apply. Emit no
   text, URL, prompt, email, credential, price/cost field, or raw provider
   error. Server terminal activity remains work-completion evidence; the
   server records sign-in and checkout, and verified billing remains
   entitlement evidence.
2. Add a read-only, server-authorized offer projection before enabling M05:
   sellable plan IDs, display price/currency/tax treatment/cadence, customer
   limits in existing public units, and manage/cancellation copy keys. Omit
   unsellable plans and internal token/cost controls.
3. Extend GET /vocabulary before claiming complete access beyond 30 preloads/600
   items: opaque
   cursor, requested bounded page size, next cursor, and stable snapshot/order
   semantics. Ownership derives from the session; the client sends neither user
   ID nor arbitrary article URL. Generate contract artifacts from OpenAPI.

## Acceptance and regression evidence

| Scenario | Expected evidence |
| --- | --- |
| New reader views sample, signs in, then analyzes own article | Sample emits sample_viewed; activation uses explanation_rendered with own_article only after the owned explanation renders; allowance is disclosed before submit. |
| Signed-in reader has no allowance or is offline | No own preload starts; loaded vocabulary remains usable; reset/support/retry copy is clear and localized. |
| Articles A and B have saved items | Current mode shows only A; All articles reaches A and B across pages; opening B creates neither analysis nor allowance usage. |
| Logout/account switch during vocabulary, onboarding, or checkout | Late result is discarded; no prior user's content, guide, or checkout state appears. |
| Basic, Pro, and Max states | Only sellable offers appear; comparison precedes checkout; active paid users use the portal; Max has no impossible upgrade action. |
| Timeout, repeat click, provider conflict, verified return | One disabled in-flight action; no duplicate client request; conflict gives refresh/manage guidance; plan changes only after authoritative summary. |
| Keyboard, screen reader, reduced motion, ten locales | Controls have labels, selected/expanded state, non-duplicated live messages, visible focus, no motion dependency, and every new string has every supported translation. |

Roll out behind a panel feature flag after M02 fixtures prove event
deduplication and scoped races. Enable the bundled sample and current/all
selector first, then offer comparison, then the conditional revisit prompt only
after observed demand. Roll back by hiding new panel entry points and stopping
their client events; retain existing preload, saved items, entitlement, and
checkout reconciliation data. M03–M05 depend on M02's privacy-safe event
contract; M05 also depends on M01's approved sellable-offer inputs; M08 depends
on M04 return-use evidence. Release, pricing, provider configuration,
production rollout, and external communication remain separately owned and
require their own approvals.
