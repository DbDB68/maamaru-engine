/**
 * Task lifecycle: start, stop, poll, and reflect runner state in the panel UI.
 */
(function() {
  'use strict';

  const app = window.Maamaru = window.Maamaru || {};

  function create(options) {
    const {
      els,
      resolveAlias,
      getMeta,
      getState,
      setState,
      render,
      onStarted,
      onFinished,
    } = options;

    function updateStatus(running, name) {
      const meta = getMeta();
      const label = name && meta[name] ? meta[name].label : name;
      if (running) {
        els.statusDot.className = 'dot dot-yellow';
        els.statusText.textContent = label ? `运行中: ${label}` : '运行中';
        app.logViewer?.setRunning(true, label || '');
        els.taskIndicator.textContent = `⏳ ${label || '运行中'}`;
        els.taskIndicator.className = 'badge badge-running';
        els.stopAll.disabled = false;
      } else {
        els.statusDot.className = 'dot dot-green';
        els.statusText.textContent = '待命中';
        app.logViewer?.setRunning(false);
        els.taskIndicator.textContent = '空闲';
        els.taskIndicator.className = 'badge badge-idle';
        els.stopAll.disabled = true;
      }
    }

    async function run(name, params) {
      if (getState().running) return;
      const realName = resolveAlias(name);
      try {
        localStorage.setItem('maamaru_params_' + realName, JSON.stringify(params || {}));
        const response = await fetch('/api/scripts/run', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({script: realName, params: params || {}}),
        });
        const data = await response.json();
        if (!data.ok) {
          app.feedback?.show(data.reason || '任务启动失败', 'error');
          console.warn('run failed:', data.reason);
          return;
        }
        setState(true, realName);
        const label = getMeta()[realName]?.label || realName;
        app.feedback?.show(`${label}已启动`, 'success');
        updateStatus(true, realName);
        render();
        onStarted?.(realName);
        app.dashboard?.load();
      } catch (error) {
        app.feedback?.show('任务启动失败，面板后端没有响应', 'error');
        console.error('run error:', error);
      }
    }

    async function stop() {
      try {
        await fetch('/api/scripts/stop', {method: 'POST'});
      } catch (_) {}
    }

    async function poll() {
      try {
        const response = await fetch('/api/scripts');
        const data = await response.json();
        const previous = getState();
        if (data.running === previous.running && data.current === previous.current) return;
        setState(data.running, data.current);
        updateStatus(data.running, data.current);
        render();
        app.dashboard?.load();
        if (!data.running) onFinished?.();
      } catch (_) {}
    }

    els.stopAll.addEventListener('click', stop);
    return { run, stop, poll, updateStatus };
  }

  app.taskRunner = { create };
})();
