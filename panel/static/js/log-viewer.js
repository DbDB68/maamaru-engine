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

  const sectionNames = Object.freeze({
    SHOP: '万屋', TASK: '任务奖励', NAV: '界面导航',
    '出阵': '出阵', '快照': '库存快照', '日课': '日课', '脚本': '系统',
    '面板': '系统', '合成': '合成', '锻刀': '锻刀', '刀解': '刀解',
    '演练': '演练', '远征': '远征', '内番': '内番', '登录': '登录',
  });

  function analyze(message) {
    const text = String(message || '');
    const technical = /^\[(?:ADB|MAA)\]/.test(text)
      || /^(?:Traceback \(most recent call last\):|\s+File ")/.test(text);
    const detail = text.startsWith('[NAV]');
    const prefix = text.match(/^\[([^\]]+)\]\s*/);
    const banner = text.match(/^=+\s*(.*?)\s*=+$/);
    const reportLine = /^\s{2,}\S.+:\s*[✓⚠✗]/.test(text);
    let level = 'normal';

    if (text.includes('🛑') || text.includes('✗') || text.includes('翻车') || text.includes('异常退出')) level = 'bad';
    else if (text.includes('⚠')) level = 'warn';
    else if (banner) level = 'banner';
    else if (text.includes('✓') || text.includes('✅') || /完成|完毕|成功|已领/.test(text)) level = 'ok';

    return {
      visibility: technical ? 'technical' : detail ? 'detail' : 'progress',
      level,
      label: banner ? '日课' : reportLine ? '成绩' : (sectionNames[prefix?.[1]] || prefix?.[1] || '进度'),
      visualMessage: banner ? banner[1] : prefix ? text.slice(prefix[0].length) : text.trim(),
    };
  }

  function classify(message) {
    const info = analyze(message);
    return `lv-${info.level} lv-${info.visibility}`;
  }

  function createEntry(entry) {
    const info = analyze(entry.message);
    const row = document.createElement('div');
    row.className = `log-entry ${classify(entry.message)}${view === 'raw' ? ' raw' : ''}`;
    const timestamp = entry.ts ? new Date(entry.ts * 1000).toLocaleTimeString() : '';
    const label = view === 'visual' ? info.label : entry.script;
    const message = view === 'visual' ? info.visualMessage : entry.message;
    row.innerHTML = `
      <span class="ts">${timestamp}</span>
      <span class="tag tag-${esc(entry.script)}">${esc(label)}</span>
      <span class="msg">${esc(message)}</span>`;
    return row;
  }

  function updateCount() {
    const total = entries.length;
    if (view === 'raw') {
      ui().count.textContent = `${total} 条原始日志`;
      return;
    }
    const technical = entries.filter(entry => analyze(entry.message).visibility === 'technical').length;
    const details = entries.filter(entry => analyze(entry.message).visibility === 'detail').length;
    const visible = total - technical - (showNoise ? 0 : details);
    const hidden = technical + (showNoise ? 0 : details);
    ui().count.textContent = hidden ? `${visible} 条进度 · 已收起 ${hidden} 条过程日志` : `${visible} 条进度`;
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
    updateCount();
  }

  function render() {
    const u = ui();
    u.list.replaceChildren(...entries.map(createEntry));
    updateCount();
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
    updateCount();
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

  app.logViewer = Object.freeze({ init, load, append, render, classify, analyze, setRunning });
})(window);
