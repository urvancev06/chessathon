/* Mikhail LeTal web app — hash router and screen registry. Routes: #/play, #/new, #/spectate,
   #/overview, #/docs, #/weights, #/openings, #/analysis, each with an optional ?query. */
(() => {
  'use strict';
  const LT = window.LT;
  const ORDER = ['play', 'new', 'spectate', 'overview', 'docs', 'weights', 'openings', 'analysis'];
  const registry = new Map();
  LT.screens = {
    order: ORDER,
    register(id, screen) { registry.set(id, screen); },
    get(id) { return registry.get(id); },
    list() { return ORDER.filter((id) => registry.has(id)).map((id) => ({ id, label: registry.get(id).label })); },
  };
  let unmount = null;
  let currentId = null;
  const navListeners = new Set();
  function parse() {
    const hash = location.hash.replace(/^#\/?/, '');
    const [path, query = ''] = hash.split('?');
    const id = (path.split('/')[0] || 'play').toLowerCase();
    return { id: registry.has(id) ? id : 'play', params: new URLSearchParams(query) };
  }
  async function navigate() {
    const { id, params } = parse();
    const screen = registry.get(id);
    if (!screen) return;
    if (typeof unmount === 'function') { try { unmount(); } catch (error) { /* a screen that failed to mount */ } }
    unmount = null;
    currentId = id;
    const main = document.getElementById('main');
    LT.clear(main);
    const root = LT.el('div', { class: `screen screen-${id}`, 'data-screen': id });
    main.append(root);
    document.title = `${screen.label} · Mikhail LeTal`;
    for (const listener of navListeners) listener(id);
    try {
      const result = await screen.mount(root, params);
      if (currentId !== id) { if (typeof result === 'function') result(); return; }
      unmount = typeof result === 'function' ? result : null;
    } catch (error) {
      root.append(LT.el('div', { class: 'empty-line' }, LT.el('span', { class: 'notice', text: `${screen.label} could not load: ${error.message || error}` })));
    }
  }
  LT.router = {
    current() { return currentId; },
    go(hash) { location.hash = hash; },
    onNavigate(listener) { navListeners.add(listener); return () => navListeners.delete(listener); },
    start() {
      window.addEventListener('hashchange', navigate);
      if (!location.hash) history.replaceState(null, '', '#/play');
      navigate();
    },
  };
})();
