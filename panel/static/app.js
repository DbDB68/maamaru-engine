/**
 * まあ丸 近侍面板 — 前端逻辑
 */

(function() {
  'use strict';

  // ── DOM refs ──
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);

  const els = {
    tabs:       $$('.tab'),
    panels:     $$('.tab-panel'),
    logList:    $('#log-list'),
    logCount:   $('#log-count'),
    logStatus:  $('#log-status'),
    logContainer: $('#log-container'),
    scriptGrid: $('#script-grid'),
    taskIndicator: $('#task-indicator'),
    stopAll:    $('#btn-stop-all'),
    statusDot:  $('#status-dot'),
    statusText: $('#status-text'),
    btnSave:    $('#btn-save-settings'),
    honmaruStatus: $('#honmaru-status'),
    chatMessages: $('#chat-messages'),
    chatInput:  $('#chat-input'),
    chatSend:   $('#chat-send'),
    chatContainer: $('#chat-container'),
    autoScroll: $('#btn-auto-scroll'),
    clearLogs:  $('#btn-clear-logs'),
    noiseBtn:   $('#btn-noise'),
    viewToggle: $('#log-view-toggle'),
    clearChat:  $('#btn-clear-chat'),
    settingsBtn: $('#btn-settings'),
    themeBtn:   $('#btn-theme'),
    settingsModal: $('#settings-modal'),
    modalClose: $$('.modal-close'),
    cfgSave:    $('#cfg-save'),
    cfgClose:   $('#cfg-close'),
    // 仪表盘
    dashUpdated: $('#dash-updated'),
    dashRefresh: $('#btn-dash-refresh'),
    dashSnapshotAt: $('#dash-snapshot-at'),
    dashResources: $('#dash-resources'),
    dashResSub: $('#dash-res-sub'),
    dashFurnaces: $('#dash-furnaces'),
    dashExpeditions: $('#dash-expeditions'),
    dashSchedule: $('#dash-schedule'),
    dashDaily: $('#dash-daily'),
    dashNaihanka: $('#dash-naihanka'),
    dashRunning: $('#dash-running'),
    runFlavor: $('#run-flavor'),
    runSub: $('#run-sub'),
  };

  // ── State ──
  let lastLogId = 0;
  // 日志显示模式：visual=可视化（默认，分级上色+藏导航流水账）/ raw=源代码
  let logView = localStorage.getItem('maamaru_log_view') || 'visual';
  let showNoise = false;
  const logEntries = [];      // 内存里存一份，切模式时整列重绘
  const LOG_CAP = 500;
  let isRunning = false;
  let currentScript = null;
  let chatBusy = false;
  let scriptMeta = {};   // name -> {label, desc, params}

  // ── 主题切换：和纸（默认）⇄ 像素（👾）──
  function applyTheme(theme) {
    document.body.classList.toggle('theme-pixel', theme === 'pixel');
    els.themeBtn.textContent = theme === 'pixel' ? '🍂' : '👾';
    els.themeBtn.title = theme === 'pixel' ? '切回和纸主题' : '切换像素主题';
    localStorage.setItem('maamaru_theme', theme);
    // 同步到服务器（合并式存储，不会冲掉脚本参数记忆）
    fetch('/api/saved-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ theme }),
    }).catch(() => {});
  }
  els.themeBtn.addEventListener('click', () => {
    applyTheme(document.body.classList.contains('theme-pixel') ? 'washi' : 'pixel');
  });
  applyTheme(localStorage.getItem('maamaru_theme') || 'washi');

  // ── Tab switching ──
  els.tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      els.tabs.forEach(t => t.classList.remove('active'));
      els.panels.forEach(p => p.classList.remove('active'));
      tab.classList.add('active');
      document.getElementById('panel-' + tab.dataset.tab).classList.add('active');
    });
  });

  // ── Log: 分级 + 渲染 ──
  // 按消息内容分档：导航流水账 / 成功 / 警告 / 翻车 / 分节横幅 / 普通
  function classifyLog(msg) {
    if (msg.startsWith('[NAV]') || msg.startsWith('[MAA]')) return 'lv-noise';
    if (msg.includes('🛑') || msg.includes('✗') || msg.includes('翻车')) return 'lv-bad';
    if (msg.includes('⚠️')) return 'lv-warn';
    if (msg.includes('=====')) return 'lv-banner';
    if (msg.includes('✓') || msg.includes('✅')) return 'lv-ok';
    return 'lv-normal';
  }

  function makeLogDiv(entry) {
    const div = document.createElement('div');
    const lv = classifyLog(entry.message || '');
    div.className = 'log-entry ' + lv + (logView === 'raw' ? ' raw' : '');
    const ts = entry.ts ? new Date(entry.ts * 1000).toLocaleTimeString() : '';
    div.innerHTML = `
      <span class="ts">${ts}</span>
      <span class="tag tag-${escHtml(entry.script)}">${escHtml(entry.script)}</span>
      <span class="msg">${escHtml(entry.message)}</span>
    `;
    return div;
  }

  function applyViewMode() {
    els.logContainer.classList.toggle('view-visual', logView === 'visual');
    els.logContainer.classList.toggle('view-raw', logView === 'raw');
    els.logContainer.classList.toggle('show-noise', showNoise);
    els.noiseBtn.style.display = logView === 'visual' ? '' : 'none';
    els.noiseBtn.classList.toggle('active', showNoise);
    els.viewToggle.querySelectorAll('.vt-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.view === logView));
  }

  function renderAllLogs() {
    els.logList.innerHTML = '';
    logEntries.forEach(e => els.logList.appendChild(makeLogDiv(e)));
    if (els.autoScroll.classList.contains('active')) {
      els.logContainer.scrollTop = els.logContainer.scrollHeight;
    }
    els.logCount.textContent = logEntries.length + ' 条日志';
  }

  // ── Log: append entry ──
  function appendLog(entry) {
    logEntries.push(entry);
    if (logEntries.length > LOG_CAP) {
      logEntries.splice(0, logEntries.length - LOG_CAP);
      if (els.logList.firstChild) els.logList.removeChild(els.logList.firstChild);
    }
    els.logList.appendChild(makeLogDiv(entry));
    if (els.autoScroll.classList.contains('active')) {
      els.logContainer.scrollTop = els.logContainer.scrollHeight;
    }
    els.logCount.textContent = els.logList.children.length + ' 条日志';
  }

  // ── Log: load initial ──
  async function loadLogs() {
    try {
      const r = await fetch('/api/logs?limit=200');
      const data = await r.json();
      logEntries.length = 0;
      data.logs.forEach(e => logEntries.push(e));
      renderAllLogs();
      lastLogId = data.last_id;
    } catch(e) { /* will retry via SSE */ }
  }

  els.viewToggle.querySelectorAll('.vt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      logView = btn.dataset.view;
      localStorage.setItem('maamaru_log_view', logView);
      applyViewMode();
      renderAllLogs();
    });
  });

  els.noiseBtn.addEventListener('click', () => {
    showNoise = !showNoise;
    applyViewMode();
  });

  els.clearLogs.addEventListener('click', () => {
    logEntries.length = 0;
    els.logList.innerHTML = '';
    els.logCount.textContent = '0 条日志';
  });

  els.autoScroll.addEventListener('click', () => {
    els.autoScroll.classList.toggle('active');
  });

  applyViewMode();

  // ── SSE stream ──
  function connectSSE() {
    const evtSource = new EventSource('/api/logs/stream');
    evtSource.onmessage = (event) => {
      if (event.data === '') return;
      try {
        const entry = JSON.parse(event.data);
        if (entry.id) lastLogId = Math.max(lastLogId, entry.id);
        appendLog(entry);
      } catch(e) {}
    };
    evtSource.onerror = () => {
      setTimeout(connectSSE, 3000);
    };
  }

  // ── 本丸状态条 ──
  async function loadHonmaruStatus() {
    try {
      const r = await fetch('/api/status');
      const data = await r.json();
      const parts = [];
      const rep = data.latest_report;
      if (rep) {
        const fails = (rep.steps || []).filter(s => !String(s.status).startsWith('✓'));
        parts.push(`<span class="st-item ${rep.all_green ? 'st-ok' : 'st-bad'}">`
          + `📋 日课 ${rep.all_green ? '全绿' : fails.length + ' 项翻车'}`
          + `<small>${escHtml(rep.finished_at || '')}</small></span>`);
      }
      const inv = data.inventory;
      if (inv && inv.resources) {
        const r9 = inv.resources;
        parts.push(`<span class="st-item">💰 小判 ${r9['小判'] ?? '?'}<small>甲州金 ${r9['甲州金'] ?? '?'} · 委托符 ${r9['委托符'] ?? '?'} · 加速符 ${r9['加速符'] ?? '?'}</small></span>`);
        if (inv.doko) parts.push(`<span class="st-item">🗡 刀位 ${escHtml(inv.doko)}</span>`);
        if (inv.captured_at) parts.push(`<span class="st-item st-dim">快照 ${escHtml(inv.captured_at.slice(5, 16))}</span>`);
      }
      els.honmaruStatus.innerHTML = parts.join('') || '暂无状态数据';
    } catch(e) {
      els.honmaruStatus.textContent = '状态读取失败（面板后端没连上？）';
    }
  }

  // ── 仪表盘（总览首页）──
  // 倒计时状态：fetch 时记下剩余秒数，之后本地每秒递减，不一直烦后端
  let dashExpState = [];      // [{el, remain, doneEl}]
  let dashTickTimer = null;

  function fmtDuration(sec) {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    if (h > 0) return `${h}小时${String(m).padStart(2, '0')}分`;
    if (m > 0) return `${m}分${String(s).padStart(2, '0')}秒`;
    return `${s}秒`;
  }

  async function loadDashboard() {
    try {
      const r = await fetch('/api/dashboard');
      const data = await r.json();
      renderDashboard(data);
      els.dashUpdated.textContent = '更新于 ' + (data.server_time || '').slice(11, 19);
    } catch(e) {
      els.dashUpdated.textContent = '读取失败（后端没连上？）';
    }
  }

  function renderDashboard(data) {
    // ── 运行中横幅 ──
    const run = data.running || {};
    if (run.active) {
      els.dashRunning.style.display = '';
      els.runFlavor.textContent = run.flavor || '正在本丸干活🔧';
      dashRunningSince = run.started || null;
      updateRunSub(run.label);
    } else {
      els.dashRunning.style.display = 'none';
      dashRunningSince = null;
    }

    // ── 家底 ──
    const inv = data.inventory;
    if (inv && inv.resources) {
      const r9 = inv.resources;
      const tiles = [
        ['小判', r9['小判'], '🪙'],
        ['甲州金', r9['甲州金'], '💎'],
        ['委托符', r9['委托符'], '📜'],
        ['加速符', r9['加速符'], '⏩'],
      ];
      els.dashResources.innerHTML = tiles.map(([name, val, icon]) =>
        `<div class="res-tile"><span class="res-icon">${icon}</span>`
        + `<span class="res-num">${val == null ? '?' : Number(val).toLocaleString()}</span>`
        + `<span class="res-name">${name}</span></div>`).join('');
      const sub = ['木炭', '玉钢', '冷却材', '砥石']
        .map(k => `<span class="res-sub-item">${k} ${r9[k] == null ? '?' : Number(r9[k]).toLocaleString()}</span>`)
        .join('');
      els.dashResSub.innerHTML = sub
        + (inv.doko ? `<span class="res-sub-item">🗡 刀位 ${escHtml(inv.doko)}</span>` : '');
      els.dashSnapshotAt.textContent = inv.captured_at ? '快照 ' + inv.captured_at.slice(5, 16) : '';
      // 锻刀炉
      if (inv.furnaces && inv.furnaces.length) {
        els.dashFurnaces.innerHTML = inv.furnaces.map(f => {
          const busy = f.state === '锻造中';
          const cls = busy ? 'fn-busy' : 'fn-idle';
          const tail = busy && f.remain ? ` 剩 ${escHtml(f.remain)}` : (busy ? ' 快好了' : '');
          return `<span class="fn-chip ${cls}">炉${f.slot} ${escHtml(f.state)}${tail}</span>`;
        }).join('');
      } else {
        els.dashFurnaces.innerHTML = '';
      }
    } else {
      els.dashResources.innerHTML = '<div class="dash-empty">还没有库存快照<br><small>跑一次日课或库存快照就有了</small></div>';
      els.dashResSub.innerHTML = '';
      els.dashFurnaces.innerHTML = '';
    }

    // ── 远征（带倒计时）──
    if (dashTickTimer) { clearInterval(dashTickTimer); dashTickTimer = null; }
    dashExpState = [];
    const exps = data.expeditions || [];
    if (exps.length) {
      els.dashExpeditions.innerHTML = '';
      exps.forEach(e => {
        const row = document.createElement('div');
        row.className = 'exp-row' + (e.done ? ' exp-done' : '');
        row.innerHTML = `<span class="exp-team">部队${escHtml(String(e.team_no))}</span>`
          + `<span class="exp-map">${escHtml(e.map_code || '')} ${escHtml(e.map_name || '')}</span>`
          + `<span class="exp-count"></span>`;
        els.dashExpeditions.appendChild(row);
        if (e.remain_sec != null) {
          dashExpState.push({ el: row.querySelector('.exp-count'), remain: e.remain_sec });
        } else {
          row.querySelector('.exp-count').textContent = '时间不明';
        }
      });
      const tick = () => {
        dashExpState.forEach(st => {
          st.remain = Math.max(0, st.remain - 1);
          if (st.remain <= 0) {
            st.el.textContent = '🎉 该回来了';
            st.el.closest('.exp-row').classList.add('exp-done');
          } else {
            st.el.textContent = '剩 ' + fmtDuration(st.remain);
          }
        });
      };
      tick();
      dashTickTimer = setInterval(tick, 1000);
    } else {
      els.dashExpeditions.innerHTML = '<div class="dash-empty">没有部队在外面跑</div>';
    }
    // 今日待派
    const sched = data.schedule || [];
    els.dashSchedule.innerHTML = sched.length
      ? '<div class="sched-line">📅 今天待派：' + sched.map(s =>
          `${escHtml(s.time)} 部队${s.team_no}→${escHtml(s.map_code)}`).join(' · ') + '</div>'
      : '';

    // ── 日课 ──
    const rep = data.latest_report;
    if (rep && rep.steps && rep.steps.length) {
      const fails = rep.steps.filter(s => !String(s.status).startsWith('✓'));
      const head = `<div class="daily-banner ${rep.all_green ? 'daily-ok' : 'daily-bad'}">`
        + (rep.all_green ? '🌸 全绿收工' : `🍂 ${fails.length} 项翻车`)
        + `<small>${escHtml(rep.finished_at || '')}</small></div>`;
      const chips = rep.steps.map(s => {
        const ok = String(s.status).startsWith('✓');
        const skip = String(s.status).includes('⏭') || String(s.status).includes('跳');
        const cls = ok ? 'step-ok' : (skip ? 'step-skip' : 'step-bad');
        return `<span class="step-chip ${cls}">${escHtml(s.name)}</span>`;
      }).join('');
      els.dashDaily.innerHTML = head + `<div class="step-list">${chips}</div>`;
    } else {
      els.dashDaily.innerHTML = '<div class="dash-empty">今天还没跑过日课</div>';
    }

    // ── 内番 ──
    const nh = data.naihanka;
    els.dashNaihanka.innerHTML = (nh && nh.started_at)
      ? `<div class="nh-line">🌱 内番中<small>${escHtml(nh.started_at)} 开始</small></div>`
      : '<div class="dash-empty">内番闲着呢</div>';
  }

  els.dashRefresh.addEventListener('click', loadDashboard);
  // 横幅「已跑多久」每秒本地走；启动时间从最近一次 dashboard 数据来
  let dashRunningSince = null;
  let dashRunningLabel = '';
  function updateRunSub(label) {
    if (label) dashRunningLabel = label;
    if (!dashRunningSince) return;
    const elapsed = fmtDuration(Math.max(0, Date.now() / 1000 - dashRunningSince));
    els.runSub.textContent = (dashRunningLabel ? dashRunningLabel + ' · ' : '') + '已跑 ' + elapsed;
  }
  setInterval(() => updateRunSub(''), 1000);
  // 每 30 秒自动刷新一次（倒计时本身每秒本地走）；有活在跑时加快到 5 秒，步骤文案跟得上
  setInterval(() => {
    if (document.querySelector('.tab.active').dataset.tab === 'home') loadDashboard();
  }, 30000);
  setInterval(() => {
    if (dashRunningSince && document.querySelector('.tab.active').dataset.tab === 'home') loadDashboard();
  }, 5000);
  // 切回总览时立刻刷新
  document.querySelector('[data-tab="home"]').addEventListener('click', loadDashboard);

  // ── Scripts: load list ──
  async function loadScripts() {
    try {
      const r = await fetch('/api/scripts');
      const data = await r.json();
      isRunning = data.running;
      currentScript = data.current;
      scriptMeta = data.scripts;
      renderScripts();
      updateStatus(data.running, data.current);
    } catch(e) {
      els.scriptGrid.innerHTML = '<p style="color:var(--red)">无法连接面板后端，确认 panel 已启动。</p>';
    }
  }

  // ── 参数记忆：每张卡的上次选项存 localStorage，重启不丢 ──
  function savedParams(scriptName) {
    try {
      return JSON.parse(localStorage.getItem('maamaru_params_' + scriptName) || '{}');
    } catch(e) { return {}; }
  }

  // ── 参数表单渲染 ──
  function renderParamField(scriptName, field) {
    const wrap = document.createElement('div');
    wrap.className = 'pf pf-' + field.type;
    wrap._field = field;   // 条件显隐要用
    const saved = savedParams(scriptName)[field.key];
    const label = document.createElement('label');
    label.className = 'pf-label';
    label.textContent = field.label;
    wrap.appendChild(label);

    if (field.type === 'select') {
      const sel = document.createElement('select');
      sel.dataset.paramKey = field.key;
      field.options.forEach(([val, text]) => {
        const opt = document.createElement('option');
        opt.value = val;
        opt.textContent = text;
        if (val === String(field.default)) opt.selected = true;
        sel.appendChild(opt);
      });
      wrap.appendChild(sel);
    } else if (field.type === 'number') {
      const inp = document.createElement('input');
      inp.type = 'number';
      inp.dataset.paramKey = field.key;
      inp.value = field.default;
      if (field.min !== undefined) inp.min = field.min;
      if (field.max !== undefined) inp.max = field.max;
      wrap.appendChild(inp);
    } else if (field.type === 'text') {
      const inp = document.createElement('input');
      inp.type = 'text';
      inp.dataset.paramKey = field.key;
      inp.value = field.default || '';
      if (field.placeholder) inp.placeholder = field.placeholder;
      wrap.appendChild(inp);
    } else if (field.type === 'checks') {
      const box = document.createElement('div');
      box.className = 'pf-checks';
      box.dataset.paramKey = field.key;
      const defaults = new Set(field.default || []);
      field.options.forEach(name => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'pill' + (defaults.has(name) ? ' on' : '');
        pill.textContent = name;
        pill.dataset.value = name;
        pill.addEventListener('click', () => pill.classList.toggle('on'));
        box.appendChild(pill);
      });
      const tools = document.createElement('div');
      tools.className = 'pf-checks-tools';
      tools.innerHTML = '<a href="javascript:void 0" data-act="all">全选</a>'
                      + '<a href="javascript:void 0" data-act="none">清空</a>';
      tools.addEventListener('click', (e) => {
        const act = e.target.dataset.act;
        if (!act) return;
        box.querySelectorAll('.pill').forEach(p => {
          p.classList.toggle('on', act === 'all');
        });
      });
      wrap.appendChild(box);
      wrap.appendChild(tools);
    }

    // ── 应用上次记住的选项（有记忆就覆盖默认值）──
    if (saved !== undefined) {
      if (field.type === 'select') {
        const sel = wrap.querySelector('select');
        if ([...sel.options].some(o => o.value === String(saved))) sel.value = String(saved);
      } else if (field.type === 'number' || field.type === 'text') {
        wrap.querySelector('input').value = saved;
      } else if (field.type === 'checks' && Array.isArray(saved)) {
        const on = new Set(saved);
        wrap.querySelectorAll('.pill').forEach(p =>
          p.classList.toggle('on', on.has(p.dataset.value)));
      }
    }
    return wrap;
  }

  // ── 条件显隐：visibleWhen {key, is|not}，比如选了联队战才露圈数 ──
  function updateCardVisibility(card) {
    card.querySelectorAll('.pf').forEach(wrap => {
      const f = wrap._field;
      if (!f || !f.visibleWhen) return;
      const ctrl = card.querySelector(`[data-param-key="${f.visibleWhen.key}"]`);
      if (!ctrl) return;
      const val = ctrl.value;
      const vw = f.visibleWhen;
      const show = vw.is !== undefined ? val === vw.is
                 : vw.not !== undefined ? val !== vw.not : true;
      wrap.style.display = show ? '' : 'none';
    });
  }

  function collectParams(card) {
    const params = {};
    card.querySelectorAll('[data-param-key]').forEach(el => {
      const key = el.dataset.paramKey;
      if (el.classList.contains('pf-checks')) {
        params[key] = [...el.querySelectorAll('.pill.on')].map(p => p.dataset.value);
      } else {
        params[key] = el.value;
      }
    });
    return params;
  }

  // ── 脚本卡片渲染 ──
  function renderScripts() {
    els.scriptGrid.innerHTML = '';
    Object.entries(scriptMeta).forEach(([key, info]) => {
      const running = isRunning && currentScript === key;
      const card = document.createElement('div');
      card.className = 'script-card' + (running ? ' running' : '')
                     + (key === 'daily' ? ' card-wide' : '');
      card.dataset.script = key;

      const head = document.createElement('div');
      head.className = 's-head';
      head.innerHTML = `<span class="s-label">${escHtml(info.label)}</span>`
        + `<span class="s-badge">${running ? '⏳ 运行中' : '待命'}</span>`;
      card.appendChild(head);

      const desc = document.createElement('div');
      desc.className = 's-desc';
      desc.textContent = info.desc;
      card.appendChild(desc);

      // 参数区可折叠：有参数的卡才给折叠钮，状态记 localStorage
      const paramFields = info.params || [];
      let paramsWrap = null;
      if (paramFields.length) {
        const foldKey = 'maamaru_fold_' + key;
        const folded = localStorage.getItem(foldKey) === '1';
        card.classList.toggle('card-folded', folded);

        const foldBtn = document.createElement('button');
        foldBtn.className = 's-fold';
        foldBtn.type = 'button';
        foldBtn.title = '展开/收起参数';
        foldBtn.addEventListener('click', () => {
          const nowFolded = card.classList.toggle('card-folded');
          localStorage.setItem(foldKey, nowFolded ? '1' : '0');
        });
        head.appendChild(foldBtn);

        paramsWrap = document.createElement('div');
        paramsWrap.className = 's-params';
        paramFields.forEach(field => {
          paramsWrap.appendChild(renderParamField(key, field));
        });
        card.appendChild(paramsWrap);
      }

      const runBtn = document.createElement('button');
      runBtn.className = 's-run';
      runBtn.textContent = running ? '⏳ 正在跑…' : '▶ 运行';
      runBtn.disabled = isRunning;
      runBtn.addEventListener('click', () => runScript(key, collectParams(card)));
      card.appendChild(runBtn);

      // 条件显隐：控制器变了就重算，先算一遍初始状态
      card.querySelectorAll('select[data-param-key]').forEach(sel =>
        sel.addEventListener('change', () => updateCardVisibility(card)));
      updateCardVisibility(card);

      els.scriptGrid.appendChild(card);
    });
  }

  async function runScript(name, params) {
    if (isRunning) return;
    try {
      // 记住这次选项，下次打开/重启面板自动回填
      localStorage.setItem('maamaru_params_' + name, JSON.stringify(params || {}));
      const r = await fetch('/api/scripts/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({script: name, params: params || {}}),
      });
      const data = await r.json();
      if (data.ok) {
        isRunning = true;
        currentScript = name;
        updateStatus(true, name);
        renderScripts();
      } else {
        console.warn('run failed:', data.reason);
      }
    } catch(e) {
      console.error('run error:', e);
    }
  }

  async function stopScript() {
    try {
      await fetch('/api/scripts/stop', {method: 'POST'});
    } catch(e) {}
  }

  // ── Scripts: periodic status poll ──
  async function pollStatus() {
    try {
      const r = await fetch('/api/scripts');
      const data = await r.json();
      if (data.running !== isRunning || data.current !== currentScript) {
        isRunning = data.running;
        currentScript = data.current;
        updateStatus(data.running, data.current);
        renderScripts();
        if (!data.running) loadHonmaruStatus();  // 跑完刷新状态条
      }
    } catch(e) {}
  }

  function updateStatus(running, name) {
    const label = name && scriptMeta[name] ? scriptMeta[name].label : name;
    if (running) {
      els.statusDot.className = 'dot dot-yellow';
      els.statusText.textContent = label ? `运行中: ${label}` : '运行中';
      els.logStatus.textContent = `● 运行中: ${label || ''}`;
      els.logStatus.className = 'bar-status running';
      els.taskIndicator.textContent = `⏳ ${label || '运行中'}`;
      els.taskIndicator.className = 'badge badge-running';
      els.stopAll.disabled = false;
    } else {
      els.statusDot.className = 'dot dot-green';
      els.statusText.textContent = '待命中';
      els.logStatus.textContent = '● 空闲';
      els.logStatus.className = 'bar-status';
      els.taskIndicator.textContent = '空闲';
      els.taskIndicator.className = 'badge badge-idle';
      els.stopAll.disabled = true;
    }
  }

  els.stopAll.addEventListener('click', stopScript);

  // ── Chat ──
  async function loadChatHistory() {
    try {
      const r = await fetch('/api/chat/history');
      const data = await r.json();
      if (data.history && data.history.length > 0) {
        const sysMsg = els.chatMessages.querySelector('.msg-system');
        els.chatMessages.innerHTML = '';
        if (sysMsg) els.chatMessages.appendChild(sysMsg);
        data.history.forEach(h => {
          if (h.role === 'user') addChatBubble('user', h.content);
          else addChatBubble('assistant', h.content);
        });
      }
    } catch(e) {}
  }

  function addChatBubble(role, text) {
    const div = document.createElement('div');
    div.className = role === 'user' ? 'msg msg-user' : 'msg msg-system';
    div.innerHTML = `
      <div class="msg-avatar">${role === 'user' ? '🧑' : '🦊'}</div>
      <div class="msg-bubble">
        <div class="msg-name">${role === 'user' ? '审神者' : '狐之助'}</div>
        <div class="msg-text">${escHtml(text)}</div>
      </div>
    `;
    els.chatMessages.appendChild(div);
    els.chatContainer.scrollTop = els.chatContainer.scrollHeight;
  }

  function addTypingIndicator() {
    const div = document.createElement('div');
    div.className = 'msg msg-system msg-typing';
    div.id = 'typing-indicator';
    div.innerHTML = `
      <div class="msg-avatar">🦊</div>
      <div class="msg-bubble">
        <div class="msg-name">狐之助</div>
        <div class="msg-text">思考中…</div>
      </div>
    `;
    els.chatMessages.appendChild(div);
    els.chatContainer.scrollTop = els.chatContainer.scrollHeight;
  }

  function removeTypingIndicator() {
    const el = document.getElementById('typing-indicator');
    if (el) el.remove();
  }

  async function sendChatMessage(text) {
    if (!text.trim() || chatBusy) return;
    chatBusy = true;
    els.chatSend.disabled = true;
    els.chatInput.disabled = true;

    addChatBubble('user', text);
    els.chatInput.value = '';
    addTypingIndicator();

    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text}),
      });
      const data = await r.json();
      removeTypingIndicator();
      addChatBubble('assistant', data.reply);
    } catch(e) {
      removeTypingIndicator();
      addChatBubble('assistant', '（狐之助耳朵耷拉下来：主君…面板好像断线了）');
    }

    chatBusy = false;
    els.chatSend.disabled = false;
    els.chatInput.disabled = false;
    els.chatInput.focus();
  }

  els.chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendChatMessage(els.chatInput.value);
    }
  });
  els.chatInput.addEventListener('input', () => {
    els.chatSend.disabled = !els.chatInput.value.trim();
  });
  els.chatSend.addEventListener('click', () => sendChatMessage(els.chatInput.value));

  els.clearChat.addEventListener('click', () => {
    if (confirm('确定清空所有聊天记录？')) {
      els.chatMessages.innerHTML = `
        <div class="msg msg-system">
          <div class="msg-avatar">🦊</div>
          <div class="msg-bubble">
            <div class="msg-name">狐之助</div>
            <div class="msg-text">主君，您来了！本丸一切正常，有什么需要我帮忙的吗？</div>
          </div>
        </div>`;
    }
  });

  // ── Settings modal ──
  els.settingsBtn.addEventListener('click', async () => {
    els.settingsModal.style.display = 'flex';
    // 读当前配置：key 只回显掩码，地址和模型原样填
    try {
      const r = await fetch('/api/chat-config');
      const c = await r.json();
      $('#cfg-api-key').placeholder = c.has_key ? `已配置（${c.api_key_masked}），留空不改` : 'sk-...';
      $('#cfg-api-url').value = c.base_url || '';
      $('#cfg-model').value = c.model || '';
      // 角色设定：自定义的原样显示；没自定义就显示默认狐之助方便参考着改
      $('#cfg-prompt').value = c.system_prompt || c.default_prompt || '';
    } catch(e) {}
  });
  els.modalClose.forEach(btn => {
    btn.addEventListener('click', () => {
      els.settingsModal.style.display = 'none';
    });
  });
  els.cfgClose.addEventListener('click', () => {
    els.settingsModal.style.display = 'none';
  });
  els.settingsModal.addEventListener('click', (e) => {
    if (e.target === els.settingsModal) els.settingsModal.style.display = 'none';
  });
  els.cfgSave.addEventListener('click', async () => {
    const body = {
      api_key: $('#cfg-api-key').value.trim(),   // 留空 = 不改
      base_url: $('#cfg-api-url').value.trim(),
      model: $('#cfg-model').value.trim(),
      system_prompt: $('#cfg-prompt').value.trim(),
    };
    try {
      const r = await fetch('/api/chat-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.ok) {
        alert('保存成功，立刻生效（不用重启）！去「近侍」tab 找狐之助聊一句试试。');
        $('#cfg-api-key').value = '';
      } else {
        alert('保存失败：' + JSON.stringify(d));
      }
    } catch(e) {
      alert('保存失败：' + e.message);
    }
    els.settingsModal.style.display = 'none';
  });

  // ── 远征时刻表 ──
  const sched = {
    rows: $('#sched-rows'),
    add: $('#sched-add'),
    save: $('#sched-save'),
    msg: $('#sched-msg'),
  };
  let schedMaps = [];
  let schedLoaded = [];   // 上次从后端读到的，保存时好把 last_fired 续上
  const TEAM_OPTS = [["1","部队一"],["2","部队二"],["3","部队三"],["4","部队四"],["5","部队五"]];

  function schedRowHtml(e) {
    const teamOpts = TEAM_OPTS.map(([v, t]) =>
      `<option value="${v}" ${String(e.team_no) === v ? 'selected' : ''}>${t}</option>`).join('');
    const mapOpts = schedMaps.map(m =>
      `<option value="${m.code}" ${e.map_code === m.code ? 'selected' : ''}>`
      + `${m.code} · ${escHtml(m.name)}（${m.duration_text}）</option>`).join('');
    return `
      <input type="time" class="sr-time" value="${escHtml(e.time || '06:40')}">
      <select class="sr-team">${teamOpts}</select>
      <select class="sr-map">${mapOpts}</select>
      <label class="sr-on"><input type="checkbox" ${e.enabled !== false ? 'checked' : ''}> 启用</label>
      <button class="sr-del" title="删除这行">🗑</button>
    `;
  }

  function addSchedRow(e) {
    const div = document.createElement('div');
    div.className = 'sched-row';
    div.innerHTML = schedRowHtml(e || {time: '06:40', team_no: 5, map_code: schedMaps[0]?.code || '', enabled: true});
    div.querySelector('.sr-del').addEventListener('click', () => div.remove());
    sched.rows.appendChild(div);
  }

  async function loadSchedule() {
    try {
      const r = await fetch('/api/expedition-schedule');
      const data = await r.json();
      schedMaps = data.maps || [];
      schedLoaded = data.entries || [];
      sched.rows.innerHTML = '';
      schedLoaded.forEach(addSchedRow);
    } catch(e) {
      sched.msg.textContent = '时刻表读取失败';
    }
  }

  sched.add.addEventListener('click', () => addSchedRow());

  sched.save.addEventListener('click', async () => {
    const entries = [...sched.rows.querySelectorAll('.sched-row')].map(row => {
      const mapSel = row.querySelector('.sr-map');
      const m = schedMaps.find(x => x.code === mapSel.value);
      const time = row.querySelector('.sr-time').value;
      const team = parseInt(row.querySelector('.sr-team').value, 10);
      // 同一行上次今天已经派过的话，把 last_fired 续上，别存完又派一遍
      const prev = schedLoaded.find(x =>
        x.time === time && x.team_no === team && x.map_code === mapSel.value);
      return {
        time,
        team_no: team,
        map_code: mapSel.value,
        map_name: m ? m.name : '',
        enabled: row.querySelector('.sr-on input').checked,
        last_fired: prev ? (prev.last_fired || '') : '',
      };
    });
    try {
      const r = await fetch('/api/expedition-schedule', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entries}),
      });
      const data = await r.json();
      sched.msg.textContent = data.ok ? `✓ 存好了（${data.count} 条）` : '保存失败';
    } catch(e) {
      sched.msg.textContent = '保存失败（面板没连上？）';
    }
    setTimeout(() => { sched.msg.textContent = ''; }, 3000);
  });

  // ── Utility ──
  function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  // ── 设置持久化：服务器端保存/加载 ──

  async function loadSavedSettings() {
    try {
      const r = await fetch('/api/saved-settings');
      const data = await r.json();
      const params = data.params || {};
      // 把服务器端保存的设置合并进 localStorage，renderParamField 会自动应用
      Object.entries(params).forEach(([name, vals]) => {
        if (vals && typeof vals === 'object') {
          localStorage.setItem('maamaru_params_' + name, JSON.stringify(vals));
        }
      });
      // 主题也是服务器说了算（客户端/手机/浏览器 localStorage 各玩各的，统一拉齐）
      if (data.theme === 'pixel' || data.theme === 'washi') {
        applyTheme(data.theme);
      }
    } catch(e) {
      // 首加载失败无所谓，至少 localStorage 里的还在
    }
  }

  async function saveSettings() {
    // 从所有脚本卡片收集当前参数
    const allParams = {};
    document.querySelectorAll('.script-card').forEach(card => {
      const name = card.dataset.script;
      if (!name) return;
      allParams[name] = collectParams(card);
    });
    // 保存当前日志显示模式也算上（前端偏好）
    const payload = {params: allParams};
    try {
      const r = await fetch('/api/saved-settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const data = await r.json();
      // 也写 localStorage 做缓存
      Object.entries(allParams).forEach(([k, v]) => {
        localStorage.setItem('maamaru_params_' + k, JSON.stringify(v));
      });
      if (data.ok) {
        const oldText = els.btnSave.textContent;
        els.btnSave.textContent = '✓ 已保存';
        setTimeout(() => { els.btnSave.textContent = oldText; }, 2000);
      }
    } catch(e) {
      alert('保存失败，面板后端没连上？');
    }
  }

  if (els.btnSave) {
    els.btnSave.addEventListener('click', saveSettings);
  }

  // ── Init ──
  async function init() {
    // 先从服务器加载保存的设置（会在 render 之前写入 localStorage）
    await loadSavedSettings();
    await loadLogs();
    await loadScripts();
    await loadChatHistory();
    loadHonmaruStatus();
    loadSchedule();
    loadDashboard();
    connectSSE();
    setInterval(pollStatus, 3000);
    setInterval(loadHonmaruStatus, 60000);  // 状态条每分钟刷
    document.querySelector('[data-tab="chat"]').addEventListener('click', () => {
      setTimeout(() => els.chatInput.focus(), 100);
    });
  }

  init();
})();
