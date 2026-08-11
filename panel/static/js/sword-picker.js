/** 刀剑名单选择器：负责候选加载、刀种分组、搜索、预设与选中同步。 */
(function registerSwordPicker(global) {
  'use strict';
  const app = global.Maamaru;
  const esc = app.dom.escape;
  let candidatesPromise = null;

  function loadCandidates() {
    if (candidatesPromise) return candidatesPromise;
    candidatesPromise = app.api.json('/api/swords')
      .then(data => (data.swords || []).filter(sword => sword.name_zh || sword.name))
      .catch(() => []);
    return candidatesPromise;
  }

  function render(wrap, textarea, presets) {
    wrap.classList.add('pf-sword-list');
    textarea.classList.add('sl-input');
    textarea.rows = 3;

    const editor = document.createElement('div');
    editor.className = 'sl-editor';

    if (presets?.length) {
      const presetsBox = document.createElement('div');
      presetsBox.className = 'sl-presets';
      presets.forEach(preset => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'small-btn sl-preset';
        button.textContent = preset.label;
        button.addEventListener('click', () => {
          textarea.value = (preset.value || []).map(String).join('，');
          syncChips();
          textarea.dispatchEvent(new Event('change', { bubbles: true }));
        });
        presetsBox.appendChild(button);
      });
      editor.appendChild(presetsBox);
    }

    const candidatesPanel = document.createElement('details');
    candidatesPanel.className = 'sl-candidates';
    const summary = document.createElement('summary');
    summary.textContent = '展开候选刀剑';
    candidatesPanel.appendChild(summary);

    const search = document.createElement('input');
    search.type = 'text';
    search.className = 'sl-search';
    search.placeholder = '搜索刀剑…';
    candidatesPanel.appendChild(search);

    const pool = document.createElement('div');
    pool.className = 'sl-pool';
    pool.innerHTML = '<div class="sl-loading">加载刀剑名册中…</div>';
    candidatesPanel.appendChild(pool);
    editor.appendChild(candidatesPanel);
    wrap.appendChild(editor);

    function parseNames() {
      return String(textarea.value || '').split(/[,，、]/).map(name => name.trim()).filter(Boolean);
    }

    function syncChips() {
      const selected = new Set(parseNames());
      summary.textContent = selected.size
        ? `展开候选刀剑 · 已选 ${selected.size} 把`
        : '展开候选刀剑 · 当前不认刀';
      pool.querySelectorAll('.sl-chip').forEach(chip => {
        chip.classList.toggle('on', selected.has(chip.dataset.name));
      });
    }

    function toggleName(name) {
      const names = parseNames();
      const index = names.indexOf(name);
      if (index >= 0) names.splice(index, 1);
      else names.push(name);
      textarea.value = names.join('，');
      syncChips();
      textarea.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function filterChips() {
      const query = search.value.trim().toLowerCase();
      pool.querySelectorAll('.sl-chip').forEach(chip => {
        const text = (chip.textContent || '').toLowerCase();
        const name = (chip.dataset.name || '').toLowerCase();
        chip.style.display = (!query || text.includes(query) || name.includes(query)) ? '' : 'none';
      });
      pool.querySelectorAll('.sl-type-group').forEach(group => {
        const visible = [...group.querySelectorAll('.sl-chip')].some(chip => chip.style.display !== 'none');
        group.style.display = visible ? '' : 'none';
      });
    }

    textarea.addEventListener('input', syncChips);
    search.addEventListener('input', filterChips);
    syncChips();

    loadCandidates().then(candidates => {
      pool.replaceChildren();
      const typeOrder = ['短刀', '脇差', '打刀', '太刀', '大太刀', '槍', '薙刀', '剣', '其他'];
      const grouped = new Map();
      candidates.forEach(sword => {
        const type = sword.type || '其他';
        if (!grouped.has(type)) grouped.set(type, []);
        grouped.get(type).push(sword);
      });

      [...grouped.keys()].sort((left, right) => {
        const leftIndex = typeOrder.indexOf(left);
        const rightIndex = typeOrder.indexOf(right);
        return (leftIndex < 0 ? 999 : leftIndex) - (rightIndex < 0 ? 999 : rightIndex)
          || left.localeCompare(right, 'zh-CN');
      }).forEach(type => {
        const group = document.createElement('section');
        group.className = 'sl-type-group';
        group.innerHTML = `<div class="sl-type-head"><span>${esc(type)}</span><small>${grouped.get(type).length}</small></div>`;
        const chips = document.createElement('div');
        chips.className = 'sl-type-chips';
        grouped.get(type).sort((left, right) =>
          (left.name_zh || left.name).localeCompare(right.name_zh || right.name, 'zh-CN')
        ).forEach(sword => {
          const name = sword.name_zh || sword.name;
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'sl-chip';
          chip.dataset.name = name;
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

  app.swordPicker = Object.freeze({ render, loadCandidates });
})(window);
