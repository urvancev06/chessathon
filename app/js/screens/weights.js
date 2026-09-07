/* Mikhail LeTal web app — Weights, README §6: piece values, provenance, twelve PSQT heatmaps. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el } = LT;
  const PIECES = ['P', 'N', 'B', 'R', 'Q', 'K'];
  const NAMES = { P: 'Pawn', N: 'Knight', B: 'Bishop', R: 'Rook', Q: 'Queen', K: 'King' };

  /** The _provenance object as aligned key/value lines; parameters indented with their reasons. */
  function provenanceText(prov) {
    if (!prov || typeof prov !== 'object') return '(no provenance in pst.json)';
    const lines = [];
    const keys = Object.keys(prov).filter((key) => key !== 'parameters');
    const width = Math.max(...keys.map((key) => key.length), 6);
    for (const key of keys) lines.push(`${key.padEnd(width)}  ${typeof prov[key] === 'object' ? JSON.stringify(prov[key]) : String(prov[key])}`);
    if (prov.parameters && typeof prov.parameters === 'object') {
      lines.push('', 'parameters');
      const names = Object.keys(prov.parameters);
      const nameWidth = Math.max(...names.map((name) => name.length), 4);
      for (const name of names) {
        const item = prov.parameters[name];
        const value = item && typeof item === 'object' && 'value' in item ? item.value : item;
        const why = item && typeof item === 'object' && item.why ? `  ${item.why}` : '';
        lines.push(`  ${name.padEnd(nameWidth)}  ${String(value).padStart(4)}${why}`);
      }
    }
    return lines.join('\n');
  }

  LT.screens.register('weights', {
    label: 'Weights',
    async mount(root) {
      const data = await LT.api.get('/api/weights');
      const page = el('div', { class: 'weights' });
      root.append(page);
      for (const error of data.errors || []) page.append(el('div', { class: 'notice', text: error }));
      if (!data.present || !data.pst) {
        page.append(el('div', {}, el('div', { class: 't20', text: 'Not generated yet' }), el('p', { class: 'grey t12', style: { margin: '8px 0 0' }, text: `${data.path} does not exist in this checkout. Run tools/gen_pst.py to generate the tables; this page reads the file on every load.` })));
        return () => {};
      }
      const pst = data.pst;
      const mg = pst.piece_values_mg || {};
      const eg = pst.piece_values_eg || {};
      const phase = pst.phase_weights || {};
      const table = el('div', { class: 'table tight pv-table' },
        el('span', { class: 'th', text: 'piece' }), el('span', { class: 'th r', text: 'mg' }), el('span', { class: 'th r', text: 'eg' }), el('span', { class: 'th r', text: 'phase' }));
      const show = (value) => (value == null ? '—' : String(value));
      for (const piece of PIECES) {
        table.append(el('span', { text: NAMES[piece] }),
          el('span', { class: 'r', text: piece === 'K' && !mg[piece] ? '—' : show(mg[piece]) }),
          el('span', { class: 'r', text: piece === 'K' && !eg[piece] ? '—' : show(eg[piece]) }),
          el('span', { class: 'r grey', text: phase[piece] != null ? String(phase[piece]) : '—' }));
      }
      const phaseMax = (Number(phase.N) || 0) * 4 + (Number(phase.B) || 0) * 4 + (Number(phase.R) || 0) * 4 + (Number(phase.Q) || 0) * 2 || 24;
      const tables = [];
      for (const piece of PIECES) {
        for (const [key, label] of [['pst_mg', 'middlegame'], ['pst_eg', 'endgame']]) {
          const values = pst[key] && Array.isArray(pst[key][piece]) ? pst[key][piece].map(Number) : null;
          if (values) tables.push({ piece, label, values });
        }
      }
      const all = tables.flatMap((t) => t.values);
      const max = all.length ? Math.max(...all) : 0;
      const min = all.length ? Math.min(...all) : 0;
      const heatmaps = el('div', { class: 'heatmaps' });
      for (const { piece, label, values } of tables) {
        const grid = el('div', { class: 'hm-grid', role: 'img', 'aria-label': `${NAMES[piece]} ${label} table` });
        for (let row = 0; row < 8; row++) {
          const rank = 8 - row;
          for (let file = 0; file < 8; file++) {
            const value = values[(rank - 1) * 8 + file];
            const cell = el('span', { text: String(value), title: `${LT.FILES[file]}${rank}: ${value}` });
            if (value >= 0) cell.style.setProperty('--pos', `${(max > 0 ? Math.min(1, value / max) * 62 : 0).toFixed(1)}%`);
            else { cell.classList.add('neg'); cell.style.setProperty('--neg', `${(min < 0 ? Math.min(1, value / min) * 70 : 0).toFixed(1)}%`); }
            grid.append(cell);
          }
        }
        heatmaps.append(el('div', {},
          el('div', { class: 'hm-head' }, el('span', { class: 'w500', text: NAMES[piece] }), el('span', { class: 'grey', text: label })),
          grid,
          el('div', { class: 'hm-files' }, 'abcdefgh'.split('').map((f) => el('span', { text: f })))));
      }
      page.append(
        el('div', { class: 'weights-top' },
          el('div', {}, el('div', { class: 'label', text: 'Piece values and phase weights' }), table,
            el('div', { class: 'formula', text: `Phase = Σ weights of non-pawn pieces on the board, ${phaseMax} at the start, 0 in a pawn ending. Score = (mg · phase + eg · (${phaseMax} − phase)) / ${phaseMax}.` })),
          el('div', {}, el('div', { class: 'label', text: 'Provenance' }), el('pre', { class: 'prov', text: provenanceText(pst._provenance) }))),
        el('div', {},
          el('div', { class: 'psqt-head' },
            el('span', { class: 'label', text: "Piece-square tables · white's view, rank 8 at the top" }),
            el('span', { class: 'legend' }, el('span', { text: String(min) }), el('span', { class: 'chip' }), el('span', { text: String(max) }))),
          heatmaps));
      return () => {};
    },
  });
})();
