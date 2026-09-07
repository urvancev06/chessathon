/* Mikhail LeTal web app — Overview, README §4. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el } = LT;
  const HOW = [
    ['Search', 'It looks ahead by trying moves and replies, one ply deeper at a time, until the time budget is used. Lines that cannot change the outcome are skipped (alpha–beta), positions already judged are remembered (a transposition table), and the most promising moves are tried first. That ordering is what makes depth affordable.'],
    ['Evaluation', 'At the end of each line it scores the position: material, then where each piece stands, using piece-square tables that blend a middlegame view with an endgame view as pieces leave the board. The tables come from a small set of geometric rules; their provenance ships with the engine.'],
    ['Time management', 'Each move gets a soft budget, after which no new iteration starts, and a hard budget, at which the search aborts. Both derive from the clock, the increment and the stage of the game, and always leave a reserve, because running out of time loses.'],
    ['Safety wrapper', 'agent.py wraps all of that so nothing can raise. Every move is re-checked for legality on a fresh board, a fast fallback plays when time is short or anything fails, and one compact log line per move records what the search did.'],
  ];
  // The prototype's four contract rows, mapped onto the server's; the rest follow in the same table.
  const MAP = [['Time control', ['Time control']], ['Hardware', ['CPU', 'Memory']], ['Initialisation', ['Init budget']], ['Game length', ['Ply cap']]];

  LT.screens.register('overview', {
    label: 'Overview',
    async mount(root) {
      const info = await LT.api.cached('/api/info', true);
      const git = info.git || {};
      const contract = info.contract || [];
      const used = new Set();
      const rows = [];
      for (const [label, sources] of MAP) {
        const values = sources.map((name) => { const row = contract.find((r) => r.label === name); if (row) used.add(row.label); return row ? row.value : null; }).filter(Boolean);
        if (values.length) rows.push([label, values.join(' · ')]);
      }
      for (const row of contract) if (!used.has(row.label)) rows.push([row.label, row.value]);
      const table = el('div', { class: 'table contract' });
      for (const [k, v] of rows) table.append(el('span', { class: 'k', text: k }), el('span', { text: v }));

      const results = info.results || {};
      let resultsNode;
      if (results.present && results.rows && results.rows.length) {
        const columns = results.columns || [];
        const grid = el('div', { class: 'table results', style: { gridTemplateColumns: `repeat(${columns.length}, auto)` } });
        for (const column of columns) grid.append(el('span', { class: 'th', text: column }));
        for (const row of results.rows) columns.forEach((column, i) => grid.append(el('span', { class: i === 0 ? 'k' : (/score|result/i.test(column) ? 'w500' : ''), text: row[column] || '' })));
        resultsNode = el('div', { class: 'scroll-x' }, grid);
      } else {
        resultsNode = el('div', { class: 'grey t12', text: results.present ? 'no results yet' : 'docs/RESULTS.md is not present' });
      }
      root.append(el('div', { class: 'overview' },
        el('div', {},
          el('div', { class: 'ov-brand' }, LT.mark(40), LT.wordmark()),
          el('p', { class: 'ov-tagline', text: info.tagline || '' }),
          el('div', { class: 'ov-meta', text: `v${info.version || '?'} · ${git.short || '?'}${git.built ? ` · built ${git.built}` : ''} · Python 3.12, python-chess` })),
        el('div', {}, el('div', { class: 'label', text: 'Competition contract' }), table),
        el('div', {}, el('div', { class: 'label how', text: 'How it works' }),
          el('div', { class: 'how-grid' }, HOW.map(([title, text]) => el('div', {}, el('div', { class: 'w500', text: title }), el('p', { text }))))),
        el('div', {}, el('div', { class: 'label', text: 'Latest results' }), resultsNode)));
      return () => {};
    },
  });
})();
