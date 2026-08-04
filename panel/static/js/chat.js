/** 近侍聊天：历史记录、消息发送、输入状态与聊天清屏。 */
(function registerChat(global) {
  'use strict';

  const app = global.Maamaru;
  const $ = app.dom.one;
  const esc = app.dom.escape;
  let busy = false;
  let bound = false;

  const ui = () => ({
    messages: $('#chat-messages'),
    input: $('#chat-input'),
    send: $('#chat-send'),
    container: $('#chat-container'),
    clear: $('#btn-clear-chat'),
    tab: $('[data-tab="chat"]'),
  });

  function addBubble(role, text) {
    const u = ui();
    const div = document.createElement('div');
    div.className = role === 'user' ? 'msg msg-user' : 'msg msg-system';
    div.innerHTML = `
      <div class="msg-avatar">${role === 'user' ? '🧑' : '🦊'}</div>
      <div class="msg-bubble">
        <div class="msg-name">${role === 'user' ? '审神者' : '狐之助'}</div>
        <div class="msg-text">${esc(text)}</div>
      </div>`;
    u.messages.appendChild(div);
    u.container.scrollTop = u.container.scrollHeight;
  }

  function showTyping() {
    const u = ui();
    const div = document.createElement('div');
    div.className = 'msg msg-system msg-typing';
    div.id = 'typing-indicator';
    div.innerHTML = `
      <div class="msg-avatar">🦊</div>
      <div class="msg-bubble">
        <div class="msg-name">狐之助</div>
        <div class="msg-text">思考中…</div>
      </div>`;
    u.messages.appendChild(div);
    u.container.scrollTop = u.container.scrollHeight;
  }

  function hideTyping() {
    $('#typing-indicator')?.remove();
  }

  async function loadHistory() {
    try {
      const data = await app.api.json('/api/chat/history');
      if (!data.history?.length) return;
      const u = ui();
      const greeting = u.messages.querySelector('.msg-system');
      u.messages.replaceChildren();
      if (greeting) u.messages.appendChild(greeting);
      data.history.forEach(message => addBubble(
        message.role === 'user' ? 'user' : 'assistant', message.content));
    } catch (_) {
      // 历史记录不是启动面板的硬依赖。
    }
  }

  async function sendMessage(text) {
    const value = String(text || '').trim();
    if (!value || busy) return;
    const u = ui();
    busy = true;
    u.send.disabled = true;
    u.input.disabled = true;
    addBubble('user', value);
    u.input.value = '';
    showTyping();

    try {
      const data = await app.api.post('/api/chat', { message: value });
      hideTyping();
      addBubble('assistant', data.reply);
    } catch (_) {
      hideTyping();
      addBubble('assistant', '（狐之助耳朵耷拉下来：主君…面板好像断线了）');
    } finally {
      busy = false;
      u.send.disabled = false;
      u.input.disabled = false;
      u.input.focus();
    }
  }

  function clearMessages() {
    if (!global.confirm('确定清空所有聊天记录？')) return;
    ui().messages.innerHTML = `
      <div class="msg msg-system">
        <div class="msg-avatar">🦊</div>
        <div class="msg-bubble">
          <div class="msg-name">狐之助</div>
          <div class="msg-text">主君，您来了！本丸一切正常，有什么需要我帮忙的吗？</div>
        </div>
      </div>`;
  }

  function bind() {
    if (bound) return;
    bound = true;
    const u = ui();
    u.input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage(u.input.value);
      }
    });
    u.input.addEventListener('input', () => {
      u.send.disabled = !u.input.value.trim();
    });
    u.send.addEventListener('click', () => sendMessage(u.input.value));
    u.clear.addEventListener('click', clearMessages);
    u.tab.addEventListener('click', () => setTimeout(() => u.input.focus(), 100));
  }

  async function init() {
    bind();
    await loadHistory();
  }

  app.chat = Object.freeze({ init, loadHistory, sendMessage, addBubble });
})(window);
