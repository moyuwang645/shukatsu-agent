# 開発ロードマップ（永久参照用）
# ⚠️ このファイルは追記のみ。既存の内容を削除・変更しないこと。
# ⚠️ This is an append-only reference. Do NOT delete or modify existing content.
# 最終更新: 2026-02-26

> **🤖 Antigravity Global Rule: Automated Documentation Sync**
> 毎回大きな機能（Feature）やアーキテクチャの変更を完了した後、ユーザーに通知（Notify User）する前に、**必ず**自発的に `DEVELOPMENT_ROADMAP.md` の履歴と `ARCHITECTURE.md` の図（Mermaid）を更新すること。プロンプトによる指示を待たず、コードの変更に合わせてドキュメントと図表を同期させること。

---

## TODO 3: スクレイパーAI統合

### 目的
スクレイパーが取得する求人の詳細ページ全文をAIで解析し、
給与・福利厚生・勤務条件等の構造化データを自動抽出する。

### 変更後パイプライン
```
BaseScraper._run_pipeline()
  → login()
  → job_fetcher() → list[dict]  （従来通り）
  → [NEW] _enrich_with_ai(jobs)
    → 各jobに対して (6s間隔):
      → fetch_detail_text(job_url) → 全文テキスト
      → ai/job_detail_parser.py: parse_job_detail_with_ai(text)
        → call_llm() → {salary, location, description, benefits, ...}
      → jobデータにマージ
  → upsert_job_from_scraper(enriched_job)
```

### 新規ファイル: ai/job_detail_parser.py

```python
def parse_job_detail_with_ai(
    raw_text: str,
    company_name: str = '',
    existing_data: dict = None
) -> dict | None:
    """Parse a scraped job detail page using AI.

    Args:
        raw_text: Full text content (max 3000 chars).
        company_name: Company name for context.
        existing_data: Already-extracted fields (skip these).

    Returns:
        dict: position, salary, location, benefits,
              job_description, work_style, requirements,
              deadline_date, industry
        None: if AI not configured.
    """
```

### BaseScraper 追加メソッド

```python
async def fetch_detail_text(self, url: str) -> str:
    """Fetch a detail page and return cleaned text.
    Uses browser context HTTP request (no navigation).
    """

async def _enrich_with_ai(self, jobs: list, max_per_run: int = 20) -> list:
    """Enrich job dicts with AI-parsed detail page data.
    Rate: 6s/call (10 calls/min). Skips ai_enriched=1 jobs.
    """
```

### 各サイト実装スコープ

| サイト | 既存の詳細取得 | AI統合方法 | 難易度 |
|--------|-------------|-----------|--------|
| mynavi | ✅ `_fetch_employment_details_fast` (HTML table解析済) | 既存テキストをAIに渡す | 低 |
| career_tasu | ✅ `_fetch_detail` (HTML解析済) | 既存テキストをAIに渡す | 低 |
| gaishishukatsu | ❌ SPAリスト表のみ | `fetch_detail_text(/view/{id})`追加 | 中 |
| onecareer | ❌ | `fetch_detail_text`追加 | 中 |
| engineer_shukatu | ❌ | `fetch_detail_text`追加 | 中 |

### レート制限設計

```
速度: 6秒/件 = 10件/分（Gemini無料15RPMの67%）
1回実行: 最大20件 × 6秒 = 120秒（2分）
1日: 2回(7:00,18:30) × 20件 = 40件
```

### 既存 enrichment_service との関係

- scraper AI → 詳細ページ全文から**事実データ**抽出（給与・福利・条件）
- enrichment_service → 事実データ+ユーザー希望から**スコアリング**
- 順序: scraper AI → upsert → enrichment_service（3h後）
- scraper AI済みの求人はenrichment_serviceで**より精度の高い**スコアが出る

---

## TODO 4: 自律型スクレイパーエンジン（Self-healing Config-Driven Scraper）

### 目的
現在ハードコードされている5つのスクレイパーのCSS選択器・ナビゲーションロジックをJSON設定に外部化し、
AIによる「自動生成」「健康監視」「自動修復」を統合した自律型エンジンを構築する。

### Phase 1: 設定化エンジン ⭐⭐⭐
- 各スクレイパーの選択器・ナビゲーションをJSON設定ファイルに抽出
- 通用 `ConfigDrivenScraper` エンジンがJSONを読み取り、検索→解析→結果返却を実行
- 現有5サイト（mynavi, career_tasu, onecareer, gaishishukatsu, engineer_shukatu）を移行
- **Scrape Mode Registry（爬取モード登録制）**をdispatcher層に構築:

```python
# 拡張可能なモード定義 — 将来いくらでも追加可能
SCRAPE_MODES = {
    'full':         {'max_results': 0, 'skip_complete': False, 'description': '全件取得'},
    'incremental':  {'max_results': 0, 'skip_complete': True,  'description': '差分のみ'},
    'single':       {'max_results': 1, 'skip_complete': False, 'description': '1件のみ'},
    'health_check': {'max_results': 1, 'dry_run': True,        'description': '検証用'},
    # 将来追加例:
    # 'top_n':      {'max_results': 5, 'skip_complete': False},
    # 'monitor':    {'max_results': 0, 'notify_only': True},
}
```

#### 現状の各スクレイパー能力マトリクス

| 能力 | mynavi | career_tasu | onecareer | gaishishukatsu | engineer_shukatu |
|------|--------|-------------|-----------|----------------|------------------|
| **login** | Cookie (**手動**) | 不要 | Email/PW (任意) | Email/PW (任意) | Email/PW (任意) |
| **fetch_jobs** | ✅ ブックマーク+エントリー | ✅ 全企業一覧 | ✅ カテゴリ別イベント | ✅ SPA テーブル | ✅ 求人+イベント |
| **search_jobs** | ✅ URL直叩き+フォーム | ✅ キーワード検索 | ✅ カテゴリ+キーワード | ✅ SPA+フィルタ | ✅ URLフィルタ+キーワード |
| **pagination** | ✅ 5ページ | ❌ 1ページ | ❌ カテゴリ別 | ❌ SPA全件表示 | ✅ 5ページ |
| **AI enrichment** | ✅ 2段階(概要+採用) | ✅ 全AI抽出 | ✅ 2段階(企業+イベント) | ✅ 企業ページ | ✅ 3段階(企業+採用+職位) |
| **incremental (DB)** | ✅ pipeline層 | ✅ pipeline層 | ✅ pipeline層 | ✅ pipeline層 | ✅ pipeline層 |
| **incremental (server)** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **max_results** | ✅ (暫定) | ✅ (暫定) | ✅ (暫定) | ✅ (暫定) | ✅ (暫定) |
| **レンダリング** | SSR | SSR | SSR | **SPA** (JS必須) | SSR |

> ⚠️ **incremental の現状**: 全スクレイパーのincremental は `_run_pipeline` 内の DB ベーススキップ
> （`_is_data_complete` → skip）であり、**サーバー側の差分取得ではない**。
> 全件フェッチ後にDB照合でスキップする方式のため、ネットワーク負荷は full と同等。
> 将来サーバー側 incremental が可能なサイトが出てきた場合、capability として `server_incremental: true` を追加。

- 個別スクレイパーは爬取モードを意識しない — dispatcher/pipeline がモード定義に基づき制御
- モード追加は `SCRAPE_MODES` dict に1行追加するだけ — コード変更不要
- 現在のコード: `max_results` を各スクレイパーに渡す方式（暫定）→ P1完成時に廃止

```json
{
  "name": "mynavi",
  "search_url": "https://job.mynavi.jp/.../index/?cond=FW:{keyword}",
  "result_selector": ".entryList__item",
  "company_name_selector": ".entryList__item__name",
  "detail_url_pattern": "/corp/{id}/outline/",
  "pagination": { "type": "url_param", "param": "page" },
  "login": { "type": "cookie", "check_url": "..." }
}
```

### Phase 2: 健康監視 + 自動修復 ⭐⭐
- 毎朝固定キーワード（例: "トヨタ"）で各サイトを検索
- 結果を基準値と比較（件数・構造・レスポンスコード）
- 異常検知時: HTML取得 → AI分析 → 新選択器生成 → テスト → 設定更新
- 成功/失敗をユーザーに通知

**Dynamic Baseline Test（動的基準テスト）方式**:
- 検証時、DB から `SELECT * FROM jobs WHERE source='{scraper_name}' ORDER BY id DESC LIMIT 1` で最後の成功入庫岗位を取得
- その企業名で再検索 → 結果が正常に返ること（件数≥1, 構造正常）を確認
- 各サイトごとに独立した基準 — mynavi が壊れても career_tasu の基準は影響なし
- 追加ファイル不要、DBの既存データをそのまま活用
- 新規爬虫（DB にまだデータなし）の初回検証のみ固定キーワード（例: トヨタ）をフォールバック

### Phase 3: 新サイト自動生成 ⭐⭐⭐⭐
- ユーザーが新URLを入力 → AI が Playwright でサイトを探索
- 検索フォーム、結果リスト、詳細ページの構造を自動分析
- JSON設定を生成 → **Golden Testで検証** → 合格なら search_registry に自動登録
- 「1クリックで新しい就活サイトを追加」

### 評価

**メリット:**
- スクレイパー保守コスト激減（サイト変更時に人手ゼロ対応の可能性）
- 新サイト追加が劇的に高速化（コード不要、設定のみ）
- 安定性向上（壊れても自動復旧）
- Golden Test方式により**検証が結果ベース**で信頼性が高い

**リスク・課題:**
- P1の移行工数が大きい（5サイト×異なるロジック）
- SPA系サイト（gaishishukatsu等）はJSONだけでは表現しきれない可能性
- AI生成の精度（特にP3）は試行錯誤が必要
- ログイン方式の多様性（Cookie/OAuth/公開）の統一が困難

**総合評価: 非常に先進的で実用的 ✅**
- P1だけでも保守性が大幅改善される
- P2まで実装すれば、実質的に「放置しても動き続ける」システムになる
- P3は野心的だが、LLM技術の進化に伴い十分実現可能

---

# === 変更履歴（追記のみ）===

## 2026-02-25: 初版作成
- TODO 3 開発ロードマップ策定

## 2026-02-26: Career Tasu スクレイパーの全面的なAI抽出化
- **正規表現ベースの面倒な抽出処理を全廃**（`_fetch_detail`の130行を30行に削減、`_fetch_employment_page`を完全削除）。コードを約200行削減。
- `career_tasu.py` の全フィールド（給与、職種、勤務地、福利厚生、仕事内容、締切等）と企業詳細分析（事業、社風、選考フロー等）の抽出をすべて **DeepSeek V3 (`_enrich_with_ai`)** による1回のAI呼び出しに統合。
- AIが抽出した結果が無条件に既存の空フィールドを上書きする仕様に変更。
- DBの`deadline`に対してAIが`deadline_date`を返すマッピングを実装。

## 2026-02-26: 定時スクレイピングの致命的バグ修正
- **全5スクレイパーのクラッシュ修正**: `scrapers.stealth` への `create_context_options` import エラー解消（前セッションで追加済み）。
- **`fetch_jobs()` デッドロック修正**: `career_tasu.py` の `fetch_jobs()` で、AI抽出前に `deadline` でフィルタしていたため全件スキップされていた問題を修正。フィルタを削除し、全企業をAI解析パスに流す方式に変更。
- **バックフィル完了**: `scripts/backfill_ai.py` で71件全件AI補完完了（成功率100%）。修正前→修正後: position欠損 87%→22%, location欠損 82%→7%, industry欠損 34%→7%。

## 2026-02-26: ストリーミングパイプライン化
- **バッチ処理→逐次処理**: `_run_pipeline` を `fetch ALL → enrich ALL → save ALL` から `fetch one → enrich → save → next` に改修。中途失敗時のデータ損失防止。
- **`_enrich_with_ai(jobs)` → `_enrich_single_job(job)`**: バッチ方式の一括AI呼出しから、1企業ずつの逐次呼出しに変更。`career_tasu.py` でもオーバーライド対応。
- 進捗ログ: `[1/71] 川口薬品: NEW +AI` 形式でリアルタイム可視化。

## 2026-02-26: Unified API Task Queue & Priority Scheduling（タスク#2）
- **`db/task_queue.py` 新規作成**: `task_queue` テーブル（priority, status, params, retry_count）+ CRUD（`enqueue`, `claim_next`, `complete`, `fail`, `cancel`）。タスク重複排除（dedup）、自動リトライ（max_retries=2）、インデックス付き。
- **`services/task_worker.py` 新規作成**: バックグラウンド`TaskWorker`スレッド。12種類のハンドラー（scrape×5, enrich, email_check, keyword_search, application_queue, check_deadlines, check_interviews, cleanup_old_tasks）を登録。AI系タスク間3秒レート制限、連続失敗5回で自動停止+通知。
- **`routes/api_scheduler.py` 新規作成**: 9つのAPIエンドポイント — スケジューラ状態確認、APSchedulerジョブ一覧、タスクキュー一覧、実行履歴、手動トリガー（priority=1）、タスクキャンセル、worker制御。
- **`scheduler.py` 改修**: `run_all_scrapers()` と `run_enrichment()` をキュー投入方式に変更。APSchedulerは「いつ投入するか」のみ担当、実処理はTaskWorkerが実行。フォールバック（直接実行）も維持。
- **ドキュメント同期ルール強化**: `.antigravityrules` にchangelog形式ルール（#6）とtask.md自動更新ルール（#7）を追加。

## 2026-02-26: Cross-Site Company Data Merge（タスク#3 + #5一部）
- **`services/company_normalizer.py` 新規作成**: 会社名正規化（`株式会社`/`(株)`等の除去、全角→半角変換、スペース除去）。`normalize()` と `find_matching_job()` を提供。
- **`db/jobs.py` `upsert_job_from_scraper()` 拡張**: 3段階マッチング — ①`(source, source_id)` 完全一致 → ②正規化社名クロスソースマッチ → ③新規作成。異なるソースからの同一会社は既存レコードにマージ（空フィールドのみ補完）。
- **検証結果**: 正規化テスト8/8、等価性テスト3/3、クロスソースマージテスト（source_a + source_b → 同一レコード id に統合、既存データ保護+欠損補完）全合格。

## 2026-02-26: Structured Logging（タスク#6）
- **`db/activity_log.py` 新規作成**: `activity_log` テーブル（category, message, level, details JSON）+ CRUD。カテゴリ・レベルフィルタリング、今日の統計集計、30日超のログ自動クリーンアップ。
- **API追加**: `GET /api/scheduler/logs` (カテゴリ/レベル/ページネーション付き)、`GET /api/scheduler/logs/stats`(今日のサマリー)。
- **TaskWorker統合**: タスク完了/失敗時に自動で `log_activity()` を呼び出し、構造化イベントをDBに記録。連続エラー5回で通知も発行。

## 2026-02-26: Job Card Convergence（タスク#5）
- **`event_detector.py` リファクタリング**: 重複していた `_normalize_company_name()` を `services/company_normalizer.normalize()` に統合。
- **Email-trigger-scrape 実装**: `match_or_create_job()` でメールから新規企業作成時、自動で `keyword_search` タスク（priority=4）をキューに投入。メール→スクレイピングの自動ループ完成。
- **Frontend**: バックエンドの `upsert_job_from_scraper()` + `company_normalizer` による dedup で、実質的に一企業一カード化済み。

## 2026-02-26: Architecture Bug Fixes（7件）
- **BUG-1~3 修正**: `shutdown_scheduler()` にTaskWorker停止追加、`_recover_stuck_tasks()` 起動時リカバリ、`upsert_job_from_scraper()` 接続リーク修正。
- **`get_db_connection()` コンテキストマネージャ追加**: `db/__init__.py` に安全な接続管理。`db/jobs.py` (15関数), `db/notifications.py` (5), `db/preferences.py` (7), `db/activity_log.py` (5), `db/task_queue.py` (12) — 計44関数を変換。
- **`claim_next()` 原子性改善**: `BEGIN EXCLUSIVE` トランザクションで競合条件を完全排除。
- **Scheduler enqueue 移行**: `run_application_queue()`, `check_deadlines_today()` をタスクキュー投入方式に変更。

## 2026-02-26: SSE Real-time Push 完成 & キーワード検索dedup修正
- **SSE `updated` イベント追加**: `update_job()` と `update_job_enrichment()` に `publish_job_event('updated', ...)` を追加。スクレイパー更新やAI enrichment完了時にフロントエンドへリアルタイム通知。
- **フロントエンド `updateJobCard()` 実装**: SSE `updated` イベント受信時に既存カードの内容をDOM操作で即座に更新（会社名、職種、勤務地、給与、締切、ステータス、AI分析）。更新時にflashアニメーション付き。
- **キーワード検索dedup修正**: `_run_keyword_search()` が `params` を無視して全preferencesキーワードを検索していたバグを修正。`keywords_override` パラメータ追加により、メール検出時は特定企業名のみ検索。定時タスクは従来通り全キーワード検索。

## 2026-02-27: キーワードDispatcher + Email Backfill
- **`scrapers/__init__.py` 新規作成**: 統一検索レジストリ `get_search_registry()` に全5スクレイパーを登録（従来は2つのみハードコード）。`dispatch_search(keywords, mode, job_id, scrapers)` で3モード（scheduled/email_backfill/one_shot）+ スクレイパー選択フィルタ。
- **`scheduler/keyword_tasks.py` リファクタ**: ハードコードされた2スクレイパーマップを `dispatch_search()` 呼び出しに置換。`scrapers` パラメータで選択的実行対応。
- **`services/email_backfill.py` 新規作成**: メール検出企業のバックフィル薄ラッパー。`dispatch_search(mode='email_backfill')` → 検索 → 最良マッチを既存emailジョブにマージ。`update_job(force=False)` でメールデータ優先。
- **`services/event_detector.py` 修正**: `keyword_search` → `email_backfill` タスクタイプに変更。`job_id` を渡して既存ジョブへのマージを実現。メール企業名での無関係ジョブ生成バグ解消。
- **`services/task_worker.py` 修正**: `email_backfill` ハンドラー登録 + AI限速リスト追加。`keyword_search` にも `scrapers` フィルタ対応。
- **`scrapers/career_tasu.py` 修正**: `search_jobs()` のシグネチャを `filters` パラメータ追加で基底クラスに統一。

## 2026-02-27: 統一Dispatch + 多頭管理解消
- **`scrapers/__init__.py` 全面リファクタ**: 4つの分散レジストリ（`scraper_tasks._get_scraper_registry`, `task_worker.SCRAPER_MAP`, `api_scraping.SCRAPER_RUNNERS/SCRAPER_SEARCH`, `scrapers.get_search_registry`）を `_SCRAPER_REGISTRY` 1か所に統合。統一 `dispatch(action, mode, ...)` 関数で全スクレイパー起動を一元化。`login_url` もレジストリに統合。
- **`api_scraping.py` 簡略化**: `SCRAPER_RUNNERS`, `SCRAPER_SEARCH`, `SITE_LOGIN_URLS`, `_import_func` を全削除。`dispatch()` と `get_login_urls()` に置換。
- **`services/gmail_dispatcher.py` 新規作成**: Gmail のブラウザ/API自動選択 + キャッシュ + フィルタ + AI処理パイプラインを統一。`gmail_tasks.py`(114→26行)と`api_gmail.py`(93→50行)から重複ロジックを抽出。
- **`keyword_tasks.py` 重複通知削除**: `dispatch()` 内部で通知済みのため、外部の `create_notification` を削除。

---

## TODO 5: Workflow Engine（ワークフロー編排エンジン）

### 目的
現在ハードコードされているクロスドメイン処理チェーン（メール→AI→爬虫→DB→通知）を宣言型ワークフロー定義に移行。
新しいワークフロー追加はコード変更不要、設定のみで対応。

### 対象ワークフロー（9+）
1. メール発見 → AI解析 → ジョブ作成 → 爬虫補完 → 通知
2. 定時爬取 → AI enrichment → スコアリング → 通知
3. 手動検索 → 爬虫 → AI → DB → SSE
4. 健康監視 → テスト → 異常検知 → AI修復 → 再テスト
5. 新サイト → AI探索 → JSON生成 → テスト → 登録
6. 面接衝突 → 取消メール送信 → カレンダー更新
7. ES文書 → AI生成 → 審査 → 提出
8. OpenWork → 口コミ抓取 → AI適合度分析 → スコア更新
9. 面接体験記 → AI抽出 → 企業関連付け → 面接前リマインダー

### 優先度: TODO 4 Phase 1 完了後

---

## TODO 10+: マルチタイプ・国際展開（超長期目標） 🔮

### 目的
新卒就活システムをベースに、中途・打工・実習・海外求人にも対応するマルチプラットフォーム化。
新卒システムが完全に安定稼働し、問題がないと判断した後に初めて着手。

### アーキテクチャ方針
- **方案B**採用: 共通テーブル (`companies`, `jobs`) + 類型別拡張テーブル (`job_shinsotsu`, `job_chuto`, `job_part_time`, `job_intern`)
- フロントエンドは類型別に分離（新卒/中途/打工/実習）
- バックエンド（爬虫/AI/Workflow/DB共通層）は共有

### 前提条件
- 新卒システムの全TODO完了・安定稼働確認済み
- Workflow Engine 稼働済み
- `_SCRAPER_REGISTRY` に `job_type`, `locale` フィールド追加

### 優先度: 全TODO完了後、プロジェクトが問題ないと判断してから

## 2026-02-27: ドキュメント全面リライト
- **`ARCHITECTURE.md` 全面書き換え**: 追記形式のchangelog方式を廃止し、現在のコードベースを正確に反映するクリーンなリファレンスに刷新。
  - 完全なプロジェクトツリー（全ディレクトリ + 60+ファイル）
  - 6本のMermaidパイプライン図を全面更新: TaskWorker/dispatch()/SSE/DBWriter/gmail_dispatcher を反映
  - コア設計パターン5件を新規追記: DBWriter, 統一Dispatch, 会社名正規化, SSE, LLMマルチプロバイダー
  - API全エンドポイント表（50+エンドポイント）
  - DB全テーブル一覧（主要7 + 補助11 = 18テーブル）
  - スクレイパーレジストリ能力マトリクス
  - スケジューラ定時タスク表
  - フロントエンド8画面一覧
- **`FUNCTION_REFERENCE.md` 全面書き換え**: 新規モジュール13件を追加。
  - ai/adapters.py, ai/prompt_loader.py
  - db/task_queue.py (10関数), db/activity_log.py (4関数)
  - services/sse_hub.py, services/company_normalizer.py, services/gmail_dispatcher.py, services/email_backfill.py, services/task_worker.py (12ハンドラー)
  - scrapers/__init__.py (dispatch + registry), scrapers/openwork.py
  - automators/entry_bot.py
  - db/emails.py に get_email_count() 追加
  - db/jobs.py に delete_all_jobs(), get_job_by_source_id() 追加
- **`README.md` 更新**: 現在の機能セットを反映（5サイト対応、AIマルチプロバイダー、SSEリアルタイム更新、タスクキュー、Gmail dispatcher等）

