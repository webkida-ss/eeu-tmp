# 追加質問のカスタムプロンプト — 設計

- 日付: 2026-07-20
- 状態: 設計合意済み（実装計画待ち）

## 目的

追加質問（context chat）に、ユーザーが自分で登録・管理できるカスタムプロンプトボタンを追加する。既存の組み込みプリセット（`syntax` / `paraphrase`）はそのまま維持し、その上にユーザー登録分を重ねる「組み込み＋ユーザー追加」構成とする。

## 現状

追加質問は3つの画面に存在する。

- 文単位（reading-panel）: 組み込みプリセット `syntax` `paraphrase` あり
- 選択ポップアップ（content）: 組み込みプリセット `syntax` `paraphrase` あり
- 単語 / 学習アイテム: プリセットなし

プリセットは `extension/shared.js`（`SENTENCE_QUICK_CHAT_ACTIONS`, `getQuickChatAction`, `renderContextChat`）と `extension/i18n.js`（ラベル・本文）にハードコードされており、ユーザーが編集する手段はない。チャット本文は `CHAT_FOLLOW_UP` 経由で `POST /chat` に送られ、バックエンドが文脈（context_text / analysis 等）をシステムプロンプトに付加する。

## スコープ

### 含む
- カスタムプロンプトの登録・編集・削除・並び替え（サイドパネル設定ビュー）
- 全チャット画面（文・単語・選択）へのカスタムボタン表示（グローバル1リスト）
- `chrome.storage.local` への永続化

### 含まない
- 組み込みプリセットの編集・削除（固定のまま）
- プロンプト本文内のプレースホルダ／テンプレート変数（文脈はバックエンドが付加するため不要）
- バックエンド変更（既存の `/chat` 経路をそのまま利用）
- `chrome.storage.sync` によるデバイス間同期

## 設計

### 1. データモデル / 保存

- `chrome.storage.local` に新キー `customChatPrompts` を追加。値は配列 `[{ id, label, message }]`。
  - `id`: `crypto.randomUUID()` で生成する安定な識別子
  - `label`: ボタン表示名（1行）
  - `message`: 送信されるプロンプト本文（複数行可）
- `extension/settings.js` にアクセサを追加: `getCustomChatPrompts()` / `saveCustomChatPrompts(list)`。既存アクセサと同じ流儀。キー未設定時は `[]` を返す。
- 保存先は既存設定と揃えて `local`。`sync` は 1 項目 8KB / 全体 100KB の制限があり、認証もサーバー側のため採用しない。
- 上限件数: 20 件。超過時は追加を拒否しメッセージ表示。

### 2. 表示・送信

- `renderContextChat(chatKey, { quickActions })` を活用。`quickActions` を「組み込み(id文字列) ＋ カスタム(`{label, message}`)」の混在に対応させる。
  - `getQuickChatAction` を拡張するか、レンダー直前に全項目を `{ label, message }` に正規化する。組み込みは i18n から解決、カスタムはストレージ値をそのまま使う。
- 各画面のボタン並び順は **組み込み → カスタム**。
  - 文（reading-panel）: `syntax` `paraphrase` ＋ カスタム
  - 選択（content）: `syntax` `paraphrase` ＋ カスタム
  - 単語 / 学習アイテム: カスタムのみ（組み込みは文構造向けのため単語では出さない）
- カスタムボタンのタップ挙動は組み込みと同じく **即送信**（`message` をそのまま送る）。
- カスタムが0件の場合、カスタムボタンは描画しない（単語画面は従来通り何も出ない）。
- 反映の仕組み: `renderContextChat` は同期処理で、`chrome.storage` は非同期のため、カスタムプロンプトはメモリキャッシュ経由で描画する。読み込み時（サイドパネル／コンテンツスクリプトのロード時）にキャッシュを温め、`chrome.storage.onChanged` で更新を反映する。これによりサイドパネルでの編集がコンテンツスクリプト側（別コンテキスト）にも伝わる。

### 3. 管理UI（サイドパネル設定ビュー）

- `extension/sidepanel.html` ＋ `extension/panel-ui.js` の設定ビューに「追加質問のカスタムプロンプト」セクションを新設。専用オプションページ（`options_ui`）は作らず、既存設定ビュー内に置く。
- 構成:
  - 登録済みカスタムの一覧（ラベル表示）。各行に「編集」「削除」「▲▼（並び替え）」。
  - 「追加」ボタン → ラベル（input）＋ 本文（textarea）の入力フォーム。
- バリデーション: `label` と `message` はともに必須（空白のみは不可）。件数が上限（20）に達したら追加不可。
- 保存操作で `saveCustomChatPrompts` を呼び、`chrome.storage.local` を更新する。

### 4. i18n

- 設定UIの新規文言（例: セクション見出し、「追加」「編集」「削除」「ラベル」「本文」「上限に達しました」等）を全ロケール（ja/en/zh/ko/fr/de/es/it/pt/ru）に追加。
- 組み込みプリセット（`quickSyntax*` / `quickParaphrase*`）の文言は変更しない。

### 5. テスト / 検証

- `settings.js` のアクセサ（未設定→`[]`、保存→取得の往復）と、quickActions 正規化ロジック（組み込み＋カスタム混在→`{label, message}` 配列）にユニット的なカバレッジを追加。JSテストハーネスがあればそこへ、無ければ既存の extension smoke-test で経路を確認する。
- 手動確認:
  - 文・単語・選択の3画面すべてでカスタムボタンが表示され、送信できる
  - カスタム0件時の挙動（単語画面で何も出ない、文/選択は組み込みのみ）
  - 追加 / 編集 / 削除 / 並び替え
  - 上限（20件）到達時の追加拒否

## エッジケース

- キー未設定（初回）→ 空配列として扱う
- 長いラベル → 既存のチップ折り返し表示（commit d7b360f と同じ）に従う
- ラベル重複 → 許容（`id` で区別）
- 本文が非常に長い → 送信は既存 `/chat` の扱いに委ねる（追加の切り詰めはしない）
