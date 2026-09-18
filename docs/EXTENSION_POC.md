# Chrome Extension PoC

## 実装済み

- 解析モードON/OFF
- APIサーバーURL設定
- ページ上の文字選択検知
- AI解析結果ポップアップ
- 例文帳保存

## 解析内容

選択した英文に対して、以下を日本語で返す。

- 自然な訳
- 構文・文法
- ニュアンス
- 重要語彙
- 例文
- 学習の一言

## 開発時の確認手順

1. `backend/.env.example` を `backend/.env` にコピーし、`OPENAI_API_KEY` を設定する。
2. `backend` を `uvicorn main:app --reload --port 18765` で起動する。
3. Chromeの `chrome://extensions` で `extension/` をLoad unpackedする。
   - For development, also run `extension/dev.sh`: it
     starts a local reload server that watches the extension source and tells
     the unpacked extension (via a dev-only WebSocket client in background.js,
     active only on unpacked installs) to reload itself on every file change —
     no manual reloading at `chrome://extensions` needed. Reload the extension
     manually once after first adding the client; content scripts on open tabs
     still need a page refresh.
4. 拡張機能ポップアップで解析モードをONにする。
5. BBCなどの英語ページを開き、英文を選択する。
6. 解析ポップアップが表示されることを確認する。

## 既知の制約

- Chrome拡張機能はスマホChromeでは使えない。
- PDFや特殊なWebアプリでは選択位置の取得が安定しない場合がある。
- 選択ごとにOpenAI APIを呼ぶため、短時間に大量選択するとコストが増える。
- PoCでは保存先がローカルJSONなので、複数端末同期はできない。

## UX改善候補

- ダブルクリック時は単語用の短い解説にする。
- 長文選択時は「全文訳」と「構文解析」を分ける。
- 同じ選択テキストはキャッシュしてAPI呼び出しを減らす。
- サイドパネル表示モードを追加する。
- 解析モードON時にツールバーアイコンの見た目を変える。
