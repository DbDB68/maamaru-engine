/** 通用任务参数表单：字段渲染、记忆值恢复、条件显隐与取值。 */
(function registerParamForm(global) {
  'use strict';
  const app = global.Maamaru;
  const esc = app.dom.escape;

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

    const parse = () => String(hidden.value || '').split(/[,，、;；\s]+/)
      .map(value => value.trim()).filter(Boolean);

    function sync(values) {
      const unique = [...new Set(values)];
      hidden.value = unique.join(',');
      chips.replaceChildren();
      if (!unique.length) {
        chips.innerHTML = '<span class="duration-empty">没有关注时长，命中时不会特别提醒</span>';
        return;
      }
      unique.forEach(value => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'duration-chip';
        chip.innerHTML = `<span>${esc(value)}</span><b aria-label="删除">×</b>`;
        chip.addEventListener('click', () => {
          sync(parse().filter(item => item !== value));
          hidden.dispatchEvent(new Event('change', { bubbles: true }));
        });
        chips.appendChild(chip);
      });
    }

    editor.querySelector('.dur-add').addEventListener('click', () => {
      const readPart = (selector, max) => Math.max(0, Math.min(max,
        Number(editor.querySelector(selector).value) || 0));
      const value = [readPart('.dur-hour', 23), readPart('.dur-minute', 59), readPart('.dur-second', 59)]
        .map(part => String(part).padStart(2, '0')).join(':');
      sync([...parse(), value]);
      hidden.dispatchEvent(new Event('change', { bubbles: true }));
    });

    wrap._setDurationValue = value => {
      hidden.value = value || '';
      sync(parse());
    };
    wrap._setDurationValue(initialValue);
  }

  function renderField(field, saved) {
    const wrap = document.createElement('div');
    wrap.className = `pf pf-${field.type === 'checks' ? 'checks-wrap' : field.type}`;
    wrap._field = field;
    const label = document.createElement('label');
    label.className = 'pf-label';
    label.textContent = field.label;
    wrap.appendChild(label);

    if (field.type === 'select') {
      const select = document.createElement('select');
      select.dataset.paramKey = field.key;
      field.options.forEach(([value, text]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        option.selected = value === String(field.default);
        select.appendChild(option);
      });
      wrap.appendChild(select);
    } else if (field.type === 'number') {
      const input = document.createElement('input');
      input.type = 'number';
      input.dataset.paramKey = field.key;
      input.value = field.default;
      if (field.min !== undefined) input.min = field.min;
      if (field.max !== undefined) input.max = field.max;
      wrap.appendChild(input);
    } else if (field.type === 'text') {
      const input = document.createElement(field.swords ? 'textarea' : 'input');
      if (!field.swords) input.type = 'text';
      input.dataset.paramKey = field.key;
      input.value = field.default || '';
      if (field.placeholder) input.placeholder = field.placeholder;
      wrap.appendChild(input);
      if (field.swords) app.swordPicker.render(wrap, input, field.presets || []);
    } else if (field.type === 'duration-list') {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.dataset.paramKey = field.key;
      wrap.appendChild(input);
      renderDurationList(wrap, input, field.default || '');
    } else if (field.type === 'checks') {
      const box = document.createElement('div');
      box.className = 'pf-checks';
      box.dataset.paramKey = field.key;
      const defaults = new Set(field.default || []);
      field.options.forEach(name => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = `pill${defaults.has(name) ? ' on' : ''}`;
        pill.textContent = name;
        pill.dataset.value = name;
        pill.addEventListener('click', () => pill.classList.toggle('on'));
        box.appendChild(pill);
      });
      const tools = document.createElement('div');
      tools.className = 'pf-checks-tools';
      tools.innerHTML = '<a href="javascript:void 0" data-act="all">全选</a>'
        + '<a href="javascript:void 0" data-act="none">清空</a>';
      tools.addEventListener('click', event => {
        const action = event.target.dataset.act;
        if (!action) return;
        box.querySelectorAll('.pill').forEach(pill => pill.classList.toggle('on', action === 'all'));
      });
      wrap.append(box, tools);
    } else if (field.type === 'note') {
      wrap.classList.add('pf-note');
      wrap.removeChild(label);
      const note = document.createElement('div');
      note.className = 'pf-help';
      note.textContent = field.text || '';
      wrap.appendChild(note);
    }

    if (field.help) {
      const help = document.createElement('div');
      help.className = 'pf-help';
      help.textContent = field.help;
      wrap.appendChild(help);
    }

    if (saved !== undefined) {
      if (field.type === 'select') {
        const select = wrap.querySelector('select');
        if ([...select.options].some(option => option.value === String(saved))) select.value = String(saved);
      } else if (field.type === 'number') {
        wrap.querySelector('input').value = saved;
      } else if (field.type === 'text') {
        const input = wrap.querySelector('input, textarea');
        if (input) input.value = saved;
      } else if (field.type === 'duration-list') {
        wrap._setDurationValue(saved);
      } else if (field.type === 'checks' && Array.isArray(saved)) {
        const selected = new Set(saved);
        wrap.querySelectorAll('.pill').forEach(pill =>
          pill.classList.toggle('on', selected.has(pill.dataset.value)));
      }
    }
    return wrap;
  }

  function updateVisibility(form) {
    form.querySelectorAll('.pf').forEach(wrap => {
      const rule = wrap._field?.visibleWhen;
      if (!rule) return;
      const control = form.querySelector(`[data-param-key="${rule.key}"]`);
      if (!control) return;
      const show = rule.is !== undefined ? control.value === String(rule.is)
        : rule.not !== undefined ? control.value !== String(rule.not) : true;
      wrap.style.display = show ? '' : 'none';
    });
  }

  function collect(form) {
    const params = {};
    if (!form) return params;
    form.querySelectorAll('[data-param-key]').forEach(control => {
      const key = control.dataset.paramKey;
      params[key] = control.classList.contains('pf-checks')
        ? [...control.querySelectorAll('.pill.on')].map(pill => pill.dataset.value)
        : control.value;
    });
    return params;
  }

  app.paramForm = Object.freeze({ renderField, updateVisibility, collect });
})(window);
