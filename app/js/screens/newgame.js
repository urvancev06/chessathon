/* Mikhail LeTal web app — New game, README §2. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el } = LT;
  const FORM_KEY = 'letal.new';
  const GROUPS = ['letal', 'version', 'baseline', 'stockfish'];

  /** The spec's validation messages, verbatim. */
  LT.validateFen = function validateFen(f) {
    const parts = String(f || '').trim().split(/\s+/).filter(Boolean);
    if (parts.length < 2) return { ok: false, msg: 'Needs at least placement and side to move' };
    const ranks = parts[0].split('/');
    if (ranks.length !== 8) return { ok: false, msg: `${ranks.length} ranks, expected 8` };
    for (let r = 0; r < 8; r++) {
      let n = 0;
      for (const ch of ranks[r]) {
        if (/[1-8]/.test(ch)) n += Number(ch);
        else if (/[prnbqkPRNBQK]/.test(ch)) n += 1;
        else return { ok: false, msg: `Unknown character “${ch}” in rank ${8 - r}` };
      }
      if (n !== 8) return { ok: false, msg: `Rank ${8 - r} has ${n} squares` };
    }
    const K = (parts[0].match(/K/g) || []).length;
    const k = (parts[0].match(/k/g) || []).length;
    if (K !== 1 || k !== 1) return { ok: false, msg: 'Each side needs exactly one king' };
    if (!/^[wb]$/.test(parts[1])) return { ok: false, msg: 'Side to move must be w or b' };
    if (parts[2] && !/^(-|K?Q?k?q?)$/.test(parts[2])) return { ok: false, msg: 'Castling field is malformed' };
    if (parts[3] && !/^(-|[a-h][36])$/.test(parts[3])) return { ok: false, msg: 'En passant square is malformed' };
    return { ok: true, msg: `Valid · ${parts[1] === 'w' ? 'white' : 'black'} to move · castling ${parts[2] || '-'}` };
  };

  /** Engine seats grouped: working tree, versions, baselines, Stockfish levels. */
  LT.engineRows = function engineRows(info) {
    const git = info.git || {};
    const rows = [];
    for (const kind of GROUPS) {
      for (const engine of (info.engines || []).filter((e) => (GROUPS.includes(e.kind) ? e.kind : 'letal') === kind)) {
        let name = engine.label;
        let meta = engine.id;
        if (kind === 'letal') { name = 'Working tree'; meta = `${git.short || '?'}${git.dirty ? ' · dirty' : ''}`; }
        else if (kind === 'baseline') name = `Baseline · ${engine.short}`;
        rows.push({ id: engine.id, kind, name, meta, label: engine.label });
      }
    }
    return rows;
  };

  LT.screens.register('new', {
    label: 'New game',
    async mount(root, params) {
      const [info, openings] = await Promise.all([LT.api.cached('/api/info', true), LT.api.cached('/api/openings')]);
      const rows = LT.engineRows(info);
      const tcs = (info.time_controls || []).map((tc) => [tc.base_ms / 1000, tc.increment_ms / 1000]);
      const saved = LT.storage.get(FORM_KEY, {}) || {};
      const form = {
        engine: rows.some((r) => r.id === saved.engine) ? saved.engine : (rows[0] ? rows[0].id : ''),
        colour: [0, 1, 2].includes(saved.colour) ? saved.colour : 0,
        tc: Number.isInteger(saved.tc) && saved.tc < tcs.length ? saved.tc : 0,
        base: '', inc: '',
        start: 0, index: '0', fen: LT.START_FEN,
        movetime: saved.movetime || '',
      };
      if (form.tc < tcs.length) { form.base = String(tcs[form.tc][0]); form.inc = String(tcs[form.tc][1]); }
      else { form.base = saved.base || '120'; form.inc = saved.inc || '0.5'; }
      if (params.get('opening') != null) { form.start = 1; form.index = String(parseInt(params.get('opening'), 10) || 0); }
      const curated = (openings && openings.openings) || [];

      const notice = el('div', { class: 'notice', hidden: true });
      const start = el('button', { type: 'button', class: 'primary', text: 'Start game' });
      const list = el('div', { class: 'option-list' });
      const colours = el('div', { class: 'seg-row' });
      const tcRow = el('div', { class: 'seg-row' });
      const base = el('input', { class: 'input num', inputmode: 'decimal', 'aria-label': 'Base seconds' });
      const inc = el('input', { class: 'input num', inputmode: 'decimal', 'aria-label': 'Increment seconds' });
      const starts = el('div', { class: 'seg-row' });
      const indexInput = el('input', { class: 'input idx', inputmode: 'numeric', 'aria-label': 'Opening index' });
      const indexName = el('span', { class: 'grey' });
      const indexRow = el('div', { class: 'index-row', hidden: true }, indexInput, indexName);
      const fenInput = el('input', { class: 'input fen', spellcheck: 'false', 'aria-label': 'FEN' });
      const fenStatus = el('div', { class: 'fen-status' });
      const fenRow = el('div', { class: 'fen-row', hidden: true }, fenInput, fenStatus);
      const movetime = el('input', { class: 'input num', inputmode: 'numeric', placeholder: 'clock', 'aria-label': 'Stockfish move time in milliseconds' });
      const movetimeRow = el('div', { hidden: true },
        el('div', { class: 'label', text: 'Stockfish move time' }),
        el('div', { class: 'field-row' }, el('label', {}, 'fixed', movetime, 'ms'), el('span', { text: 'empty = it plays on the clock it is handed' })));

      root.append(el('div', { class: 'new' },
        el('div', { class: 'new-head' }, el('span', { class: 't20', text: 'New game' }), el('span', { class: 'grey t12', text: 'Nothing starts until you press Start' })),
        el('div', {}, el('div', { class: 'label', text: 'Engine build' }), list),
        el('div', { class: 'new-grid' },
          el('div', {}, el('div', { class: 'label', text: 'Your colour' }), colours),
          el('div', {}, el('div', { class: 'label', text: 'Time control' }), tcRow,
            el('div', { class: 'field-row', style: { marginTop: '10px' } }, el('label', {}, 'base', base, 's'), el('label', {}, 'increment', inc, 's')))),
        movetimeRow,
        el('div', {}, el('div', { class: 'label', text: 'Starting position' }), starts, indexRow, fenRow),
        el('div', { class: 'new-footer' }, start, el('a', { class: 'quiet', href: '#/play', text: 'Cancel' })),
        notice));

      const segButton = (label, on, pick, extra = '') => el('button', { type: 'button', class: `seg${extra}`, 'aria-pressed': String(on), text: label, onClick: pick });
      const selectedRow = () => rows.find((r) => r.id === form.engine);
      const openingAt = () => { const i = parseInt(form.index, 10); return Number.isInteger(i) && i >= 0 && i < curated.length ? curated[i] : null; };

      function render() {
        LT.clear(list);
        for (const row of rows) {
          list.append(el('button', { type: 'button', class: 'option', 'aria-pressed': String(row.id === form.engine), onClick: () => { form.engine = row.id; render(); } },
            el('span', { class: 'mark' }), el('span', { class: 'name', text: row.name }), el('span', { class: 'meta', text: row.meta })));
        }
        if (!rows.length) list.append(el('div', { class: 'grey t12', style: { padding: '10px 0' }, text: 'No engine seats found: the server lists none.' }));
        LT.clear(colours);
        ['White', 'Black', 'Random'].forEach((label, i) => colours.append(segButton(label, form.colour === i, () => { form.colour = i; render(); })));
        LT.clear(tcRow);
        tcs.forEach(([b, i], index) => tcRow.append(segButton(`${b} + ${i}`, form.tc === index, () => { form.tc = index; form.base = String(b); form.inc = String(i); render(); }, ' tc')));
        if (document.activeElement !== base) base.value = form.base;
        if (document.activeElement !== inc) inc.value = form.inc;
        LT.clear(starts);
        ['Standard', 'Curated opening by index', 'Custom FEN'].forEach((label, i) => starts.append(segButton(label, form.start === i, () => { form.start = i; render(); })));
        indexRow.hidden = form.start !== 1;
        fenRow.hidden = form.start !== 2;
        if (document.activeElement !== indexInput) indexInput.value = form.index;
        if (document.activeElement !== fenInput) fenInput.value = form.fen;
        const opening = openingAt();
        indexName.textContent = opening ? (opening.name || '(unnamed)') : (curated.length ? `no opening at this index (0–${curated.length - 1})` : 'no curated openings');
        const fenVal = LT.validateFen(form.fen);
        fenStatus.textContent = fenVal.msg;
        fenStatus.className = `fen-status ${fenVal.ok ? 'grey' : 'error'}`;
        const row = selectedRow();
        movetimeRow.hidden = !(row && row.kind === 'stockfish');
        if (document.activeElement !== movetime) movetime.value = form.movetime;
        const baseOk = Number(form.base) >= 0.1 && Number(form.base) <= 3600;
        const incOk = Number(form.inc) >= 0 && Number(form.inc) <= 60;
        const invalid = !row || (form.start === 2 && !fenVal.ok) || (form.start === 1 && !opening) || !baseOk || !incOk;
        start.disabled = invalid;
      }
      base.addEventListener('input', () => { form.base = base.value; form.tc = 99; render(); });
      inc.addEventListener('input', () => { form.inc = inc.value; form.tc = 99; render(); });
      indexInput.addEventListener('input', () => { form.index = indexInput.value; render(); });
      fenInput.addEventListener('input', () => { form.fen = fenInput.value; render(); });
      movetime.addEventListener('input', () => { form.movetime = movetime.value; render(); });

      start.addEventListener('click', async () => {
        const row = selectedRow();
        if (!row) return;
        const colour = form.colour === 2 ? (Math.random() < 0.5 ? 'white' : 'black') : (form.colour === 1 ? 'black' : 'white');
        const body = { kind: 'play', engine: row.id, human: colour, base_ms: Math.round(Number(form.base) * 1000), increment_ms: Math.round(Number(form.inc) * 1000) };
        if (form.start === 1) { const opening = openingAt(); body.fen = opening.fen; body.opening = opening.name || `curated ${form.index}`; }
        else if (form.start === 2) body.fen = form.fen.trim();
        const ms = Math.round(Number(form.movetime));
        if (row.kind === 'stockfish' && form.movetime.trim() && ms > 0) body.stockfish_movetime_ms = ms;
        LT.storage.set(FORM_KEY, { engine: form.engine, colour: form.colour, tc: form.tc, base: form.base, inc: form.inc, movetime: form.movetime });
        start.disabled = true;
        notice.hidden = true;
        try {
          const game = await LT.api.post('/api/games', body);
          LT.storage.session('letal.play', game.id);
          location.hash = `#/play?game=${encodeURIComponent(game.id)}`;
        } catch (error) {
          notice.textContent = error.message;
          notice.hidden = false;
          start.disabled = false;
        }
      });
      render();
      return () => {};
    },
  });
})();
