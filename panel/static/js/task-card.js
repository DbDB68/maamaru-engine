/** 任务卡片：概览摘要与配置页卡片的统一展示。 */
(function registerTaskCard(global) {
  'use strict';
  const app = global.Maamaru;
  const esc = app.dom.escape;

  function isVisible(field, params) {
    const rule = field?.visibleWhen;
    if (!rule) return true;
    const current = String(params[rule.key] ?? '');
    if (Object.prototype.hasOwnProperty.call(rule, 'is')) return current === String(rule.is);
    if (Object.prototype.hasOwnProperty.call(rule, 'not')) return current !== String(rule.not);
    return true;
  }

  function displayValue(field, value) {
    if (Array.isArray(value)) return value.length ? value.join('、') : '都不跑';
    if (field?.type === 'select' && Array.isArray(field.options)) {
      const option = field.options.find(item =>
        String(Array.isArray(item) ? item[0] : item) === String(value));
      if (option) return String(Array.isArray(option) ? option[1] : option);
    }
    return value === '' || value == null ? '未设置' : String(value);
  }

  function summaryItems(info, params) {
    return Object.entries(params).map(([key, value]) => {
      const field = (info.params || []).find(item => item.key === key);
      if (!isVisible(field, params)) return null;
      if (field?.key === 'steps' && Array.isArray(value)) {
        return {
          label: '日课',
          value: value.length ? `${value.length} 项` : '不执行',
          title: value.length ? value.join('、') : '没有勾选任何日课',
        };
      }
      return { label: field?.label || '', value: displayValue(field, value), title: '' };
    }).filter(Boolean);
  }

  function dailyPlanParts(params) {
    const steps = Array.isArray(params.steps) ? params.steps : [];
    const parts = [steps.length ? `${steps.length} 项日课` : '未选择日课'];
    if (!steps.includes('出阵')) return parts;

    const team = { 1: '部队一', 2: '部队二', 3: '部队三', 4: '部队四', 5: '部队五' }[String(params.team_no)];
    if (params.sortie_mode === 'raid') {
      parts.push(`联队战 ${params.raid_rounds || 1} 圈`);
    } else if (params.sortie_mode === 'sortie') {
      parts.push(`${params.chapter || 1}-${params.map_no || 1} × ${params.loops || 1} 圈`);
    } else if (params.sortie_mode === 'pumpkin') {
      parts.push('南瓜每日四次');
    } else {
      parts.push('不出阵');
    }
    if (params.sortie_mode !== 'none' && team) parts.push(team);
    return parts;
  }

  function compactPlanValue(item) {
    const value = String(item.value);
    if (!/^\d+(?:[章图])?$/.test(value) || !item.label) return value;
    if (item.label === '圈数') return `${value} 圈`;
    if (item.label.startsWith('手形最多买几次')) return `最多买手形 ${value} 次`;
    return `${item.label.replace(/（.*）/, '')} ${value}`;
  }

  function renderOverview(target, options) {
    const { key, info, icon = '🧰', running, busy, params, onRun, onStop, onConfig } = options;
    const items = summaryItems(info, params);
    const details = items.map(item =>
      `<span class="fd-chip" title="${esc(item.title || `${item.label}：${item.value}`)}">`
      + `<b>${esc(item.label)}</b> ${esc(item.value)}</span>`).join('');
    const extra = Math.max(0, items.length - 3);
    const planParts = key === 'daily'
      ? dailyPlanParts(params)
      : items.slice(0, 3).map(compactPlanValue).concat(extra ? [`另 ${extra} 项`] : []);
    const paramsBlock = `
      <div class="fd-plan-line" aria-label="本次任务安排">
        ${(planParts.length ? planParts : ['无需设置，直接运行'])
          .map((part, index) => `${index ? '<i>·</i>' : ''}<span>${esc(part)}</span>`).join('')}
      </div>
      ${items.length ? `<details class="fd-details">
        <summary>查看全部设置</summary>
        <div class="fd-params">${details}</div>
      </details>` : ''}`;

    target.innerHTML = `
      <div class="fd-head">
        <span class="fd-icon">${icon}</span>
        <span class="fd-label">${esc(info.label)}</span>
        <span class="s-badge">${running ? '⏳ 运行中' : '待命'}</span>
      </div>
      <div class="fd-desc">${esc(info.desc)}</div>
      ${paramsBlock}
      <div class="fd-actions">
        ${running
          ? '<button data-task-action="stop" class="btn-danger fd-btn with-ui-icon ui-stop">强制关闭</button>'
          : `<button data-task-action="run" class="btn-primary fd-btn with-ui-icon ui-play" ${busy ? 'disabled' : ''}>`
            + `${busy ? '有别的任务在跑…' : '开始任务'}</button>`}
        <button data-task-action="config" class="fd-config-btn with-ui-icon ui-gear" type="button">调整配置</button>
      </div>`;

    target.querySelector('[data-task-action="run"]')?.addEventListener('click', onRun);
    target.querySelector('[data-task-action="stop"]')?.addEventListener('click', onStop);
    target.querySelector('[data-task-action="config"]')?.addEventListener('click', onConfig);
  }

  function createConfig(options) {
    const { key, label, info, icon = '🧰', running, busy, form, showSave = true, onSave, onRun } = options;
    const card = document.createElement('div');
    card.className = `config-detail-card${running ? ' running' : ''}`;
    card.dataset.script = key;
    card.innerHTML = `
      <div class="cd-head">
        <div class="cd-title"><span>${icon}</span> ${esc(label)}</div>
        <span class="s-badge">${running ? '⏳ 运行中' : '待命'}</span>
      </div>
      <div class="cd-desc">${esc(info.desc)}</div>`;
    if (form) card.appendChild(form);

    const actions = document.createElement('div');
    actions.className = 'cd-actions';
    if (showSave) {
      const save = document.createElement('button');
      save.className = 's-save with-ui-icon ui-check';
      save.textContent = '保存配置';
      save.addEventListener('click', () => onSave(save));
      actions.appendChild(save);
    }
    const run = document.createElement('button');
    run.className = 's-run with-ui-icon ui-play';
    run.textContent = running ? '正在跑…' : '运行';
    run.disabled = busy;
    run.addEventListener('click', onRun);
    actions.appendChild(run);
    card.appendChild(actions);
    return card;
  }

  app.taskCard = Object.freeze({ renderOverview, createConfig, summaryItems });
})(window);
