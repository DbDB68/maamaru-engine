/** 名单配置页：读取、编辑与保存；刀剑候选由共用选择器渲染。 */
(function registerListEditor(global) {
  'use strict';
  const app = global.Maamaru;
  const esc = app.dom.escape;

  async function render(item, target) {
    const card = document.createElement('div');
    card.className = 'config-detail-card';
    card.innerHTML = `<div class="cd-head"><div class="cd-title with-ui-icon ui-menu-list">${esc(item.label)}</div></div>
      <div class="cd-desc">${esc(item.desc)}</div>`;

    const editor = document.createElement('div');
    editor.className = 'pf pf-text pf-sword-list';
    editor.innerHTML = '<label class="pf-label">名单（点下方候选添加/删除，留空 = 不限制）</label>';
    const textarea = document.createElement('textarea');
    textarea.className = 'sl-input'; textarea.rows = 4;
    textarea.placeholder = '留空 = 不限制'; editor.appendChild(textarea); card.appendChild(editor);

    const actions = document.createElement('div'); actions.className = 'cd-actions';
    const save = document.createElement('button'); save.className = 's-run with-ui-icon ui-check';
    save.textContent = '保存名单'; actions.appendChild(save); card.appendChild(actions);
    target.replaceChildren(card);

    let original = [];
    try {
      const lists = await app.api.json('/api/config-lists');
      original = lists[item.listKey] || [];
      textarea.value = original.join('，');
      app.swordPicker.render(editor, textarea, [{ label: '恢复打开时名单', value: original }]);
    } catch (_) {
      app.feedback?.show(`${item.label}读取失败`, 'error');
    }

    save.addEventListener('click', async () => {
      const values = String(textarea.value || '').split(/[,，、\n]/).map(x => x.trim()).filter(Boolean);
      save.disabled = true; save.textContent = '正在保存…';
      try {
        const data = await app.api.post('/api/config-lists', { [item.listKey]: values });
        save.textContent = data.ok ? '✓ 已保存' : '保存失败';
        app.feedback?.show(data.ok ? `${item.label}已保存` : `${item.label}保存失败`, data.ok ? 'success' : 'error');
      } catch (_) {
        save.textContent = '保存失败'; app.feedback?.show(`${item.label}保存失败`, 'error');
      } finally {
        setTimeout(() => { save.disabled = false; save.textContent = '保存名单'; }, 1800);
      }
    });
  }

  app.listEditor = Object.freeze({ render });
})(window);
