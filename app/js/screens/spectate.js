/* Mikhail LeTal web app — Spectate, README §3: engine against engine, played by the server. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el, fmt } = LT;
  const GAME_KEY = 'letal.spectate';
  const SPEC_KEY = 'letal.spectate.spec';
  const FORM_KEY = 'letal.spectate.form';
  const GROUP_TITLES = { letal: 'Mikhail LeTal', version: 'Versions', baseline: 'Baselines', stockfish: 'Stockfish' };

  function thinkRow(seat) {
    const records = (seat && seat.log) || [];
    const record = records.length ? records[records.length - 1] : null;
    if (!record) return seat && seat.kind === 'engine' && !seat.init_ok && seat.init_failure ? [`failed: ${seat.init_failure}`] : ['no moves yet'];
    if (!record.raw || !record.raw.length) return ['no log'];
    const known = record.known || {};
    return [
      known.depth ? `d ${known.depth}` : null,
      known.nodes != null ? `${fmt.count(known.nodes)} nodes` : null,
      known.nps != null ? fmt.rate(known.nps) : null,
      fmt.seconds(known.time_ms != null ? known.time_ms : record.spent_ms),
    ].filter(Boolean);
  }

  function seatSelect(info, label, value) {
    const select = el('select', { class: 'input', 'aria-label': label });
    const rows = LT.engineRows(info);
    let group = null;
    let kind = null;
    for (const row of rows) {
      if (row.kind !== kind) { kind = row.kind; group = el('optgroup', { label: GROUP_TITLES[kind] || kind }); select.append(group); }
      group.append(el('option', { value: row.id, text: row.kind === 'letal' ? `${row.label} · ${row.meta}` : row.label, dataset: { kind: row.kind } }));
    }
    if (value && rows.some((row) => row.id === value)) select.value = value;
    return select;
  }

  LT.screens.register('spectate', {
    label: 'Spectate',
    async mount(root, params) {
      const [info, openings] = await Promise.all([LT.api.cached('/api/info', true), LT.api.cached('/api/openings')]);
      const gameId = params.get('game') || LT.storage.session(GAME_KEY);
      let state = null;
      if (gameId) { try { state = await LT.api.get(`/api/games/${encodeURIComponent(gameId)}`); } catch (error) { state = null; } }
      if (state && state.kind !== 'spectate') state = null;
      if (state) LT.storage.session(GAME_KEY, state.id); else LT.storage.session(GAME_KEY, null);

      // -- setup form -------------------------------------------------------------------------------
      const saved = LT.storage.get(FORM_KEY, {}) || {};
      const tcs = (info.time_controls || []).map((tc) => [tc.base_ms / 1000, tc.increment_ms / 1000]);
      const form = { tc: Number.isInteger(saved.tc) ? saved.tc : 0, base: saved.base || '120', inc: saved.inc || '0.5', start: saved.start || 'standard', index: saved.index || '0', harness: saved.harness || '0', plyCap: saved.plyCap || String(info.ply_cap || 600), movetime: saved.movetime || '' };
      if (form.tc < tcs.length) { form.base = String(tcs[form.tc][0]); form.inc = String(tcs[form.tc][1]); }
      const rows = LT.engineRows(info);
      const white = seatSelect(info, 'White seat', saved.white || (rows[0] && rows[0].id));
      const black = seatSelect(info, 'Black seat', saved.black || (rows.find((r) => r.kind === 'baseline') || rows[1] || rows[0] || {}).id);
      const tcRow = el('div', { class: 'seg-row' });
      const base = el('input', { class: 'input num', inputmode: 'decimal', 'aria-label': 'Base seconds' });
      const inc = el('input', { class: 'input num', inputmode: 'decimal', 'aria-label': 'Increment seconds' });
      const startSelect = el('select', { class: 'input', 'aria-label': 'Starting position' },
        el('option', { value: 'standard', text: 'Standard' }),
        el('option', { value: 'curated', text: 'Curated opening by index' }),
        el('option', { value: 'harness', text: 'Harness opening' }));
      const indexInput = el('input', { class: 'input idx', inputmode: 'numeric', 'aria-label': 'Opening index' });
      const indexName = el('span', { class: 'grey t13' });
      const harnessSelect = el('select', { class: 'input', 'aria-label': 'Harness opening' }, (openings.harness || []).map((o, i) => el('option', { value: String(i), text: o.name })));
      const plyCap = el('input', { class: 'input num', inputmode: 'numeric', 'aria-label': 'Ply cap' });
      const movetime = el('input', { class: 'input num', inputmode: 'numeric', placeholder: 'clock', 'aria-label': 'Stockfish move time in milliseconds' });
      const movetimeRow = el('label', { hidden: true }, 'Stockfish move time', movetime, 'ms');
      const startButton = el('button', { type: 'button', class: 'primary', text: state ? 'Start another' : 'Start' });
      const notice = el('div', { class: 'notice', hidden: true });
      const summaryText = el('span');
      const setup = el('details', { class: 'spec-setup', open: !state },
        el('summary', {}, summaryText, el('span', { class: 'quiet', text: 'Setup' })),
        el('div', { class: 'spec-form' },
          el('div', { class: 'two' }, el('div', {}, el('div', { class: 'label', text: 'White' }), white), el('div', {}, el('div', { class: 'label', text: 'Black' }), black)),
          el('div', {}, el('div', { class: 'label', text: 'Time control' }), tcRow,
            el('div', { class: 'field-row', style: { marginTop: '10px' } }, el('label', {}, 'base', base, 's'), el('label', {}, 'increment', inc, 's'), el('label', {}, 'ply cap', plyCap), movetimeRow)),
          el('div', {}, el('div', { class: 'label', text: 'Starting position' }),
            el('div', { class: 'field-row' }, startSelect, indexInput, indexName, harnessSelect)),
          el('div', { style: { display: 'flex', gap: '20px', alignItems: 'center' } }, startButton, notice)));
      const isStockfish = (select) => select.selectedOptions[0] && select.selectedOptions[0].dataset.kind === 'stockfish';
      const openingAt = () => { const i = parseInt(form.index, 10); const list = openings.openings || []; return Number.isInteger(i) && i >= 0 && i < list.length ? list[i] : null; };
      function renderForm() {
        LT.clear(tcRow);
        tcs.forEach(([b, i], index) => tcRow.append(el('button', { type: 'button', class: 'seg tc', 'aria-pressed': String(form.tc === index), text: `${b} + ${i}`, onClick: () => { form.tc = index; form.base = String(b); form.inc = String(i); renderForm(); } })));
        if (document.activeElement !== base) base.value = form.base;
        if (document.activeElement !== inc) inc.value = form.inc;
        if (document.activeElement !== plyCap) plyCap.value = form.plyCap;
        if (document.activeElement !== movetime) movetime.value = form.movetime;
        startSelect.value = form.start;
        indexInput.hidden = form.start !== 'curated';
        indexName.hidden = form.start !== 'curated';
        harnessSelect.hidden = form.start !== 'harness';
        if (document.activeElement !== indexInput) indexInput.value = form.index;
        harnessSelect.value = form.harness;
        const opening = openingAt();
        indexName.textContent = opening ? (opening.name || '(unnamed)') : 'no opening at this index';
        movetimeRow.hidden = !(isStockfish(white) || isStockfish(black));
        startButton.disabled = !rows.length || (form.start === 'curated' && !opening) || !(Number(form.base) >= 0.1) || !(Number(form.inc) >= 0);
        summaryText.textContent = state ? `${state.white.label} vs ${state.black.label}` : 'No game is running';
      }
      base.addEventListener('input', () => { form.base = base.value; form.tc = 99; renderForm(); });
      inc.addEventListener('input', () => { form.inc = inc.value; form.tc = 99; renderForm(); });
      plyCap.addEventListener('input', () => { form.plyCap = plyCap.value; });
      movetime.addEventListener('input', () => { form.movetime = movetime.value; });
      indexInput.addEventListener('input', () => { form.index = indexInput.value; renderForm(); });
      startSelect.addEventListener('change', () => { form.start = startSelect.value; renderForm(); });
      harnessSelect.addEventListener('change', () => { form.harness = harnessSelect.value; });
      white.addEventListener('change', renderForm);
      black.addEventListener('change', renderForm);

      function buildSpec() {
        const body = { kind: 'spectate', white: white.value, black: black.value, base_ms: Math.round(Number(form.base) * 1000), increment_ms: Math.round(Number(form.inc) * 1000) };
        const cap = parseInt(form.plyCap, 10);
        if (Number.isInteger(cap) && cap > 0) body.ply_cap = Math.min(cap, info.ply_cap || cap);
        if (form.start === 'curated') { const opening = openingAt(); body.fen = opening.fen; body.opening = opening.name || `curated ${form.index}`; }
        else if (form.start === 'harness') { const opening = (openings.harness || [])[Number(form.harness)] || null; if (opening) { body.fen = opening.fen; body.opening = opening.name; } }
        const ms = Math.round(Number(form.movetime));
        if ((isStockfish(white) || isStockfish(black)) && form.movetime.trim() && ms > 0) body.stockfish_movetime_ms = ms;
        return body;
      }
      async function startGame(body) {
        startButton.disabled = true;
        notice.hidden = true;
        try {
          if (state && state.status !== 'finished') { try { await LT.api.post(`/api/games/${state.id}/stop`); } catch (error) { /* already over */ } }
          const game = await LT.api.post('/api/games', body);
          LT.storage.session(GAME_KEY, game.id);
          LT.storage.session(SPEC_KEY, body);
          location.hash = `#/spectate?game=${encodeURIComponent(game.id)}`;
        } catch (error) {
          notice.textContent = error.message;
          notice.hidden = false;
          startButton.disabled = false;
        }
      }
      startButton.addEventListener('click', () => {
        LT.storage.set(FORM_KEY, { white: white.value, black: black.value, tc: form.tc, base: form.base, inc: form.inc, start: form.start, index: form.index, harness: form.harness, plyCap: form.plyCap, movetime: form.movetime });
        startGame(buildSpec());
      });
      renderForm();

      const page = el('div', { class: 'spectate' }, setup);
      root.append(page);
      if (!state) {
        page.append(el('div', { class: 'grey t12', text: 'Pick two seats and press Start; the server plays the game and the browser watches.' }));
        return () => {};
      }

      // -- the game ---------------------------------------------------------------------------------
      const statusLeft = el('span');
      const statusRight = el('span', { text: `${fmt.tc(state.time_control.base_ms, state.time_control.increment_ms)} · one core each` });
      const agentNodes = {};
      const agentBlock = (colour, position) => {
        const name = el('span', { class: 'agent-name' });
        const clock = el('span', { class: 'agent-clock' });
        const think = el('div', { class: 'agent-think' });
        const node = el('div', { class: `agent ${position}` }, el('div', { class: 'agent-head' }, name, clock), think);
        agentNodes[colour] = { node, name, clock, think };
        return node;
      };
      const boardEl = el('div');
      const moves = el('div', { class: 'movelist' });
      const toggle = el('button', { type: 'button', class: 'quiet', text: 'Stop' });
      const restart = el('button', { type: 'button', class: 'quiet', text: 'Restart' });
      const analyse = el('a', { class: 'quiet', href: `#/analysis?game=${encodeURIComponent(state.id)}`, text: 'Analyse', hidden: true });
      const actionNotice = el('div', { class: 'notice', hidden: true });
      page.append(
        el('div', { class: 'spec-status' }, statusLeft, statusRight),
        agentBlock('black', 'top'), boardEl, agentBlock('white', 'bottom'), moves,
        el('div', { class: 'spec-actions' }, toggle, restart, analyse), actionNotice);
      const board = new LT.Board(boardEl, { interactive: false });
      let signature = '';
      let busy = false;
      let poll = null;

      function elapsedMs() {
        let total = state.moves.reduce((sum, move) => sum + (Number(move.spent_ms) || 0), 0);
        if (state.thinking && state.thinking_since) total += Math.max(0, Date.now() - state.thinking_since);
        return total;
      }
      function render() {
        const finished = state.status === 'finished';
        board.setPosition(state.fen, { lastMove: state.moves.length ? state.moves[state.moves.length - 1].uci : null, check: state.check_square, targets: [], interactive: false });
        for (const colour of ['white', 'black']) {
          const seat = state[colour];
          const nodes = agentNodes[colour];
          nodes.name.textContent = seat.label;
          nodes.name.title = seat.path || '';
          LT.clear(nodes.think);
          for (const text of thinkRow(seat)) nodes.think.append(el('span', { text }));
          nodes.node.classList.toggle('off', finished || state.turn !== colour);
        }
        LT.moveList(moves, state.moves.map((move) => ({ san: move.san, clock: fmt.clock(move.clock_ms) })), { latestBold: true, maxHeight: 220, startFen: state.start_fen });
        toggle.hidden = finished;
        toggle.textContent = state.paused ? 'Resume' : 'Stop';
        toggle.disabled = busy || state.status === 'starting';
        restart.disabled = busy;
        analyse.hidden = !(finished && state.moves.length && LT.info && LT.info.analysis && LT.info.analysis.available);
        summaryText.textContent = `${state.white.label} vs ${state.black.label}`;
        startButton.textContent = 'Start another';
      }
      function tick() {
        const finished = state.status === 'finished';
        for (const colour of ['white', 'black']) {
          let ms = state.clocks[colour];
          if (state.status === 'running' && state.turn === colour && state.thinking && state.thinking_since) ms -= Math.max(0, Date.now() - state.thinking_since);
          agentNodes[colour].clock.textContent = fmt.clock(Math.max(0, ms));
        }
        const number = Math.floor(state.ply / 2) + 1;
        let middle = `${state.turn} to move`;
        if (finished) middle = `${LT.score(state.result)} · ${LT.reason(state)}`;
        else if (state.status === 'starting') middle = 'starting the engines';
        const suffix = finished ? ' · stopped' : state.paused ? ' · paused' : '';
        statusLeft.textContent = `move ${number} · ${middle} · ${fmt.clock(elapsedMs())} elapsed${suffix}`;
      }
      function apply(next) {
        state = next;
        const sig = [state.status, state.ply, state.thinking, state.paused, state.result, state.termination, state.white.log.length, state.black.log.length, busy].join('|');
        if (sig !== signature) { signature = sig; render(); }
        tick();
      }
      async function action(name) {
        if (busy) return;
        busy = true;
        render();
        try { apply(await LT.api.post(`/api/games/${state.id}/${name}`)); actionNotice.hidden = true; } catch (error) { actionNotice.textContent = error.message; actionNotice.hidden = false; }
        busy = false;
        signature = '';
        apply(state);
      }
      toggle.addEventListener('click', () => action(state.paused ? 'resume' : 'pause'));
      restart.addEventListener('click', () => {
        const spec = LT.storage.session(SPEC_KEY) || buildSpec();
        startGame(spec);
      });
      poll = LT.api.poll(async () => {
        if (busy) return true;
        try { apply(await LT.api.get(`/api/games/${state.id}`)); } catch (error) {
          if (error.status === 404) { statusLeft.textContent = 'This game is no longer on the server.'; return false; }
        }
        return state.status !== 'finished';
      }, 500);
      const ticker = setInterval(tick, 250);
      apply(state);
      return () => { clearInterval(ticker); if (poll) poll.cancel(); board.destroy(); };
    },
  });
})();
