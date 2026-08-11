/**
 * QQ / OneBot 状态卡。
 *
 * 协议端安装器以后可以继续扩展在这个模块里，不必再修改主 app.js。
 */
(function registerQQModule(global) {
  'use strict';

  const app = global.Maamaru;
  if (!app) throw new Error('Maamaru core must be loaded first');

  const { escape } = app.dom;

  function checkItem(label, online, yes, no, detail) {
    return `
      <div class="${online ? 'ok' : 'bad'}">
        <span>${label}</span>
        <b>${online ? yes : no}</b>
        <small>${escape(detail)}</small>
      </div>`;
  }

  async function refresh() {
    const box = document.getElementById('qq-status-box');
    if (!box) return;

    box.className = 'qq-status-card checking';
    box.innerHTML = `
      <div class="qq-status-main">
        <span class="qq-light"></span><b>正在检测协议端…</b>
      </div>`;

    try {
      const data = await app.api.json('/api/qq-status');
      const connected = data.state === 'connected';
      box.className = `qq-status-card ${connected ? 'connected' : 'unavailable'}`;
      box.innerHTML = `
        <div class="qq-status-main">
          <span class="qq-light"></span>
          <div>
            <b>${connected ? '协议端已连接' : '未检测到协议端'}</b>
            <small>${connected
              ? 'OneBot 消息 API 可以访问'
              : '可能尚未安装、未启动，或端口配置不正确'}</small>
          </div>
          <button id="qq-recheck" type="button" class="small-btn with-ui-icon ui-return">重新检测</button>
        </div>
        <div class="qq-check-grid">
          ${checkItem('消息 API', data.api_online, '可用', '不可用', data.api_detail)}
          ${checkItem('管理页面', data.gui_online, '可打开', '未响应', data.gui_detail)}
          ${checkItem('消息入口', data.webhook_ready, '已准备', '未挂载', data.webhook_url)}
        </div>
        <div class="qq-status-actions">
          <button id="qq-open-gui" type="button" class="small-btn"
            ${data.gui_url ? '' : 'disabled'}>↗ 打开协议端管理页</button>
          <span>一键下载会由正式启动器提供；当前页面不会自动下载任何程序。</span>
        </div>`;

      document.getElementById('qq-recheck')?.addEventListener('click', refresh);
      document.getElementById('qq-open-gui')?.addEventListener('click', () => {
        const configured = document.getElementById('sys-qq-gui')?.value.trim();
        const url = configured || data.gui_url;
        if (url) global.open(url, '_blank');
      });
    } catch (error) {
      box.className = 'qq-status-card unavailable';
      box.innerHTML = `
        <div class="qq-status-main">
          <span class="qq-light"></span>
          <div><b>状态检测失败</b><small>まあ丸后端暂时没有响应</small></div>
          <button id="qq-recheck" type="button" class="small-btn with-ui-icon ui-return">重试</button>
        </div>`;
      document.getElementById('qq-recheck')?.addEventListener('click', refresh);
    }
  }

  app.system.qq = Object.freeze({ refresh });
})(window);
