/* Mikhail LeTal web app — Openings, README §7: data/openings.txt with mini boards. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el } = LT;
  const FIRST = 13;

  LT.screens.register('openings', {
    label: 'Openings',
    async mount(root) {
      const data = await LT.api.cached('/api/openings');
      const rows = (data.present ? data.openings : []) || [];
      const total = rows.length;
      let filter = '';
      let showAll = false;
      const input = el('input', { class: 'input filter', placeholder: 'Filter by name', 'aria-label': 'Filter openings' });
      const list = el('div', { class: 'op-list' });
      const footer = el('div', { class: 'op-footer' });
      const count = el('span', { class: 'grey t12 tabular', text: `${total} positions` });
      let style = LT.boardStyle.get();
      function render() {
        LT.clear(list);
        const needle = filter.trim().toLowerCase();
        const matching = needle ? rows.filter((row) => (row.name || '').toLowerCase().includes(needle)) : rows;
        const shown = needle || showAll ? matching : matching.slice(0, FIRST);
        for (const row of shown) {
          list.append(el('div', { class: 'op-row' },
            el('span', { class: 'op-idx', text: String(row.index).padStart(3, '0') }),
            el('span', { class: 'op-name', text: row.name || '(unnamed)' }),
            row.valid ? LT.miniBoard(row.fen, style) : el('span', { class: 'mini' }),
            el('span', { class: 'op-fen', text: row.fen }),
            row.valid ? el('a', { class: 'quiet', href: `#/new?opening=${row.index}`, text: 'Play' }) : el('span', { class: 'notice', text: 'invalid FEN' })));
        }
        LT.clear(footer);
        if (!total) footer.append(el('span', { text: `${data.path} is not present` }));
        else if (needle) footer.append(el('span', { text: `${matching.length} of ${total} match “${filter.trim()}”` }));
        else if (showAll) footer.append(el('span', { text: `All ${total} · from ${data.path}` }));
        else footer.append(el('span', { text: `Showing the first ${shown.length} of ${total} · the full set is in ${data.path}` }), el('button', { type: 'button', class: 'quiet small', text: 'Show all', onClick: () => { showAll = true; render(); } }));
      }
      input.addEventListener('input', () => { filter = input.value; render(); });
      const unsubscribe = LT.boardStyle.onChange((next) => { style = next; render(); });
      root.append(el('div', { class: 'openings' },
        el('div', { class: 'op-head' }, el('div', { class: 'op-title' }, el('span', { class: 't20', text: 'Openings' }), count), input),
        list, footer));
      render();
      return () => unsubscribe();
    },
  });
})();
