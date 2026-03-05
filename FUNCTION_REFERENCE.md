# 就活エージェント 全関数リファレンス
# 最終更新: 2026-03-01

---

## app.py（Flask アプリケーション）
| ルート | テンプレート | 用途 |
|--------|------------|------|
| / | dashboard.html | ダッシュボード |
| /jobs | jobs.html | 求人管理 |
| /calendar | calendar.html | カレンダー |
| /emails | emails.html | メール一覧 |
| /settings | settings.html | 設定 |
| /chat | chat.html | AIチャット |
| /es | es_management.html | ES管理 |
| /mypage | mypage.html | マイページ |

---

## ai/__init__.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| call_llm(prompt, priority=2, workflow='chat', model=None, temperature=0.7, max_tokens=4096) | → str | LLM呼び出し（dispatcher経由） |
| is_ai_configured() | → bool | APIキー有無 |
| get_ai_status() | → dict | AI設定状態 |
| clean_json_response(raw) | → str | LLM応答からJSON抽出 |

## ai/adapters.py
| クラス | メソッド | 用途 |
|--------|---------|------|
| BaseAdapter | generate(prompt, api_key, model, endpoint_url, temperature, max_tokens) → str | 抽象基底 |
| GeminiAdapter | generate(...) | Gemini REST API |
| OpenAICompatAdapter | generate(...) | OpenAI / DeepSeek / 互換API |
| RateLimitError | (exception) | 429エラー例外 |
| get_adapter(provider) | → BaseAdapter | アダプターファクトリ |

## ai/dispatcher.py
| クラス/関数 | メソッド | 用途 |
|------------|---------|------|
| LLMDispatcher | submit(prompt, priority, workflow, ...) → str | リクエスト発行 |
| LLMDispatcher | reload_keys() | DB APIキー再読込 |
| LLMDispatcher | is_configured() → bool | キー有無 |
| LLMDispatcher | get_status() → dict | ステータス |
| dispatcher | (グローバルシングルトン) | 全体共有 |

## ai/prompt_loader.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| get_prompt(prompt_name, default_text) | → str | prompts/*.txt 読込（なければ自動作成） |

## ai/chat_agent.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| chat_and_generate_keywords(user_message, session_id=None) | → dict{session_id, reply, keywords} | チャット→キーワード生成 |

## ai/email_parser.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| parse_email_with_ai(subject, sender, body) | → dict\|None (14フィールド) | メール構造化解析 |

## ai/job_detail_parser.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| parse_job_detail_with_ai(raw_text, company_name, existing_data) | → dict\|None (9フィールド) | 求人詳細ページAI解析 |

## ai/job_enricher.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| enrich_single_job(job_data, user_preferences=None, openwork_data=None) | → dict{match_score, ai_summary, tags}\|None | 求人スコアリング |

## ai/es_writer.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| generate_custom_es(base_es, job_data, openwork_data=None) | → dict{custom_self_pr, custom_motivation}\|None | 企業別ES生成 |

## ai/ai_merge.py
| クラス/関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| MergeMode | AI / DIRECT / AUTO | マージモード定数 |
| ai_merge(existing, new_data, data_source, mode, prompt_key, constraints) | → dict | 統一データマージ（ルールベース or LLM） |
| DEFAULT_CONSTRAINTS | dict | フィールド別制約（locked/write_once/updatable/ai_only） |

---

## db/__init__.py
| 関数/クラス | 引数 → 戻り値 | 用途 |
|------------|--------------|------|
| get_db() | → sqlite3.Connection | 新規読取り接続 |
| get_db_connection(max_retries=3) | → context manager | DBWriter経由の安全な接続 |
| DBWriter | (class) | 単一接続シリアライズ書込み |
| init_db() | → None | 全テーブル初期化 |

## db/models.py
| クラス | 用途 |
|------|------|
| JobRecord (TypedDict) | 求人レコード型定義（24フィールド） |
| InterviewRecord (TypedDict) | 面接レコード型定義 |
| TaskRecord (TypedDict) | タスクキューレコード型定義 |
| JobStatus (Literal) | 15種ステータス列挙 |
| JobSource (Literal) | 7種ソース列挙 |

## db/jobs.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| create_job(data) | → int | 求人作成 |
| update_job(job_id, data) | → bool | 求人更新 |
| delete_job(job_id) | → None | 求人削除 |
| delete_all_jobs() | → int | 全求人削除 |
| get_job(job_id) | → dict\|None | 求人取得 |
| get_all_jobs(status=None, source=None) | → list[dict] | 全求人取得 |
| get_jobs_by_deadline(date_str) | → list[dict] | 締切日検索 |
| get_upcoming_deadlines(days=7) | → list[dict] | 近日締切 |
| get_honsen_urgent_deadlines(days=3) | → list[dict] | 本選考緊急締切 |
| upsert_job_from_scraper(data) | → (int, bool) | スクレイパー → DB（3段階マッチ） |
| get_job_stats() | → dict | 統計（GROUP BY動的） |
| job_exists_by_source_id(source_id) | → bool | source_id存在確認 |
| get_job_by_source_id(source, source_id) | → dict\|None | source_id検索 |
| get_unenriched_jobs(limit=10) | → list[dict] | 未エンリッチ取得 |
| update_job_enrichment(job_id, data) | → bool | エンリッチ更新 |

## db/interviews.py
| 関数 | 引数 → 戻り値 |
|------|--------------|
| create_interview(data) | → int |
| get_interviews_for_job(job_id) | → list |
| get_upcoming_interviews(days=7) | → list |
| get_all_interviews() | → list |
| update_interview(interview_id, data) | → bool |
| delete_interview(interview_id) | → None |

## db/emails.py
| 関数 | 引数 → 戻り値 |
|------|--------------|
| cache_email(data) | → None |
| get_cached_emails(job_related_only=False, limit=100) | → list |
| mark_email_processed(gmail_id) | → None |
| is_email_processed(gmail_id) | → bool |
| get_email_count() | → int |

## db/applications.py
| 関数 | 引数 → 戻り値 |
|------|--------------|
| create_application(data) | → int |
| application_exists(job_id, es_id) | → bool |
| get_pending_applications(limit=5) | → list |
| get_applications_for_job(job_id) | → list |
| get_all_applications(status=None) | → list |
| update_application_status(app_id, status, message) | → None |
| set_generated_es(app_id, text) | → None |
| delete_application(app_id) | → None |
| get_application_stats() | → dict |

## db/task_queue.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| enqueue(task_type, priority=5, params=None) | → int | タスク投入（重複排除付き） |
| claim_next() | → dict\|None | 最高優先度タスク取得（原子的） |
| complete(task_id, result=None) | → None | 完了マーク |
| fail(task_id, error, retry=True) | → None | 失敗マーク（自動リトライ） |
| cancel(task_id) | → bool | キャンセル |
| get_queue(status=None, limit=50) | → list | キュー一覧 |
| get_history(limit=30) | → list | 実行履歴 |
| get_task(task_id) | → dict | タスク取得 |
| get_queue_stats() | → dict | キュー統計 |
| cleanup_old_tasks(days=7) | → int | 古タスク削除 |

## db/activity_log.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| log_activity(category, message, level='info', details=None) | → None | 構造化ログ記録 |
| get_activity_log(category=None, level=None, limit=50, offset=0) | → list | ログ取得 |
| get_activity_stats() | → dict | 今日の統計 |
| cleanup_old_logs(days=30) | → int | 古ログ削除 |

## db/llm_settings.py
| 関数 | 用途 |
|------|------|
| APIキーCRUD (AES暗号化) | add/get/delete/list_api_keys |
| ワークフローCRUD | get/update/list_workflow_configs |
| モデル一覧 | get_available_models |
| 使用量ログ | log_usage, get_usage_stats |

## db/ その他
| ファイル | 関数群 | 用途 |
|---------|--------|------|
| notifications.py | create/get/mark_read | 通知管理 |
| preferences.py | get/add/delete/toggle | 希望条件 |
| user_profile.py | get/save_profile | プロフィール |
| mypages.py | CRUD | マイページ認証情報 |
| openwork.py | get/cache_openwork_data, is_cache_fresh | OpenWorkキャッシュ |
| es.py | CRUD | ES文書 |
| chat.py | save/get | チャット履歴 |

---

## services/

### event_detector.py
| 関数/定数 | 用途 |
|----------|------|
| auto_register_interview(email_data) | メール→AI→面接/ES/rejection処理 |
| match_or_create_job(company_name, ai=None) | 4段階マッチ → 既存/新規job_id |
| STATUSES_PRE / IN_PROGRESS / TERMINAL / UPGRADABLE | ステータス定数 |
| EVENT_TYPE_TO_STATUS | event_type→status マッピング |

### email_filter.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| layer1_regex_filter(emails) | → (passed, filtered) | 正規表現フィルタ |
| layer2_batch_prescreen(emails, batch_size=8) | → (job_related, non_job) | LLMバッチ |
| layer3_deep_analysis(emails) | → list[dict] | 深層AI解析 |
| filter_emails(emails, skip_layer2=False) | → dict | 3層統合 |

### gmail_dispatcher.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| fetch_emails(mode='incremental', params=None, apply_filter=True) | → dict | モード駆動統一取得（registry経由） |

### gmail_modes.py
| クラス/関数 | 用途 |
|------|------|
| FetchMode (ABC) | 取得モード基底クラス（build_query, get_limit, after_fetch） |
| GmailModeRegistry | モード登録・検索（register, get, list_modes） |
| BackfillMode | 初回全量取得（past N days, 上限なし） |
| IncrementalMode | 日常増分（since last_fetched_at, 上限なし） |
| KeywordSearchMode | キーワード検索（limit付き） |
| registry | グローバルレジストリインスタンス |

### db/gmail_settings.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| get_gmail_config() | → dict | 全gmail_*設定を取得 |
| update_gmail_config(updates) | → None | 設定を更新 |
| get_last_fetched_at() | → str | 最終取得時刻 |
| set_last_fetched_at(ts) | → None | 最終取得時刻を記録 |

### email_backfill.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| run_email_backfill(keyword, job_id, scrapers=None) | → dict | メール企業のスクレイパー補完 |

### ai_search_service.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| run_ai_search(user_message, session_id=None) | → dict | チャット→キーワード→爬取→保存 |

### enrichment_service.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| enrich_pending_jobs(max_jobs=10) | → dict | バッチAIスコアリング |

### application_service.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| create_application_queue(job_ids, es_document_id, dry_run=True) | → dict | 海投キュー作成 |
| process_application_queue(max_per_run=3) | → dict | キュー処理 |
| get_queue_status() | → dict | キュー統計 |

### company_normalizer.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| normalize(name) | → str | 会社名正規化（株式会社除去, NFKC, 全角→半角） |
| find_matching_job(company_name, exclude_id=None) | → dict\|None | クロスソースマッチ |

### company_matcher.py
| 関数/クラス | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| MatchResult | dataclass(job, score, method) | マッチ結果 |
| find_best_match(company_name, jobs, url, exclude_ids, min_score) | → MatchResult\|None | 4戦略スコアベースマッチング |

### sse_hub.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| subscribe() | → Queue | SSE購読開始 |
| unsubscribe(q) | → None | 購読解除 |
| publish_job_event(event_type, job) | → None | イベント配信（created/updated/deleted） |

### task_worker.py
| クラス | メソッド | 用途 |
|--------|---------|------|
| TaskWorker | start() | ワーカースレッド開始 |
| TaskWorker | stop() | 停止 |
| TaskWorker | is_running() → bool | 稼働確認 |
| TaskWorker | get_status() → dict | ステータス取得 |
| task_worker | (グローバルシングルトン) | 全体共有 |

**登録ハンドラー（12種）:**
scrape_\<site\>, enrich, email_check, keyword_search, email_backfill,
application_queue, check_deadlines, check_interviews, cleanup_old_tasks

### es_parser.py
| ファイル | 関数 | 用途 |
|---------|------|------|
| es_parser | parse_es_file(path) → dict | PDF/DOCX→AI構造化（履歴書自動判定） |
| es_parser | extract_text(path) → str | PyMuPDFでテキスト抽出 |
| es_parser | save_es_to_db(path, title, parsed, photo_path) → int | DB保存 |

### resume_parser.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| parse_resume(file_path) | → dict | OpenES座標ベース全フィールド抽出 |
| is_resume_pdf(file_path) | → bool | 履歴書判定（マーカーテキスト検出） |

### detail_enrich_service.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| enrich_job_detail(job_id) | → dict | 求人詳細ページ取得+AI解析 |

サイト別URL戦略: mynavi(2ページ), career_tasu(2), onecareer(2), engineer_shukatu(3), gaishishukatsu(1)

### profile_extractor.py / strict_es_generator.py
| ファイル | 関数 | 用途 |
|---------|------|------|
| profile_extractor | extract_and_save_profile(text) → dict | ES→プロフィール |
| strict_es_generator | generate_strict_es(question, max_chars, ...) → dict | 文字数厳密ES |

### services/__init__.py
| 関数 | 用途 |
|------|------|
| extract_company_name(sender, subject, body) | メールから企業名抽出 |
| detect_interview_type(text) | 面接種別判定 |
| extract_location(text) | 場所抽出 |
| extract_online_url(text) | 会議URL抽出 |
| extract_dates_from_text(text) | 日付抽出 |

---

## scrapers/

### __init__.py（統一Dispatch）
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| dispatch(action, mode, keywords, scrapers, max_results, job_id) | → dict | **全スクレイパー唯一のエントリポイント** |
| get_registry(action='search') | → dict{name: fn} | レジストリ取得 |
| get_scraper_names() | → list[str] | 登録名一覧 |
| get_login_urls() | → dict{name: url} | ログインURL |
| dispatch_search(...) | (後方互換alias) | → dispatch(action='search') |

### base.py（BaseScraper）
| メソッド | 用途 |
|---------|------|
| _run_pipeline() | login→fetch→(AI enrich→save)×N |
| fetch_detail_text(url) → str | 詳細ページテキスト取得 |
| _enrich_single_job(job) → dict | 1企業AI解析 |
| _is_data_complete(job) → bool | データ完全性チェック |

### 各スクレイパー
| ファイル | fetch関数 | search関数 |
|---------|----------|-----------|
| mynavi.py | run_mynavi_scraper() | run_mynavi_search(keywords) |
| career_tasu.py | run_career_tasu_scraper() | run_career_tasu_search(keywords) |
| gaishishukatsu.py | run_gaishishukatsu_scraper() | run_gaishishukatsu_search(keywords) |
| onecareer.py | run_onecareer_scraper() | run_onecareer_search(keywords) |
| engineer_shukatu.py | run_engineer_shukatu_scraper() | run_engineer_shukatu_search(keywords) |

### openwork.py
| 関数 | 引数 → 戻り値 | 用途 |
|------|--------------|------|
| fetch_company_scores(company_name) | → dict\|None | OpenWork口コミスコア（キャッシュ付き） |

---

## scheduler/

### __init__.py
| 関数 | 用途 |
|------|------|
| init_scheduler() | APScheduler + TaskWorker 初期化 + 全ジョブ登録 |
| shutdown_scheduler() | TaskWorker停止 + scheduler停止 |

### サブモジュール
| ファイル | 関数 | 用途 |
|---------|------|------|
| scraper_tasks.py | run_all_scrapers(), run_scraper() | 全/単体スクレイプ投入 |
| gmail_tasks.py | check_gmail(backfill=False) | Gmail → task_queue投入 |
| keyword_tasks.py | run_keyword_search() | キーワード検索 → task_queue投入 |
| enrich_tasks.py | run_enrichment(), run_application_queue() | AI/応募 → task_queue投入 |
| check_tasks.py | check_deadlines_today(), check_upcoming_deadlines(), check_interviews_today() | アラート → task_queue投入 |

---

## gmail_browser.py / gmail_service.py

| ファイル | 関数 | 用途 |
|---------|------|------|
| gmail_browser | is_gmail_browser_configured() → bool | Cookie有無確認 |
| gmail_browser | gmail_cookie_login() | Playwright Cookie ログイン |
| gmail_browser | fetch_emails_via_browser(max_results=20) → list | Cookie経由取得 |
| gmail_browser | fetch_emails_backfill(days=30) → list | 過去30日バックフィル |
| gmail_service | get_gmail_service() → service | OAuth2認証 |
| gmail_service | fetch_recent_emails(max_results=50) → list | API経由取得 |
| gmail_service | start_gmail_auth() → (bool, str) | Gmail OAuth開始 |

---

## automators/entry_bot.py
| 関数 | 用途 |
|------|------|
| auto_fill_form(job_url, es_data, profile) | Playwrightでフォーム自動入力 |
