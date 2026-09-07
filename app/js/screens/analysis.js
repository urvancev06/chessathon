/* Mikhail LeTal web app — Analysis: a finished game graded move by move by the local Stockfish.
   Not in the prototypes; drawn in the handoff's language (hairlines, 11px labels, quiet buttons). */
(() => {
  'use strict';
  const LT = window.LT;
  const { el, fmt } = LT;
  const ANNOTATION = { inaccuracy: '?!', mistake: '?', blunder: '??' };
  const JUDGEMENT = { best: 'best move', good: 'good move', inaccuracy: 'inaccuracy', mistake: 'mistake', blunder: 'blunder' };
  const CAP = 10; // pawns; the eval graph clips here, a mate sits on the cap
  const MATE_CP = 1000;
  const DEPTH = [8, 30];
  const LINES = [1, 5];

  function evalCp(ev, fen) {
    if (!ev) return 0;
    if (ev.mate != null) {
      if (ev.mate === 0) return fen && LT.sideToMove(fen) === 'white' ? -MATE_CP : MATE_CP;
      return ev.mate > 0 ? MATE_CP : -MATE_CP;
    }
    return Number(ev.cp) || 0;
  }
  const winPct = (cp) => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
  function evalText(ev) {
    if (!ev) return '';
    if (ev.mate != null) return ev.mate === 0 ? '#' : `${ev.mate < 0 ? '−' : ''}M${Math.abs(ev.mate)}`;
    const pawns = Math.round((Number(ev.cp) || 0) / 10) / 10;
    return `${pawns > 0 ? '+' : pawns < 0 ? '−' : ''}${Math.abs(pawns).toFixed(1)}`;
  }
  const evalAfter = (ply) => (/#$/.test(ply.san) ? { cp: null, mate: 0, pov: 'white' } : ply.eval_after);
  const graphValue = (ev, fen) => Math.max(-CAP, Math.min(CAP, evalCp(ev, fen) / 100));
  function ordinal(n) { const s = n % 10 === 1 && n % 100 !== 11 ? 'st' : n % 10 === 2 && n % 100 !== 12 ? 'nd' : n % 10 === 3 && n % 100 !== 13 ? 'rd' : 'th'; return `${n}${s}`; }
  function numberedLine(sans, moveNumber, mover) {
    const parts = [];
    let number = moveNumber;
    let white = mover === 'white';
    sans.forEach((san, index) => {
      if (white) parts.push(`${number}. ${san}`); else parts.push(index === 0 ? `${number}… ${san}` : san);
      if (!white) number += 1;
      white = !white;
    });
    return parts.join(' ');
  }
  function rankText(rank, multipv) {
    if (rank === 1) return "the engine's first choice";
    if (rank != null) return `the engine's ${ordinal(rank)} choice`;
    return multipv > 1 ? `not among the engine's top ${multipv}` : "not the engine's choice";
  }

  LT.screens.register('analysis', {
    label: 'Analysis',
    async mount(root, params) {
      const info = await LT.api.cached('/api/info');
      let engine;
      try { engine = await LT.api.get('/api/analysis/engine'); } catch (error) { engine = { available: false, reason: error.message }; }
      let sources = { games: [], files: [] };
      try { sources = await LT.api.get('/api/analysis/sources'); } catch (error) { /* shown as empty */ }

      // -- form -------------------------------------------------------------------------------------
      const finished = (sources.games || []).filter((game) => game.finished);
      const gameSelect = el('select', { class: 'input', 'aria-label': 'Game from this session', disabled: !finished.length },
        finished.length ? finished.map((game) => el('option', { value: game.id, text: game.label })) : el('option', { value: '', text: 'no finished games in this session' }));
      const fileSelect = el('select', { class: 'input', 'aria-label': 'Saved PGN file', disabled: !(sources.files || []).length },
        (sources.files || []).length ? sources.files.map((file) => el('option', { value: file.path, text: `${file.label}${file.date ? ` · ${file.date}` : ''} · ${file.path}` })) : el('option', { value: '', text: 'no PGN files under data/webapp_games or data/pgn' }));
      const pgnArea = el('textarea', { class: 'input', placeholder: '[Event "…"]\n\n1. e4 e5 2. Nf3 …', spellcheck: 'false', 'aria-label': 'PGN' });
      const kinds = [['game', 'This session', gameSelect], ['file', 'Saved PGN', fileSelect], ['pgn', 'Paste', pgnArea]];
      let kind = LT.storage.get('letal.analysisSource', finished.length ? 'game' : 'file');
      if (!kinds.some(([key]) => key === kind)) kind = 'game';
      const kindRow = el('div', { class: 'seg-row' });
      const sourceBox = el('div', { class: 'source' });
      const depth = el('input', { class: 'input num', inputmode: 'numeric', value: String(LT.storage.get('letal.analysisDepth', 18)), 'aria-label': 'Depth' });
      const lines = el('input', { class: 'input num', inputmode: 'numeric', value: String(LT.storage.get('letal.analysisLines', 3)), 'aria-label': 'Lines' });
      const analyse = el('button', { type: 'button', class: 'primary', text: 'Analyse', disabled: !engine.available });
      const progress = el('span', { class: 'an-progress', hidden: true });
      const cancel = el('button', { type: 'button', class: 'quiet', text: 'Cancel', hidden: true });
      const notice = el('div', { class: 'notice', hidden: true });
      const engineLine = el('span', { class: 'grey t12', text: engine.available ? `${engine.name} · every position searched once at the chosen depth` : (engine.reason || 'no analysis engine') });
      function renderKinds() {
        LT.clear(kindRow);
        for (const [key, label] of kinds) kindRow.append(el('button', { type: 'button', class: 'seg', 'aria-pressed': String(kind === key), text: label, disabled: !engine.available, onClick: () => { kind = key; LT.storage.set('letal.analysisSource', key); renderKinds(); } }));
        LT.clear(sourceBox);
        sourceBox.append(kinds.find(([key]) => key === kind)[2]);
      }
      renderKinds();
      for (const control of [gameSelect, fileSelect, pgnArea, depth, lines]) control.disabled = control.disabled || !engine.available;

      // -- jobs -------------------------------------------------------------------------------------
      const jobsBox = el('div', { hidden: true });
      const jobsList = el('div', { class: 'table an-jobs' });
      jobsBox.append(el('div', { class: 'label', text: 'Analyses on this server' }), jobsList);
      let currentJob = null;
      let poll = null;
      async function refreshJobs() {
        let payload;
        try { payload = await LT.api.get('/api/analysis/jobs'); } catch (error) { jobsBox.hidden = true; return; }
        const jobs = (payload.jobs || []).slice().reverse();
        jobsBox.hidden = !jobs.length;
        LT.clear(jobsList);
        for (const job of jobs) {
          const p = job.progress || { done: 0, total: 0 };
          const active = job.status === 'running' || job.status === 'queued';
          jobsList.append(
            el('span', { class: 'grey', text: job.status }),
            el('span', {}, el('a', { class: 'quiet', style: { padding: 0 }, href: `#/analysis?job=${encodeURIComponent(job.job_id)}`, text: job.label || job.job_id, onClick: (event) => { event.preventDefault(); openJob(job.job_id); } })),
            el('span', { class: 'grey tabular', text: active ? (p.total ? `${p.done} of ${p.total}` : 'waiting') : '' }),
            el('span', {}, active ? el('button', { type: 'button', class: 'quiet', style: { padding: 0 }, text: 'Cancel', onClick: () => cancelJob(job.job_id) }) : null));
        }
      }
      async function cancelJob(jobId) {
        try { await LT.api.del(`/api/analysis/${encodeURIComponent(jobId)}`); } catch (error) { notice.textContent = error.message; notice.hidden = false; }
        refreshJobs();
      }

      // -- result view ------------------------------------------------------------------------------
      const view = { result: null, index: 0, geometry: null, cursorLine: null, cursorDot: null, list: null };
      const boardEl = el('div');
      const evalWhite = el('div', { class: 'white' });
      const evalBar = el('div', { class: 'eval-bar', role: 'img', 'aria-label': 'Evaluation' }, evalWhite, el('div', { class: 'tick' }));
      const evalLine = el('div', { class: 'an-eval-line' });
      const navBox = el('div', { class: 'an-nav' });
      const detail = el('div', { class: 'an-detail' });
      const title = el('div', { class: 'grey t12' });
      const summary = el('div', { class: 'table tight summary' });
      const graphBox = el('div');
      const movesBox = el('div', { class: 'movelist' });
      const resultBox = el('div', { class: 'an-result', hidden: true },
        el('div', { class: 'an-board' }, el('div', { class: 'an-frame' }, evalBar, boardEl), evalLine, navBox, detail),
        el('div', { class: 'an-side' },
          el('div', {}, el('div', { class: 'label', style: { marginBottom: '8px' }, text: 'Summary' }), title, summary),
          el('div', { class: 'block' }, el('div', { class: 'label', text: 'Evaluation' }), graphBox),
          el('div', { class: 'block' }, el('div', { class: 'label', text: 'Moves' }), movesBox)));
      const board = new LT.Board(boardEl, { interactive: false });
      const plies = () => (view.result ? view.result.plies : []);
      function current() {
        const list = plies();
        const ply = view.index > 0 ? list[view.index - 1] : null;
        const fen = ply ? ply.fen_after : view.result.start_fen;
        const ev = ply ? evalAfter(ply) : (list.length ? list[0].eval_before : null);
        return { ply, fen, ev, next: view.index < list.length ? list[view.index] : null };
      }
      function goTo(index) {
        view.index = Math.max(0, Math.min(plies().length, index));
        const { ply, fen, ev, next } = current();
        board.setPosition(fen, { lastMove: ply ? ply.uci : null, check: ply ? LT.checkedKing(fen, ply.san) : null, targets: [], interactive: false });
        board.setArrows(next ? [{ from: next.best.uci.slice(0, 2), to: next.best.uci.slice(2, 4), brush: 'green' }] : []);
        const cp = evalCp(ev, fen);
        const share = ev && ev.mate != null ? (cp > 0 ? 100 : 0) : Math.max(2, Math.min(98, winPct(cp)));
        evalWhite.style.height = `${share.toFixed(1)}%`;
        evalBar.classList.toggle('flipped', board.flipped);
        const total = plies().length;
        LT.clear(evalLine);
        evalLine.append(el('span', { text: `eval ${evalText(ev) || '—'}` }), el('span', { text: view.index === 0 ? `start · ${total} plies` : `ply ${view.index} of ${total}` }));
        renderNav();
        renderDetail();
        if (view.list) view.list.update(view.index);
        if (view.geometry && view.cursorLine) {
          const cx = view.geometry.x(view.index).toFixed(1);
          view.cursorLine.setAttribute('x1', cx);
          view.cursorLine.setAttribute('x2', cx);
          view.cursorDot.setAttribute('cx', cx);
          view.cursorDot.setAttribute('cy', view.geometry.y(view.geometry.values[view.index]).toFixed(1));
        }
      }
      function renderNav() {
        LT.clear(navBox);
        const total = plies().length;
        const button = (label, target, help) => el('button', { type: 'button', class: 'quiet', title: help, 'aria-label': help, disabled: target === view.index, text: label, onClick: () => goTo(target) });
        navBox.append(button('|<', 0, 'First position (Home)'), button('<', Math.max(0, view.index - 1), 'Previous move (left arrow)'), button('>', Math.min(total, view.index + 1), 'Next move (right arrow)'), button('>|', total, 'Last position (End)'),
          el('button', { type: 'button', class: 'quiet', text: 'Flip board', onClick: () => { board.flip(); evalBar.classList.toggle('flipped', board.flipped); } }),
          view.result.pgn ? LT.copyButton('Copy PGN', () => view.result.pgn) : null);
      }
      function renderDetail() {
        LT.clear(detail);
        const { ply, ev, next } = current();
        const multipv = view.result.engine.multipv;
        if (!ply) {
          detail.append(el('div', { class: 'lead' }, el('span', { class: 'w500', text: 'Starting position' }), el('span', { class: 'grey', text: `evaluation ${evalText(ev) || '—'}` })));
          if (next) detail.append(el('div', { class: 'line' }, 'engine suggests ', el('span', { class: 'san', text: numberedLine(next.best.line_san || [next.best.san], next.move_number, next.mover) })));
          return;
        }
        detail.append(el('div', { class: 'lead' },
          el('span', { class: 'w500', text: `${ply.move_number}${ply.mover === 'white' ? '.' : '…'} ${ply.san}${ANNOTATION[ply.judgement] || ''}` }),
          el('span', { class: ply.judgement === 'blunder' || ply.judgement === 'mistake' ? 'error' : 'grey', text: JUDGEMENT[ply.judgement] || ply.judgement }),
          el('span', { class: 'grey', text: rankText(ply.rank, multipv) })));
        const facts = el('div', { class: 'facts' });
        const fact = (name, value) => facts.append(el('span', {}, `${name} `, el('b', { text: value })));
        fact('eval', `${evalText(ply.eval_before)} → ${evalText(evalAfter(ply))}`);
        fact(`win% for ${ply.mover}`, `${ply.win_before.toFixed(1)} → ${ply.win_after.toFixed(1)}`);
        fact('cp loss', String(ply.cp_loss));
        fact('accuracy', `${ply.accuracy.toFixed(0)}%`);
        if (ply.clock_after != null) fact('clock', fmt.clock(ply.clock_after * 1000));
        detail.append(facts);
        if (ply.rank !== 1) detail.append(el('div', { class: 'line' }, `best was ${ply.best.san} (${evalText(ply.best.eval)}): `, el('span', { class: 'san', text: numberedLine(ply.best.line_san || [ply.best.san], ply.move_number, ply.mover) })));
        else if (ply.best.line_san && ply.best.line_san.length > 1) detail.append(el('div', { class: 'line' }, 'engine line: ', el('span', { class: 'san', text: numberedLine(ply.best.line_san, ply.move_number, ply.mover) })));
        if (ply.top && ply.top.length > 1) detail.append(el('div', { class: 'line' }, `top ${ply.top.length}: ${ply.top.map((c) => `${c.san} ${evalText(c.eval)}`).join(' · ')}`));
      }
      function renderSummary() {
        const { headers, summary: sides, engine: used } = view.result;
        title.textContent = `${headers.White || 'White'} vs ${headers.Black || 'Black'} · ${headers.Result || '*'}${headers.Date ? ` · ${headers.Date}` : ''} · ${used.name}, depth ${used.depth}, ${used.multipv} line${used.multipv === 1 ? '' : 's'}`;
        LT.clear(summary);
        const ours = (name) => name && info && info.name && name.startsWith(info.name);
        summary.append(el('span', { class: 'th' }), el('span', { class: 'th r', text: sides.white.name + (ours(sides.white.name) ? ' · ours' : '') }), el('span', { class: 'th r', text: sides.black.name + (ours(sides.black.name) ? ' · ours' : '') }));
        const rows = [
          ['Moves', (s) => String(s.moves)],
          ['Best move', (s) => `${fmt.pct(s.best_move_pct)} (${s.best_moves})`],
          ['Top-3', (s) => (used.multipv >= 3 ? `${fmt.pct(s.top3_pct)} (${s.top3_moves})` : 'needs 3 lines')],
          ['ACPL', (s) => Number(s.acpl).toFixed(1)],
          ['Accuracy (mean)', (s) => fmt.pct(s.accuracy)],
          ['Inaccuracies', (s) => String(s.inaccuracies)],
          ['Mistakes', (s) => String(s.mistakes)],
          ['Blunders', (s) => String(s.blunders)],
        ];
        for (const [label, value] of rows) summary.append(el('span', { class: 'k', text: label }), el('span', { class: 'r', text: value(sides.white) }), el('span', { class: 'r', text: value(sides.black) }));
      }
      function renderGraph() {
        const list = plies();
        LT.clear(graphBox);
        if (!list.length) { graphBox.append(el('div', { class: 'grey t12', text: 'no moves' })); return; }
        const width = 400;
        const height = 120;
        const pad = { left: 22, right: 4, top: 6, bottom: 6 };
        const innerWidth = width - pad.left - pad.right;
        const innerHeight = height - pad.top - pad.bottom;
        const zeroY = pad.top + innerHeight / 2;
        const values = [graphValue(list[0].eval_before, list[0].fen_before)].concat(list.map((ply) => graphValue(evalAfter(ply), ply.fen_after)));
        const step = innerWidth / Math.max(1, values.length - 1);
        const x = (index) => pad.left + index * step;
        const y = (value) => zeroY - (value / CAP) * (innerHeight / 2);
        const points = values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`);
        const area = `M${x(0).toFixed(1)},${zeroY.toFixed(1)} L${points.join(' L')} L${x(values.length - 1).toFixed(1)},${zeroY.toFixed(1)} Z`;
        const graph = LT.svg('svg', { class: 'eval-graph', viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Evaluation over the game, White advantage upwards' },
          LT.svg('path', { class: 'area', d: area }),
          LT.svg('line', { class: 'axis', x1: pad.left, x2: width - pad.right, y1: zeroY.toFixed(1), y2: zeroY.toFixed(1) }),
          LT.svg('line', { class: 'axis', x1: pad.left, x2: pad.left, y1: pad.top, y2: height - pad.bottom }),
          LT.svg('text', { x: pad.left - 4, y: y(CAP) + 4, 'text-anchor': 'end' }, `+${CAP}`),
          LT.svg('text', { x: pad.left - 4, y: zeroY + 3, 'text-anchor': 'end' }, '0'),
          LT.svg('text', { x: pad.left - 4, y: y(-CAP) + 2, 'text-anchor': 'end' }, `−${CAP}`),
          LT.svg('polyline', { class: 'curve', points: points.join(' ') }));
        list.forEach((ply, index) => {
          if (ply.judgement === 'blunder' || ply.judgement === 'mistake') graph.append(LT.svg('circle', { class: `mark ${ply.judgement}`, cx: x(index + 1).toFixed(1), cy: y(values[index + 1]).toFixed(1), r: 2.4 }));
        });
        view.cursorLine = LT.svg('line', { class: 'cursor', y1: pad.top, y2: height - pad.bottom });
        view.cursorDot = LT.svg('circle', { class: 'cursor-dot', r: 2.5 });
        graph.append(view.cursorLine, view.cursorDot);
        values.forEach((value, index) => {
          const hit = LT.svg('rect', { class: 'hit', x: (x(index) - step / 2).toFixed(1), y: pad.top, width: step.toFixed(2), height: innerHeight },
            LT.svg('title', {}, index === 0 ? 'start' : `ply ${index}, ${list[index - 1].san}, ${evalText(evalAfter(list[index - 1]))}`));
          hit.addEventListener('click', () => goTo(index));
          graph.append(hit);
        });
        view.geometry = { x, y, values };
        graphBox.append(graph, el('div', { class: 'graph-caption' }, el('span', { text: `White advantage up, ±${CAP} pawns, mates on the cap` }), el('span', { text: 'click to jump' })));
      }
      function renderMoves() {
        const list = plies();
        const counts = { inaccuracy: 0, mistake: 0, blunder: 0 };
        for (const ply of list) if (counts[ply.judgement] != null) counts[ply.judgement] += 1;
        view.list = LT.moveList(movesBox, list.map((ply) => ({ san: ply.san, mark: ANNOTATION[ply.judgement] || null, best: ply.rank === 1, after: evalText(evalAfter(ply)), clock: '' })), { latestBold: false, maxHeight: 300, marginTop: 8, startFen: view.result.start_fen, onSelect: (index) => goTo(index), current: 0 });
        movesBox.parentElement.querySelectorAll('.legend-line').forEach((node) => node.remove());
        movesBox.parentElement.append(el('div', { class: 'grey t11 legend-line', style: { marginTop: '8px' }, text: `?! inaccuracy (${counts.inaccuracy}) · ? mistake (${counts.mistake}) · ?? blunder (${counts.blunder}) · ✓ engine's first choice · eval after the move` }));
      }
      function show(result) {
        view.result = result;
        resultBox.hidden = false;
        board.setFlipped(false);
        renderSummary();
        renderGraph();
        renderMoves();
        goTo(0);
      }
      const onKey = (event) => {
        if (!view.result || resultBox.hidden || event.target.matches('input, select, textarea')) return;
        if (event.key === 'ArrowLeft') goTo(view.index - 1);
        else if (event.key === 'ArrowRight') goTo(view.index + 1);
        else if (event.key === 'Home') goTo(0);
        else if (event.key === 'End') goTo(plies().length);
        else return;
        event.preventDefault();
      };
      document.addEventListener('keydown', onKey);

      // -- submitting and polling ---------------------------------------------------------------------
      const stopPolling = () => { if (poll) poll.cancel(); poll = null; };
      function showJob(job) {
        const p = job.progress || { done: 0, total: 0 };
        if (job.status === 'queued' || job.status === 'running') {
          progress.hidden = false;
          cancel.hidden = false;
          progress.textContent = job.status === 'queued' ? `${job.label || job.job_id} · queued` : `position ${p.done} of ${p.total || '?'}`;
          cancel.disabled = false;
          return false;
        }
        progress.hidden = true;
        cancel.hidden = true;
        if (job.status === 'done' && job.result) { show(job.result); }
        else if (job.status === 'failed') { notice.textContent = `analysis failed: ${job.error || 'unknown error'}`; notice.hidden = false; }
        else if (job.status === 'cancelled') { progress.hidden = false; progress.textContent = 'cancelled'; }
        return true;
      }
      function openJob(jobId) {
        stopPolling();
        currentJob = jobId;
        history.replaceState(null, '', `#/analysis?job=${encodeURIComponent(jobId)}`);
        let ticks = 0;
        poll = LT.api.poll(async () => {
          if (currentJob !== jobId) return false;
          let job;
          try { job = await LT.api.get(`/api/analysis/${encodeURIComponent(jobId)}`); } catch (error) { progress.hidden = true; cancel.hidden = true; notice.textContent = error.message; notice.hidden = false; return false; }
          const done = showJob(job);
          ticks += 1;
          if (done || ticks % 4 === 0) refreshJobs();
          return !done;
        }, 500);
      }
      cancel.addEventListener('click', () => { if (currentJob) { cancel.disabled = true; cancelJob(currentJob); } });
      const clampInt = (input, [low, high], fallback) => { const n = Math.round(Number(input.value)); return Number.isFinite(n) ? Math.max(low, Math.min(high, n)) : fallback; };
      async function submit(source) {
        notice.hidden = true;
        analyse.disabled = true;
        const body = { source, depth: clampInt(depth, DEPTH, 18), multipv: clampInt(lines, LINES, 3) };
        LT.storage.set('letal.analysisDepth', body.depth);
        LT.storage.set('letal.analysisLines', body.multipv);
        try { const created = await LT.api.post('/api/analysis', body); openJob(created.job_id); } catch (error) { notice.textContent = error.message; notice.hidden = false; }
        analyse.disabled = !engine.available;
      }
      analyse.addEventListener('click', () => {
        if (kind === 'game') { if (!gameSelect.value) { notice.textContent = 'no finished game to analyse; play or watch one first'; notice.hidden = false; return; } submit({ game_id: gameSelect.value }); }
        else if (kind === 'file') { if (!fileSelect.value) { notice.textContent = 'no PGN file to analyse'; notice.hidden = false; return; } submit({ file: fileSelect.value }); }
        else { const text = pgnArea.value.trim(); if (!text) { notice.textContent = 'paste a PGN first'; notice.hidden = false; return; } submit({ pgn: text }); }
      });

      root.append(el('div', { class: 'analysis' },
        el('div', { class: 'an-head' }, el('span', { class: 't20', text: 'Analysis' }), engineLine),
        el('div', { class: 'an-form' },
          el('div', {}, el('div', { class: 'label', text: 'Source' }), kindRow, sourceBox),
          el('div', { class: 'an-params' },
            el('div', {}, el('div', { class: 'label', text: `Depth · ${DEPTH[0]}–${DEPTH[1]}` }), depth),
            el('div', {}, el('div', { class: 'label', text: `Lines · ${LINES[0]}–${LINES[1]}` }), lines)),
          el('div', { class: 'an-footer' }, analyse, progress, cancel),
          notice),
        jobsBox,
        resultBox));
      refreshJobs();
      if (params.get('job')) openJob(params.get('job'));
      else if (params.get('game') && engine.available) { kind = 'game'; if ([...gameSelect.options].some((o) => o.value === params.get('game'))) gameSelect.value = params.get('game'); renderKinds(); submit({ game_id: params.get('game') }); }
      else if (params.get('game')) { notice.textContent = `cannot analyse: ${engine.reason}`; notice.hidden = false; }
      return () => { stopPolling(); document.removeEventListener('keydown', onKey); board.destroy(); };
    },
  });
})();
