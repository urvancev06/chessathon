/* Mikhail LeTal web app — Play: you against an engine seat, README §1. */
(() => {
  'use strict';
  const LT = window.LT;
  const { el, fmt } = LT;
  const GAME_KEY = 'letal.play';

  function sparkPoints(values) {
    if (values.length < 2) return '0,27 100,27';
    const max = Math.max(...values, 1e-9);
    return values.map((v, i) => `${((i / (values.length - 1)) * 100).toFixed(1)},${(27 - (v / max) * 26).toFixed(1)}`).join(' ');
  }
  function latestRecord(seat) {
    const records = (seat && seat.log) || [];
    return records.length ? records[records.length - 1] : null;
  }
  function numberOf(ply) { return `${Math.ceil(ply / 2)}${ply % 2 ? '.' : '…'}`; }

  LT.screens.register('play', {
    label: 'Play',
    async mount(root, params) {
      const gameId = params.get('game') || LT.storage.session(GAME_KEY);
      let state = null;
      if (gameId) {
        try { state = await LT.api.get(`/api/games/${encodeURIComponent(gameId)}`); } catch (error) { state = null; }
      }
      if (!state || state.kind !== 'play') {
        LT.storage.session(GAME_KEY, null);
        root.append(el('div', { class: 'empty-line' }, el('span', { text: gameId ? 'That game is no longer on the server.' : 'No game is running.' }), el('a', { class: 'quiet', href: '#/new', text: 'New game' })));
        return () => {};
      }
      LT.storage.session(GAME_KEY, state.id);
      const human = state.human || 'white';
      const engine = human === 'white' ? 'black' : 'white';

      // -- DOM ------------------------------------------------------------------------------------
      const statusText = el('span');
      const boardEl = el('div');
      const fenLine = el('div', { class: 'play-fen' });
      const flipButton = el('button', { type: 'button', class: 'quiet small', text: 'Flip board' });
      const banner = el('div', { class: 'banner', hidden: true });
      const clockNodes = {};
      const clockBlock = (colour) => {
        const who = colour === human ? 'you' : 'engine';
        const value = el('span', { class: 'clock' });
        const inc = el('span', { class: 'inc' });
        clockNodes[colour] = { value, inc };
        return el('div', {}, el('div', { class: 'label', text: `${colour === 'white' ? 'White' : 'Black'} · ${who}` }), el('div', { class: 'clock-line' }, value, inc));
      };
      const think = { title: el('span', { class: 'label' }), clock: el('span', { class: 'grey t12 tabular' }), depth: el('div', { class: 'val' }), nodes: el('div', { class: 'val' }), nps: el('div', { class: 'val' }), time: el('div', { class: 'val' }), soft: el('span', { class: 'soft' }), used: el('span', { class: 'used' }), tick: el('span', { class: 'tick' }), capUsed: el('span'), capSoft: el('span'), capHard: el('span') };
      const spark = (name) => { const last = el('span', { class: 'tabular' }); const line = LT.svg('polyline', { points: '0,27 100,27' }); const node = el('div', { class: 'spark' }, el('div', { class: 'spark-head' }, el('span', { text: name }), last), LT.svg('svg', { viewBox: '0 0 100 28', preserveAspectRatio: 'none' }, line)); return { node, last, line }; };
      const sparkTime = spark('time per move');
      const sparkNodes = spark('nodes per move');
      const plyCount = el('span', { class: 'tabular' });
      const moves = el('div', { class: 'movelist' });
      const takeback = el('button', { type: 'button', class: 'quiet', text: 'Takeback' });
      const resign = el('button', { type: 'button', class: 'quiet', text: 'Resign' });
      const newGame = el('a', { class: 'quiet', href: '#/new', text: 'New game' });
      const pgn = el('a', { class: 'quiet', href: `/api/games/${state.id}/pgn`, download: '', text: 'Download PGN' });
      const copyPgn = LT.copyButton('Copy PGN', () => LT.api.text(`/api/games/${state.id}/pgn`));
      const copy = LT.copyButton('Copy FEN', () => state.fen);
      const analyse = el('a', { class: 'quiet', href: `#/analysis?game=${encodeURIComponent(state.id)}`, text: 'Analyse', hidden: true });
      const notice = el('div', { class: 'notice', hidden: true });

      root.append(el('div', { class: 'play' },
        el('div', { class: 'play-board' },
          el('div', { class: 'play-status' }, statusText, flipButton),
          boardEl,
          fenLine),
        el('div', { class: 'play-side' },
          banner,
          el('div', { class: 'clocks' }, clockBlock('white'), clockBlock('black')),
          el('div', { class: 'block' },
            el('div', { class: 'block-head' }, think.title, think.clock),
            el('div', { class: 'think-grid' },
              el('div', {}, el('div', { class: 'cap', text: 'depth' }), think.depth),
              el('div', {}, el('div', { class: 'cap', text: 'nodes' }), think.nodes),
              el('div', {}, el('div', { class: 'cap', text: 'nodes/s' }), think.nps),
              el('div', {}, el('div', { class: 'cap', text: 'time' }), think.time)),
            el('div', { class: 'budget' },
              el('div', { class: 'track' }, think.soft, think.used, think.tick),
              el('div', { class: 'caption' }, think.capUsed, think.capSoft, think.capHard))),
          el('div', { class: 'sparks' }, sparkTime.node, sparkNodes.node),
          el('div', { class: 'block' }, el('div', { class: 'block-head label' }, el('span', { text: 'Moves' }), plyCount), moves),
          el('div', { class: 'actions' }, takeback, resign, newGame, pgn, copyPgn, copy, analyse),
          notice)));

      // -- board and state ------------------------------------------------------------------------
      const board = new LT.Board(boardEl, { interactive: false, flipped: human === 'black' });
      let flippedByUser = false;
      flipButton.addEventListener('click', () => { flippedByUser = true; board.flip(); });
      let busy = false;
      let signature = '';
      let turnStartedAt = null;
      let turnPly = -1;
      let flagged = false;
      let poll = null;
      let pollMs = 500;

      const humanTurn = (s) => s.status === 'running' && !s.thinking && s.turn === human;

      function apply(next) {
        state = next;
        if (humanTurn(state) && turnPly !== state.ply) { turnStartedAt = Date.now(); turnPly = state.ply; }
        if (!humanTurn(state)) turnPly = -1;
        const seat = state[engine];
        const sig = [state.status, state.ply, state.thinking, state.result, state.termination, state.stopping, seat.log.length, state.moves.length, state.error, busy].join('|');
        if (sig !== signature) { signature = sig; render(); }
        tick();
        const wanted = state.status === 'finished' ? 0 : (state.thinking || state.status === 'starting' ? 500 : 2000);
        if (wanted !== pollMs) { pollMs = wanted; startPolling(); }
      }

      function startPolling() {
        if (poll) poll.cancel();
        poll = null;
        if (!pollMs) return;
        poll = LT.api.poll(async () => {
          if (busy) return true;
          let next;
          try { next = await LT.api.get(`/api/games/${state.id}`); } catch (error) {
            if (error.status === 404) { statusText.textContent = 'This game is no longer on the server.'; board.setPosition(state.fen, { interactive: false, targets: [] }); return false; }
            return true;
          }
          apply(next);
          return state.status !== 'finished';
        }, pollMs);
      }

      function render() {
        const finished = state.status === 'finished';
        const interactive = humanTurn(state) && !busy;
        board.setPosition(state.fen, {
          lastMove: state.moves.length ? state.moves[state.moves.length - 1].uci : null,
          check: state.check_square,
          targets: interactive ? state.legal_moves : [],
          interactive,
        });
        if (!flippedByUser) board.setFlipped(human === 'black');
        fenLine.textContent = state.fen;
        statusText.textContent = finished ? 'Game over' : state.status === 'starting' ? 'Starting the engine…' : state.thinking ? 'Engine is thinking' : `${state.turn === 'white' ? 'White' : 'Black'} to move`;

        // result banner
        LT.clear(banner);
        banner.hidden = !finished;
        if (finished) {
          banner.append(el('span', { class: 'score', text: LT.score(state.result) }), el('span', { class: 'grey', text: LT.reason(state) }));
          if (state.error) banner.append(el('span', { class: 'error t12', text: state.error }));
        }
        analyse.hidden = !(finished && state.moves.length && LT.info && LT.info.analysis && LT.info.analysis.available);

        // clocks
        for (const colour of ['white', 'black']) clockNodes[colour].inc.textContent = `+${state.time_control.increment_ms / 1000}`;

        // thinking strip
        const seat = state[engine];
        const record = latestRecord(seat);
        const known = (record && record.known) || {};
        const engineMoves = state.moves.filter((move) => move.by === engine);
        const lastEngineMove = engineMoves.length ? engineMoves[engineMoves.length - 1] : null;
        if (state.thinking) {
          think.title.textContent = 'Thinking…';
          for (const key of ['depth', 'nodes', 'nps', 'time']) think[key].textContent = '·';
        } else {
          think.title.textContent = lastEngineMove ? `Last move · ${numberOf(lastEngineMove.ply)} ${lastEngineMove.san}` : 'Engine · idle';
          think.depth.textContent = known.depth || '—';
          think.nodes.textContent = known.nodes != null ? fmt.count(known.nodes) : '—';
          think.nps.textContent = known.nps != null ? fmt.rate(known.nps) : '—';
          think.time.textContent = known.time_ms != null ? fmt.seconds(known.time_ms) : (record ? fmt.seconds(record.spent_ms) : '—');
        }
        const soft = Number(known.soft_ms);
        const hard = Number(known.hard_ms);
        const used = known.time_ms != null ? Number(known.time_ms) : (record ? Number(record.spent_ms) : NaN);
        const haveBudget = Number.isFinite(soft) && Number.isFinite(hard) && hard > 0 && !state.thinking;
        const softPct = haveBudget ? Math.min(100, (soft / hard) * 100) : 0;
        const usedPct = haveBudget && Number.isFinite(used) ? Math.min(100, (used / hard) * 100) : 0;
        think.soft.style.width = `${softPct.toFixed(1)}%`;
        think.used.style.width = `${usedPct.toFixed(1)}%`;
        think.tick.style.left = `${softPct.toFixed(1)}%`;
        think.tick.hidden = !haveBudget;
        think.capUsed.textContent = `${haveBudget && Number.isFinite(used) ? fmt.seconds(used) : '—'} used`;
        think.capSoft.textContent = `soft ${haveBudget ? fmt.seconds(soft) : '—'}`;
        think.capHard.textContent = `hard ${haveBudget ? fmt.seconds(hard) : '—'}`;

        // sparklines: the last 24 engine moves
        const records = (seat.log || []).slice(-24);
        const times = records.map((r) => Number(r.known && r.known.time_ms != null ? r.known.time_ms : r.spent_ms)).filter(Number.isFinite);
        const nodes = records.map((r) => Number(r.known && r.known.nodes)).filter(Number.isFinite);
        sparkTime.line.setAttribute('points', sparkPoints(times));
        sparkTime.last.textContent = times.length ? fmt.seconds(times[times.length - 1]) : '—';
        sparkNodes.line.setAttribute('points', sparkPoints(nodes));
        sparkNodes.last.textContent = nodes.length ? fmt.count(nodes[nodes.length - 1]) : '—';

        // moves
        plyCount.textContent = `${state.moves.length} plies`;
        LT.moveList(moves, state.moves.map((move) => ({ san: move.san, clock: fmt.clock(move.clock_ms) })), { latestBold: true, maxHeight: 260, marginTop: 8, startFen: state.start_fen });

        // buttons
        takeback.disabled = state.moves.length < 2 || finished || state.thinking || !humanTurn(state) || busy;
        resign.disabled = finished || busy;
      }

      function tick() {
        if (!state) return;
        const now = Date.now();
        for (const colour of ['white', 'black']) {
          let ms = state.clocks[colour];
          const onTurn = state.status === 'running' && state.turn === colour;
          if (onTurn && state.thinking && state.thinking_since) ms -= Math.max(0, now - state.thinking_since);
          else if (onTurn && !state.thinking && colour === human && turnStartedAt) ms -= now - turnStartedAt;
          ms = Math.max(0, ms);
          clockNodes[colour].value.textContent = fmt.clock(ms);
          clockNodes[colour].value.classList.toggle('off', !(onTurn || (state.status !== 'running' && state.turn === colour && state.status !== 'finished')));
          if (colour === human && onTurn && ms <= 0 && !flagged && !busy) flag();
        }
        const seat = state[engine];
        const record = latestRecord(seat);
        const engineClock = record && record.known && record.known.clock_ms != null ? Number(record.known.clock_ms) : state.clocks[engine];
        think.clock.textContent = `clock left ${fmt.clock(engineClock)}`;
      }

      async function flag() {
        flagged = true;
        try { apply(await LT.api.post(`/api/games/${state.id}/resign`, { reason: 'flag' })); } catch (error) { flagged = false; }
      }

      async function submitMove(uci) {
        if (busy || !humanTurn(state)) return;
        const spent = turnStartedAt ? Date.now() - turnStartedAt : 0;
        busy = true;
        board.setPosition(state.fen, { interactive: false, targets: [] });
        try {
          const next = await LT.api.post(`/api/games/${state.id}/move`, { uci, spent_ms: spent });
          turnStartedAt = null;
          turnPly = -1;
          busy = false;
          notice.hidden = true;
          signature = '';
          apply(next);
        } catch (error) {
          busy = false;
          notice.textContent = error.message;
          notice.hidden = false;
          signature = '';
          apply(state);
        }
      }
      async function action(name, body) {
        if (busy) return;
        busy = true;
        try {
          const next = await LT.api.post(`/api/games/${state.id}/${name}`, body);
          busy = false;
          notice.hidden = true;
          signature = '';
          apply(next);
        } catch (error) {
          busy = false;
          notice.textContent = error.message;
          notice.hidden = false;
          signature = '';
          apply(state);
        }
      }
      board.onMove(submitMove);
      takeback.addEventListener('click', () => action('takeback'));
      resign.addEventListener('click', () => action('resign'));

      const ticker = setInterval(tick, 250);
      apply(state);
      startPolling();
      return () => { clearInterval(ticker); if (poll) poll.cancel(); board.destroy(); };
    },
  });
})();
