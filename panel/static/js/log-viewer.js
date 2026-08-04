/** 日志视图：历史加载、SSE、分级渲染、视图切换与运行状态。 */
(function registerLogViewer(global) {
  'use strict';

  const app = global.Maamaru;
  const $ = app.dom.one;
  const esc = app.dom.escape;
  const entries = [];
  const cap = 500;
  let view = localStorage.getItem('maamaru_log_view') || 'visual';
  let showNoise = false;
  let source = null;
  let reconnectTimer = null;
  let bound = false;

  const ui = () => ({
    list: $('#log-list'), count: $('#log-count'), status: $('#log-status'),
    container: $('#log-container'), autoScroll: $('#btn-auto-scroll'),
    clear: $('#btn-clear-logs'), noise: $('#btn-noise'), toggle: $('#log-view-toggle'),
  });

  function classify(message) {
    const text = String(message || '');
    if (text.startsWith('[NAV]') || text.startsWith('[MAA]')) return 'lv-noise';
    if (text.includes('🛑') || text.includes('✗') || text.includes('翻车')) return 'lv-bad';
    if (text.includes('⚠️')) return 'lv-warn';
    if (text.includes('=====')) return 'lv-banner';
    if (text.includes('✓') || text.includes('✅')) return 'lv-ok';
    return 'lv-normal';
  }

  function createEntry(entry) {
    const row = document.createElement('div');
    row.className = `log-entry ${classify(entry.message)}${view === 'raw' ? ' raw' : ''}`;
    const timestamp = entry.ts ? new Date(entry.ts * 1000).toLocaleTimeString() : '';
    row.innerHTML = `
      <span class="ts">${timestamp}</span>
      <span class="tag tag-${esc(entry.script)}">${esc(entry.script)}</span>
      <span class="msg">${esc(entry.message)}</span>`;
    return row;
  }

  function scrollToLatest() {
    const u = ui();
    if (u.autoScroll.classList.contains('active')) {
      u.container.scrollTop = u.container.scrollHeight;
    }
  }

  function applyView() {
    const u = ui();
    u.container.classList.toggle('view-visual', view === 'visual');
    u.container.classList.toggle('view-raw', view === 'raw');
    u.container.classList.toggle('show-noise', showNoise);
    u.noise.style.display = view === 'visual' ? '' : 'none';
    u.noise.classList.toggle('active', showNoise);
    u.toggle.querySelectorAll('.vt-btn').forEach(button =>
      button.classList.toggle('active', button.dataset.view === view));
  }

  function render() {
    const u = ui();
    u.list.replaceChildren(...entries.map(createEntry));
    u.count.textContent = `${entries.length} 条日志`;
    scrollToLatest();
  }

  function append(entry) {
    const u = ui();
    entries.push(entry);
    if (entries.length > cap) {
      entries.splice(0, entries.length - cap);
      u.list.firstChild?.remove();
    }
    u.list.appendChild(createEntry(entry));
    u.count.textContent = `${u.list.children.length} 条日志`;
    scrollToLatest();
    global.dispatchEvent(new CustomEvent('maamaru:log', { detail: entry }));
  }

  async function load() {
    try {
      const data = await app.api.json('/api/logs?limit=200');
      entries.splice(0, entries.length, ...(data.logs || []));
      render();
    } catch (_) {
      // SSE 连上后仍会继续接收新日志。
    }
  }

  function connect() {
    if (source) source.close();
    source = new EventSource('/api/logs/stream');
    source.onmessage = event => {
      if (!event.data) return;
      try {
        const entry = JSON.parse(event.data);
        append(entry);
        if (entry.script === 'scheduler' && String(entry.message || '').startsWith('⏳')) {
          app.dashboard?.showSchedulerWarning(entry.message);
        }
      } catch (_) {}
    };
    source.onerror = () => {
      source?.close();
      source = null;
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(connect, 3000);
    };
  }

  function setRunning(running, label = '') {
    const status = ui().status;
    status.textContent = running ? `● 运行中: ${label}` : '● 空闲';
    status.className = running ? 'bar-status running' : 'bar-status';
  }

  function bind() {
    if (bound) return;
    bound = true;
    const u = ui();
    u.toggle.querySelectorAll('.vt-btn').forEach(button => {
      button.addEventListener('click', () => {
        view = button.dataset.view;
        localStorage.setItem('maamaru_log_view', view);
        applyView();
        render();
      });
    });
    u.noise.addEventListener('click', () => {
      showNoise = !showNoise;
      applyView();
    });
    u.clear.addEventListener('click', () => {
      entries.length = 0;
      render();
    });
    u.autoScroll.addEventListener('click', () => u.autoScroll.classList.toggle('active'));
    applyView();
  }

  async function init() {
    bind();
    await load();
    connect();
  }

  app.logViewer = Object.freeze({ init, load, append, render, classify, setRunning });
})(window);
