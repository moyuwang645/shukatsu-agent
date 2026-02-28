# shukatsu-agent — 新卒就職活動管理ツール

<div align="center">

🎯 **日本の新卒採用プロセスを自動化・管理するWebダッシュボード**

5サイト自動スクレイピング ・ AIメール解析 ・ チャット検索 ・ リアルタイム更新 ・ 面接管理

</div>

> [!WARNING]
> **🚧 このプロジェクトは現在開発中（WIP）です 🚧**
>
> 現在 **DeepSeek** でのAI適配は完了していますが、**Gemini** 向けのプロンプトチューニングはまだ調整中です。
> その他一部の機能は未実装・不安定な場合があります。フィードバックや Issue は歓迎します！

---

## 📋 現在の開発状況

| 機能 | 状態 | 補足 |
|------|------|------|
| マルチサイトスクレイピング（5サイト） | ✅ 稼働中 | マイナビ / キャリタス / 外資就活 / ワンキャリア / エンジニア就活 |
| Gmail自動連携（Cookie方式） | ✅ 稼働中 | メール解析 → 企業・面接自動登録 |
| AI解析（DeepSeek） | ✅ 稼働中 | メール解析・求人エンリッチメント・チャット |
| AI解析（Gemini） | 🔧 調整中 | アダプター実装済み、プロンプトチューニング中 |
| ダッシュボード・カレンダー | ✅ 稼働中 | 15ステータス対応、SSEリアルタイム更新 |
| 統一タスクキュー | ✅ 稼働中 | SQLiteベース優先度キュー |
| ES管理・AI生成 | ✅ 基本機能 | PDF/DOCX抽出、AI文字数厳密生成 |
| 自動エントリー（海投） | 🚧 開発中 | キュー実装済み、ボット部分は開発中 |
| OpenWork連携 | ✅ 稼働中 | 口コミスコア自動取得 |

---

## ✨ 主な機能

### 🔄 マルチサイト自動スクレイピング
- **5サイト対応**: マイナビ / キャリタス / 外資就活 / ワンキャリア / エンジニア就活
- 統一Dispatchシステム: 新サイト追加はレジストリに1行追加のみ
- Playwrightによる手動ログイン補助（CAPTCHA・セキュリティ回避）
- AI自動解析: 求人詳細ページの全文をAIで構造化（給与・福利・勤務条件）
- OpenWork口コミスコア自動取得

### 🧠 AI統合（マルチプロバイダー）
- **DeepSeek**（推奨・動作確認済み） / **Gemini**（調整中） / **OpenAI**（アダプター実装済み）
- APIキーDB管理 + AES暗号化
- チャット→キーワード生成→自動爬取パイプライン
- メール3層フィルタ（正規表現 → LLMバッチ → 深層解析）
- 求人スコアリング（ユーザー希望条件 × OpenWorkデータ）
- プロンプト外部化（`prompts/*.txt` をユーザーが直接編集可能）

### 📩 Gmail自動連携
- Cookie経由ブラウザログイン（OAuth不要）
- 定時メール自動チェック（6:00, 18:00, 2h毎）
- 面接招待 / ES締切 / 不採用通知を自動解析・登録
- メールから企業発見時に自動スクレイパー補完

### 📊 ダッシュボード & リアルタイム更新
- **SSE（Server-Sent Events）**: スクレイピング完了時にブラウザ自動更新
- 締切3日以内アラート（本選・応募済・面接中）
- 月間カレンダー連動（締切🔴・面接🔵）
- 求人カードのカンバン風管理（15ステータス対応）

### ⏰ バックグラウンド自動化
- **統一タスクキュー**: SQLiteベースの優先度付きキュー + バックグラウンドワーカー
- 定時スクレイピング（朝/夕）
- AIエンリッチメント（3時間毎）
- キーワード自動検索（10:00/15:00）
- 海投（自動エントリー）キュー

### 📝 ES・マイページ管理
- PDF/DOCX/画像からES自動テキスト抽出
- AI文字数厳密ES生成
- マイページ一括管理

---

## 🚀 セットアップ方法

### 1. 必要環境
- Python 3.10以降
- [Playwright](https://playwright.dev/python/)（スクレイピング用ブラウザエンジン）

### 2. インストール

**Linux / macOS:**
```bash
cd shukatsu-agent
chmod +x setup.sh start.sh
./setup.sh
```

**Windows:**
```cmd
cd shukatsu-agent
setup.bat
```

**手動インストール:**
```bash
cd shukatsu-agent
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

### 3. 環境設定 (`.env`)

`.env` 内の設定を自身の就活状況に合わせて編集します：

```env
# ----- 必須設定 -----
SECRET_KEY=your_secret_key_here
MYNAVI_YEAR=27                  # あなたの卒業年 (27 = 2027卒)

# ----- オプション設定 -----
HEADLESS=true                   # ブラウザ非表示
TIMEZONE=Asia/Tokyo
```

> [!TIP]
> AIキーとワークフロー設定は設定画面（`/settings`）からGUI操作可能です。`.env`に直接書く必要はありません。

### 4. 起動

```bash
# Linux / macOS
./start.sh

# Windows
start.bat

# または直接
python app.py
```

ブラウザで [http://localhost:5000](http://localhost:5000) にアクセスします。

---

## 💡 使い方とフロー

1. **初回セットアップ**: 設定画面で AIキー + マイナビログイン + Gmail Cookie設定
2. **自動同期**: スクレイパーが定時起動、メールも自動チェック
3. **チャット検索**: AIにキーワードを生成させて新規企業を発見
4. **求人管理**: ステータス管理 + 面接予定追加
5. **ダッシュボード**: 毎朝確認して今日のタスクを把握

## 🏗️ アーキテクチャ

詳細は [ARCHITECTURE.md](ARCHITECTURE.md) を参照してください。

- **Backend**: Flask, SQLite3 (WAL + DBWriter serialization), APScheduler
- **AI**: DeepSeek（推奨） / Gemini（調整中） / OpenAI (multi-provider adapters)
- **Scraping**: Playwright (async), BeautifulSoup
- **Frontend**: HTML5, Vanilla JS, CSS Variables (ダークモード, SSE)
- **Task Queue**: SQLite priority queue + background worker thread

## 📖 その他のドキュメント

- [ARCHITECTURE.md](ARCHITECTURE.md) — システムアーキテクチャ・パイプライン図
- [FUNCTION_REFERENCE.md](FUNCTION_REFERENCE.md) — 全関数リファレンス
- [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) — 開発ロードマップ・変更履歴

## ⚠️ 注意事項

- 本ツールは個人での就職活動の効率化のためのツールです。
- マイナビ等の利用規約に従い、サーバーに過度な負荷をかけないよう `chunk_size` や `wait_for_timeout` 等のスロットリング処理が実装されています。
- `data/` フォルダ（SQLiteデータベースとクッキーファイル）は個人情報が含まれるため `.gitignore` で除外されています。
- AI機能は現在 **DeepSeek** で最適化されています。Gemini対応はプロンプト調整中です。
