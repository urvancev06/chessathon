/* Mikhail LeTal web app — boot: theme, the nav bar, the router. */
(() => {
  'use strict';
  const LT = window.LT;
  LT.theme.init();
  LT.boardStyle.init();

  const nav = document.getElementById('nav');
  const brand = LT.el('a', { class: 'brand', href: '#/overview', 'aria-label': 'Mikhail LeTal, overview' }, LT.mark(20), LT.wordmark());
  const items = LT.el('nav', { class: 'nav-items', 'aria-label': 'Screens' });
  const links = new Map();
  for (const { id, label } of LT.screens.list()) {
    const link = LT.el('a', { class: 'quiet', href: `#/${id}`, text: label });
    links.set(id, link);
    items.append(link);
  }
  LT.router.onNavigate((id) => {
    for (const [key, link] of links) {
      if (key === id) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    }
  });
  const version = LT.el('span', { class: 'version', text: '' });
  const boardSwitch = LT.el('span', { class: 'board-switch', role: 'group', 'aria-label': 'Board style' }, 'Board');
  const styleButtons = {};
  for (const style of LT.boardStyle.STYLES) {
    styleButtons[style] = LT.el('button', { type: 'button', class: 'quiet', text: style, 'aria-pressed': String(LT.boardStyle.get() === style), onClick: () => LT.boardStyle.set(style) });
    boardSwitch.append(styleButtons[style]);
  }
  LT.boardStyle.onChange((style) => { for (const [key, button] of Object.entries(styleButtons)) button.setAttribute('aria-pressed', String(key === style)); });
  const themeToggle = LT.el('button', { type: 'button', class: 'quiet', text: LT.theme.label(), onClick: () => LT.theme.toggle() });
  LT.theme.onChange(() => { themeToggle.textContent = LT.theme.label(); });
  nav.append(brand, items, LT.el('div', { class: 'nav-right' }, version, boardSwitch, themeToggle));

  LT.api.cached('/api/info').then((info) => {
    LT.info = info;
    const git = info.git || {};
    version.textContent = `v${info.version || '?'} · ${git.short || '?'}`;
    version.title = [git.branch, git.describe, git.dirty ? 'uncommitted changes' : ''].filter(Boolean).join(' · ');
  }).catch(() => { version.textContent = ''; });

  LT.router.start();
})();
