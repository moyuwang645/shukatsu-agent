/* ===== Job Hunting Agent — Frontend JavaScript ===== */

// ===== Sidebar Toggle =====
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}

// ===== Notification Panel =====
function toggleNotifPanel() {
    const panel = document.getElementById('notif-panel');
    panel.classList.toggle('show');
}

// Close notification panel when clicking outside
document.addEventListener('click', (e) => {
    const panel = document.getElementById('notif-panel');
    const badge = document.getElementById('notif-badge');
    if (panel && badge && !panel.contains(e.target) && !badge.contains(e.target)) {
        panel.classList.remove('show');
    }
});

// ===== Modal =====
function openModal(title, bodyHtml) {
    document.getElementById('modal-title').textContent = title;
    document.getElementById('modal-body').innerHTML = bodyHtml;
    document.getElementById('modal-overlay').classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeModal() {
    document.getElementById('modal-overlay').classList.remove('show');
    document.body.style.overflow = '';
}

// Close modal with Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
});

// ===== Toast Notifications =====
let toastContainer;
function ensureToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        document.body.appendChild(toastContainer);
    }
}

function showToast(message, type = 'info', duration = 4000) {
    ensureToastContainer();
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) toast.remove();
    }, duration);
}

// ===== Job Detail View =====
async function viewJob(jobId) {
    try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) throw new Error('Not found');
        const job = await res.json();

        const statusOptions = ['interested', '本選', 'applied', 'interviewing', 'offered', 'rejected', 'withdrawn'];
        const statusLabels = {
            interested: '検討中', '本選': '📌 本選', applied: '応募済', interviewing: '面接中',
            offered: '内定', rejected: '不合格', withdrawn: '辞退'
        };

        let interviewsHtml = '';
        if (job.interviews && job.interviews.length > 0) {
            interviewsHtml = `
                <div class="detail-section">
                    <h4>🎯 面接一覧</h4>
                    ${job.interviews.map(iv => `
                        <div class="detail-item" style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);">
                            <div style="flex:1;">
                                <span style="font-weight:500;">${iv.interview_type || '面接'}</span>
                                <span style="margin-left:12px;color:var(--text-muted);">${iv.scheduled_at ? iv.scheduled_at.replace('T', ' ').substring(0, 16) : '日程未定'}</span>
                                ${iv.location ? `<div style="font-size:0.85em;color:var(--text-muted);margin-top:2px;">📍 ${iv.location}</div>` : ''}
                                ${iv.online_url ? `<div style="font-size:0.85em;margin-top:2px;"><a href="${iv.online_url}" target="_blank" style="color:#2ed573;">🔗 ${iv.online_url.length > 40 ? iv.online_url.substring(0, 40) + '...' : iv.online_url}</a></div>` : ''}
                            </div>
                            <button class="btn-icon" onclick="deleteInterviewConfirm(${iv.id}, this)" title="削除">🗑</button>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        // Build AI analysis section
        let aiHtml = '';
        if (job.ai_summary && job.ai_summary.trim()) {
            const lines = job.ai_summary.split('\n').filter(l => l.trim());
            aiHtml = `
                <div class="detail-section">
                    <h4>🤖 AI企業分析 <span style="font-size:0.7rem;color:var(--text-muted);font-weight:400;">powered by DeepSeek V3</span></h4>
                    <div class="ai-cards">
                        ${lines.map(line => {
                            let icon = '📋', color = '#6366f1', bgColor = 'rgba(99,102,241,0.08)';
                            if (line.includes('【事業】')) { icon = '🏢'; color = '#8b5cf6'; bgColor = 'rgba(139,92,246,0.08)'; }
                            else if (line.includes('【社風】')) { icon = '💡'; color = '#10b981'; bgColor = 'rgba(16,185,129,0.08)'; }
                            else if (line.includes('【選考】')) { icon = '📋'; color = '#3b82f6'; bgColor = 'rgba(59,130,246,0.08)'; }
                            else if (line.includes('【次のステップ】')) { icon = '⏭️'; color = '#f59e0b'; bgColor = 'rgba(245,158,11,0.08)'; }
                            else if (line.includes('【URL】')) { icon = '🔗'; color = '#2ed573'; bgColor = 'rgba(46,213,115,0.08)'; }
                            const cleanLine = line.replace(/^【[^】]+】/, '').trim();
                            const label = line.match(/^【([^】]+)】/)?.[1] || '';

                            if (line.includes('【URL】') && cleanLine.startsWith('http')) {
                                return `<div class="ai-card" style="background:${bgColor};border-left:3px solid ${color};padding:10px 12px;border-radius:6px;margin-bottom:6px;">
                                    <div style="font-size:0.72rem;color:${color};font-weight:600;margin-bottom:3px;">${icon} ${label}</div>
                                    <a href="${cleanLine}" target="_blank" style="color:${color};font-size:0.85rem;word-break:break-all;">${cleanLine}</a>
                                </div>`;
                            }
                            return `<div class="ai-card" style="background:${bgColor};border-left:3px solid ${color};padding:10px 12px;border-radius:6px;margin-bottom:6px;">
                                <div style="font-size:0.72rem;color:${color};font-weight:600;margin-bottom:3px;">${icon} ${label}</div>
                                <div style="font-size:0.85rem;color:var(--text-primary);line-height:1.5;">${cleanLine}</div>
                            </div>`;
                        }).join('')}
                    </div>
                </div>
            `;
        }

        openModal(job.company_name, `
            <div class="job-detail">
                <div class="detail-row">
                    <label>ステータス</label>
                    <select onchange="updateJobField(${job.id}, 'status', this.value)" class="select-sm">
                        ${statusOptions.map(s =>
            `<option value="${s}" ${job.status === s ? 'selected' : ''}>${statusLabels[s] || s}</option>`
        ).join('')}
                    </select>
                </div>
                <div class="detail-row"><label>職種</label><input class="edit-input" value="${job.position || ''}" placeholder="なし" onblur="updateJobField(${job.id}, 'position', this.value)"></div>
                <div class="detail-row"><label>求人URL</label><input class="edit-input" value="${job.job_url || ''}" placeholder="https://..." onblur="updateJobField(${job.id}, 'job_url', this.value)">${job.job_url ? `<a href="${job.job_url}" target="_blank" style="margin-left:6px;font-size:0.8em;" onclick="event.stopPropagation()">🔗</a>` : ''}</div>
                <div class="detail-row"><label>締切</label><input type="date" class="edit-input" value="${job.deadline || ''}" onblur="updateJobField(${job.id}, 'deadline', this.value)"></div>
                <div class="detail-row"><label>勤務地</label><input class="edit-input" value="${job.location || ''}" placeholder="なし" onblur="updateJobField(${job.id}, 'location', this.value)"></div>
                <div class="detail-row"><label>給与</label><input class="edit-input" value="${job.salary || ''}" placeholder="なし" onblur="updateJobField(${job.id}, 'salary', this.value)"></div>
                <div class="detail-row"><label>業界</label><span style="flex:1;text-align:right;">${job.industry || 'なし'}</span></div>
                <div class="detail-row"><label>ソース</label><span class="source-tag source-${job.source}">${job.source || 'manual'}</span></div>
                <div class="detail-row" style="align-items:flex-start;"><label>メモ</label><textarea class="edit-input" rows="3" placeholder="なし" onblur="updateJobField(${job.id}, 'notes', this.value)" style="resize:vertical;">${job.notes || ''}</textarea></div>

                ${job.job_description ? `
                <div class="detail-section">
                    <h4>📝 仕事内容</h4>
                    <div style="font-size:0.9rem; color:var(--text-muted); white-space:pre-wrap; max-height:200px; overflow-y:auto; padding:8px; background:var(--background-alt); border-radius:4px;">${job.job_description}</div>
                </div>` : ''}

                ${aiHtml}

                ${interviewsHtml}

                <div class="form-actions" style="justify-content: space-between;">
                    <button class="btn btn-outline" onclick="showAddInterviewModal(${job.id})">＋ 面接追加</button>
                    <div style="display:flex;gap:8px;">
                        <button class="btn btn-ghost" style="color:var(--accent-red)" id="delete-btn-${job.id}" onclick="deleteJobConfirm(${job.id}, this)">削除</button>
                        <button class="btn btn-primary" onclick="closeModal()">閉じる</button>
                    </div>
                </div>
            </div>
        `);
    } catch (err) {
        showToast('求人情報の取得に失敗しました', 'error');
    }
}

async function updateJobField(jobId, field, value) {
    try {
        await fetch(`/api/jobs/${jobId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ [field]: value })
        });
        showToast('更新しました', 'success');
    } catch (err) {
        showToast('更新に失敗しました', 'error');
    }
}

async function updateJobStatus(jobId, status) {
    try {
        await fetch(`/api/jobs/${jobId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });
        showToast('ステータスを更新しました', 'success');
    } catch (err) {
        showToast('更新に失敗しました', 'error');
    }
}

async function deleteJobConfirm(jobId, btn) {
    console.log('[delete] deleteJobConfirm called, jobId=', jobId);
    // Two-click confirmation: first click changes text, second click deletes
    if (!btn.dataset.confirmed) {
        btn.dataset.confirmed = 'true';
        btn.textContent = '本当に削除？';
        btn.style.fontWeight = '700';
        setTimeout(() => { btn.dataset.confirmed = ''; btn.textContent = '削除'; btn.style.fontWeight = ''; }, 3000);
        return;
    }
    try {
        console.log('[delete] Sending DELETE /api/jobs/' + jobId);
        const res = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
        console.log('[delete] Response status:', res.status);
        closeModal();
        showToast('求人を削除しました', 'success');
        setTimeout(() => location.reload(), 500);
    } catch (err) {
        console.error('[delete] Error:', err);
        showToast('削除に失敗しました', 'error');
    }
}

// ===== Interview =====
function showAddInterviewModal(jobId) {
    closeModal();
    setTimeout(() => {
        openModal('面接追加', `
            <form onsubmit="submitInterview(event, ${jobId})">
                <div class="form-group">
                    <label>面接タイプ</label>
                    <select id="iv-type" name="interview_type">
                        <option value="一次面接">一次面接</option>
                        <option value="二次面接">二次面接</option>
                        <option value="最終面接">最終面接</option>
                        <option value="グループディスカッション">グループディスカッション</option>
                        <option value="Webテスト">Webテスト</option>
                        <option value="適性検査">適性検査</option>
                        <option value="その他">その他</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>日時</label>
                    <input type="datetime-local" id="iv-datetime" name="scheduled_at">
                </div>
                <div class="form-group">
                    <label>場所</label>
                    <input type="text" id="iv-location" name="location" placeholder="例: 本社5F">
                </div>
                <div class="form-group">
                    <label>オンラインURL</label>
                    <input type="url" id="iv-url" name="online_url" placeholder="https://zoom.us/...">
                </div>
                <div class="form-group">
                    <label>メモ</label>
                    <textarea id="iv-notes" name="notes" rows="2"></textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-ghost" onclick="closeModal()">キャンセル</button>
                    <button type="submit" class="btn btn-primary">追加</button>
                </div>
            </form>
        `);
    }, 200);
}

async function submitInterview(e, jobId) {
    e.preventDefault();
    const form = e.target;
    const data = Object.fromEntries(new FormData(form));
    data.job_id = jobId;
    try {
        const res = await fetch('/api/interviews', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (res.ok) {
            closeModal();
            showToast('面接を追加しました', 'success');
            setTimeout(() => location.reload(), 500);
        }
    } catch (err) {
        showToast('追加に失敗しました', 'error');
    }
}

async function deleteInterviewConfirm(interviewId, btn) {
    if (!btn) { console.warn('no btn ref'); return; }
    if (!btn.dataset.confirmed) {
        btn.dataset.confirmed = 'true';
        btn.textContent = '確認？';
        btn.style.color = '#ff4757';
        setTimeout(() => { btn.dataset.confirmed = ''; btn.textContent = '🗑'; btn.style.color = ''; }, 3000);
        return;
    }
    try {
        await fetch(`/api/interviews/${interviewId}`, { method: 'DELETE' });
        showToast('面接を削除しました', 'success');
        closeModal();
        setTimeout(() => location.reload(), 500);
    } catch (err) {
        showToast('削除に失敗しました', 'error');
    }
}

// ===== Notifications =====
async function markAllRead() {
    try {
        await fetch('/api/notifications/read-all', { method: 'POST' });
        document.querySelectorAll('.notif-item.unread').forEach(el => el.classList.remove('unread'));
        const badge = document.querySelector('.badge');
        if (badge) badge.remove();
        showToast('すべて既読にしました', 'success');
    } catch (err) { }
}

// Poll for new notifications every 60 seconds
setInterval(async () => {
    try {
        const res = await fetch('/api/notifications/unread');
        const data = await res.json();
        const badge = document.querySelector('.badge');
        if (data.length > 0) {
            if (badge) {
                badge.textContent = data.length;
            } else {
                const badgeEl = document.createElement('span');
                badgeEl.className = 'badge';
                badgeEl.textContent = data.length;
                document.getElementById('notif-badge').appendChild(badgeEl);
            }
        } else {
            if (badge) badge.remove();
        }
    } catch (err) { }
}, 60000);

// ===== Scrape Trigger =====
async function triggerScrape() {
    showToast('マイナビの自動同期を開始します...', 'info');
    try {
        const res = await fetch('/api/scrape/mynavi', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`✅ マイナビ同期完了: ${data.jobs_found}件検出、${data.jobs_updated}件新規`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(`❌ ${data.error_message || '同期に失敗しました'}`, 'error', 8000);
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error', 8000);
    }
}

async function triggerGaishiScrape() {
    showToast('外資就活の同期を開始します...', 'info');
    try {
        const res = await fetch('/api/scrape/gaishishukatsu', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`✅ 外資就活同期完了: ${data.jobs_found}件検出、${data.jobs_updated}件新規`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(`❌ ${data.error_message || '同期に失敗しました'}`, 'error', 8000);
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error', 8000);
    }
}

async function triggerCareerTasuScrape() {
    showToast('キャリタス就活の同期を開始します...', 'info');
    try {
        const res = await fetch('/api/scrape/career_tasu', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`✅ キャリタス同期完了: ${data.jobs_found}件検出、${data.jobs_updated}件新規`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(`❌ ${data.error_message || '同期に失敗しました'}`, 'error', 8000);
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error', 8000);
    }
}

async function triggerOneCareerScrape() {
    showToast('ワンキャリアの同期を開始します...', 'info');
    try {
        const res = await fetch('/api/scrape/onecareer', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`✅ ワンキャリア同期完了: ${data.jobs_found}件検出、${data.jobs_updated}件新規`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(`❌ ${data.error_message || '同期に失敗しました'}`, 'error', 8000);
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error', 8000);
    }
}

async function triggerEngShukatuScrape() {
    showToast('エンジニア就活の同期を開始します...', 'info');
    try {
        const res = await fetch('/api/scrape/engineer_shukatu', { method: 'POST' });
        const data = await res.json();
        if (data.status === 'success') {
            showToast(`✅ エンジニア就活同期完了: ${data.jobs_found}件検出、${data.jobs_updated}件新規`, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showToast(`❌ ${data.error_message || '同期に失敗しました'}`, 'error', 8000);
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error', 8000);
    }
}

async function triggerAllScrape() {
    showToast('全サイトの同期を開始します...', 'info');
    let totalFound = 0, totalNew = 0, errors = [];
    for (const [name, url] of [
        ['マイナビ', '/api/scrape/mynavi'],
        ['外資就活', '/api/scrape/gaishishukatsu'],
        ['キャリタス', '/api/scrape/career_tasu'],
        ['ワンキャリア', '/api/scrape/onecareer'],
        ['エンジニア就活', '/api/scrape/engineer_shukatu'],
    ]) {
        try {
            const res = await fetch(url, { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                totalFound += data.jobs_found || 0;
                totalNew += data.jobs_updated || 0;
            } else {
                errors.push(name);
            }
        } catch (err) {
            errors.push(name);
        }
    }
    if (errors.length === 0) {
        showToast(`✅ 全サイト同期完了: ${totalFound}件検出、${totalNew}件新規`, 'success');
    } else {
        showToast(`⚠️ 一部失敗 (${errors.join(', ')}): ${totalFound}件検出、${totalNew}件新規`, 'warning', 8000);
    }
    setTimeout(() => location.reload(), 1500);
}

// ===== Manual Login Trigger =====
async function triggerManualLogin() {
    const email = document.getElementById('mynavi-email').value;
    const pwd = document.getElementById('mynavi-password').value;
    if (!email || !pwd) {
        showToast('先にメールアドレスとパスワードを入力して保存してください', 'error');
        return;
    }

    // Auto-save credentials first just in case
    await fetch('/api/settings/credentials', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mynavi_email: email, mynavi_password: pwd })
    });

    showToast('ブラウザを起動しています... ポップアップウィンドウでログインしてください（最大2分待機します）', 'info', 10000);

    try {
        const res = await fetch('/api/mynavi/manual-login', { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast(`✅ ${data.message}`, 'success', 5000);
            setTimeout(() => triggerScrape(), 2000); // Auto-start scrape using the new cookies
        } else {
            showToast(`❌ ${data.error || 'ログインに失敗しました'}`, 'error', 8000);
        }
    } catch (err) {
        showToast('❌ サーバーとの通信に失敗しました', 'error', 8000);
    }
}

// ===== Add detail-row styles dynamically =====
const style = document.createElement('style');
style.textContent = `
    .job-detail { }
    .detail-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--border);
    }
    .detail-row label {
        font-weight: 500;
        color: var(--text-muted);
        min-width: 80px;
    }
    .detail-row span, .detail-row a {
        flex: 1;
        text-align: right;
        word-break: break-all;
    }
    .detail-section {
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--border);
    }
    .detail-section h4 {
        margin-bottom: 10px;
        font-size: 0.95rem;
    }
`;
document.head.appendChild(style);
