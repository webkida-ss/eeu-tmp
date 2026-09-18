# Untangle Architecture

## Goal

英語記事を読んでいる最中の「分からない単語や文章をコピーしてAIに聞く」手間を減らす。

PoCではPCブラウザ体験を優先し、Chrome拡張機能でページを離れずにAI解説を表示する。

## User Flow

1. ユーザーがChrome拡張機能のポップアップで解析モードをONにする。
2. BBCなどの英語記事ページで英文を選択する。
3. 拡張機能のContent Scriptが選択テキストを検知する。
4. Background Service Worker経由でローカルAPIに送信する。
5. ローカルAPIがOpenAI APIに問い合わせる。
6. ページ上に訳・構文・ニュアンス・語彙・例文を表示する。
7. 必要なら「例文帳に保存」でローカルJSONに保存する。

## Components

```text
Chrome Extension (extension/)
  manifest.json
    - MV3 manifest. Content scripts: settings.js, shared.js, content.js.

  settings.js
    - Storage-backed settings and auth session helpers, page URL
      normalization, and the learner's language pair (target language
      being studied + native language used for explanations; the target
      can be auto-detected from the page's lang attribute). Loaded in
      every context (page, panel, worker).

  i18n.js
    - UI localization. Message catalogs for all ten supported languages
      plus t()/setUiLocale() and DOM translation helpers. The UI locale
      follows the native (explanation) language, so panel labels, chat
      prompts, quick-action AI requests, status and error messages all
      render in the learner's language. Also provides locale-aware
      learner-level presets (TOEIC/Eiken for Japanese, CEFR otherwise).

  shared.js
    - Context-free utilities shared by the page and the panel: text
      normalization and matching, preload model helpers, analysis
      rendering, and the context chat UI.

  content.js / content.css
    - Runs on web pages: selection detection and analysis popup,
      sentence/vocabulary anchoring and highlighting in the article,
      preload orchestration, launcher button, and the in-page panel
      shell (an iframe hosting sidepanel.html).

  sidepanel.html / panel-ui.js / panel-ui.css
    - Panel document (loaded inside the in-page iframe) with three
      top-level tabs: settings (login, per-site toggle, languages,
      learner level, preload controls), reading (container for the
      reading view), and the word book — the single home for
      vocabulary, aggregating /vocabulary across articles with the
      current article pinned first, expandable entries (example,
      jump-to-text, follow-up chat), and per-word read-aloud.
      Vocabulary marks clicked on the page open here.

  reading-panel.js / reading-panel.css
    - Reading view inside sidepanel.html: sentence list and detail
      only (vocabulary lives in the word book), read-aloud, context
      chat, theme toggle, and the continuous read-aloud mode (audio
      bar with play/pause, sentence skip, adjustable rate; the
      current sentence follows along in the panel and on the page).
      Exposed as window.ReadingPanel, including the shared
      read-aloud primitives the word book reuses.

  background.js
    - Service worker: message hub between page and panel, API client
      for the local backend, content script injection, preload job
      state, and badge updates.

Backend (backend/) — layered so the handler
layer is swappable (uvicorn/FastAPI locally today; an AWS Lambda
handler can replace it without touching the layers below):

  schemas.py
    - API contracts (pydantic only). Shared by every handler layer.

  core/pipeline.py
    - The AI reading pipeline: article extraction, sentence
      splitting (one-shot + agent fallback), parallel batch analysis
      behind the OpenAI concurrency semaphore, study-item selection,
      and prompt building. Framework-free; failures raise
      PipelineError with a transport hint instead of HTTP exceptions.

  services/ (reading.py, entitlements.py, usage_meter.py)
    - Use cases: preload creation/status, vocabulary book, selection
      analysis, chat, phrases, and plan entitlement checks with
      monthly usage metering. Orchestrate core/ and the repositories;
      no FastAPI imports (test_handler_independence.py enforces this
      in a fresh interpreter).

  accounts/
    - The shared account foundation: sign-in (mock/Google via
      AUTH_PROVIDER) and subscriptions (mock/Stripe via
      BILLING_PROVIDER), including their HTTP routes. Self-contained
      and byte-identical with the copy in the `realtime` repository so
      it can later become an installed package; see
      backend/accounts/README.md. It knows plan *identifiers* only —
      what a plan allows stays in services/entitlements.py.

  repositories/, storage/, auth/
    - Ports and adapters: Protocol-typed repositories with JSON and
      DynamoDB implementations (STORAGE_BACKEND), plus the DynamoDB
      adapter for the accounts AuthService port.

  main.py + deps.py
    - The FastAPI adapter: routes parse HTTP, call one service
      function, and map domain errors (PipelineError,
      IdentityVerificationError, ValueError) onto HTTP responses.
      deps.py wires concrete adapters via FastAPI Depends. A Lambda
      handler would replace exactly these two files (or wrap `app`
      with an ASGI adapter such as Mangum).

  Endpoints (main.py)
    /health
      - Health check.

    /auth/config, /auth/login, /auth/me, /auth/logout
      - SSO-shaped sign-in, served by the accounts router. An
        IdentityProvider (chosen by AUTH_PROVIDER and injected via DI)
        verifies the credential: the mock provider accepts
        "mock:<email>" locally, the Google provider verifies Google ID
        tokens in production. Sessions are issued and stored by the
        AuthService (JSON or DynamoDB).

    /analyze
      - Sends selected text to the OpenAI API and returns a JSON
        analysis.

    /pages/preload
      - Asynchronous lifecycle. POST extracts the article text (fast,
        no OpenAI), saves a `status: "processing"` record, enqueues a
        job, and returns HTTP 202; the slow split + analyze runs off
        the request path (inline thread locally, SQS + worker Lambda on
        AWS), so it is not bound by API Gateway's 30-second integration
        cap. GET returns the record with `ready` = record exists AND
        status in (null, "ready"); a "failed" record surfaces `error`.
        Records saved before this lifecycle carry no status and are
        treated as ready. The client polls GET until ready or failed.

    /chat
      - Follow-up questions about a sentence, vocabulary item, or
        selection.

    /vocabulary
      - Cross-article word book: study items aggregated from the
        user's preloaded articles, newest first, with source article
        and language metadata.

    /phrases
      - Lists and registers saved expressions.

    /billing/checkout, /billing/portal, /billing/webhook, /billing/done
      - Subscription management, served by the accounts router. The
        billing provider (mock or Stripe) is injected via DI; see
        docs/BILLING.md.

    /billing/me
      - Untangle's own view of the plan: monthly article/chat quotas
        and what is left of them. Stays in main.py because quotas are
        application-specific.
```

## Data

PoCではDBを使わず、`backend/data/phrases.json` に保存する。

本番化する場合はSupabase/PostgreSQLなどに移行し、ユーザーID単位で保存する。

## Security

PoCではローカルサーバー前提のため、APIキーは `backend/.env` に置く。

本番化する場合は以下を追加する。

- 拡張機能からのログイン
- JWTによるAPI認証
- ユーザー単位のレート制限
- サーバー側でのExtension Origin検証
- AI利用量の上限管理

## Future Ideas

- Webアプリで例文帳を閲覧・編集する
- 単語・例文から復習カードを生成する
- 読んだ記事と保存した表現を紐づける
- モバイル向けにPWAリーダーを追加する
