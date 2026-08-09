/** Theme registry and persistence. New skins register here and provide CSS tokens. */
(function registerThemeManager(global) {
  'use strict';

  const themes = Object.freeze([
    { id: 'washi', label: '和纸', icon: '🍂' },
    { id: 'pixel', label: '像素', icon: '👾' },
  ]);
  const fallback = themes[0].id;
  let current = fallback;

  function get(id) {
    return themes.find(theme => theme.id === id);
  }

  function apply(id) {
    const theme = get(id) || get(fallback);
    current = theme.id;
    document.body.dataset.theme = theme.id;
    document.body.classList.toggle('theme-pixel', theme.id === 'pixel');
    localStorage.setItem('maamaru_theme', theme.id);
    global.dispatchEvent(new CustomEvent('maamaru:theme', { detail: theme }));
    return theme;
  }

  function next() {
    const index = themes.findIndex(theme => theme.id === current);
    return apply(themes[(index + 1) % themes.length].id);
  }

  global.Maamaru.theme = Object.freeze({ themes, apply, next, get, current: () => current });
})(window);
