/** 远征排班：预设、自定义时刻表、常用派遣与暂停。 */
(function registerExpeditionSchedule(global) {
  'use strict';
  const app = global.Maamaru;
  const $ = app.dom.one;
  const esc = app.dom.escape;
  const teams = [['1','部队一'],['2','部队二'],['3','部队三'],['4','部队四'],['5','部队五']];
  let maps = [], presets = {}, loaded = [], config = null, bound = false;

  const ui = () => ({
    panel: $('#sched-panel'), rows: $('#sched-rows'), add: $('#sched-add'), save: $('#sched-save'),
    msg: $('#sched-msg'), common: $('#common-plan'), enabled: $('#auto-enabled'), mode: $('#auto-mode'),
    start: $('#auto-start'), capitalist: $('#auto-capitalist'), preset: $('#preset-name'),
    total: $('#preset-total'), preview: $('#preset-preview'), presetBox: $('#preset-controls'),
    customBox: $('#custom-controls'), pause: $('#pause-state'),
  });
  const teamOptions = selected => teams.map(([v,t]) =>
    `<option value="${v}" ${String(selected) === v ? 'selected' : ''}>${t}</option>`).join('');
  const mapOptions = selected => maps.map(m =>
    `<option value="${esc(m.code)}" ${selected === m.code ? 'selected' : ''}>${esc(m.code)} · ${esc(m.name)}（${esc(m.duration_text)}）</option>`).join('');

  function addRow(entry = {}) {
    const u = ui();
    const row = document.createElement('div');
    row.className = 'sched-row';
    row.innerHTML = `<input type="time" class="sr-time" value="${esc(entry.time || '06:40')}">
      <select class="sr-team">${teamOptions(entry.team_no || 5)}</select>
      <select class="sr-map">${mapOptions(entry.map_code || maps[0]?.code || '')}</select>
      <label class="sr-on"><input type="checkbox" ${entry.enabled !== false ? 'checked' : ''}> 启用</label>
      <button class="sr-del" title="删除这行">🗑</button>`;
    row.querySelector('.sr-del').addEventListener('click', () => row.remove());
    u.rows.appendChild(row);
    app.components.enhanceSelects(row);
  }

  function renderCommon(rows) {
    const u = ui();
    u.common.innerHTML = '';
    const byTeam = new Map((rows || []).map(row => [Number(row.team_no), row]));
    teams.forEach(([value, label]) => {
      const data = byTeam.get(Number(value)) || { team_no: value, map_code: maps[0]?.code || '', enabled: false };
      const row = document.createElement('div');
      row.className = 'common-row'; row.dataset.team = value;
      row.innerHTML = `<label class="sr-on"><input class="cp-enabled" type="checkbox" ${data.enabled ? 'checked' : ''}> 启用</label>
        <b>${label}</b><select class="cp-map">${mapOptions(data.map_code)}</select>`;
      u.common.appendChild(row);
    });
  }

  function clock(offset) {
    const [h,m] = (ui().start.value || '08:00').split(':').map(Number);
    const total = ((h * 60 + m + offset) % 1440 + 1440) % 1440;
    return `${String(Math.floor(total / 60)).padStart(2,'0')}:${String(total % 60).padStart(2,'0')}`;
  }
  function preview() {
    const u = ui(), data = presets[u.preset.value];
    if (!data) return;
    u.total.textContent = `攻略预计：${data.totals || '暂无统计'}`;
    const selected = [...document.querySelectorAll('.preset-team')].map(x => x.value);
    u.preview.innerHTML = (data.lanes || []).map((lane, index) =>
      `<div class="preset-lane"><strong>${teams[Number(selected[index] || index + 2) - 1][1]}</strong><div>${lane.map(p =>
        `<span title="${clock(p.offset_min)} 开始，${p.duration_min} 分钟"><b>${clock(p.offset_min)}</b> ${esc(p.map_code)}</span>`).join('')}</div></div>`).join('');
  }
  function syncMode() {
    const u = ui(), isPreset = u.mode.value === 'preset';
    u.presetBox.hidden = !isPreset; u.customBox.hidden = isPreset;
    u.start.closest('label').style.display = isPreset ? '' : 'none';
  }

  async function save() {
    const u = ui();
    const entries = [...u.rows.querySelectorAll('.sched-row')].map(row => {
      const time = row.querySelector('.sr-time').value;
      const team = Number(row.querySelector('.sr-team').value);
      const code = row.querySelector('.sr-map').value;
      const previous = loaded.find(x => x.time === time && x.team_no === team && x.map_code === code);
      return { time, team_no: team, map_code: code, map_name: maps.find(x => x.code === code)?.name || '',
        enabled: row.querySelector('.sr-on input').checked, last_fired: previous?.last_fired || '' };
    });
    const common_plan = [...u.common.querySelectorAll('.common-row')].map(row => ({
      team_no: Number(row.dataset.team), map_code: row.querySelector('.cp-map').value,
      enabled: row.querySelector('.cp-enabled').checked,
    }));
    const selectedTeams = [...document.querySelectorAll('.preset-team')].map(x => Number(x.value));
    if (new Set(selectedTeams).size !== selectedTeams.length) {
      u.msg.textContent = '三条路线不能选择重复部队'; return;
    }
    try {
      const data = await app.api.post('/api/expedition-schedule', { entries, common_plan,
        automation: { enabled: u.enabled.checked, mode: u.mode.value, preset: u.preset.value,
          start_time: u.start.value || '08:00', teams: selectedTeams, capitalist: u.capitalist.checked,
          paused_until: config?.automation?.paused_until || '' } });
      u.msg.textContent = data.ok ? `✓ 存好了（${data.count} 条）` : '保存失败';
      app.feedback?.show(data.ok ? '远征设置已保存' : '远征设置保存失败', data.ok ? 'success' : 'error');
      if (data.ok) loaded = entries;
    } catch (_) { u.msg.textContent = '保存失败'; app.feedback?.show('远征设置保存失败', 'error'); }
    setTimeout(() => { u.msg.textContent = ''; }, 3000);
  }

  function bind() {
    if (bound) return; bound = true;
    const u = ui();
    u.add.addEventListener('click', () => addRow()); u.save.addEventListener('click', save);
    u.mode.addEventListener('change', syncMode); u.start.addEventListener('change', preview);
    u.preset.addEventListener('change', preview);
    document.querySelectorAll('.preset-team').forEach(x => x.addEventListener('change', preview));
    document.querySelectorAll('.pause-exp').forEach(button => button.addEventListener('click', async () => {
      const data = await app.api.post('/api/expedition-pause', { minutes: Number(button.dataset.minutes || 0) });
      u.pause.textContent = data.paused_until ? `暂停至 ${data.paused_until}` : '已恢复';
      if (config?.automation) config.automation.paused_until = data.paused_until || '';
    }));
  }

  async function load() {
    bind(); const u = ui();
    try {
      config = await app.api.json('/api/expedition-schedule'); maps = config.maps || [];
      presets = config.presets || {}; loaded = config.entries || []; u.rows.innerHTML = '';
      loaded.forEach(addRow); renderCommon(config.common_plan || []);
      const auto = config.automation || {}; u.enabled.checked = !!auto.enabled;
      u.mode.value = auto.mode || 'preset'; u.start.value = auto.start_time || '08:00';
      u.capitalist.checked = !!auto.capitalist;
      u.preset.innerHTML = Object.keys(presets).map(name => `<option value="${esc(name)}" ${name === auto.preset ? 'selected' : ''}>${esc(name)}</option>`).join('');
      document.querySelectorAll('.preset-team').forEach((select, index) => select.innerHTML = teamOptions((auto.teams || [2,3,4])[index]));
      u.pause.textContent = auto.paused_until ? `暂停至 ${auto.paused_until}` : '';
      syncMode(); preview(); app.components.enhanceSelects(u.panel);
    } catch (_) { u.msg.textContent = '时刻表读取失败'; }
  }
  app.expeditionSchedule = Object.freeze({ load, addRow, save });
})(window);
