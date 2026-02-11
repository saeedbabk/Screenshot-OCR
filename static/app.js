/* ========================================
   Screenshot OCR v2.0 — Frontend App
   ======================================== */

const App = {
    currentPage: 'process',
    currentJob: null,
    eventSource: null,
    settings: {},
    previewData: [],

    init() {
        this.bindNavigation();
        this.loadSettings();
        this.loadHistory();
        this.showPage('process');
    },

    // ========================================
    // Navigation
    // ========================================

    bindNavigation() {
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => {
                const page = item.dataset.page;
                this.showPage(page);
            });
        });
    },

    showPage(page) {
        this.currentPage = page;

        // Update nav
        document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
        document.querySelector(`.nav-item[data-page="${page}"]`)?.classList.add('active');

        // Update pages
        document.querySelectorAll('.page').forEach(el => el.classList.remove('active'));
        const target = document.getElementById(`page-${page}`);
        if (target) {
            target.classList.add('active');
            // Re-trigger card animations
            target.querySelectorAll('.card').forEach((card, i) => {
                card.style.animation = 'none';
                card.offsetHeight; // trigger reflow
                card.style.animation = `fadeInUp 0.4s ease ${i * 0.05}s both`;
            });
        }

        // Refresh data for certain pages
        if (page === 'history') this.loadHistory();
        if (page === 'review') this.loadFailures();
    },

    // ========================================
    // Toast Notifications
    // ========================================

    toast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const icons = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `<span class="toast-icon">${icons[type]}</span><span>${message}</span>`;
        container.appendChild(toast);
        setTimeout(() => toast.remove(), 5000);
    },

    // ========================================
    // Browse Folders
    // ========================================

    async browseFolder(targetId) {
        try {
            const res = await fetch('/browse');
            const data = await res.json();
            if (data.path) {
                document.getElementById(targetId).value = data.path;
            }
        } catch (err) {
            this.toast('Failed to open folder dialog', 'error');
        }
    },

    // ========================================
    // Processing
    // ========================================

    async startProcessing() {
        const inputFolder = document.getElementById('input_folder').value;
        const outputFolder = document.getElementById('output_folder').value;

        if (!inputFolder || !outputFolder) {
            this.toast('Please select both Input and Output folders.', 'warning');
            return;
        }

        const btn = document.getElementById('start-btn');
        btn.disabled = true;
        btn.innerHTML = '<div class="spinner"></div> Starting...';

        // Show progress UI
        this.showProcessingUI();

        try {
            const res = await fetch('/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ input_folder: inputFolder, output_folder: outputFolder })
            });

            const data = await res.json();

            if (data.job_id) {
                this.currentJob = data.job_id;
                this.connectSSE(data.job_id);
            } else if (data.error) {
                this.toast(data.error, 'error');
                this.resetProcessingUI();
            } else {
                // Legacy non-async response
                this.showResults(data);
            }
        } catch (err) {
            this.toast('Failed to start processing: ' + err, 'error');
            this.resetProcessingUI();
        }
    },

    connectSSE(jobId) {
        if (this.eventSource) this.eventSource.close();

        this.eventSource = new EventSource(`/stream?job_id=${jobId}`);
        const log = document.getElementById('live-log');

        this.eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);

            if (data.type === 'progress') {
                this.updateProgress(data);
                this.appendLog(data);
            } else if (data.type === 'complete') {
                this.eventSource.close();
                this.eventSource = null;
                this.showResults(data.results);
                this.toast(`Done! ${data.results.success}/${data.results.total} images processed.`, 'success');
                this.loadHistory();
            } else if (data.type === 'error') {
                this.eventSource.close();
                this.eventSource = null;
                this.toast(data.message, 'error');
                this.resetProcessingUI();
            }
        };

        this.eventSource.onerror = () => {
            this.eventSource.close();
            this.eventSource = null;
            // Check job status via polling as fallback
            this.pollJobStatus(jobId);
        };
    },

    async pollJobStatus(jobId) {
        try {
            const res = await fetch(`/job/${jobId}/status`);
            const data = await res.json();

            if (data.status === 'complete') {
                this.showResults(data.results);
                this.toast(`Done! ${data.results.success}/${data.results.total} images processed.`, 'success');
            } else if (data.status === 'running') {
                setTimeout(() => this.pollJobStatus(jobId), 2000);
            } else if (data.status === 'error') {
                this.toast(data.message || 'Processing failed', 'error');
                this.resetProcessingUI();
            }
        } catch (err) {
            this.toast('Lost connection to server', 'error');
            this.resetProcessingUI();
        }
    },

    showProcessingUI() {
        document.getElementById('processing-status').classList.remove('hidden');
        document.getElementById('processing-results').classList.add('hidden');
        document.getElementById('progress-fill').style.width = '0%';
        document.getElementById('progress-text').textContent = '0%';
        document.getElementById('progress-detail').textContent = 'Initializing...';
        document.getElementById('live-log').innerHTML = '';

        // Update stats
        document.getElementById('stat-total').textContent = '-';
        document.getElementById('stat-success').textContent = '-';
        document.getElementById('stat-failed').textContent = '-';
        document.getElementById('stat-rate').textContent = '-';
    },

    updateProgress(data) {
        const pct = Math.round((data.current / data.total) * 100);
        document.getElementById('progress-fill').style.width = pct + '%';
        document.getElementById('progress-text').textContent = pct + '%';
        document.getElementById('progress-detail').textContent =
            `Processing ${data.current} of ${data.total}...`;

        // Update live stats
        if (data.success !== undefined) {
            document.getElementById('stat-total').textContent = data.total;
            document.getElementById('stat-success').textContent = data.success;
            document.getElementById('stat-failed').textContent = data.failed;
            const rate = data.current > 0 ? Math.round((data.success / data.current) * 100) : 0;
            document.getElementById('stat-rate').textContent = rate + '%';
        }
    },

    appendLog(data) {
        const log = document.getElementById('live-log');
        const entry = document.createElement('div');
        entry.className = `log-entry ${data.status === 'success' ? 'success' : data.status === 'failed' ? 'error' : ''}`;
        entry.innerHTML = `<span class="log-index">[${data.current}/${data.total}]</span> ${data.message || data.filename || ''}`;
        log.appendChild(entry);
        log.scrollTop = log.scrollHeight;
    },

    showResults(results) {
        document.getElementById('processing-status').classList.add('hidden');
        document.getElementById('processing-results').classList.remove('hidden');

        document.getElementById('stat-total').textContent = results.total;
        document.getElementById('stat-success').textContent = results.success;
        document.getElementById('stat-failed').textContent = results.failed;
        const rate = results.total > 0 ? Math.round((results.success / results.total) * 100) : 0;
        document.getElementById('stat-rate').textContent = rate + '%';

        document.getElementById('result-message').textContent =
            `Processed ${results.total} images. ${results.success} succeeded, ${results.failed} failed.`;
        document.getElementById('result-log-path').textContent = results.log_file || '';

        this.resetStartButton();
    },

    resetProcessingUI() {
        document.getElementById('processing-status').classList.add('hidden');
        this.resetStartButton();
    },

    resetStartButton() {
        const btn = document.getElementById('start-btn');
        btn.disabled = false;
        btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><polygon points="5,3 13,8 5,13"/></svg> Start Batch Processing';
    },

    // ========================================
    // Settings
    // ========================================

    async loadSettings() {
        try {
            const res = await fetch('/api/settings');
            if (res.ok) {
                this.settings = await res.json();
                this.populateSettings();
            }
        } catch (e) { /* Settings endpoint may not exist yet */ }
    },

    populateSettings() {
        const s = this.settings;
        const setChecked = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.checked = val;
        };
        const setVal = (id, val) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
        };

        setChecked('setting-easyocr', s.engines?.easyocr ?? true);
        setChecked('setting-paddleocr', s.engines?.paddleocr ?? true);
        setChecked('setting-trocr', s.engines?.trocr ?? true);
        setChecked('setting-cloudvision', s.engines?.cloud_vision ?? true);
        setVal('setting-confidence', s.cloud_vision_min_confidence ?? 0.85);
        setVal('setting-workers', s.parallel_workers ?? 2);
        setVal('setting-naming', s.naming_template ?? '{YYYY}-{MM}-{DD}_{HH}_{mm}_{ss}');
    },

    async saveSettings() {
        const settings = {
            engines: {
                easyocr: document.getElementById('setting-easyocr')?.checked ?? true,
                paddleocr: document.getElementById('setting-paddleocr')?.checked ?? true,
                trocr: document.getElementById('setting-trocr')?.checked ?? true,
                cloud_vision: document.getElementById('setting-cloudvision')?.checked ?? true,
            },
            cloud_vision_min_confidence: parseFloat(document.getElementById('setting-confidence')?.value || 0.85),
            parallel_workers: parseInt(document.getElementById('setting-workers')?.value || 2),
            naming_template: document.getElementById('setting-naming')?.value || '{YYYY}-{MM}-{DD}_{HH}_{mm}_{ss}',
        };

        try {
            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });

            if (res.ok) {
                this.settings = settings;
                this.toast('Settings saved!', 'success');
            } else {
                this.toast('Failed to save settings', 'error');
            }
        } catch (e) {
            this.toast('Failed to save settings', 'error');
        }
    },

    // ========================================
    // History
    // ========================================

    async loadHistory() {
        const tbody = document.getElementById('history-tbody');
        if (!tbody) return;

        try {
            const res = await fetch('/api/history');
            if (!res.ok) {
                tbody.innerHTML = '<tr><td colspan="6" class="table-empty">No history available yet.</td></tr>';
                return;
            }

            const jobs = await res.json();

            if (jobs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" class="table-empty">No processing jobs recorded yet.</td></tr>';
                return;
            }

            tbody.innerHTML = jobs.map(job => `
                <tr>
                    <td class="font-mono text-sm">${this.formatDate(job.timestamp)}</td>
                    <td class="text-sm" title="${job.input_path}">${this.shortPath(job.input_path)}</td>
                    <td>${job.total}</td>
                    <td><span class="text-success">${job.success}</span></td>
                    <td><span class="text-error">${job.failed}</span></td>
                    <td class="text-sm text-muted">${job.duration || '-'}</td>
                </tr>
            `).join('');
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="6" class="table-empty">Could not load history.</td></tr>';
        }
    },

    // ========================================
    // Review Failures
    // ========================================

    async loadFailures() {
        const container = document.getElementById('failures-container');
        if (!container) return;

        try {
            const res = await fetch('/api/failures');
            if (!res.ok) {
                container.innerHTML = '<div class="empty-state"><p>No failed images to review.</p></div>';
                return;
            }

            const failures = await res.json();

            if (failures.length === 0) {
                container.innerHTML = '<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg><p>All images processed successfully! Nothing to review.</p></div>';
                return;
            }

            container.innerHTML = failures.map((f, i) => `
                <div class="preview-row" data-index="${i}">
                    <img src="/api/thumbnail/${encodeURIComponent(f.filename)}" class="preview-thumb" alt="" onerror="this.style.display='none'">
                    <div class="text-sm font-mono">${f.filename}</div>
                    <div class="text-sm text-muted" title="${f.ocr_text}">${(f.ocr_text || 'No text detected').substring(0, 60)}...</div>
                    <div><input type="text" class="inline-edit" placeholder="YYYY-MM-DD_HH_mm_ss" data-filename="${f.filename}"></div>
                    <div class="preview-actions">
                        <button class="btn btn-sm btn-success" onclick="App.submitOverride('${f.filename}', ${i})">Apply</button>
                        <button class="btn btn-sm btn-secondary" onclick="App.retryImage('${f.filename}')">Retry</button>
                    </div>
                </div>
            `).join('');
        } catch (e) {
            container.innerHTML = '<div class="empty-state"><p>Could not load failures. Run a processing job first.</p></div>';
        }
    },

    async submitOverride(filename, index) {
        const input = document.querySelector(`.inline-edit[data-filename="${filename}"]`);
        if (!input || !input.value.trim()) {
            this.toast('Please enter a timestamp', 'warning');
            return;
        }

        try {
            const res = await fetch('/api/override', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename, timestamp: input.value.trim() })
            });

            if (res.ok) {
                this.toast(`Override applied for ${filename}`, 'success');
                this.loadFailures();
            } else {
                const data = await res.json();
                this.toast(data.error || 'Override failed', 'error');
            }
        } catch (e) {
            this.toast('Override failed', 'error');
        }
    },

    async retryImage(filename) {
        try {
            const res = await fetch('/api/retry', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filename })
            });

            if (res.ok) {
                const data = await res.json();
                if (data.success) {
                    this.toast(`Retry succeeded: ${data.timestamp}`, 'success');
                } else {
                    this.toast('Retry failed — no timestamp found', 'warning');
                }
                this.loadFailures();
            }
        } catch (e) {
            this.toast('Retry failed', 'error');
        }
    },

    // ========================================
    // Utilities
    // ========================================

    formatDate(ts) {
        if (!ts) return '-';
        const d = new Date(ts);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    },

    shortPath(p) {
        if (!p) return '-';
        const parts = p.replace(/\\/g, '/').split('/');
        return parts.length > 3 ? '.../' + parts.slice(-2).join('/') : p;
    }
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
