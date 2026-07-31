/**
 * まあ丸前端公共入口。
 *
 * 页面功能模块统一挂在 window.Maamaru 下，避免继续往 app.js 的闭包里
 * 堆共享状态。这里不依赖构建工具，仍可直接由 FastAPI 静态托管。
 */
(function bootstrapMaamaru(global) {
  'use strict';

  const app = global.Maamaru = global.Maamaru || {};

  app.dom = app.dom || {
    one(selector, root = document) {
      return root.querySelector(selector);
    },
    all(selector, root = document) {
      return root.querySelectorAll(selector);
    },
    escape(value) {
      return String(value ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
    },
  };

  app.api = app.api || {
    async json(url, options) {
      const response = await fetch(url, options);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    },
    post(url, body) {
      return this.json(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    },
  };

  app.components = app.components || {
    input({ id, label, value = '', placeholder = '', type = 'text', className = '' }) {
      const wrap = document.createElement('div');
      wrap.className = `pf ${className}`.trim();
      wrap.innerHTML = `
        <label for="${app.dom.escape(id)}">${app.dom.escape(label)}</label>
        <input type="${app.dom.escape(type)}" id="${app.dom.escape(id)}"
          value="${app.dom.escape(value)}" placeholder="${app.dom.escape(placeholder)}">`;
      return wrap;
    },
    checkbox({ id, label, checked = false }) {
      const wrap = document.createElement('div');
      wrap.className = 'pf pf-check';
      wrap.innerHTML = `
        <label class="sys-check-label">
          <input type="checkbox" id="${app.dom.escape(id)}" ${checked ? 'checked' : ''}>
          ${app.dom.escape(label)}
        </label>`;
      return wrap;
    },
    enhanceSelect(select) {
      if (!select || select.dataset.enhancedSelect === '1') return;
      select.dataset.enhancedSelect = '1';

      const wrap = document.createElement('div');
      wrap.className = 'mm-select';
      select.parentNode.insertBefore(wrap, select);
      wrap.appendChild(select);

      const trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = 'mm-select-trigger';
      wrap.appendChild(trigger);

      const menu = document.createElement('div');
      menu.className = 'mm-select-menu';
      menu.hidden = true;
      document.body.appendChild(menu);

      const sync = () => {
        const option = select.options[select.selectedIndex];
        trigger.textContent = option?.textContent || '请选择';
        trigger.disabled = select.disabled;
        trigger.title = option?.textContent || '';
      };

      const close = () => {
        menu.hidden = true;
        trigger.classList.remove('open');
      };

      const open = () => {
        if (trigger.disabled) return;
        window.dispatchEvent(new CustomEvent('maamaru:close-selects'));
        menu.innerHTML = '';
        [...select.options].forEach(option => {
          const item = document.createElement('button');
          item.type = 'button';
          item.className = 'mm-select-option';
          item.textContent = option.textContent;
          item.disabled = option.disabled;
          if (option.selected) item.classList.add('selected');
          item.addEventListener('click', () => {
            select.value = option.value;
            sync();
            close();
            select.dispatchEvent(new Event('change', { bubbles: true }));
            trigger.focus();
          });
          menu.appendChild(item);
        });
        const rect = trigger.getBoundingClientRect();
        const below = window.innerHeight - rect.bottom;
        const menuHeight = Math.min(menu.scrollHeight || 260, 280);
        const openAbove = below < Math.min(menuHeight, 180) && rect.top > below;
        menu.style.left = `${Math.max(8, rect.left)}px`;
        menu.style.width = `${Math.max(rect.width, 150)}px`;
        menu.style.maxWidth = `${Math.max(180, window.innerWidth - rect.left - 12)}px`;
        menu.style.top = openAbove
          ? `${Math.max(8, rect.top - menuHeight - 4)}px`
          : `${rect.bottom + 4}px`;
        menu.hidden = false;
        trigger.classList.add('open');
      };

      trigger.addEventListener('click', () => menu.hidden ? open() : close());
      select.addEventListener('change', sync);
      window.addEventListener('maamaru:close-selects', close);
      window.addEventListener('resize', close);
      document.addEventListener('scroll', event => {
        // 页面滚动时菜单位置会失效，需要关闭；菜单自己滚动则必须保持展开。
        if (!menu.contains(event.target)) close();
      }, true);
      document.addEventListener('pointerdown', event => {
        if (!menu.hidden && !menu.contains(event.target) && !trigger.contains(event.target)) close();
      });
      sync();
    },
    enhanceSelects(root = document) {
      root.querySelectorAll('select').forEach(select => this.enhanceSelect(select));
    },
  };

  app.system = app.system || {};
})(window);
