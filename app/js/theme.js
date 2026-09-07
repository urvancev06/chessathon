/* Mikhail LeTal web app — theme (light | dark | system) and board style (lichess | studio). */
(() => {
  'use strict';
  const LT = window.LT;
  const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  const listeners = new Set();
  const styleListeners = new Set();
  function effective(mode) {
    if (mode === 'light' || mode === 'dark') return mode;
    return media && media.matches ? 'dark' : 'light';
  }
  LT.theme = {
    KEY: 'letal.theme',
    get() { const mode = LT.storage.get(this.KEY, 'system'); return ['light', 'dark', 'system'].includes(mode) ? mode : 'system'; },
    effective() { return effective(this.get()); },
    apply() {
      const theme = this.effective();
      document.documentElement.setAttribute('data-theme', theme);
      for (const listener of listeners) listener(theme);
    },
    set(mode) { LT.storage.set(this.KEY, mode); this.apply(); },
    /** The toggle names the theme it switches to: "Dark" while light, "Light" while dark. */
    label() { return this.effective() === 'dark' ? 'Light' : 'Dark'; },
    toggle() { this.set(this.effective() === 'dark' ? 'light' : 'dark'); },
    onChange(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    init() {
      this.apply();
      if (media) {
        const follow = () => { if (this.get() === 'system') this.apply(); };
        if (media.addEventListener) media.addEventListener('change', follow); else media.addListener(follow);
      }
    },
  };
  LT.boardStyle = {
    KEY: 'letal.board',
    STYLES: ['lichess', 'studio'],
    get() { const style = LT.storage.get(this.KEY, 'lichess'); return this.STYLES.includes(style) ? style : 'lichess'; },
    set(style) {
      if (!this.STYLES.includes(style)) return;
      LT.storage.set(this.KEY, style);
      document.documentElement.setAttribute('data-board', style);
      for (const listener of styleListeners) listener(style);
    },
    onChange(listener) { styleListeners.add(listener); return () => styleListeners.delete(listener); },
    init() { document.documentElement.setAttribute('data-board', this.get()); },
  };
})();
