# Quick-Action Visibility Toggle + Meaning Preset — 設計

- 日付: 2026-07-20
- 状態: 設計合意済み（実装計画待ち）
- 関連: ADR 0002（カスタムプロンプト）、`docs/superpowers/specs/2026-07-20-custom-chat-prompts-design.md`

## 目的

追加質問（context chat）のクイックアクションに、2つの機能を足す。

- **A. 意味理解プリセット**: 文の意味・意図を尋ねる組み込みプリセットを追加（構文解析ではなく意味理解）。
- **B. 表示/非表示トグル**: ボタンを削除せずに隠せるようにする。組み込みプリセット・カスタム両方に適用。

## A. 意味理解プリセット

- 組み込み quick action の id に `meaning` を追加（既存 `syntax` / `paraphrase` と並ぶ3つ目）。
- `SENTENCE_QUICK_CHAT_ACTIONS`（shared.js）に `'meaning'` を追加 → 文・選択の追加質問に表示（単語画面は従来どおりカスタムのみ）。順序は `syntax` → `paraphrase` → `meaning`。
- `getQuickChatAction` に `meaning` の分岐を追加（`t('quickMeaningLabel')` / `t('quickMeaningMessage')`）。
- 全10ロケールに `quickMeaningLabel` / `quickMeaningMessage` を追加。
  - ja ラベル: 「意味理解」
  - ja 本文: 「この文の意味を日本語でわかりやすく説明してください。文法や構文の分析ではなく、この文が全体として何を言おうとしているのかを、含意やニュアンスも含めて理解できるように説明してください。」

## B. 表示/非表示トグル

### データモデル / 保存
- `chrome.storage.local` に新キー `hiddenQuickActions`（非表示にした id の配列）。
- id はプリセット（`syntax` / `paraphrase` / `meaning`）でもカスタム（UUID v7）でも同じ枠で扱う。仕組みが1つで済む。
- settings.js に追加:
  - `HIDDEN_QUICK_ACTIONS_KEY = 'hiddenQuickActions'`
  - `normalizeHiddenQuickActions(value)`（配列ガード、空文字除外、重複除去、文字列化）
  - `toggleHiddenQuickAction(list, id)`（純粋関数: id があれば外す／なければ足す、正規化して返す）
  - `getHiddenQuickActions()` / `setHiddenQuickActions(list)`（chrome.storage.local アクセサ）

### 表示ロジック（shared.js）
- 非表示キャッシュを追加（`customChatPromptsCache` と同型）: `hiddenQuickActionsCache`、`getCachedHiddenQuickActions()`、`setHiddenQuickActionsCache(list)`、`loadHiddenQuickActionsCache()`。
- `initCustomChatPrompts()` を拡張し、非表示キャッシュも起動時ロード。`chrome.storage.onChanged` の監視を `HIDDEN_QUICK_ACTIONS_KEY` にも拡張。
- `resolveQuickChatActions(actionIds, customPrompts, hidden = getCachedHiddenQuickActions())` を後方互換で拡張:
  - hidden セットに含まれる id を、**組み込み・カスタムとも除外**してから `{label, message}` に整形。
  - 除外は id で行い、resolve 結果の形（`{label, message}`）は現状維持（既存の描画・テストに影響しない）。

### 設定UI（panel-ui.js / sidepanel.html）
- 現在の「追加質問のカスタムボタン」セクションを、**プリセットも含む管理一覧**に拡張する。
- 一覧は2グループ:
  1. **プリセット**（`SENTENCE_QUICK_CHAT_ACTIONS` の各 id）… ラベル（`getQuickChatAction(id).label`）＋ **表示/非表示トグルのみ**（編集・削除・並び替えなし）。
  2. **カスタム**（`getCachedCustomChatPrompts()`）… 表示/非表示トグル＋編集＋削除＋▲▼（既存）。
- トグル: 1行1ボタン。表示中なら「非表示」、非表示中なら「表示」を出す（`title`/`aria-label` 付き）。押すと `toggleHiddenQuickAction` → 保存 → キャッシュ更新 → 再描画。
- 非表示の行は薄く表示（`is-hidden` クラス）。削除とは独立（隠すだけ）。
- 新 i18n キー（全ロケール）: `customPromptShow`（表示）、`customPromptHide`（非表示）、`customPromptsPresetGroup`（プリセット）、`customPromptsCustomGroup`（カスタム）。

### バックエンド
- 変更なし。

## スコープ外
- プリセットの編集・削除・並び替え（表示/非表示のみ）。
- 非表示状態のデバイス間同期（`chrome.storage.sync` は使わない）。

## エッジケース
- `hiddenQuickActions` にもう存在しないカスタム id が残っても無害（除外対象が無いだけ）。カスタム削除時に掃除は必須ではない。
- すべてのプリセット＋カスタムを非表示にした場合、クイックアクション行は描画されない（自由入力欄は残る）。
- 未設定キー → 空配列。
- 反映は既存同様キャッシュ＋`onChanged` 経由（サイドパネル編集がコンテンツスクリプト側にも伝わる）。
