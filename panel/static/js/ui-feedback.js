/** 统一的非阻塞操作反馈；配置页、启动器和协议端都可以复用。 */
(function registerFeedback(global) {
  'use strict';

  const app = global.Maamaru;
  if (!app) throw new Error('Maamaru core must be loaded first');

  function host() {
    let node = document.getElementById('mm-toast-host');
    if (!node) {
      node = document.createElement('div');
      node.id = 'mm-toast-host';
      node.setAttribute('aria-live', 'polite');
      document.body.appendChild(node);
    }
    return node;
  }

  function show(message, type = 'info', timeout = 2800) {
    const toast = document.createElement('div');
    toast.className = `mm-toast ${type}`;
    const icon = { success: '✓', error: '!', warning: '△', info: '·' }[type] || '·';
    toast.innerHTML = `<b>${icon}</b><span>${app.dom.escape(message)}</span>`;
    host().appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('visible'));
    const remove = () => {
      toast.classList.remove('visible');
      setTimeout(() => toast.remove(), 180);
    };
    toast.addEventListener('click', remove);
    setTimeout(remove, timeout);
    return toast;
  }

  app.feedback = Object.freeze({ show });
})(window);
