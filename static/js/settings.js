// =====================================================
// Settings page JavaScript — extracted from settings.html
// =====================================================

// ---- Keyword tag management ----
async function addKeyword() {
    const input = document.getElementById('new-keyword');
    const keyword = input.value.trim();
    if (!keyword) return;
    try {
        const res = await fetch('/api/preferences', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keyword })
        });
        const data = await res.json();
        if (res.ok) {
            input.value = '';
            appendTag(data.id, keyword, true);
            showToast(`「${keyword}」を追加しました`, 'success');
        } else {
            showToast(data.error || '追加に失敗しました', 'error');
        }
    } catch (err) {
        showToast('追加に失敗しました', 'error');
    }
}

function appendTag(id, keyword, enabled) {
    const container = document.getElementById('keyword-tags');
    const span = document.createElement('span');
    span.className = 'keyword-tag' + (enabled ? '' : ' tag-disabled');
    span.dataset.id = id;
    span.dataset.enabled = enabled ? '1' : '0';
    span.innerHTML = `
        <span class="tag-label" onclick="toggleKeyword(${id}, this.parentElement)">${keyword}</span>
        <button class="tag-remove" onclick="removeKeyword(${id}, this.parentElement)" title="削除">✕</button>`;
    container.appendChild(span);
}

async function removeKeyword(id, el) {
    try {
        await fetch(`/api/preferences/${id}`, { method: 'DELETE' });
        el.remove();
        showToast('キーワードを削除しました', 'success');
    } catch (err) {
        showToast('削除に失敗しました', 'error');
    }
}

async function toggleKeyword(id, el) {
    try {
        await fetch(`/api/preferences/${id}/toggle`, { method: 'POST' });
        el.classList.toggle('tag-disabled');
        const isNowDisabled = el.classList.contains('tag-disabled');
        el.dataset.enabled = isNowDisabled ? '0' : '1';
    } catch (err) {
        showToast('更新に失敗しました', 'error');
    }
}

async function runKeywordSearch() {
    const btn = document.getElementById('search-btn');
    const resultEl = document.getElementById('search-result');
    btn.disabled = true;
    btn.textContent = '🔄 検索中...';
    resultEl.textContent = '';
    try {
        const res = await fetch('/api/scrape/search', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            resultEl.textContent = `完了: ${data.jobs_found}件検出 / ${data.jobs_updated}件新規追加`;
            showToast(`検索完了！ ${data.jobs_updated}件の新しい求人を発見しました`, 'success');
        } else {
            showToast(data.error || '検索に失敗しました', 'error');
        }
    } catch (err) {
        showToast('検索に失敗しました', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '🔍 キーワード検索を実行';
    }
}

// ---- Credential management ----
async function saveCredentials() {
    const email = document.getElementById('mynavi-email').value.trim();
    const password = document.getElementById('mynavi-password').value.trim();
    if (!email || !password) {
        showToast('メールアドレスとパスワードを入力してください', 'error');
        return false;
    }
    try {
        const res = await fetch('/api/settings/credentials', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mynavi_email: email, mynavi_password: password })
        });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message, 'success');
            return true;
        } else {
            showToast(data.error || '保存に失敗しました', 'error');
            return false;
        }
    } catch (err) {
        showToast('保存に失敗しました', 'error');
        return false;
    }
}

async function saveAndSync() {
    const saved = await saveCredentials();
    if (saved) {
        showToast('同期を開始します...', 'info');
        triggerScrape();
    }
}

async function authGmail() {
    showToast('Gmail認証を開始します...ブラウザで認証画面が開きます', 'info');
    try {
        const res = await fetch('/api/gmail/auth', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`Gmail認証成功: ${data.message}`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(data.error || 'Gmail認証に失敗しました', 'error');
        }
    } catch (err) {
        showToast('Gmail認証に失敗しました', 'error');
    }
}

async function fetchGmail() {
    const mode = document.getElementById('gmail-fetch-mode')?.value || 'incremental';
    const btn = document.getElementById('gmail-fetch-btn');
    const resultEl = document.getElementById('gmail-fetch-result');

    const body = { mode };
    if (mode === 'keyword_search') {
        const kw = document.getElementById('gmail-keyword')?.value?.trim();
        if (!kw) { showToast('キーワードを入力してください', 'error'); return; }
        body.keyword = kw;
        body.limit = parseInt(document.getElementById('gmail-keyword-limit')?.value || '10');
    } else if (mode === 'backfill') {
        body.days = parseInt(document.getElementById('gmail-backfill-days')?.value || '30');
    }

    btn.disabled = true;
    btn.textContent = '🔄 取得中...';
    resultEl.textContent = '取得中...しばらくお待ちください';

    // Start progress polling
    startGmailProgressPoll();

    try {
        const res = await fetch('/api/gmail/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const data = await res.json();
        stopGmailProgressPoll();
        if (res.ok) {
            let msg = `📧 ${data.count}件のメールを取得`;
            if (data.events_registered > 0) {
                msg += ` | 🎯 ${data.events_registered}件の予定を自動登録`;
            }
            resultEl.textContent = msg;
            showToast(msg, 'success', 5000);
        } else {
            resultEl.textContent = '❌ ' + (data.error || '取得失敗');
            showToast(data.error || 'メール取得に失敗しました', 'error');
        }
    } catch (err) {
        stopGmailProgressPoll();
        resultEl.textContent = '❌ 通信エラー';
        showToast('メール取得に失敗しました', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = '📧 実行';
    }
}

// ── Gmail progress polling ──────────────────────────────────────
let _gmailProgressTimer = null;

function startGmailProgressPoll() {
    stopGmailProgressPoll();
    const wrap = document.getElementById('gmail-progress-wrap');
    if (wrap) wrap.style.display = 'block';
    _gmailProgressTimer = setInterval(pollGmailProgress, 1000);
}

function stopGmailProgressPoll() {
    if (_gmailProgressTimer) {
        clearInterval(_gmailProgressTimer);
        _gmailProgressTimer = null;
    }
}

async function pollGmailProgress() {
    try {
        const res = await fetch('/api/gmail/progress');
        const p = await res.json();

        const wrap = document.getElementById('gmail-progress-wrap');
        const bar = document.getElementById('gmail-progress-bar');
        const text = document.getElementById('gmail-progress-text');
        const pct = document.getElementById('gmail-progress-pct');
        if (!wrap) return;

        if (p.active || p.stage === 'done') {
            wrap.style.display = 'block';
            text.textContent = p.message || p.stage;

            if (p.total > 0) {
                const percent = Math.round((p.current / p.total) * 100);
                bar.style.width = percent + '%';
                pct.textContent = percent + '%';
            } else {
                bar.style.width = '100%';
                pct.textContent = '';
            }

            if (!p.active) {
                // Done — show for 5s then hide
                setTimeout(() => {
                    wrap.style.display = 'none';
                    bar.style.width = '0%';
                }, 5000);
                stopGmailProgressPoll();
            }
        } else {
            wrap.style.display = 'none';
        }
    } catch (e) { /* ignore polling errors */ }
}

// Check if a background fetch is already running on page load
function checkGmailProgress() {
    fetch('/api/gmail/progress')
        .then(r => r.json())
        .then(p => {
            if (p.active) startGmailProgressPoll();
        })
        .catch(() => { });
}


const GMAIL_MODE_DESCS = {
    incremental: '前回取得以降の新着メールを自動取得します。',
    backfill: '指定日数分の全メールを取得します（初回または再取得用）。',
    keyword_search: '指定キーワードに一致するメールを検索して取得します。',
};

function onGmailModeChange() {
    const mode = document.getElementById('gmail-fetch-mode').value;
    document.getElementById('gmail-keyword').style.display = mode === 'keyword_search' ? '' : 'none';
    document.getElementById('gmail-limit-wrap').style.display = mode === 'keyword_search' ? 'flex' : 'none';
    document.getElementById('gmail-days-wrap').style.display = mode === 'backfill' ? 'flex' : 'none';
    document.getElementById('gmail-mode-desc').textContent = GMAIL_MODE_DESCS[mode] || '';
}

function toggleGmailSettings() {
    const panel = document.getElementById('gmail-settings-panel');
    const chevron = document.getElementById('gmail-settings-chevron');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        chevron.textContent = '▲';
        loadGmailSettings();
    } else {
        panel.style.display = 'none';
        chevron.textContent = '▼';
    }
}

async function loadGmailSettings() {
    try {
        const res = await fetch('/api/gmail/settings');
        const cfg = await res.json();
        const daysEl = document.getElementById('gmail-cfg-backfill-days');
        const limitEl = document.getElementById('gmail-cfg-keyword-limit');
        const lastEl = document.getElementById('gmail-cfg-last-fetched');
        if (daysEl) daysEl.value = cfg.gmail_backfill_days || 30;
        if (limitEl) limitEl.value = cfg.gmail_keyword_limit || 10;
        if (lastEl) lastEl.textContent = cfg.gmail_last_fetched_at || '未取得';
        // Also sync the fetch form defaults
        const formLimit = document.getElementById('gmail-keyword-limit');
        if (formLimit) formLimit.value = cfg.gmail_keyword_limit || 10;
        const formDays = document.getElementById('gmail-backfill-days');
        if (formDays) formDays.value = cfg.gmail_backfill_days || 30;
    } catch (e) { /* ignore */ }
}

async function saveGmailSettings() {
    const resultEl = document.getElementById('gmail-settings-result');
    resultEl.textContent = '保存中...';
    const body = {
        gmail_backfill_days: document.getElementById('gmail-cfg-backfill-days')?.value || '30',
        gmail_keyword_limit: document.getElementById('gmail-cfg-keyword-limit')?.value || '10',
    };
    try {
        const res = await fetch('/api/gmail/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            resultEl.textContent = '✅ 保存完了';
            showToast('Gmail設定を保存しました', 'success');
        } else {
            resultEl.textContent = '❌ エラー';
        }
    } catch (e) {
        resultEl.textContent = '❌ 通信エラー';
    }
}


// ── Sender Blocklist ────────────────────────────────────────
function toggleBlocklist() {
    const panel = document.getElementById('blocklist-panel');
    const chevron = document.getElementById('blocklist-chevron');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        chevron.textContent = '▲';
        loadBlocklistRules();
    } else {
        panel.style.display = 'none';
        chevron.textContent = '▼';
    }
}

async function loadBlocklistRules() {
    try {
        const res = await fetch('/api/llm/filters');
        const rules = await res.json();
        const container = document.getElementById('blocklist-rules');
        if (!container) return;

        if (!rules.length) {
            container.innerHTML = '<p style="font-size:0.8em; color:var(--text-secondary);">ブロックルールなし</p>';
            return;
        }

        container.innerHTML = rules.map(r => `
            <div style="display:flex; align-items:center; gap:6px; padding:4px 0; border-bottom:1px solid rgba(255,255,255,0.05); font-size:0.8em;">
                <span style="cursor:pointer; opacity:${r.enabled ? 1 : 0.4};" onclick="toggleBlockRule(${r.id})"
                    title="${r.enabled ? '有効' : '無効'}">${r.enabled ? '✅' : '⬜'}</span>
                <span style="color:var(--accent-primary); min-width:40px;">${r.rule_type === 'sender' ? '送信者' : '件名'}</span>
                <code style="flex:1; font-size:0.85em; opacity:${r.enabled ? 1 : 0.5};">${escapeHtml(r.pattern)}</code>
                <span style="color:var(--text-secondary); font-size:0.85em; max-width:100px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${escapeHtml(r.description || '')}</span>
                <button class="btn btn-outline btn-sm" style="font-size:0.65em; padding:1px 6px; color:var(--danger);"
                    onclick="deleteBlockRule(${r.id})">✕</button>
            </div>
        `).join('');
    } catch (e) { /* ignore */ }
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function addBlocklistRule() {
    const type = document.getElementById('blocklist-type').value;
    const pattern = document.getElementById('blocklist-pattern').value.trim();
    const desc = document.getElementById('blocklist-desc').value.trim();
    if (!pattern) { showToast('パターンを入力してください', 'error'); return; }

    try {
        const res = await fetch('/api/llm/filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rule_type: type, pattern, description: desc }),
        });
        const data = await res.json();
        if (res.ok) {
            document.getElementById('blocklist-pattern').value = '';
            document.getElementById('blocklist-desc').value = '';
            showToast('ブロックルールを追加しました', 'success');
            loadBlocklistRules();
        } else {
            showToast(data.error || 'エラー', 'error');
        }
    } catch (e) { showToast('通信エラー', 'error'); }
}

async function addPresetBlock(pattern, desc) {
    try {
        const res = await fetch('/api/llm/filters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rule_type: 'sender', pattern, description: desc }),
        });
        if (res.ok) {
            showToast(`${desc} を追加しました`, 'success');
            loadBlocklistRules();
            // Open panel if closed
            const panel = document.getElementById('blocklist-panel');
            if (panel && panel.style.display === 'none') toggleBlocklist();
        } else {
            const data = await res.json();
            showToast(data.error || 'エラー', 'error');
        }
    } catch (e) { showToast('通信エラー', 'error'); }
}

async function deleteBlockRule(ruleId) {
    try {
        await fetch(`/api/llm/filters/${ruleId}`, { method: 'DELETE' });
        loadBlocklistRules();
    } catch (e) { /* ignore */ }
}

async function toggleBlockRule(ruleId) {
    try {
        await fetch(`/api/llm/filters/${ruleId}/toggle`, { method: 'POST' });
        loadBlocklistRules();
    } catch (e) { /* ignore */ }
}


const SITE_NAMES = {
    mynavi: 'マイナビ',
    gaishishukatsu: '外資就活',
    career_tasu: 'キャリタス',
    onecareer: 'ワンキャリア',
    engineer_shukatu: 'エンジニア就活',
};

async function cookieLogin(site) {
    const name = SITE_NAMES[site] || site;
    showToast(`${name} のログインブラウザを開いています...`, 'info');
    try {
        const res = await fetch(`/api/login/${site}`, { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`🍪 ${name}: ${data.message}`, 'success', 5000);
        } else {
            showToast(`❌ ${data.error || 'ログインに失敗しました'}`, 'error');
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error');
    }
}

// --- AI Settings ---
async function saveAiSettings() {
    const provider = document.getElementById('ai-provider').value;
    const apiKey = document.getElementById('ai-api-key').value.trim();
    const resultEl = document.getElementById('ai-save-result');
    if (!apiKey) {
        showToast('❌ APIキーを入力してください', 'error');
        return;
    }
    resultEl.textContent = '保存中...';
    try {
        const res = await fetch('/api/ai/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, api_key: apiKey })
        });
        const data = await res.json();
        if (data.status === 'success') {
            showToast('✅ AI設定を保存しました', 'success');
            resultEl.textContent = '✅ 保存完了';
            document.getElementById('ai-status').innerHTML =
                '<span class="status-dot active"></span> ' + provider.toUpperCase() + ' 設定済み (' + apiKey.substring(0, 8) + '...)';
        } else {
            showToast('❌ ' + (data.error || '保存に失敗'), 'error');
            resultEl.textContent = '❌ エラー';
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error');
        resultEl.textContent = '';
    }
}

async function testAiConnection() {
    const resultEl = document.getElementById('ai-save-result');
    resultEl.textContent = '🧪 テスト中...';
    try {
        const res = await fetch('/api/ai/test');
        const data = await res.json();
        if (data.status === 'success') {
            showToast('✅ AI接続OK: ' + (data.message || ''), 'success', 5000);
            resultEl.textContent = '✅ 接続成功';
        } else {
            showToast('❌ ' + (data.error || 'テスト失敗'), 'error');
            resultEl.textContent = '❌ 接続失敗';
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error');
        resultEl.textContent = '';
    }
}

async function exportData() {
    try {
        const res = await fetch('/api/jobs');
        const jobs = await res.json();
        const blob = new Blob([JSON.stringify(jobs, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `job-agent-export-${new Date().toISOString().split('T')[0]}.json`;
        a.click();
        URL.revokeObjectURL(url);
        showToast('データをエクスポートしました', 'success');
    } catch (err) {
        showToast('エクスポートに失敗しました', 'error');
    }
}

// ===== Phase 7: Advanced LLM Settings =====

const WF_LABELS = { chat: '💬 チャット', email: '📧 メール解析', job: '🔍 求人分析', es: '📝 ES生成' };

function toggleLLMPanel() {
    const panel = document.getElementById('llm-panel');
    const chevron = document.getElementById('llm-chevron');
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        chevron.textContent = '▲';
        refreshLLMKeys();
        refreshLLMModels();
        refreshLLMFilters();
        refreshLLMUsage();
    } else {
        panel.style.display = 'none';
        chevron.textContent = '▼';
    }
}

// --- API Keys ---
async function refreshLLMKeys() {
    const container = document.getElementById('llm-keys-list');
    try {
        const res = await fetch('/api/llm/keys');
        const keys = await res.json();
        if (!keys.length) {
            container.innerHTML = '<p class="setting-desc" style="opacity:0.5">まだAPIキーが登録されていません。上のAI設定の.envキーがフォールバックとして使用されます。</p>';
            return;
        }
        container.innerHTML = keys.map(k => `
            <div class="llm-item ${k.enabled ? '' : 'llm-item-disabled'}">
                <span class="llm-item-badge">${k.provider.toUpperCase()}</span>
                <span class="llm-item-label">${k.label || 'Key'} ${k.api_key_preview}</span>
                <span class="llm-item-meta">RPM:${k.rpm_limit} 日:${k.daily_limit}</span>
                <button class="btn btn-outline btn-xs" onclick="toggleLLMKey(${k.id})">${k.enabled ? '⏸ 無効' : '▶ 有効'}</button>
                <button class="btn btn-outline btn-xs btn-danger" onclick="deleteLLMKey(${k.id}, this)">🗑</button>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<p class="setting-desc" style="color:var(--error)">読み込みエラー</p>';
    }
}

async function addLLMKey() {
    const provider = document.getElementById('llm-key-provider').value;
    const apiKey = document.getElementById('llm-key-value').value.trim();
    const label = document.getElementById('llm-key-label').value.trim();
    if (!apiKey) { showToast('APIキーを入力してください', 'error'); return; }
    try {
        const res = await fetch('/api/llm/keys', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ provider, api_key: apiKey, label })
        });
        const data = await res.json();
        if (res.ok) {
            document.getElementById('llm-key-value').value = '';
            document.getElementById('llm-key-label').value = '';
            showToast(data.message, 'success');
            refreshLLMKeys();
        } else {
            showToast(data.error, 'error');
        }
    } catch (e) { showToast('追加に失敗しました', 'error'); }
}

async function toggleLLMKey(id) {
    await fetch(`/api/llm/keys/${id}/toggle`, { method: 'POST' });
    refreshLLMKeys();
}

async function deleteLLMKey(id, btn) {
    if (btn && !btn.dataset.confirmed) {
        btn.dataset.confirmed = 'true';
        btn.textContent = '確認？';
        setTimeout(() => { btn.dataset.confirmed = ''; btn.textContent = '🗑'; }, 3000);
        return;
    }
    await fetch(`/api/llm/keys/${id}`, { method: 'DELETE' });
    refreshLLMKeys();
    showToast('キーを削除しました', 'success');
}

// --- Model Config ---
async function refreshLLMModels() {
    const container = document.getElementById('llm-models-list');
    try {
        const res = await fetch('/api/llm/models');
        const models = await res.json();
        container.innerHTML = models.map(m => `
            <div class="llm-model-row" data-workflow="${m.workflow}">
                <span class="llm-model-label">${WF_LABELS[m.workflow] || m.workflow}</span>
                <select class="form-input form-input-sm llm-model-provider" style="width:100px;">
                    <option value="gemini" ${m.provider === 'gemini' ? 'selected' : ''}>Gemini</option>
                    <option value="openai" ${m.provider === 'openai' ? 'selected' : ''}>OpenAI</option>
                    <option value="deepseek" ${m.provider === 'deepseek' ? 'selected' : ''}>DeepSeek</option>
                </select>
                <input type="text" class="form-input form-input-sm llm-model-name" value="${m.model_name}" placeholder="モデル名" style="width:180px;">
                <input type="number" class="form-input form-input-sm llm-model-temp" value="${m.temperature}" step="0.1" min="0" max="1" style="width:60px;" title="Temperature">
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<p class="setting-desc" style="color:var(--error)">読み込みエラー</p>';
    }
}

async function saveAllModels() {
    const rows = document.querySelectorAll('.llm-model-row');
    const resultEl = document.getElementById('model-save-result');
    resultEl.textContent = '保存中...';
    try {
        for (const row of rows) {
            await fetch('/api/llm/models', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    workflow: row.dataset.workflow,
                    provider: row.querySelector('.llm-model-provider').value,
                    model_name: row.querySelector('.llm-model-name').value,
                    temperature: parseFloat(row.querySelector('.llm-model-temp').value),
                })
            });
        }
        resultEl.textContent = '✅ 保存完了';
        showToast('モデル設定を保存しました', 'success');
    } catch (e) {
        resultEl.textContent = '❌ エラー';
        showToast('保存に失敗しました', 'error');
    }
}

// --- Filter Rules ---
async function refreshLLMFilters() {
    const container = document.getElementById('llm-filters-list');
    try {
        const res = await fetch('/api/llm/filters');
        const rules = await res.json();
        if (!rules.length) {
            container.innerHTML = '<p class="setting-desc" style="opacity:0.5">フィルタルールはまだありません</p>';
            return;
        }
        container.innerHTML = rules.map(r => `
            <div class="llm-item ${r.enabled ? '' : 'llm-item-disabled'}">
                <span class="llm-item-badge">${r.rule_type === 'sender' ? '📤' : '📋'}</span>
                <code class="llm-filter-pattern">${escapeHtml(r.pattern)}</code>
                <span class="llm-item-meta">${escapeHtml(r.description || '')}</span>
                <button class="btn btn-outline btn-xs" onclick="toggleFilter(${r.id})">${r.enabled ? '⏸' : '▶'}</button>
                <button class="btn btn-outline btn-xs btn-danger" onclick="deleteFilter(${r.id})">🗑</button>
            </div>
        `).join('');
    } catch (e) {
        container.innerHTML = '<p class="setting-desc" style="color:var(--error)">読み込みエラー</p>';
    }
}

function escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

async function addFilterRule() {
    const type = document.getElementById('filter-type').value;
    const pattern = document.getElementById('filter-pattern').value.trim();
    const desc = document.getElementById('filter-desc').value.trim();
    if (!pattern) { showToast('パターンを入力してください', 'error'); return; }
    try {
        const res = await fetch('/api/llm/filters', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rule_type: type, pattern, description: desc })
        });
        const data = await res.json();
        if (res.ok) {
            document.getElementById('filter-pattern').value = '';
            document.getElementById('filter-desc').value = '';
            showToast(data.message, 'success');
            refreshLLMFilters();
        } else {
            showToast(data.error, 'error');
        }
    } catch (e) { showToast('追加に失敗しました', 'error'); }
}

async function toggleFilter(id) {
    await fetch(`/api/llm/filters/${id}/toggle`, { method: 'POST' });
    refreshLLMFilters();
}

async function deleteFilter(id) {
    await fetch(`/api/llm/filters/${id}`, { method: 'DELETE' });
    refreshLLMFilters();
    showToast('ルールを削除しました', 'success');
}

// --- Usage Stats ---
async function refreshLLMUsage() {
    try {
        const res = await fetch('/api/llm/usage');
        const data = await res.json();
        document.getElementById('usage-total').textContent = data.total_calls || 0;
        const perKey = document.getElementById('usage-per-key');
        if (data.per_key && data.per_key.length) {
            perKey.innerHTML = data.per_key.map(u => {
                const pct = u.daily_limit ? Math.min(100, Math.round(u.call_count / u.daily_limit * 100)) : 0;
                return `<div class="usage-bar-row">
                    <span>${u.label || u.provider || 'Key'}: ${u.call_count}/${u.daily_limit}</span>
                    <div class="usage-bar"><div class="usage-bar-fill" style="width:${pct}%;background:${pct > 80 ? 'var(--error)' : 'var(--accent-primary)'}"></div></div>
                </div>`;
            }).join('');
        } else {
            perKey.innerHTML = '<p class="setting-desc" style="opacity:0.5">まだ使用データがありません</p>';
        }
    } catch (e) {
        document.getElementById('usage-total').textContent = '—';
    }
}

// --- Database Location ---
async function loadDBConfig() {
    try {
        const res = await fetch('/api/db/config');
        const data = await res.json();
        document.getElementById('db-current-path').textContent = data.current_path;
        document.getElementById('db-file-size').textContent = data.file_size_mb + ' MB';
        document.getElementById('db-reset-btn').style.display = data.is_default ? 'none' : 'inline-flex';
    } catch (e) {
        document.getElementById('db-current-path').textContent = '取得失敗';
    }
}

async function migrateDB() {
    const newPath = document.getElementById('db-new-path').value.trim();
    if (!newPath) {
        showToast('移動先パスを入力してください', 'error');
        return;
    }
    if (!confirm(`データベースを移動しますか？\n\n移動先: ${newPath}\n\n※ 移動後はアプリの再起動が必要です`)) return;

    try {
        const res = await fetch('/api/db/migrate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ new_path: newPath })
        });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('✅ ' + data.message, 'success');
            loadDBConfig();
            document.getElementById('db-new-path').value = '';
            if (data.needs_restart) {
                setTimeout(() => alert('アプリを再起動してください。'), 500);
            }
        } else {
            showToast('❌ ' + (data.error || '移動に失敗しました'), 'error');
        }
    } catch (err) {
        showToast('❌ 通信エラー', 'error');
    }
}

async function resetDBPath() {
    if (!confirm('データベースパスをデフォルトに戻しますか？')) return;
    try {
        const res = await fetch('/api/db/reset', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('✅ ' + data.message, 'success');
            loadDBConfig();
        } else {
            showToast('❌ ' + (data.error || 'リセットに失敗'), 'error');
        }
    } catch (err) {
        showToast('❌ 通信エラー', 'error');
    }
}

// --- TaskWorker Concurrency Settings ---
async function loadWorkerSettings() {
    try {
        const res = await fetch('/api/scheduler/worker/settings');
        const data = await res.json();
        const slider = document.getElementById('worker-max-concurrent');
        const display = document.getElementById('worker-count-display');
        if (slider && display) {
            slider.value = data.max_workers;
            display.textContent = data.max_workers;
        }
    } catch (e) { /* ignore */ }

    // Also load worker status
    try {
        const res = await fetch('/api/scheduler/status');
        const data = await res.json();
        const statusEl = document.getElementById('worker-status-display');
        if (statusEl && data.worker) {
            const w = data.worker;
            const dot = w.running ? '<span class="status-dot active"></span>' : '<span class="status-dot inactive"></span>';
            statusEl.innerHTML = `${dot} ${w.running ? '実行中' : '停止'} ` +
                `| 並列数: ${w.max_workers || '?'} | アクティブ: ${w.active_workers || 0} ` +
                `| 処理済み: ${w.tasks_processed}`;
        }
    } catch (e) { /* ignore */ }
}

async function saveWorkerSettings() {
    const slider = document.getElementById('worker-max-concurrent');
    const resultEl = document.getElementById('worker-save-result');
    const val = parseInt(slider.value);
    resultEl.textContent = '保存中...';
    try {
        const res = await fetch('/api/scheduler/worker/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_workers: val })
        });
        const data = await res.json();
        if (res.ok) {
            resultEl.textContent = `✅ ${val}に設定 (再起動で反映)`;
            showToast(`同時実行数を${val}に設定しました`, 'success');
        } else {
            resultEl.textContent = '❌ エラー';
            showToast(data.error || '保存に失敗しました', 'error');
        }
    } catch (e) {
        resultEl.textContent = '❌ 通信エラー';
        showToast('保存に失敗しました', 'error');
    }
}

async function restartWorker() {
    const resultEl = document.getElementById('worker-save-result');
    resultEl.textContent = '再起動中...';
    try {
        await fetch('/api/scheduler/worker/stop', { method: 'POST' });
        await new Promise(r => setTimeout(r, 1000));
        await fetch('/api/scheduler/worker/start', { method: 'POST' });
        resultEl.textContent = '✅ 再起動完了';
        showToast('ワーカーを再起動しました', 'success');
        setTimeout(() => loadWorkerSettings(), 1500);
    } catch (e) {
        resultEl.textContent = '❌ 再起動失敗';
        showToast('再起動に失敗しました', 'error');
    }
}

// --- Init on page load ---
document.addEventListener('DOMContentLoaded', function () {
    loadDBConfig();
    loadWorkerSettings();
    loadGmailSettings();
    checkGmailProgress();
});
