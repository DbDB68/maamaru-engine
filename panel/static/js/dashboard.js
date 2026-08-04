/** 概览统计：运行横幅、库存、远征倒计时、日课与内番状态。 */
(function registerDashboard(global) {
  'use strict';

  const app = global.Maamaru;
  const $ = app.dom.one;
  const esc = app.dom.escape;
  let expeditionState = [];
  let expeditionTimer = null;
  let runningSince = null;
  let runningLabel = '';
  let isRunning = () => false;
  let bound = false;

  const ui = () => ({
    updated: $('#dash-updated'), refresh: $('#btn-dash-refresh'), snapshotAt: $('#dash-snapshot-at'),
    resources: $('#dash-resources'), resourceSub: $('#dash-res-sub'), furnaces: $('#dash-furnaces'),
    expeditions: $('#dash-expeditions'), schedule: $('#dash-schedule'), daily: $('#dash-daily'),
    naihanka: $('#dash-naihanka'), running: $('#dash-running'), flavor: $('#run-flavor'), sub: $('#run-sub'),
  });

  function duration(seconds) {
    const value = Math.max(0, Math.floor(seconds));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    const secs = value % 60;
    if (hours > 0) return `${hours}小时${String(minutes).padStart(2, '0')}分`;
    if (minutes > 0) return `${minutes}分${String(secs).padStart(2, '0')}秒`;
    return `${secs}秒`;
  }

  function updateRunningSub(label) {
    if (label) runningLabel = label;
    if (!runningSince) return;
    const elapsed = duration(Math.max(0, Date.now() / 1000 - runningSince));
    ui().sub.textContent = (runningLabel ? `${runningLabel} · ` : '') + `已跑 ${elapsed}`;
  }

  function render(data) {
    const u = ui();
    const run = data.running || {};
    if (run.active) {
      u.running.style.display = '';
      u.flavor.textContent = run.flavor || '正在本丸干活🔧';
      runningSince = run.started || null;
      updateRunningSub(run.label);
    } else {
      u.running.style.display = 'none';
      runningSince = null;
    }

    const inventory = data.inventory;
    if (inventory?.resources) {
      const resources = inventory.resources;
      const tiles = [['小判', resources['小判'], '🪙'], ['甲州金', resources['甲州金'], '💎'],
        ['委托符', resources['委托符'], '📜'], ['加速符', resources['加速符'], '⏩']];
      u.resources.innerHTML = tiles.map(([name, value, icon]) =>
        `<div class="res-tile"><span class="res-icon">${icon}</span>`
        + `<span class="res-num">${value == null ? '?' : Number(value).toLocaleString()}</span>`
        + `<span class="res-name">${name}</span></div>`).join('');
      u.resourceSub.innerHTML = ['木炭', '玉钢', '冷却材', '砥石']
        .map(name => `<span class="res-sub-item">${name} ${resources[name] == null ? '?' : Number(resources[name]).toLocaleString()}</span>`)
        .join('') + (inventory.doko ? `<span class="res-sub-item">🗡 刀位 ${esc(inventory.doko)}</span>` : '');
      u.snapshotAt.textContent = inventory.captured_at ? `快照 ${inventory.captured_at.slice(5, 16)}` : '';
      u.furnaces.innerHTML = (inventory.furnaces || []).map(furnace => {
        const busy = furnace.state === '锻造中';
        const tail = busy && furnace.remain ? ` 剩 ${esc(furnace.remain)}` : (busy ? ' 快好了' : '');
        return `<span class="fn-chip ${busy ? 'fn-busy' : 'fn-idle'}">炉${furnace.slot} ${esc(furnace.state)}${tail}</span>`;
      }).join('');
    } else {
      u.resources.innerHTML = '<div class="dash-empty">还没有库存快照<br><small>跑一次日课或库存快照就有了</small></div>';
      u.resourceSub.innerHTML = '';
      u.furnaces.innerHTML = '';
    }

    if (expeditionTimer) clearInterval(expeditionTimer);
    expeditionTimer = null;
    expeditionState = [];
    const expeditions = data.expeditions || [];
    if (expeditions.length) {
      u.expeditions.replaceChildren();
      expeditions.forEach(expedition => {
        const row = document.createElement('div');
        row.className = `exp-row${expedition.done ? ' exp-done' : ''}`;
        row.innerHTML = `<span class="exp-team">部队${esc(expedition.team_no)}</span>`
          + `<span class="exp-map">${esc(expedition.map_code || '')} ${esc(expedition.map_name || '')}</span>`
          + '<span class="exp-count"></span>';
        u.expeditions.appendChild(row);
        const counter = row.querySelector('.exp-count');
        if (expedition.remain_sec == null) counter.textContent = '时间不明';
        else expeditionState.push({ element: counter, remain: expedition.remain_sec });
      });
      const tick = () => expeditionState.forEach(state => {
        state.remain = Math.max(0, state.remain - 1);
        state.element.textContent = state.remain <= 0 ? '🎉 该回来了' : `剩 ${duration(state.remain)}`;
        if (state.remain <= 0) state.element.closest('.exp-row').classList.add('exp-done');
      });
      tick();
      expeditionTimer = setInterval(tick, 1000);
    } else {
      u.expeditions.innerHTML = '<div class="dash-empty">没有部队在外面跑</div>';
    }

    const schedule = data.schedule || [];
    u.schedule.innerHTML = schedule.length
      ? '<div class="sched-line">📅 今天待派：' + schedule.map(item =>
        `${esc(item.time)} 部队${item.team_no}→${esc(item.map_code)}`).join(' · ') + '</div>' : '';

    const report = data.latest_report;
    if (report?.steps?.length) {
      const failures = report.steps.filter(step => !String(step.status).startsWith('✓'));
      const header = `<div class="daily-banner ${report.all_green ? 'daily-ok' : 'daily-bad'}">`
        + (report.all_green ? '🌸 全绿收工' : `🍂 ${failures.length} 项翻车`)
        + `<small>${esc(report.finished_at || '')}</small></div>`;
      const steps = report.steps.map(step => {
        const ok = String(step.status).startsWith('✓');
        const skipped = String(step.status).includes('⏭') || String(step.status).includes('跳');
        return `<span class="step-chip ${ok ? 'step-ok' : (skipped ? 'step-skip' : 'step-bad')}">${esc(step.name)}</span>`;
      }).join('');
      u.daily.innerHTML = header + `<div class="step-list">${steps}</div>`;
    } else {
      u.daily.innerHTML = '<div class="dash-empty">今天还没跑过日课</div>';
    }

    const naihanka = data.naihanka;
    u.naihanka.innerHTML = naihanka?.started_at
      ? `<div class="nh-line">🌱 内番中<small>${esc(naihanka.started_at)} 开始</small></div>`
      : '<div class="dash-empty">内番闲着呢</div>';
  }

  async function load() {
    const u = ui();
    try {
      const data = await app.api.json('/api/dashboard');
      render(data);
      u.updated.textContent = `更新于 ${(data.server_time || '').slice(11, 19)}`;
    } catch (_) {
      u.updated.textContent = '读取失败';
    }
  }

  function showSchedulerWarning(message) {
    const u = ui();
    u.running.style.display = '';
    u.flavor.textContent = '⏳ 远征即将接管游戏';
    u.sub.innerHTML = `${esc(message)} <button id="cancel-scheduled-exp" class="small-btn">先别动游戏</button>`;
    $('#cancel-scheduled-exp')?.addEventListener('click', async () => {
      await app.api.post('/api/expedition-pause', { minutes: 30 });
      u.flavor.textContent = '已暂停自动远征 30 分钟';
      u.sub.textContent = '这次不会接管游戏';
      setTimeout(() => { if (!isRunning()) u.running.style.display = 'none'; }, 3000);
    });
  }

  function bind() {
    if (bound) return;
    bound = true;
    ui().refresh.addEventListener('click', load);
    $('[data-tab="home"]').addEventListener('click', load);
    setInterval(() => updateRunningSub(''), 1000);
    setInterval(() => {
      if ($('.tab.active')?.dataset.tab === 'home') load();
    }, 30000);
    setInterval(() => {
      if (runningSince && $('.tab.active')?.dataset.tab === 'home') load();
    }, 5000);
  }

  function init(options = {}) {
    if (typeof options.isRunning === 'function') isRunning = options.isRunning;
    bind();
    load();
  }

  app.dashboard = Object.freeze({ init, load, render, showSchedulerWarning, duration });
})(window);
