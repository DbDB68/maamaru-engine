/**
 * まあ丸 近侍面板 — 前端逻辑
 * 2026-07-30 布局重构（按鹿目圆草图）：
 *   概览 = 左常用功能列表 + 中选中功能区/日志 + 右统计表
 *   配置 = 双栏卡片，参数内嵌卡片直接调，运行按钮小小的
 */

(function() {
  'use strict';

  // ── DOM refs ──
  const frontend = window.Maamaru;
  const $ = frontend?.dom.one || ((s) => document.querySelector(s));
  const $$ = frontend?.dom.all || ((s) => document.querySelectorAll(s));

  const els = {
    tabs:       $$('.tab'),
    panels:     $$('.tab-panel'),
    logList:    $('#log-list'),
    logCount:   $('#log-count'),
    logStatus:  $('#log-status'),
    logContainer: $('#log-container'),
    scriptGrid: $('#script-grid'),
    configNav:  $('#config-nav'),
    configDetail: $('#config-detail'),
    schedPanel: $('#sched-panel'),
    schedDock:  $('#sched-dock'),
    funcList:   $('#func-list'),
    funcDetail: $('#func-detail'),
    taskIndicator: $('#task-indicator'),
    stopAll:    $('#btn-stop-all'),
    statusDot:  $('#status-dot'),
    statusText: $('#status-text'),
    chatMessages: $('#chat-messages'),
    chatInput:  $('#chat-input'),
    chatSend:   $('#chat-send'),
    chatContainer: $('#chat-container'),
    autoScroll: $('#btn-auto-scroll'),
    clearLogs:  $('#btn-clear-logs'),
    noiseBtn:   $('#btn-noise'),
    viewToggle: $('#log-view-toggle'),
    clearChat:  $('#btn-clear-chat'),
    settingsBtn: null,
    themeBtn:   $('#btn-theme'),
    systemNav:  $('#system-nav'),
    systemDetail: $('#system-detail'),
    sysStatus:  $('#sys-status'),
    // 统计表
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
  // 概览左侧选中的功能（默认日课，记住上次选择）
  let selectedScript = localStorage.getItem('maamaru_selected') || 'daily';
  // 参数表单：创建一次常驻内存，配置页渲染时挂进卡片（DOM 搬家，状态不丢）
  const paramForms = {};
  // 全局名单配置缓存（repair_blacklist / dismantle_whitelist）
  let configLists = null;

  // 配置页左侧分组（按青叶酩酊草图）
  const CONFIG_GROUPS = [
    { label: '日常配置', items: [
      { key: 'daily', label: '一键日课' },
      { key: 'repair', label: '手入' },
    ]},
    { label: '活动配置', items: [
      { key: 'raid', label: '联队战' },
      { key: 'pumpkin', label: '南瓜大作战' },
    ]},
    { label: '出阵配置', items: [
      { key: 'sortie', label: '出阵' },
      { key: 'sakura', label: '刷花' },
      { key: 'practice', label: '演练' },
    ]},
    { label: '后勤配置', items: [
      { key: 'expedition', label: '远征' },
      { key: 'dispatch', label: '派遣远征' },
      { key: 'forge', label: '锻刀' },
      { key: 'sugar', label: '炼糖' },
      { key: 'snapshot', label: '库存快照' },
    ]},
    { label: '名单设置', items: [
      { key: '_repair_blacklist', label: '手入黑名单', listKey: 'repair_blacklist',
        desc: '修复列表里看到这几把刀就跳过，适合碰瓷队带伤上班' },
      { key: '_dismantle_whitelist', label: '刀解白名单', listKey: 'dismantle_whitelist',
        desc: '刀解只解这里面的刀，留空不解' },
      { key: 'pumpkin_watch', label: '南瓜监视名单', target: 'pumpkin', scrollTo: 'watch',
        desc: '只刷这些刀的剪影，认出别的刀就烧令牌换板子' },
    ]},
  ];

  function resolveAlias(key) {
    for (const g of CONFIG_GROUPS) {
      for (const it of g.items) {
        if (it.key === key) return it.target || it.key;
      }
    }
    return key;
  }

  function findConfigItem(key) {
    for (const g of CONFIG_GROUPS) {
      for (const it of g.items) {
        if (it.key === key) return it;
      }
    }
    return null;
  }

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
        if (entry.script === 'scheduler' && String(entry.message || '').startsWith('⏳')) {
          showSchedulerWarning(entry.message);
        }
      } catch(e) {}
    };
    evtSource.onerror = () => {
      setTimeout(connectSSE, 3000);
    };
  }

  function showSchedulerWarning(message) {
    els.dashRunning.style.display = '';
    els.runFlavor.textContent = '⏳ 远征即将接管游戏';
    els.runSub.innerHTML = `${escHtml(message)} `
      + '<button id="cancel-scheduled-exp" class="small-btn">先别动游戏</button>';
    const btn = document.getElementById('cancel-scheduled-exp');
    if (btn) btn.addEventListener('click', async () => {
      await fetch('/api/expedition-pause', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({minutes: 30}),
      });
      els.runFlavor.textContent = '已暂停自动远征 30 分钟';
      els.runSub.textContent = '这次不会接管游戏';
      setTimeout(() => { if (!isRunning) els.dashRunning.style.display = 'none'; }, 3000);
    });
  }

  // ── 统计表（概览右栏）──
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
      els.dashUpdated.textContent = '读取失败';
    }
  }

  function renderDashboard(data) {
    // ── 运行中横幅（小狐狸跑步区）──
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
  // 切回概览时立刻刷新
  document.querySelector('[data-tab="home"]').addEventListener('click', loadDashboard);

  // ── Scripts: load list ──
  async function loadScripts() {
    try {
      const r = await fetch('/api/scripts');
      const data = await r.json();
      isRunning = data.running;
      currentScript = data.current;
      scriptMeta = data.scripts;
      if (!scriptMeta[resolveAlias(selectedScript)]) selectedScript = 'daily';
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

  // ── 刀剑候选列表（名单选择器共用）──
  let swordCandidates = [];
  let swordCandidatesPromise = null;

  function ensureSwordCandidates() {
    if (swordCandidatesPromise) return swordCandidatesPromise;
    swordCandidatesPromise = fetch('/api/swords')
      .then(r => r.json())
      .then(data => {
        swordCandidates = (data.swords || []).filter(s => s.name_zh || s.name);
        return swordCandidates;
      })
      .catch(() => { swordCandidates = []; return []; });
    return swordCandidatesPromise;
  }

  function renderSwordList(wrap, textarea, presets) {
    if (frontend.swordPicker) {
      frontend.swordPicker.render(wrap, textarea, presets);
      return;
    }
    wrap.classList.add('pf-sword-list');
    textarea.classList.add('sl-input');
    textarea.rows = 3;

    const editor = document.createElement('div');
    editor.className = 'sl-editor';

    // 预设按钮
    if (presets && presets.length) {
      const presetsDiv = document.createElement('div');
      presetsDiv.className = 'sl-presets';
      presets.forEach(p => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'small-btn sl-preset';
        btn.textContent = p.label;
        btn.addEventListener('click', () => {
          const arr = (p.value || []).map(String);
          textarea.value = arr.join('，');
          syncChips();
          textarea.dispatchEvent(new Event('change', { bubbles: true }));
        });
        presetsDiv.appendChild(btn);
      });
      editor.appendChild(presetsDiv);
    }

    const search = document.createElement('input');
    search.type = 'text';
    search.className = 'sl-search';
    search.placeholder = '搜索刀剑…';
    editor.appendChild(search);

    const pool = document.createElement('div');
    pool.className = 'sl-pool';
    const loading = document.createElement('div');
    loading.className = 'sl-loading';
    loading.textContent = '加载刀剑名册中…';
    pool.appendChild(loading);
    editor.appendChild(pool);

    wrap.appendChild(editor);

    function parseNames() {
      return String(textarea.value || '')
        .split(/[,，、]/)
        .map(s => s.trim())
        .filter(Boolean);
    }

    function syncChips() {
      const on = new Set(parseNames());
      pool.querySelectorAll('.sl-chip').forEach(chip => {
        chip.classList.toggle('on', on.has(chip.dataset.name));
      });
    }

    function toggleName(name) {
      const arr = parseNames();
      const idx = arr.indexOf(name);
      if (idx >= 0) arr.splice(idx, 1);
      else arr.push(name);
      textarea.value = arr.join('，');
      syncChips();
      textarea.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function filterChips() {
      const q = search.value.trim().toLowerCase();
      pool.querySelectorAll('.sl-chip').forEach(chip => {
        const txt = (chip.textContent || '').toLowerCase();
        const name = (chip.dataset.name || '').toLowerCase();
        chip.style.display = (!q || txt.includes(q) || name.includes(q)) ? '' : 'none';
      });
      pool.querySelectorAll('.sl-type-group').forEach(group => {
        const hasVisible = [...group.querySelectorAll('.sl-chip')]
          .some(chip => chip.style.display !== 'none');
        group.style.display = hasVisible ? '' : 'none';
      });
    }

    textarea.addEventListener('input', syncChips);
    search.addEventListener('input', filterChips);

    ensureSwordCandidates().then(() => {
      pool.innerHTML = '';
      const typeOrder = ['短刀', '脇差', '打刀', '太刀', '大太刀', '槍', '薙刀', '剣', '其他'];
      const grouped = new Map();
      swordCandidates.forEach(s => {
        const type = s.type || '其他';
        if (!grouped.has(type)) grouped.set(type, []);
        grouped.get(type).push(s);
      });
      [...grouped.keys()].sort((a, b) => {
        const ai = typeOrder.indexOf(a);
        const bi = typeOrder.indexOf(b);
        return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.localeCompare(b, 'zh-CN');
      }).forEach(type => {
        const group = document.createElement('section');
        group.className = 'sl-type-group';
        const head = document.createElement('div');
        head.className = 'sl-type-head';
        head.innerHTML = `<span>${escHtml(type)}</span><small>${grouped.get(type).length}</small>`;
        group.appendChild(head);
        const chips = document.createElement('div');
        chips.className = 'sl-type-chips';
        grouped.get(type).sort((a, b) =>
          (a.name_zh || a.name).localeCompare((b.name_zh || b.name), 'zh-CN')
        ).forEach(s => {
          const name = s.name_zh || s.name;
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'sl-chip';
          chip.dataset.name = name;
          // 只显示中文名（脚本不做日语适配，省得 pill 太宽重复）
          chip.textContent = name;
          chip.addEventListener('click', () => toggleName(name));
          chips.appendChild(chip);
        });
        group.appendChild(chips);
        pool.appendChild(group);
      });
      syncChips();
    });
  }

  async function loadConfigLists() {
    if (configLists) return configLists;
    try {
      const r = await fetch('/api/config-lists');
      configLists = await r.json();
    } catch(e) {
      configLists = { repair_blacklist: [], dismantle_whitelist: [] };
    }
    return configLists;
  }

  function renderDurationList(wrap, hidden, initialValue) {
    const editor = document.createElement('div');
    editor.className = 'duration-editor';
    editor.innerHTML = `
      <div class="duration-pick">
        <label><input class="dur-hour" type="number" min="0" max="23" value="3"><span>时</span></label>
        <i>:</i>
        <label><input class="dur-minute" type="number" min="0" max="59" value="20"><span>分</span></label>
        <i>:</i>
        <label><input class="dur-second" type="number" min="0" max="59" value="0"><span>秒</span></label>
        <button type="button" class="small-btn dur-add">＋ 添加关注时长</button>
      </div>
      <div class="duration-chips"></div>`;
    wrap.appendChild(editor);
    const chips = editor.querySelector('.duration-chips');

    function parse() {
      return String(hidden.value || '').split(/[,，、;；\s]+/)
        .map(x => x.trim()).filter(Boolean);
    }
    function sync(values) {
      const unique = [...new Set(values)];
      hidden.value = unique.join(',');
      chips.innerHTML = '';
      if (!unique.length) {
        chips.innerHTML = '<span class="duration-empty">没有关注时长，命中时不会特别提醒</span>';
      } else {
        unique.forEach(value => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'duration-chip';
          chip.innerHTML = `<span>${escHtml(value)}</span><b aria-label="删除">×</b>`;
          chip.addEventListener('click', () => {
            sync(parse().filter(x => x !== value));
            hidden.dispatchEvent(new Event('change', { bubbles: true }));
          });
          chips.appendChild(chip);
        });
      }
    }
    editor.querySelector('.dur-add').addEventListener('click', () => {
      const hour = Math.max(0, Math.min(23, Number(editor.querySelector('.dur-hour').value) || 0));
      const minute = Math.max(0, Math.min(59, Number(editor.querySelector('.dur-minute').value) || 0));
      const second = Math.max(0, Math.min(59, Number(editor.querySelector('.dur-second').value) || 0));
      const value = [hour, minute, second].map(n => String(n).padStart(2, '0')).join(':');
      sync([...parse(), value]);
      hidden.dispatchEvent(new Event('change', { bubbles: true }));
    });
    wrap._setDurationValue = value => {
      hidden.value = value || '';
      sync(parse());
    };
    wrap._setDurationValue(initialValue);
  }

  // ── 参数表单渲染 ──
  function renderParamField(scriptName, field) {
    if (frontend.paramForm) {
      return frontend.paramForm.renderField(field, savedParams(scriptName)[field.key]);
    }
    const wrap = document.createElement('div');
    // checks 的外层叫 pf-checks-wrap，别和内层 pills 容器 .pf-checks 撞类名
    wrap.className = 'pf pf-' + (field.type === 'checks' ? 'checks-wrap' : field.type);
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
      const inp = document.createElement(field.swords ? 'textarea' : 'input');
      if (!field.swords) inp.type = 'text';
      inp.dataset.paramKey = field.key;
      inp.value = field.default || '';
      if (field.placeholder) inp.placeholder = field.placeholder;
      wrap.appendChild(inp);
      if (field.swords) renderSwordList(wrap, inp, field.presets || []);
    } else if (field.type === 'duration-list') {
      const inp = document.createElement('input');
      inp.type = 'hidden';
      inp.dataset.paramKey = field.key;
      wrap.appendChild(inp);
      renderDurationList(wrap, inp, field.default || '');
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
    if (field.help) {
      const help = document.createElement('div');
      help.className = 'pf-help';
      help.textContent = field.help;
      wrap.appendChild(help);
    }

    // ── 应用上次记住的选项（有记忆就覆盖默认值）──
    if (saved !== undefined) {
      if (field.type === 'select') {
        const sel = wrap.querySelector('select');
        if ([...sel.options].some(o => o.value === String(saved))) sel.value = String(saved);
      } else if (field.type === 'number') {
        wrap.querySelector('input').value = saved;
      } else if (field.type === 'text') {
        const inp = wrap.querySelector('input, textarea');
        if (inp) inp.value = saved;
      } else if (field.type === 'duration-list') {
        wrap._setDurationValue(saved);
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
    if (frontend.paramForm) {
      frontend.paramForm.updateVisibility(card);
      return;
    }
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
    if (frontend.paramForm) return frontend.paramForm.collect(card);
    const params = {};
    if (!card) return params;
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

  // ── 参数表单：创建一次常驻 paramForms，渲染配置卡片时挂进去 ──
  function ensureParamForms() {
    Object.entries(scriptMeta).forEach(([key, info]) => {
      if (paramForms[key]) return;
      const fields = info.params || [];
      if (!fields.length) return;
      const form = document.createElement('div');
      form.className = 'param-form';
      form.dataset.script = key;
      fields.forEach(f => form.appendChild(renderParamField(key, f)));
      // 条件显隐：控制器变了就重算，先算一遍初始状态
      form.querySelectorAll('select[data-param-key]').forEach(sel =>
        sel.addEventListener('change', () => updateCardVisibility(form)));
      updateCardVisibility(form);
      // 概览选中区的参数摘要跟着表单一起变
      form.addEventListener('change', () => {
        if (key === resolveAlias(selectedScript)) renderFuncDetail();
      });
      form.addEventListener('click', (e) => {
        if ((e.target.closest('.pill') || e.target.closest('[data-act]'))
            && key === resolveAlias(selectedScript)) renderFuncDetail();
      });
      paramForms[key] = form;
    });
  }

  function paramsOf(key) {
    return collectParams(paramForms[resolveAlias(key)]);
  }

  // ── 概览左栏：常用功能列表 ──
  const FUNC_ICONS = {
    daily: '🌅', raid: '⚔️', pumpkin: '🎃', sortie: '🗡', sakura: '🌸',
    practice: '🥊', expedition: '🏕', dispatch: '⛺', forge: '🔥',
    sugar: '🍬', repair: '🛠', snapshot: '📦',
  };

  function scriptOrder() {
    return ['daily', ...Object.keys(scriptMeta).filter(k => k !== 'daily')]
      .filter(k => scriptMeta[k]);
  }

  function renderFuncList() {
    const selReal = resolveAlias(selectedScript);
    els.funcList.innerHTML = '';
    scriptOrder().forEach(k => {
      const info = scriptMeta[k];
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'func-item' + (k === selReal ? ' sel' : '')
                     + ((isRunning && currentScript === k) ? ' running' : '');
      item.innerHTML = `<span class="fi-icon">${FUNC_ICONS[k] || '🧰'}</span>`
        + `<span class="fi-name">${escHtml(info.label)}</span>`;
      item.addEventListener('click', () => {
        selectedScript = k;
        localStorage.setItem('maamaru_selected', k);
        renderFuncList();
        renderFuncDetail();
      });
      els.funcList.appendChild(item);
    });
  }

  function paramIsVisible(field, params) {
    const rule = field && field.visibleWhen;
    if (!rule) return true;
    const current = String(params[rule.key] ?? '');
    if (Object.prototype.hasOwnProperty.call(rule, 'is')) return current === String(rule.is);
    if (Object.prototype.hasOwnProperty.call(rule, 'not')) return current !== String(rule.not);
    return true;
  }

  function paramDisplayValue(field, value) {
    if (Array.isArray(value)) return value.length ? value.join('、') : '都不跑';
    if (field && field.type === 'select' && Array.isArray(field.options)) {
      const option = field.options.find(opt => {
        const raw = Array.isArray(opt) ? opt[0] : opt;
        return String(raw) === String(value);
      });
      if (option) return Array.isArray(option) ? String(option[1]) : String(option);
    }
    if (value === '' || value == null) return '未设置';
    return String(value);
  }

  function paramSummaryItem(field, value) {
    if (field && field.key === 'steps' && Array.isArray(value)) {
      return {
        label: '日课',
        value: value.length ? `${value.length} 项` : '不执行',
        title: value.length ? value.join('、') : '没有勾选任何日课',
      };
    }
    return {
      label: field ? field.label : '',
      value: paramDisplayValue(field, value),
      title: '',
    };
  }

  // ── 概览中间：选中功能区（开始任务 / 强制关闭）──
  function renderFuncDetail() {
    const realKey = resolveAlias(selectedScript);
    const info = scriptMeta[realKey];
    if (!info) {
      els.funcDetail.innerHTML = '<div class="fd-empty">👈 左边点一个功能</div>';
      return;
    }
    const running = isRunning && currentScript === realKey;
    const busy = isRunning && !running;

    if (frontend.taskCard) {
      frontend.taskCard.renderOverview(els.funcDetail, {
        info,
        icon: FUNC_ICONS[realKey] || '🧰',
        running,
        busy,
        params: paramsOf(selectedScript),
        onRun: () => runScript(selectedScript, paramsOf(selectedScript)),
        onStop: stopScript,
        onConfig: () => {
          document.querySelector('[data-tab="control"]').click();
          setTimeout(() => els.configDetail && els.configDetail.scrollTo({ top: 0, behavior: 'smooth' }), 0);
        },
      });
      return;
    }

    // 当前参数摘要（只读，调参去配置页）
    const params = paramsOf(selectedScript);
    const activeParams = Object.entries(params).map(([k, v]) => {
      const field = (info.params || []).find(f => f.key === k);
      return { key: k, value: v, field };
    }).filter(item => paramIsVisible(item.field, params));
    const summaryItems = activeParams.map(item => paramSummaryItem(item.field, item.value));
    const summary = summaryItems.slice(0, 3).map(item =>
      `<span class="fd-summary-chip" title="${escHtml(item.title || `${item.label}：${item.value}`)}">`
        + `<b>${escHtml(item.label)}</b><span>${escHtml(item.value)}</span></span>`
    ).join('');
    const extraCount = Math.max(0, summaryItems.length - 3);
    const detailChips = summaryItems.map(item =>
      `<span class="fd-chip" title="${escHtml(item.title || `${item.label}：${item.value}`)}">`
        + `<b>${escHtml(item.label)}</b> ${escHtml(item.value)}</span>`
    ).join('');
    const paramBlock = summaryItems.length ? `
      <div class="fd-summary">
        <span class="fd-summary-label">这次会跑</span>
        <div class="fd-summary-values">${summary}</div>
        ${extraCount ? `<span class="fd-summary-more">另 ${extraCount} 项</span>` : ''}
      </div>
      <details class="fd-details">
        <summary>查看全部设置</summary>
        <div class="fd-params">${detailChips}</div>
      </details>` : '<div class="fd-summary fd-summary-empty">无需设置，直接运行</div>';

    els.funcDetail.innerHTML = `
      <div class="fd-head">
        <span class="fd-icon">${FUNC_ICONS[realKey] || '🧰'}</span>
        <span class="fd-label">${escHtml(info.label)}</span>
        <span class="s-badge">${running ? '⏳ 运行中' : '待命'}</span>
      </div>
      <div class="fd-desc">${escHtml(info.desc)}</div>
      ${paramBlock}
      <div class="fd-actions">
        ${running
          ? '<button id="fd-stop" class="btn-danger fd-btn">■ 强制关闭</button>'
          : `<button id="fd-run" class="btn-primary fd-btn" ${busy ? 'disabled' : ''}>`
            + `${busy ? '⏳ 有别的任务在跑…' : '▶ 开始任务'}</button>`}
        <button id="fd-config" class="fd-config-btn" type="button">⚙ 调整配置</button>
      </div>`;

    const runBtn = document.getElementById('fd-run');
    if (runBtn) runBtn.addEventListener('click', () => runScript(selectedScript, paramsOf(selectedScript)));
    const stopBtn = document.getElementById('fd-stop');
    if (stopBtn) stopBtn.addEventListener('click', stopScript);
    const configBtn = document.getElementById('fd-config');
    if (configBtn) configBtn.addEventListener('click', () => {
      document.querySelector('[data-tab="control"]').click();
      setTimeout(() => els.configDetail && els.configDetail.scrollTo({ top: 0, behavior: 'smooth' }), 0);
    });
  }

  // ── 配置页：左侧分类导航 ──
  function renderConfigNav() {
    if (!els.configNav) return;
    els.configNav.innerHTML = '';
    CONFIG_GROUPS.forEach(g => {
      const items = g.items.filter(it => it.listKey || scriptMeta[resolveAlias(it.key)]);
      if (!items.length) return;
      const group = document.createElement('div');
      group.className = 'config-group';
      const title = document.createElement('div');
      title.className = 'config-group-title';
      title.textContent = g.label;
      group.appendChild(title);
      const list = document.createElement('div');
      list.className = 'config-items';
      items.forEach(it => {
        const real = resolveAlias(it.key);
        const running = isRunning && currentScript === real;
        const icon = it.listKey ? '📋' : (FUNC_ICONS[real] || '🧰');
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'config-item' + (selectedScript === it.key ? ' sel' : '')
                       + (running ? ' running' : '');
        item.innerHTML = `<span class="ci-icon">${icon}</span>`
          + `<span class="ci-name">${escHtml(it.label)}</span>`;
        item.addEventListener('click', () => {
          selectedScript = it.key;
          localStorage.setItem('maamaru_selected', selectedScript);
          renderConfigNav();
          renderConfigDetail();
          renderFuncList();
          renderFuncDetail();
        });
        list.appendChild(item);
      });
      group.appendChild(list);
      els.configNav.appendChild(group);
    });
  }

  // ── 配置页：右侧选中项配置 ──
  function renderConfigDetail() {
    if (!els.configDetail) return;
    const item = findConfigItem(selectedScript);
    els.configDetail.innerHTML = '';

    // 远征时刻表先收回隐藏坞
    if (els.schedPanel && els.schedPanel.parentElement === els.configDetail) {
      els.schedDock.appendChild(els.schedPanel);
    }

    // ── 全局名单设置（手入黑名单 / 刀解白名单）──
    if (item && item.listKey) {
      if (frontend.listEditor) {
        frontend.listEditor.render(item, els.configDetail);
      } else {
        renderListEditor(item);
      }
      return;
    }

    const key = resolveAlias(selectedScript);
    const info = scriptMeta[key];
    if (!info) {
      els.configDetail.innerHTML = '<div class="fd-empty">👈 左边选一项配置</div>';
      return;
    }
    const running = isRunning && currentScript === key;
    if (frontend.taskCard) {
      const card = frontend.taskCard.createConfig({
        key,
        label: item ? item.label : info.label,
        info,
        icon: FUNC_ICONS[key] || '🧰',
        running,
        busy: isRunning,
        form: paramForms[key],
        showSave: key !== 'expedition',
        onSave: saveBtn => saveSettings(saveBtn),
        onRun: () => runScript(selectedScript, paramsOf(selectedScript)),
      });
      els.configDetail.appendChild(card);
      finishConfigDetail(card, item, key);
      return;
    }
    const card = document.createElement('div');
    card.className = 'config-detail-card' + (running ? ' running' : '');
    card.dataset.script = key;

    const head = document.createElement('div');
    head.className = 'cd-head';
    head.innerHTML = `<div class="cd-title"><span>${FUNC_ICONS[key] || '🧰'}</span> ${escHtml(item ? item.label : info.label)}</div>`
      + `<span class="s-badge">${running ? '⏳ 运行中' : '待命'}</span>`;
    card.appendChild(head);

    const desc = document.createElement('div');
    desc.className = 'cd-desc';
    desc.textContent = info.desc;
    card.appendChild(desc);

    const form = paramForms[key];
    if (form) card.appendChild(form);

    const actions = document.createElement('div');
    actions.className = 'cd-actions';
    if (key !== 'expedition') {
      const saveBtn = document.createElement('button');
      saveBtn.className = 's-save';
      saveBtn.textContent = '💾 保存配置';
      saveBtn.addEventListener('click', () => saveSettings(saveBtn));
      actions.appendChild(saveBtn);
    }
    const runBtn = document.createElement('button');
    runBtn.className = 's-run';
    runBtn.textContent = running ? '⏳ 正在跑…' : '▶ 运行';
    runBtn.disabled = isRunning;
    runBtn.addEventListener('click', () => runScript(selectedScript, paramsOf(selectedScript)));
    actions.appendChild(runBtn);
    card.appendChild(actions);

    els.configDetail.appendChild(card);

    finishConfigDetail(card, item, key);
  }

  function finishConfigDetail(card, item, key) {
    // 别名项：自动滚动并高亮对应字段（如南瓜监视名单）
    if (item && item.scrollTo) {
      const fieldEl = card.querySelector(`[data-param-key="${item.scrollTo}"]`);
      if (fieldEl) {
        const wrap = fieldEl.closest('.pf');
        if (wrap) {
          wrap.classList.add('cd-highlight');
          setTimeout(() => wrap.classList.remove('cd-highlight'), 1400);
          wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }
    }

    // 远征时刻表：选中远征时挂到右侧配置区
    if (key === 'expedition' && els.schedPanel) {
      els.configDetail.appendChild(els.schedPanel);
    }
  }

  // ── 全局名单设置编辑器 ──
  function renderListEditor(item) {
    const card = document.createElement('div');
    card.className = 'config-detail-card';
    card.innerHTML = `<div class="cd-head"><div class="cd-title"><span>📋</span> ${escHtml(item.label)}</div></div>`
      + `<div class="cd-desc">${escHtml(item.desc)}</div>`;

    const editorWrap = document.createElement('div');
    editorWrap.className = 'pf pf-text pf-sword-list';
    const label = document.createElement('label');
    label.className = 'pf-label';
    label.textContent = '名单（点下方候选添加/删除，留空 = 不限制）';
    editorWrap.appendChild(label);

    const ta = document.createElement('textarea');
    ta.className = 'sl-input';
    ta.rows = 4;
    ta.placeholder = '留空 = 不限制';
    editorWrap.appendChild(ta);
    card.appendChild(editorWrap);

    const actions = document.createElement('div');
    actions.className = 'cd-actions';
    const saveBtn = document.createElement('button');
    saveBtn.className = 's-run';
    saveBtn.textContent = '💾 保存名单';
    saveBtn.addEventListener('click', async () => {
      const payload = {};
      payload[item.listKey] = String(ta.value || '')
        .split(/[,，、]/)
        .map(s => s.trim())
        .filter(Boolean);
      try {
        const r = await fetch('/api/config-lists', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const data = await r.json();
        saveBtn.textContent = data.ok ? '✓ 已保存' : '保存失败';
        frontend.feedback?.show(
          data.ok ? `${item.label}已保存` : `${item.label}保存失败`,
          data.ok ? 'success' : 'error');
      } catch(e) {
        saveBtn.textContent = '保存失败';
        frontend.feedback?.show(`${item.label}保存失败`, 'error');
      }
      setTimeout(() => { saveBtn.textContent = '💾 保存名单'; }, 2000);
    });
    actions.appendChild(saveBtn);
    card.appendChild(actions);

    els.configDetail.appendChild(card);

    loadConfigLists().then(lists => {
      const arr = lists[item.listKey] || [];
      ta.value = arr.join('，');
      renderSwordList(editorWrap, ta, [{ label: '恢复默认', value: arr }]);
    });
  }

  // ── 渲染：配置页 + 概览功能列表 + 选中区 ──
  function renderScripts() {
    ensureParamForms();
    renderConfigNav();
    renderConfigDetail();
    renderFuncList();
    renderFuncDetail();
  }

  async function runScript(name, params) {
    if (isRunning) return;
    const realName = resolveAlias(name);
    try {
      // 记住这次选项，下次打开/重启面板自动回填
      localStorage.setItem('maamaru_params_' + realName, JSON.stringify(params || {}));
      const r = await fetch('/api/scripts/run', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({script: realName, params: params || {}}),
      });
      const data = await r.json();
      if (data.ok) {
        isRunning = true;
        currentScript = realName;
        frontend.feedback?.show(`${scriptMeta[realName]?.label || realName}已启动`, 'success');
        updateStatus(true, realName);
        renderScripts();
      } else {
        frontend.feedback?.show(data.reason || '任务启动失败', 'error');
        console.warn('run failed:', data.reason);
      }
    } catch(e) {
      frontend.feedback?.show('任务启动失败，面板后端没有响应', 'error');
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
        if (!data.running) loadDashboard();  // 跑完刷新统计表
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

  // ── 系统设置标签页（双栏布局，跟配置页同骨架）──
  const SYSTEM_GROUPS = [
    { label: '系统配置', items: [
      { key: 'ai',        label: 'AI',        icon: '🤖', desc: '近侍狐之助的脑子：API、模型、角色设定都在这' },
      { key: 'qq',        label: 'QQ',        icon: '💬', desc: 'OneBot 协议端：连接状态、消息 API 与管理页面' },
      { key: 'telegram',  label: 'Telegram',  icon: '✈', desc: 'Telegram Bot：Token + 白名单' },
      { key: 'broadcast', label: '播报',      icon: '📡', desc: '脚本状态变化时通知哪些渠道' },
    ]},
  ];

  let selectedSystem = localStorage.getItem('maamaru_system') || 'ai';
  let systemLoaded = false;       // 是否已经拉过一次配置
  let systemCache = { ai: {}, bot: {} };

  async function loadSystemConfigs() {
    const ai = await frontend.api.json('/api/chat-config');
    const bot = await frontend.api.json('/api/bot-config');
    systemCache = { ai, bot };
    systemLoaded = true;
  }

  async function refreshQQStatus() {
    if (frontend?.system?.qq) {
      return frontend.system.qq.refresh();
    }
    const box = document.getElementById('qq-status-box');
    if (!box) return;
    box.className = 'qq-status-card checking';
    box.innerHTML = '<div class="qq-status-main"><span class="qq-light"></span><b>正在检测协议端…</b></div>';
    try {
      const data = await (await fetch('/api/qq-status')).json();
      const connected = data.state === 'connected';
      box.className = 'qq-status-card ' + (connected ? 'connected' : 'unavailable');
      box.innerHTML = `
        <div class="qq-status-main">
          <span class="qq-light"></span>
          <div><b>${connected ? '协议端已连接' : '未检测到协议端'}</b>
          <small>${connected ? 'OneBot 消息 API 可以访问' : '可能尚未安装、未启动，或端口配置不正确'}</small></div>
          <button id="qq-recheck" type="button" class="small-btn">↻ 重新检测</button>
        </div>
        <div class="qq-check-grid">
          <div class="${data.api_online ? 'ok' : 'bad'}"><span>消息 API</span><b>${data.api_online ? '可用' : '不可用'}</b><small>${escHtml(data.api_detail)}</small></div>
          <div class="${data.gui_online ? 'ok' : 'bad'}"><span>管理页面</span><b>${data.gui_online ? '可打开' : '未响应'}</b><small>${escHtml(data.gui_detail)}</small></div>
          <div class="${data.webhook_ready ? 'ok' : 'bad'}"><span>消息入口</span><b>${data.webhook_ready ? '已准备' : '未挂载'}</b><small>${escHtml(data.webhook_url)}</small></div>
        </div>
        <div class="qq-status-actions">
          <button id="qq-open-gui" type="button" class="small-btn" ${data.gui_url ? '' : 'disabled'}>↗ 打开协议端管理页</button>
          <span>一键下载安装将在正式启动器中提供；当前不会自动下载任何程序。</span>
        </div>`;
      document.getElementById('qq-recheck')?.addEventListener('click', refreshQQStatus);
      document.getElementById('qq-open-gui')?.addEventListener('click', () => {
        const url = document.getElementById('sys-qq-gui')?.value.trim() || data.gui_url;
        if (url) window.open(url, '_blank');
      });
    } catch(e) {
      box.className = 'qq-status-card unavailable';
      box.innerHTML = '<div class="qq-status-main"><span class="qq-light"></span><b>状态检测失败</b></div>';
    }
  }

  async function saveSystemConfigs() {
    const msgEl = document.getElementById('sys-save-msg');
    if (msgEl) msgEl.textContent = '正在保存…';
    let ok = false;
    let detailMsg = '';
    try {
      if (selectedSystem === 'ai') {
        const body = {
          api_key: $('#sys-api-key').value.trim(),
          base_url: $('#sys-api-url').value.trim(),
          model: $('#sys-api-model').value.trim(),
          system_prompt: $('#sys-api-prompt').value,
        };
        ok = (await frontend.api.post('/api/chat-config', body)).ok;
      } else {
        const body = {};
        const cachedBot = systemCache.bot || {};
        if (selectedSystem === 'qq') {
          const enabled = $('#sys-qq-enabled').checked;
          body.enabled = enabled || (cachedBot.platform === 'telegram' && cachedBot.enabled);
          body.platform = enabled ? 'qq' : (cachedBot.platform || 'qq');
          body.qq = {
            enabled,
            provider: $('#sys-qq-provider').value,
            snowluma_http: $('#sys-qq-api').value.trim(),
            snowluma_gui_http: $('#sys-qq-gui').value.trim(),
            admin_qq: $('#sys-qq-admin').value.trim(),
          };
        } else if (selectedSystem === 'telegram') {
          const enabled = $('#sys-tg-enabled').checked;
          body.enabled = enabled || !!cachedBot.qq?.enabled;
          body.platform = enabled ? 'telegram' : (cachedBot.qq?.enabled ? 'qq' : 'telegram');
          body.telegram = {
            token: $('#sys-tg-token').value.trim(),
            allowed_users: $('#sys-tg-users').value.trim(),
          };
        } else if (selectedSystem === 'broadcast') {
          body.broadcast = {
            qq: $('#sys-bc-qq').checked,
            ntfy: $('#sys-bc-ntfy').checked,
          };
        }
        const data = await frontend.api.post('/api/bot-config', body);
        ok = data.ok;
        if (data.tg_reload_msg) detailMsg = data.tg_reload_msg;
        if (selectedSystem === 'qq' && data.qq_restart_required) {
          detailMsg += (detailMsg ? ' ' : '') + 'QQ 需重启まあ丸才生效。';
        }
      }
    } catch(e) {
      detailMsg = '保存请求失败';
    }

    if (ok) {
      if (msgEl) msgEl.textContent = '✓ 保存成功' + (detailMsg ? ' — ' + detailMsg : '');
      frontend.feedback?.show('系统设置已保存', 'success');
    } else {
      if (msgEl) msgEl.textContent = '✗ 保存失败，检查后端连接';
      frontend.feedback?.show('系统设置保存失败', 'error');
    }
    // 清空密钥字段
    if ($('#sys-api-key')) $('#sys-api-key').value = '';
    if ($('#sys-tg-token')) $('#sys-tg-token').value = '';
    if (ok && selectedSystem === 'qq') setTimeout(refreshQQStatus, 200);
    setTimeout(() => { if (msgEl) msgEl.textContent = ''; }, 4000);
  }

  function renderSystemNav() {
    if (!els.systemNav) return;
    els.systemNav.innerHTML = '';
    SYSTEM_GROUPS.forEach(g => {
      const group = document.createElement('div');
      group.className = 'config-group';
      const title = document.createElement('div');
      title.className = 'config-group-title';
      title.textContent = g.label;
      group.appendChild(title);
      const list = document.createElement('div');
      list.className = 'config-items';
      g.items.forEach(it => {
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'config-item' + (selectedSystem === it.key ? ' sel' : '');
        item.innerHTML = `<span class="ci-icon">${it.icon}</span><span class="ci-name">${it.label}</span>`;
        item.addEventListener('click', () => {
          selectedSystem = it.key;
          localStorage.setItem('maamaru_system', selectedSystem);
          renderSystemNav();
          renderSystemDetail();
        });
        list.appendChild(item);
      });
      group.appendChild(list);
      els.systemNav.appendChild(group);
    });
  }

  function renderSystemDetail() {
    if (!els.systemDetail) return;
    const item = SYSTEM_GROUPS.flatMap(g => g.items).find(i => i.key === selectedSystem);
    if (!item) {
      els.systemDetail.innerHTML = '<div class="fd-empty">👈 左边选一项</div>';
      return;
    }
    const ai = systemCache.ai || {};
    const bot = systemCache.bot || {};

    const card = document.createElement('div');
    card.className = 'config-detail-card sys-card';

    const head = document.createElement('div');
    head.className = 'cd-head';
    head.innerHTML = `<div class="cd-title"><span>${item.icon}</span> ${item.label}</div>`;
    card.appendChild(head);

    const desc = document.createElement('div');
    desc.className = 'cd-desc';
    desc.textContent = item.desc;
    card.appendChild(desc);

    const form = document.createElement('div');
    form.className = 'sys-form';

    if (item.key === 'ai') {
      const ph = ai.has_key ? `已配置（${ai.api_key_masked}），留空不改` : 'sk-...';
      fieldInput(form, 'sys-api-key', 'API Key', '', ph, 'password', 'pf-prompt');
      fieldInput(form, 'sys-api-url', 'API 地址', ai.base_url || '', 'https://api.openai.com/v1', 'text');
      fieldInput(form, 'sys-api-model', '模型', ai.model || '', 'gpt-4o-mini', 'text');
      const ta = document.createElement('div');
      ta.className = 'pf pf-prompt';
      ta.innerHTML = `<label>角色设定（System Prompt）</label>
        <textarea id="sys-api-prompt" placeholder="留空 = 默认狐之助">${escHtml(ai.system_prompt || ai.default_prompt || '')}</textarea>`;
      form.appendChild(ta);
      const hint = document.createElement('div');
      hint.className = 'sys-hint';
      hint.textContent = '保存后立刻生效，不用重启。角色设定清空保存即恢复默认狐之助。';
      form.appendChild(hint);
    } else if (item.key === 'qq') {
      const status = document.createElement('div');
      status.id = 'qq-status-box';
      status.className = 'qq-status-card checking';
      form.appendChild(status);
      const provider = document.createElement('div');
      provider.className = 'pf';
      provider.innerHTML = `<label>协议端类型</label><select id="sys-qq-provider">
        <option value="napcat" ${bot.qq.provider === 'napcat' ? 'selected' : ''}>NapCat（推荐）</option>
        <option value="snowluma" ${bot.qq.provider === 'snowluma' ? 'selected' : ''}>SnowLuma（实验性）</option>
        <option value="custom" ${bot.qq.provider === 'custom' ? 'selected' : ''}>其他 OneBot 实现</option>
      </select>`;
      form.appendChild(provider);
      fieldCheck(form, 'sys-qq-enabled', '启用 QQ 协议端', bot.qq.enabled);
      fieldInput(form, 'sys-qq-api', 'OneBot HTTP API（消息发送）', bot.qq.snowluma_http || '', 'http://127.0.0.1:3000', 'text');
      fieldInput(form, 'sys-qq-gui', '协议端管理页（WebUI）', bot.qq.snowluma_gui_http || '', 'http://127.0.0.1:6099', 'text');
      fieldInput(form, 'sys-qq-admin', '管理员 QQ', (bot.qq.admin_qq || []).join(', '), 'QQ号，逗号分隔（留空=不限制）', 'text');
      const hint = document.createElement('div');
      hint.className = 'sys-hint';
      hint.textContent = '启用只代表まあ丸会接收 QQ 消息，并不等于协议端已经安装。请在协议端中把 HTTP 上报地址设为 http://127.0.0.1:8080/onebot/webhook。QQ 配置修改后需重启まあ丸。';
      form.appendChild(hint);
      setTimeout(refreshQQStatus, 0);
    } else if (item.key === 'telegram') {
      fieldCheck(form, 'sys-tg-enabled', '启用 Telegram Bot', bot.platform === 'telegram' && bot.enabled);
      fieldInput(form, 'sys-tg-token', 'Bot Token', '', bot.telegram.has_token ? `已配置（${bot.telegram.token_masked}），留空不改` : 'token', 'password');
      fieldInput(form, 'sys-tg-users', '允许的用户 ID', (bot.telegram.allowed_users || []).join(', '), '用户 ID，逗号分隔（留空=不限制）', 'text');
      const hint = document.createElement('div');
      hint.className = 'sys-hint';
      hint.textContent = 'Token 留空不改变，修改后 Telegram 自动热重启。';
      form.appendChild(hint);
    } else if (item.key === 'broadcast') {
      fieldCheck(form, 'sys-bc-qq', 'QQ 渠道播报（由 QQ 协议端转发）', bot.broadcast.qq);
      fieldCheck(form, 'sys-bc-ntfy', 'ntfy 推送', bot.broadcast.ntfy);
      const hint = document.createElement('div');
      hint.className = 'sys-hint';
      hint.textContent = '脚本运行状态变化时自动通知对应渠道。';
      form.appendChild(hint);
    }

    // 保存按钮行
    const saveRow = document.createElement('div');
    saveRow.className = 'sys-save-row';
    const msg = document.createElement('span');
    msg.id = 'sys-save-msg';
    msg.className = 'sys-save-msg';
    const saveBtn = document.createElement('button');
    saveBtn.className = 's-run';
    saveBtn.textContent = '💾 保存到配置';
    saveBtn.addEventListener('click', saveSystemConfigs);
    saveRow.appendChild(msg);
    saveRow.appendChild(saveBtn);
    form.appendChild(saveRow);

    card.appendChild(form);
    els.systemDetail.innerHTML = '';
    els.systemDetail.appendChild(card);
  }

  // 表单字段工厂
  function fieldInput(form, id, label, value, ph, type = 'text', cls = '') {
    form.appendChild(frontend.components.input({
      id, label, value, placeholder: ph, type, className: cls,
    }));
  }
  function fieldCheck(form, id, label, checked) {
    form.appendChild(frontend.components.checkbox({ id, label, checked }));
  }

  async function renderSystemTab() {
    renderSystemNav();
    if (!systemLoaded) {
      try { await loadSystemConfigs(); } catch(e) { /* ignore */ }
    }
    renderSystemDetail();
  }

  // 系统 tab 激活时拉配置
  document.querySelector('[data-tab="system"]').addEventListener('click', () => {
    setTimeout(renderSystemTab, 0);
  });
  // 第一次启动如果是 system tab（很少见），也要拉
  if (document.querySelector('.tab.active').dataset.tab === 'system') {
    setTimeout(renderSystemTab, 0);
  }

  // ── 远征时刻表 ──
  if (!frontend.expeditionSchedule) {
  const sched = {
    rows: $('#sched-rows'),
    add: $('#sched-add'),
    save: $('#sched-save'),
    msg: $('#sched-msg'),
    common: $('#common-plan'),
    enabled: $('#auto-enabled'),
    mode: $('#auto-mode'),
    start: $('#auto-start'),
    capitalist: $('#auto-capitalist'),
    presetControls: $('#preset-controls'),
    customControls: $('#custom-controls'),
    presetName: $('#preset-name'),
    presetTotal: $('#preset-total'),
    presetPreview: $('#preset-preview'),
    pauseState: $('#pause-state'),
  };
  let schedMaps = [];
  let schedLoaded = [];   // 上次从后端读到的，保存时好把 last_fired 续上
  let schedConfig = null;
  let schedPresets = {};
  const TEAM_OPTS = [["1","部队一"],["2","部队二"],["3","部队三"],["4","部队四"],["5","部队五"]];

  function teamOptions(selected) {
    return TEAM_OPTS.map(([v, t]) =>
      `<option value="${v}" ${String(selected) === v ? 'selected' : ''}>${t}</option>`).join('');
  }

  function mapOptions(selected) {
    return schedMaps.map(m =>
      `<option value="${m.code}" ${selected === m.code ? 'selected' : ''}>`
      + `${m.code} · ${escHtml(m.name)}（${m.duration_text}）</option>`).join('');
  }

  function schedRowHtml(e) {
    return `
      <input type="time" class="sr-time" value="${escHtml(e.time || '06:40')}">
      <select class="sr-team">${teamOptions(e.team_no)}</select>
      <select class="sr-map">${mapOptions(e.map_code)}</select>
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
    frontend?.components?.enhanceSelects(div);
  }

  function renderCommonPlan(rows) {
    sched.common.innerHTML = '';
    const byTeam = new Map((rows || []).map(r => [Number(r.team_no), r]));
    for (let team = 1; team <= 5; team++) {
      const row = byTeam.get(team) || {
        team_no: team, map_code: schedMaps[0]?.code || '', enabled: false,
      };
      const div = document.createElement('div');
      div.className = 'common-row';
      div.dataset.team = String(team);
      div.innerHTML = `
        <label class="sr-on"><input class="cp-enabled" type="checkbox" ${row.enabled ? 'checked' : ''}> 启用</label>
        <b>${TEAM_OPTS[team - 1][1]}</b>
        <select class="cp-map">${mapOptions(row.map_code)}</select>`;
      sched.common.appendChild(div);
    }
  }

  function formatClock(offset) {
    const start = (sched.start.value || '08:00').split(':').map(Number);
    const minutes = ((start[0] * 60 + start[1] + offset) % 1440 + 1440) % 1440;
    return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
  }

  function renderPresetPreview() {
    const data = schedPresets[sched.presetName.value];
    if (!data) return;
    sched.presetTotal.textContent = `攻略预计：${data.totals || '暂无统计'}`;
    const teams = [...document.querySelectorAll('.preset-team')].map(x => x.value);
    sched.presetPreview.innerHTML = (data.lanes || []).map((lane, idx) => {
      const bits = lane.map(p => `<span title="${formatClock(p.offset_min)} 开始，${p.duration_min} 分钟">`
        + `<b>${formatClock(p.offset_min)}</b> ${escHtml(p.map_code)}</span>`).join('');
      return `<div class="preset-lane"><strong>${TEAM_OPTS[Number(teams[idx] || idx + 2) - 1][1]}</strong>`
        + `<div>${bits}</div></div>`;
    }).join('');
  }

  function syncScheduleMode() {
    const preset = sched.mode.value === 'preset';
    sched.presetControls.hidden = !preset;
    sched.customControls.hidden = preset;
    sched.start.closest('label').style.display = preset ? '' : 'none';
  }

  async function loadSchedule() {
    try {
      const r = await fetch('/api/expedition-schedule');
      const data = await r.json();
      schedConfig = data;
      schedMaps = data.maps || [];
      schedPresets = data.presets || {};
      schedLoaded = data.entries || [];
      sched.rows.innerHTML = '';
      schedLoaded.forEach(addSchedRow);
      renderCommonPlan(data.common_plan || []);
      const auto = data.automation || {};
      sched.enabled.checked = !!auto.enabled;
      sched.mode.value = auto.mode || 'preset';
      sched.start.value = auto.start_time || '08:00';
      sched.capitalist.checked = !!auto.capitalist;
      sched.presetName.innerHTML = Object.keys(schedPresets).map(name =>
        `<option value="${escHtml(name)}" ${name === auto.preset ? 'selected' : ''}>${escHtml(name)}</option>`
      ).join('');
      document.querySelectorAll('.preset-team').forEach((sel, idx) => {
        sel.innerHTML = teamOptions((auto.teams || [2, 3, 4])[idx]);
      });
      sched.pauseState.textContent = auto.paused_until
        ? `暂停至 ${auto.paused_until}` : '';
      syncScheduleMode();
      renderPresetPreview();
      frontend?.components?.enhanceSelects(sched.panel || document.getElementById('sched-panel'));
    } catch(e) {
      sched.msg.textContent = '时刻表读取失败';
    }
  }

  sched.add.addEventListener('click', () => addSchedRow());
  sched.mode.addEventListener('change', syncScheduleMode);
  sched.start.addEventListener('change', renderPresetPreview);
  sched.presetName.addEventListener('change', renderPresetPreview);
  document.querySelectorAll('.preset-team').forEach(sel =>
    sel.addEventListener('change', renderPresetPreview));

  document.querySelectorAll('.pause-exp').forEach(btn => {
    btn.addEventListener('click', async () => {
      const r = await fetch('/api/expedition-pause', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({minutes: Number(btn.dataset.minutes || 0)}),
      });
      const data = await r.json();
      sched.pauseState.textContent = data.paused_until
        ? `暂停至 ${data.paused_until}` : '已恢复';
      if (schedConfig && schedConfig.automation) {
        schedConfig.automation.paused_until = data.paused_until || '';
      }
    });
  });

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
    const commonPlan = [...sched.common.querySelectorAll('.common-row')].map(row => ({
      team_no: Number(row.dataset.team),
      map_code: row.querySelector('.cp-map').value,
      enabled: row.querySelector('.cp-enabled').checked,
    }));
    const presetTeams = [...document.querySelectorAll('.preset-team')].map(x => Number(x.value));
    if (new Set(presetTeams).size !== presetTeams.length) {
      sched.msg.textContent = '三条预设线路不能选择重复部队';
      return;
    }
    const automation = {
      enabled: sched.enabled.checked,
      mode: sched.mode.value,
      preset: sched.presetName.value,
      start_time: sched.start.value || '08:00',
      teams: presetTeams,
      capitalist: sched.capitalist.checked,
      paused_until: schedConfig?.automation?.paused_until || '',
    };
    try {
      const r = await fetch('/api/expedition-schedule', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({entries, common_plan: commonPlan, automation}),
      });
      const data = await r.json();
      sched.msg.textContent = data.ok ? `✓ 存好了（${data.count} 条）` : '保存失败';
      frontend.feedback?.show(
        data.ok ? '远征设置已保存' : '远征设置保存失败',
        data.ok ? 'success' : 'error');
    } catch(e) {
      sched.msg.textContent = '保存失败（面板没连上？）';
      frontend.feedback?.show('远征设置保存失败，面板后端没有响应', 'error');
    }
    setTimeout(() => { sched.msg.textContent = ''; }, 3000);
  });

  // ── Utility ──
  }

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

  async function saveSettings(sourceButton = null) {
    // 从常驻参数表单收集当前参数
    const allParams = {};
    Object.values(paramForms).forEach(form => {
      const name = form.dataset.script;
      if (!name) return;
      allParams[name] = collectParams(form);
    });
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
        frontend.feedback?.show('配置已保存', 'success');
        if (sourceButton) {
          const oldText = sourceButton.textContent;
          sourceButton.textContent = '✓ 已保存';
          setTimeout(() => { sourceButton.textContent = oldText; }, 2000);
        }
      }
    } catch(e) {
      frontend.feedback?.show('保存失败，面板后端没有响应', 'error');
    }
  }

  // ── Init ──
  async function init() {
    // 先从服务器加载保存的设置（会在 render 之前写入 localStorage）
    await loadSavedSettings();
    await loadLogs();
    await loadScripts();
    await loadChatHistory();
    frontend.expeditionSchedule?.load();
    loadDashboard();
    connectSSE();
    setInterval(pollStatus, 3000);
    document.querySelector('[data-tab="chat"]').addEventListener('click', () => {
      setTimeout(() => els.chatInput.focus(), 100);
    });
  }

  init();
})();
