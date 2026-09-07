/* Mikhail LeTal web app. Vanilla JS, no build step, nothing loaded from the network. */
(() => {
  'use strict';

  // ------------------------------------------------------------------------------------------
  // Small utilities

  const $ = (selector, root = document) => root.querySelector(selector);

  /** DOM builder: h('div', {class: 'x', onClick: fn}, child, ...). */
  function h(tag, props, ...children) {
    const node = document.createElement(tag);
    if (props) {
      for (const [key, value] of Object.entries(props)) {
        if (value == null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'dataset') Object.assign(node.dataset, value);
        else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
        else if (key.startsWith('on') && typeof value === 'function') {
          node.addEventListener(key.slice(2).toLowerCase(), value);
        } else if (value === true) node.setAttribute(key, '');
        else node.setAttribute(key, String(value));
      }
    }
    append(node, children);
    return node;
  }

  function append(node, children) {
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }

  const SVG_NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value != null) node.setAttribute(key, String(value));
    }
    append(node, children);
    return node;
  }

  function clear(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  const fmt = {
    int(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toLocaleString('en-GB') : String(value ?? '');
    },
    ms(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return String(value ?? '');
      return `${fmt.int(Math.round(number))} ms`;
    },
    seconds(ms) {
      const number = Number(ms);
      if (!Number.isFinite(number)) return '';
      return number >= 10000 ? `${(number / 1000).toFixed(1)} s` : `${Math.round(number)} ms`;
    },
    clock(ms) {
      let value = Math.max(0, Number(ms) || 0);
      const hours = Math.floor(value / 3600000);
      value -= hours * 3600000;
      const minutes = Math.floor(value / 60000);
      value -= minutes * 60000;
      const seconds = value / 1000;
      if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, '0')}:${String(Math.floor(seconds)).padStart(2, '0')}`;
      }
      // Tenths are floored, not rounded, so 9.96 s reads 0:09.9 rather than 0:10.0.
      const tenths = Math.floor(seconds * 10) / 10;
      if (minutes === 0 && tenths < 10) {
        return `0:${tenths.toFixed(1).padStart(4, '0')}`;
      }
      return `${minutes}:${String(Math.floor(seconds)).padStart(2, '0')}`;
    },
    tc(base, inc) {
      return `${base / 1000}+${inc / 1000}`;
    },
    date(ms) {
      try {
        return new Date(ms).toLocaleString('en-GB');
      } catch (error) {
        return '';
      }
    },
  };

  let toastTimer = null;
  function toast(message, isError = false) {
    const node = $('#toast');
    node.textContent = message;
    node.className = `show${isError ? ' error' : ''}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.className = ''; }, isError ? 5000 : 2600);
  }

  const storage = {
    get(key, fallback = null) {
      try {
        const raw = localStorage.getItem(key);
        return raw == null ? fallback : JSON.parse(raw);
      } catch (error) {
        return fallback;
      }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* private mode */ }
    },
    session(key, value) {
      try {
        if (value === undefined) {
          const raw = sessionStorage.getItem(key);
          return raw == null ? null : JSON.parse(raw);
        }
        if (value === null) sessionStorage.removeItem(key);
        else sessionStorage.setItem(key, JSON.stringify(value));
        return value;
      } catch (error) {
        return null;
      }
    },
  };

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (error) {
      const area = h('textarea', { style: { position: 'fixed', left: '-9999px' } });
      area.value = text;
      document.body.append(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (error2) { ok = false; }
      area.remove();
      return ok;
    }
  }

  // ------------------------------------------------------------------------------------------
  // API

  const api = {
    async request(method, path, body) {
      const options = { method, headers: {} };
      if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
      }
      let response;
      try {
        response = await fetch(path, options);
      } catch (error) {
        throw new Error('the server is not reachable; is it still running?');
      }
      const text = await response.text();
      let payload = null;
      try { payload = text ? JSON.parse(text) : null; } catch (error) { payload = { raw: text }; }
      if (!response.ok) {
        const message = payload && payload.error ? payload.error : `${response.status} ${response.statusText}`;
        const failure = new Error(message);
        failure.status = response.status;
        throw failure;
      }
      return payload;
    },
    get(path) { return api.request('GET', path); },
    post(path, body) { return api.request('POST', path, body || {}); },
    del(path) { return api.request('DELETE', path); },
  };

  const cache = { info: null, openings: null, analysisEngine: null };
  async function loadInfo(force = false) {
    if (!cache.info || force) cache.info = await api.get('/api/info');
    return cache.info;
  }
  /**
   * The analysis engine's status. Never throws: a server built before the analysis API answers
   * 404, an unreachable one throws, and both become "unavailable" with a reason the UI can show.
   */
  async function loadAnalysisEngine(force = false) {
    if (cache.analysisEngine && !force) return cache.analysisEngine;
    try {
      cache.analysisEngine = await api.get('/api/analysis/engine');
    } catch (error) {
      cache.analysisEngine = {
        available: false, path: null, name: null,
        reason: error.status === 404 ? 'this server has no analysis API; restart it from the current code' : error.message,
      };
    }
    return cache.analysisEngine;
  }
  async function loadOpenings(force = false) {
    if (!cache.openings || force) cache.openings = await api.get('/api/openings');
    return cache.openings;
  }

  // ------------------------------------------------------------------------------------------
  // Chess helpers (display only; the server is the rules authority)

  const PIECE_NAME = { k: 'king', q: 'queen', r: 'rook', b: 'bishop', n: 'knight', p: 'pawn' };
  const FILES = 'abcdefgh';
  const START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';

  /** 64 entries indexed a1=0 .. h8=63 with {color: 'w'|'b', type: 'p'..'k'} or null. */
  function parseFen(fen) {
    const squares = new Array(64).fill(null);
    const placement = String(fen || '').split(/\s+/)[0] || '';
    const ranks = placement.split('/');
    for (let rankIndex = 0; rankIndex < Math.min(8, ranks.length); rankIndex++) {
      const rank = 7 - rankIndex;
      let file = 0;
      for (const char of ranks[rankIndex]) {
        if (/[1-8]/.test(char)) { file += Number(char); continue; }
        const type = char.toLowerCase();
        if (!PIECE_NAME[type] || file > 7) continue;
        squares[rank * 8 + file] = { color: char === type ? 'b' : 'w', type };
        file += 1;
      }
    }
    return squares;
  }

  function squareName(index) { return FILES[index % 8] + (Math.floor(index / 8) + 1); }
  function squareIndex(name) { return FILES.indexOf(name[0]) + (Number(name[1]) - 1) * 8; }
  function sideToMove(fen) { return (String(fen).split(/\s+/)[1] || 'w') === 'b' ? 'black' : 'white'; }

  /** The king square of the side to move when `san` ends in + or #, else null (no rules engine here). */
  function checkedKing(fen, san) {
    if (!san || !/[+#]$/.test(san)) return null;
    const colour = sideToMove(fen) === 'white' ? 'w' : 'b';
    const index = parseFen(fen).findIndex((piece) => piece && piece.type === 'k' && piece.color === colour);
    return index >= 0 ? squareName(index) : null;
  }

  /** A piece as an element; the image comes from CSS (.piece.white.knight -> cburnett/wN.svg). */
  function pieceNode(piece, extraClass = '') {
    return h('span', {
      class: `piece ${piece.color === 'w' ? 'white' : 'black'} ${PIECE_NAME[piece.type]} ${extraClass}`.trim(),
      'aria-hidden': 'true',
    });
  }

  function miniBoard(fen) {
    const squares = parseFen(fen);
    const node = h('div', { class: 'mini', role: 'img', 'aria-label': `Position ${fen}` });
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const index = (7 - row) * 8 + col;
        const piece = squares[index];
        const dark = (row + col) % 2 === 1;
        node.append(h('span', { class: dark ? 'dark' : '' }, piece ? pieceNode(piece) : null));
      }
    }
    return node;
  }

  // -- evaluations (always White's point of view on the wire) --------------------------------

  const MATE_CP = 1000; // a forced mate counts as +-1000 cp for win% and centipawn loss

  /**
   * Centipawns from White's point of view. A "mate 0" is a checkmate on the board and the wire
   * cannot say who delivered it, so the FEN's side to move (the mated side) settles the sign.
   */
  function evalCp(ev, fen) {
    if (!ev) return 0;
    if (ev.mate != null) {
      if (ev.mate === 0) return fen && sideToMove(fen) === 'white' ? -MATE_CP : MATE_CP;
      return ev.mate > 0 ? MATE_CP : -MATE_CP;
    }
    return Number(ev.cp) || 0;
  }

  /** lichess's win% for a centipawn score: 50 + 50 * (2 / (1 + exp(-0.00368208 cp)) - 1). */
  function winPct(cp) { return 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1); }

  /** "+0.4", "-1.3", "0.0", "M3" (White mates in 3), "-M3" (Black mates), "#" (mate on the board). */
  function evalText(ev, fen) {
    if (!ev) return '';
    if (ev.mate != null) {
      if (ev.mate === 0) return '#';
      return `${ev.mate < 0 ? '-' : ''}M${Math.abs(ev.mate)}`;
    }
    // Rounded to tenths before the sign is chosen, so -3 cp reads "0.0", not "-0.0".
    const pawns = Math.round((Number(ev.cp) || 0) / 10) / 10;
    const sign = pawns > 0 ? '+' : pawns < 0 ? '-' : '';
    return `${sign}${Math.abs(pawns).toFixed(1)}`;
  }

  /** The same, from the mover's point of view, for prose ("the engine saw +0.4 for you"). */
  function evalTextFor(ev, mover, fen) {
    if (!ev) return '';
    if (mover === 'white') return evalText(ev, fen);
    if (ev.mate != null) {
      if (ev.mate === 0) return '#';
      return `${ev.mate > 0 ? '-' : ''}M${Math.abs(ev.mate)}`;
    }
    return evalText({ cp: -(Number(ev.cp) || 0), mate: null }, fen);
  }

  // ------------------------------------------------------------------------------------------
  // Board component (the lichess look: brown board, cburnett pieces, lichess highlights)

  // lichess brushes, used for the arrow overlay.
  const BRUSHES = {
    green: '#15781B',
    red: '#882020',
    blue: '#003088',
    yellow: '#e68f00',
  };
  const PROMOTION_ORDER = ['q', 'n', 'r', 'b']; // lichess's order in the promotion strip

  class Board {
    /**
     * options.onMove(uci): the user completed a move (click-click, drag, or keyboard)
     * options.evalBar: show the vertical eval bar to the left of the board
     */
    constructor({ onMove, evalBar = false } = {}) {
      this.onMove = onMove || null;
      this.flipped = false;
      this.position = { fen: START_FEN, lastMove: null, check: null, legal: [], interactive: false };
      this.selected = null;
      this.legalMap = new Map();
      this.drag = null;
      this.suppressClick = false;
      this.promo = null;
      this.pending = null; // a move dropped but not yet confirmed by the server: shown in place
      this.arrows = [];
      this.eval = null;
      this.evalFen = null;
      this.uid = `b${Math.random().toString(36).slice(2, 8)}`;

      this.grid = h('div', { class: 'board', role: 'grid', 'aria-label': 'Chess board' });
      this.cells = [];
      for (let i = 0; i < 64; i++) {
        const cell = h('button', { class: 'sq', type: 'button', role: 'gridcell', tabindex: i === 0 ? '0' : '-1' });
        cell.addEventListener('click', () => this.onCellClick(cell));
        cell.addEventListener('pointerdown', (event) => this.onPointerDown(cell, event));
        cell.addEventListener('focus', () => this.onCellFocus(cell));
        this.cells.push(cell);
        this.grid.append(cell);
      }
      this.grid.addEventListener('pointermove', (event) => this.onPointerMove(event));
      this.grid.addEventListener('pointerup', (event) => this.onPointerUp(event));
      this.grid.addEventListener('pointercancel', () => this.cancelDrag());
      this.grid.addEventListener('keydown', (event) => this.onGridKey(event));
      this.arrowLayer = svg('svg', { class: 'board-arrows', viewBox: '0 0 8 8', 'aria-hidden': 'true' });
      this.wrap = h('div', { class: 'board-wrap' }, this.grid, this.arrowLayer);
      this.evalBar = evalBar ? this.buildEvalBar() : null;
      this.el = h('div', { class: `board-frame${evalBar ? ' with-eval' : ''}` }, this.evalBar ? this.evalBar.el : null, this.wrap);
      this.layout();
    }

    // -- geometry -------------------------------------------------------------------------

    /** Which square a visual cell (row 0 = top, col 0 = left) shows in the current orientation. */
    squareAt(row, col) {
      return this.flipped ? row * 8 + (7 - col) : (7 - row) * 8 + col;
    }

    /** Visual [row, col] of a square in the current orientation. */
    cellPos(square) {
      const rank = Math.floor(square / 8);
      const file = square % 8;
      return this.flipped ? [rank, 7 - file] : [7 - rank, file];
    }

    cellFor(square) {
      const [row, col] = this.cellPos(square);
      return this.cells[row * 8 + col];
    }

    layout() {
      for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
          const cell = this.cells[row * 8 + col];
          const square = this.squareAt(row, col);
          cell.dataset.square = squareName(square);
          cell.dataset.dark = (Math.floor(square / 8) + square) % 2 === 0 ? '1' : '';
        }
      }
      this.render();
      this.drawArrows();
      this.renderEval();
    }

    flip() {
      this.flipped = !this.flipped;
      this.layout();
    }

    setFlipped(flipped) {
      if (this.flipped !== flipped) { this.flipped = flipped; this.layout(); }
    }

    // -- state ----------------------------------------------------------------------------

    /** position: {fen, lastMove (uci), check (square name), legal ([uci]), interactive} */
    setPosition(position) {
      const previous = this.position;
      this.position = Object.assign({}, previous, position);
      const changed = previous.fen !== this.position.fen;
      if (changed || !this.position.interactive) this.selected = null;
      // The optimistic drop is shown until the server answers with a new position (accepted) or
      // hands the move back to us (rejected: interactive again on the same position).
      if (changed || this.position.interactive) this.pending = null;
      this.legalMap = new Map();
      for (const uci of this.position.legal || []) {
        const from = uci.slice(0, 2);
        const to = uci.slice(2, 4);
        const promo = uci.slice(4, 5) || null;
        if (!this.legalMap.has(from)) this.legalMap.set(from, []);
        this.legalMap.get(from).push({ to, promo, uci });
      }
      if (this.promo) this.closePromo();
      if (this.drag) this.cancelDrag(false);
      this.render();
    }

    /** arrows: [{from, to, brush}] in square names; brush is a key of BRUSHES. */
    setArrows(arrows) {
      this.arrows = (arrows || []).filter((arrow) => arrow && arrow.from && arrow.to && arrow.from !== arrow.to);
      this.drawArrows();
    }

    /** ev: EVAL from White's point of view, or null to show an even bar with no text. */
    setEval(ev, fen) {
      this.eval = ev || null;
      this.evalFen = fen || null;
      this.renderEval();
    }

    render() {
      const { fen, lastMove, check, interactive } = this.position;
      const squares = parseFen(fen);
      if (this.pending) this.applyPending(squares);
      const lastFrom = lastMove ? lastMove.slice(0, 2) : null;
      const lastTo = lastMove ? lastMove.slice(2, 4) : null;
      const dests = new Set(this.selected && this.legalMap.has(this.selected)
        ? this.legalMap.get(this.selected).map((entry) => entry.to) : []);
      const dragging = this.drag && this.drag.moved ? this.drag : null;
      for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
          const cell = this.cells[row * 8 + col];
          const square = this.squareAt(row, col);
          const name = squareName(square);
          const piece = squares[square];
          clear(cell);
          if (piece) cell.append(pieceNode(piece, dragging && dragging.from === name ? 'faded' : ''));
          // Coordinates the lichess way: files along the bottom row, ranks up the right column.
          if (col === 7) cell.append(h('span', { class: 'coord rank', text: String(Math.floor(square / 8) + 1) }));
          if (row === 7) cell.append(h('span', { class: 'coord file', text: FILES[square % 8] }));
          const movable = interactive && this.legalMap.has(name);
          const isDest = dests.has(name);
          cell.className = `sq${cell.dataset.dark ? ' dark' : ''}`
            + (lastFrom === name || lastTo === name ? ' last' : '')
            + (this.selected === name ? ' selected' : '')
            + (check === name ? ' check' : '')
            + (movable ? ' movable' : '')
            + (isDest ? ' dest' : '')
            + (isDest && piece ? ' occupied' : '')
            + (dragging && dragging.over === name && isDest ? ' over' : '');
          const description = piece
            ? `${piece.color === 'w' ? 'White' : 'Black'} ${PIECE_NAME[piece.type]} on ${name}`
            : `${name}, empty`;
          cell.setAttribute('aria-label', description + (isDest ? ', legal target' : '') + (this.selected === name ? ', selected' : ''));
          cell.setAttribute('aria-selected', this.selected === name ? 'true' : 'false');
        }
      }
    }

    /** Move the dropped piece in a parsed position so a drop lands at once, before the server answers. */
    applyPending(squares) {
      const from = squareIndex(this.pending.uci.slice(0, 2));
      const to = squareIndex(this.pending.uci.slice(2, 4));
      const piece = squares[from];
      if (!piece) return;
      const promo = this.pending.uci.slice(4, 5);
      const wasEmpty = !squares[to];
      squares[to] = promo ? { color: piece.color, type: promo } : piece;
      squares[from] = null;
      // Castling shows the rook too, en passant removes the captured pawn: both are cosmetic and
      // the server's position replaces this view within a round trip.
      if (piece.type === 'k' && Math.abs(to - from) === 2) {
        const rank = Math.floor(from / 8) * 8;
        const [rookFrom, rookTo] = to > from ? [rank + 7, rank + 5] : [rank, rank + 3];
        squares[rookTo] = squares[rookFrom];
        squares[rookFrom] = null;
      }
      // A pawn that changed file onto an empty square captured en passant.
      if (piece.type === 'p' && from % 8 !== to % 8 && wasEmpty) {
        squares[to + (piece.color === 'w' ? -8 : 8)] = null;
      }
    }

    // -- arrows ---------------------------------------------------------------------------

    /** Centre of a square in the 8x8 viewBox, orientation-aware. */
    centre(name) {
      const [row, col] = this.cellPos(squareIndex(name));
      return [col + 0.5, row + 0.5];
    }

    drawArrows() {
      const layer = this.arrowLayer;
      clear(layer);
      if (!this.arrows.length) return;
      // chessground's geometry: stroke 10/64 of a square, a triangular marker (markerUnits are
      // stroke widths, so the head reaches 0.95 strokes past the shaft), and the shaft stopped
      // 10/64 short of the destination centre, which puts the tip on the centre of the square.
      const width = 10 / 64;
      const margin = 10 / 64;
      const defs = svg('defs');
      const used = new Set();
      for (const arrow of this.arrows) {
        const brush = BRUSHES[arrow.brush] ? arrow.brush : 'green';
        if (!used.has(brush)) {
          used.add(brush);
          defs.append(svg('marker', { id: `${this.uid}-${brush}`, orient: 'auto', markerWidth: 4, markerHeight: 4, refX: 2.05, refY: 2 },
            svg('path', { d: 'M0,0 V4 L3,2 Z', fill: BRUSHES[brush] })));
        }
      }
      layer.append(defs);
      for (const arrow of this.arrows) {
        const brush = BRUSHES[arrow.brush] ? arrow.brush : 'green';
        const [x1, y1] = this.centre(arrow.from);
        const [x2, y2] = this.centre(arrow.to);
        const angle = Math.atan2(y2 - y1, x2 - x1);
        layer.append(svg('line', {
          x1: x1.toFixed(3), y1: y1.toFixed(3),
          x2: (x2 - Math.cos(angle) * margin).toFixed(3), y2: (y2 - Math.sin(angle) * margin).toFixed(3),
          stroke: BRUSHES[brush], 'stroke-width': width.toFixed(4), 'stroke-linecap': 'round',
          'marker-end': `url(#${this.uid}-${brush})`, opacity: 0.8,
        }));
      }
    }

    // -- eval bar -------------------------------------------------------------------------

    buildEvalBar() {
      const white = h('div', { class: 'white' });
      const text = h('span', { class: 'text' });
      const el = h('div', { class: 'eval-bar', role: 'img', 'aria-label': 'Evaluation' }, white, h('div', { class: 'tick' }), text);
      return { el, white, text };
    }

    renderEval() {
      const bar = this.evalBar;
      if (!bar) return;
      bar.el.classList.toggle('flipped', this.flipped);
      if (!this.eval) {
        bar.white.style.height = '50%';
        bar.text.textContent = '';
        bar.el.setAttribute('aria-label', 'Evaluation: none');
        return;
      }
      const cp = evalCp(this.eval, this.evalFen);
      const share = this.eval.mate != null ? (cp > 0 ? 100 : 0) : Math.max(2, Math.min(98, winPct(cp)));
      bar.white.style.height = `${share.toFixed(1)}%`;
      const label = evalText(this.eval, this.evalFen);
      bar.text.textContent = label;
      // The text sits in the bigger share, coloured to contrast with it (lichess does the same).
      const whiteAhead = cp >= 0;
      const whiteAtBottom = !this.flipped;
      const atBottom = whiteAhead === whiteAtBottom;
      bar.text.className = `text ${atBottom ? 'bottom' : 'top'} ${whiteAhead ? 'on-white' : 'on-black'}${label.length > 4 ? ' long' : ''}`;
      bar.el.setAttribute('aria-label', `Evaluation ${label}`);
    }

    // -- interaction ----------------------------------------------------------------------

    onCellClick(cell) {
      if (this.suppressClick) { this.suppressClick = false; return; }
      this.activate(cell.dataset.square);
    }

    onCellFocus(cell) {
      // Roving tabindex: the board is one tab stop, the focused square is where arrows continue.
      for (const other of this.cells) other.tabIndex = other === cell ? 0 : -1;
    }

    onGridKey(event) {
      if (event.key === 'Escape') { this.selected = null; this.closePromo(); this.render(); return; }
      // Arrow keys walk the squares only while the board is playable; otherwise they are left
      // to the page, which uses them to step through the game.
      if (!this.position.interactive) return;
      const deltas = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
      const delta = deltas[event.key];
      if (!delta) return;
      const index = this.cells.indexOf(document.activeElement);
      if (index < 0) return;
      const row = Math.max(0, Math.min(7, Math.floor(index / 8) + delta[0]));
      const col = Math.max(0, Math.min(7, (index % 8) + delta[1]));
      this.cells[row * 8 + col].focus();
      event.preventDefault();
      event.stopPropagation();
    }

    activate(name) {
      if (!this.position.interactive) return;
      if (this.selected && this.selected !== name) {
        const entries = (this.legalMap.get(this.selected) || []).filter((entry) => entry.to === name);
        if (entries.length) { this.commit(this.selected, name, entries); return; }
      }
      if (this.legalMap.has(name)) {
        this.selected = this.selected === name ? null : name;
      } else {
        this.selected = null;
      }
      this.render();
    }

    commit(from, to, entries) {
      if (entries.some((entry) => entry.promo)) {
        this.openPromo(from, to, entries);
        return;
      }
      this.play(entries[0].uci);
    }

    play(uci) {
      this.selected = null;
      this.pending = { uci };
      this.render();
      if (this.onMove) this.onMove(uci);
    }

    /** lichess's promotion picker: a strip of four pieces down the destination file. */
    openPromo(from, to, entries) {
      this.closePromo();
      const colour = sideToMove(this.position.fen) === 'white' ? 'w' : 'b';
      const [row, col] = this.cellPos(squareIndex(to));
      const step = row < 4 ? 1 : -1; // the strip grows from the promotion square towards the mover
      const overlay = h('div', { class: 'promo', role: 'dialog', 'aria-label': 'Choose the promotion piece' });
      overlay.addEventListener('click', (event) => { if (event.target === overlay) { this.closePromo(); this.selected = null; this.render(); } });
      overlay.addEventListener('keydown', (event) => { if (event.key === 'Escape') { this.closePromo(); this.selected = null; this.render(); } });
      let offset = 0;
      for (const type of PROMOTION_ORDER) {
        const entry = entries.find((candidate) => candidate.promo === type);
        if (!entry) continue;
        const cellRow = row + step * offset;
        offset += 1;
        const button = h('button', {
          type: 'button', class: 'promo-btn', 'aria-label': `Promote to ${PIECE_NAME[type]}`,
          onClick: () => { this.closePromo(); this.play(entry.uci); },
        }, pieceNode({ color: colour, type }));
        overlay.append(h('div', { class: 'promo-sq', style: { left: `${col * 12.5}%`, top: `${cellRow * 12.5}%` } }, button));
      }
      this.promo = overlay;
      this.wrap.append(overlay);
      const first = overlay.querySelector('button');
      if (first) first.focus();
    }

    closePromo() {
      if (this.promo) { this.promo.remove(); this.promo = null; }
    }

    onPointerDown(cell, event) {
      if (!this.position.interactive || event.button !== 0) return;
      const name = cell.dataset.square;
      if (!this.legalMap.has(name)) return;
      const rect = this.wrap.getBoundingClientRect();
      this.drag = { from: name, cell, startX: event.clientX, startY: event.clientY, moved: false, ghost: null, rect, pointerId: event.pointerId, over: null };
      // Capture on the cell, not the grid: capturing elsewhere would redirect the click event too.
      try { cell.setPointerCapture(event.pointerId); } catch (error) { /* not supported */ }
    }

    squareUnder(event, rect) {
      const col = Math.floor(((event.clientX - rect.left) / rect.width) * 8);
      const row = Math.floor(((event.clientY - rect.top) / rect.height) * 8);
      if (col < 0 || col > 7 || row < 0 || row > 7) return null;
      return squareName(this.squareAt(row, col));
    }

    onPointerMove(event) {
      const drag = this.drag;
      if (!drag || event.pointerId !== drag.pointerId) return;
      const dx = event.clientX - drag.startX;
      const dy = event.clientY - drag.startY;
      if (!drag.moved) {
        if (Math.hypot(dx, dy) < 4) return;
        drag.moved = true;
        this.selected = drag.from;
        this.grid.classList.add('dragging');
        const piece = parseFen(this.position.fen)[squareIndex(drag.from)];
        if (piece) {
          drag.ghost = pieceNode(piece, 'drag');
          this.wrap.append(drag.ghost);
        }
        this.render();
      }
      const over = this.squareUnder(event, drag.rect);
      if (over !== drag.over) { drag.over = over; this.render(); }
      if (drag.ghost) {
        const x = event.clientX - drag.rect.left;
        const y = event.clientY - drag.rect.top;
        drag.ghost.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
      }
    }

    onPointerUp(event) {
      const drag = this.drag;
      if (!drag || event.pointerId !== drag.pointerId) return;
      this.drag = null;
      this.grid.classList.remove('dragging');
      if (!drag.moved) return; // the click event handles a plain tap
      this.suppressClick = true;
      setTimeout(() => { this.suppressClick = false; }, 0);
      if (drag.ghost) drag.ghost.remove();
      const target = this.squareUnder(event, drag.rect);
      if (!target || target === drag.from) { this.render(); return; }
      const entries = (this.legalMap.get(drag.from) || []).filter((entry) => entry.to === target);
      if (entries.length) this.commit(drag.from, target, entries);
      else { this.selected = null; this.render(); }
    }

    cancelDrag(rerender = true) {
      if (this.drag && this.drag.ghost) this.drag.ghost.remove();
      this.drag = null;
      this.grid.classList.remove('dragging');
      if (rerender) this.render();
    }
  }

  // ------------------------------------------------------------------------------------------
  // Markdown renderer (headings, paragraphs, emphasis, code, links, lists, tables, rules)

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function inlineMarkdown(text) {
    const codes = [];
    let out = escapeHtml(text).replace(/`([^`\n]+)`/g, (match, code) => {
      codes.push(`<code>${code}</code>`);
      return ` ${codes.length - 1} `;
    });
    out = out.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (match, alt) => `<em>[image: ${alt}]</em>`);
    out = out.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (match, label, href) => {
      const safe = /^(https?:|mailto:|#|\/)/i.test(href) ? href : '#';
      return `<a href="${safe}" rel="noopener" target="_blank">${label}</a>`;
    });
    out = out.replace(/&lt;(https?:\/\/[^\s&]+)&gt;/g, '<a href="$1" rel="noopener" target="_blank">$1</a>');
    out = out.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    out = out.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    out = out.replace(/(^|[^*\w])\*([^*\n]+)\*(?=[^*\w]|$)/g, '$1<em>$2</em>');
    out = out.replace(/(^|[^\w])_([^_\n]+)_(?=[^\w]|$)/g, '$1<em>$2</em>');
    out = out.replace(/ (\d+) /g, (match, index) => codes[Number(index)]);
    return out;
  }

  function renderMarkdown(source) {
    const lines = String(source).replace(/\r\n?/g, '\n').split('\n');
    const html = [];
    let i = 0;

    const isTableSeparator = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line) && line.includes('-');
    const splitRow = (line) => {
      let row = line.trim();
      if (row.startsWith('|')) row = row.slice(1);
      if (row.endsWith('|')) row = row.slice(0, -1);
      return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, '|'));
    };
    const listItem = (line) => /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);

    function renderList(startIndent) {
      const first = listItem(lines[i]);
      const ordered = /\d/.test(first[2]);
      const items = [];
      while (i < lines.length) {
        const match = listItem(lines[i]);
        if (!match || match[1].length !== startIndent || (/\d/.test(match[2]) !== ordered)) break;
        const item = { text: match[3], children: [] };
        i += 1;
        while (i < lines.length) {
          const line = lines[i];
          if (line.trim() === '') {
            const next = lines[i + 1];
            if (next !== undefined && (/^\s+\S/.test(next)) && !listItem(next)) { item.text += '\n'; i += 1; continue; }
            if (next !== undefined && listItem(next) && listItem(next)[1].length > startIndent) { i += 1; continue; }
            break;
          }
          const nested = listItem(line);
          if (nested && nested[1].length > startIndent) {
            item.children.push(renderList(nested[1].length));
            continue;
          }
          if (nested && nested[1].length <= startIndent) break;
          if (/^\s+\S/.test(line)) { item.text += ' ' + line.trim(); i += 1; continue; }
          break;
        }
        items.push(item);
      }
      const body = items.map((item) => `<li>${inlineMarkdown(item.text.trim())}${item.children.join('')}</li>`).join('');
      return `<${ordered ? 'ol' : 'ul'}>${body}</${ordered ? 'ol' : 'ul'}>`;
    }

    while (i < lines.length) {
      const line = lines[i];
      if (line.trim() === '') { i += 1; continue; }
      const fence = /^\s*(```|~~~)\s*([\w+-]*)/.exec(line);
      if (fence) {
        const code = [];
        i += 1;
        while (i < lines.length && !lines[i].trim().startsWith(fence[1])) { code.push(lines[i]); i += 1; }
        i += 1;
        const cls = fence[2] ? ` class="lang-${escapeHtml(fence[2])}"` : '';
        html.push(`<pre><code${cls}>${escapeHtml(code.join('\n'))}</code></pre>`);
        continue;
      }
      const heading = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
      if (heading) {
        const level = heading[1].length;
        const text = heading[2];
        const id = text.toLowerCase().replace(/[^\w]+/g, '-').replace(/^-|-$/g, '');
        html.push(`<h${level} id="${escapeHtml(id)}">${inlineMarkdown(text)}</h${level}>`);
        i += 1;
        continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { html.push('<hr>'); i += 1; continue; }
      if (line.trim().startsWith('|') && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
        const header = splitRow(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].trim().startsWith('|')) { rows.push(splitRow(lines[i])); i += 1; }
        const head = header.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join('');
        const body = rows.map((row) => `<tr>${header.map((cell, index) => `<td>${inlineMarkdown(row[index] || '')}</td>`).join('')}</tr>`).join('');
        html.push(`<div class="table-scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
        continue;
      }
      if (line.startsWith('>')) {
        const quote = [];
        while (i < lines.length && lines[i].startsWith('>')) { quote.push(lines[i].replace(/^>\s?/, '')); i += 1; }
        html.push(`<blockquote>${renderMarkdown(quote.join('\n'))}</blockquote>`);
        continue;
      }
      const item = listItem(line);
      if (item) { html.push(renderList(item[1].length)); continue; }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() !== '' && !/^(#{1,6})\s/.test(lines[i]) && !/^\s*(```|~~~)/.test(lines[i]) && !listItem(lines[i]) && !(lines[i].trim().startsWith('|') && isTableSeparator(lines[i + 1] || ''))) {
        paragraph.push(lines[i].trim());
        i += 1;
      }
      html.push(`<p>${inlineMarkdown(paragraph.join(' '))}</p>`);
    }
    return html.join('\n');
  }

  // ------------------------------------------------------------------------------------------
  // Sparklines

  function sparkline(values, { label, format = fmt.int } = {}) {
    const clean = values.map((value) => (Number.isFinite(value) ? value : null));
    const points = clean.filter((value) => value != null);
    const wrap = h('div', { class: 'spark' });
    const last = points.length ? points[points.length - 1] : null;
    wrap.append(h('div', { class: 'label' }, h('span', { text: label }), h('span', { class: 'mono', text: last == null ? '-' : format(last) })));
    if (points.length < 2) {
      wrap.append(h('div', { class: 'muted', style: { fontSize: '0.78rem' }, text: points.length ? 'one move so far' : 'no data' }));
      return wrap;
    }
    const width = 240;
    const height = 44;
    const pad = 3;
    const max = Math.max(...points);
    const min = Math.min(...points, 0);
    const span = max - min || 1;
    const step = (width - 2 * pad) / Math.max(1, clean.length - 1);
    const coords = [];
    clean.forEach((value, index) => {
      if (value == null) return;
      const x = pad + index * step;
      const y = height - pad - ((value - min) / span) * (height - 2 * pad);
      coords.push([x, y]);
    });
    const line = coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
    const baseline = height - pad - ((0 - min) / span) * (height - 2 * pad);
    const [lx, ly] = coords[coords.length - 1];
    const graph = svg('svg', { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none', role: 'img', 'aria-label': `${label}: ${points.map((value) => format(value)).join(', ')}` },
      svg('line', { class: 'base', x1: pad, y1: baseline.toFixed(1), x2: width - pad, y2: baseline.toFixed(1) }),
      svg('polyline', { points: line }),
      svg('circle', { class: 'end', cx: lx.toFixed(1), cy: ly.toFixed(1), r: 2.2 }));
    wrap.append(graph);
    wrap.append(h('div', { class: 'label' }, h('span', { text: `min ${format(Math.min(...points))}` }), h('span', { text: `max ${format(max)}` })));
    return wrap;
  }

  // ------------------------------------------------------------------------------------------
  // Game view, shared by Play and Spectate

  const TERMINATION_HINT = {
    flag: 'The engine ran out of time. On the platform that is a loss unless the other side cannot mate.',
    illegal: 'The engine answered with a move that is not legal in this position. On the platform that loses the game.',
    crash: 'The engine process died or wrote something that is not a move.',
    init: 'The engine did not report ready within the init budget.',
    ply_cap: 'The game reached the ply cap, counted from the first position, and is a draw.',
  };

  class GameView {
    /**
     * options.mode: 'play' | 'spectate'
     * options.onNewGame(): show the setup form again
     */
    constructor(options) {
      this.mode = options.mode;
      this.onNewGame = options.onNewGame;
      this.gameId = null;
      this.state = null;
      this.pollTimer = null;
      this.tickTimer = null;
      this.turnStartedAt = null;
      this.turnPly = -1;
      this.browsePly = null;
      this.busy = false;
      this.signature = '';
      this.lastLogCounts = { white: -1, black: -1 };
      this.flippedByUser = null;

      this.board = new Board({ onMove: (uci) => this.submitMove(uci) });

      this.topBar = this.playerBar();
      this.bottomBar = this.playerBar();
      this.banner = h('div', { class: 'banner', hidden: true });
      this.statusLine = h('div', { class: 'status-line' });
      this.controls = h('div', { class: 'game-controls' });
      this.movesBox = h('div', { class: 'moves' });
      this.thinkWhite = h('div', { class: 'card think' });
      this.thinkBlack = h('div', { class: 'card think' });
      this.infoBox = h('div', { class: 'game-meta' });

      this.el = h('div', { class: 'game-layout' },
        h('div', { class: 'game-main' },
          h('div', { class: 'board-column' },
            this.topBar.el,
            this.board.el,
            this.bottomBar.el,
            this.statusLine,
            this.controls,
            this.banner,
          )),
        this.side = h('div', { class: 'game-side' },
          h('div', { class: 'card' }, h('h3', { text: 'Moves' }), this.movesBox, this.infoBox),
          this.thinkWhite,
          this.thinkBlack));

      this.el.addEventListener('keydown', (event) => this.onKey(event));
      this.renderControls();
    }

    playerBar() {
      const dot = h('span', { class: 'dot' });
      const who = h('span', { class: 'who' });
      const status = h('span', { class: 'player-status' });
      const clock = h('div', { class: 'clock', text: '-' });
      const el = h('div', { class: 'player-bar' }, h('div', { class: 'player-name' }, dot, who, status), clock);
      return { el, dot, who, status, clock };
    }

    // -- lifecycle ----------------------------------------------------------------------------

    attach(gameId, initialState) {
      this.detach();
      this.gameId = gameId;
      this.browsePly = null;
      this.signature = '';
      this.turnStartedAt = null;
      this.turnPly = -1;
      this.lastLogCounts = { white: -1, black: -1 };
      if (initialState) this.apply(initialState);
      this.startPolling();
      this.tickTimer = setInterval(() => this.tick(), 100);
    }

    detach() {
      clearInterval(this.pollTimer);
      clearInterval(this.tickTimer);
      this.pollTimer = null;
      this.tickTimer = null;
    }

    startPolling() {
      clearInterval(this.pollTimer);
      const poll = async () => {
        if (!this.gameId || this.busy) return;
        try {
          const state = await api.get(`/api/games/${this.gameId}`);
          if (state.id !== this.gameId) return;
          this.apply(state);
          if (state.status === 'finished') { clearInterval(this.pollTimer); this.pollTimer = null; }
        } catch (error) {
          if (error.status === 404) {
            clearInterval(this.pollTimer);
            this.pollTimer = null;
            this.statusLine.textContent = 'This game is no longer on the server (it was restarted).';
            this.board.setPosition({ interactive: false });
          }
        }
      };
      poll();
      this.pollTimer = setInterval(poll, 500);
    }

    // -- state --------------------------------------------------------------------------------

    apply(state) {
      this.state = state;
      const humanTurn = state.status === 'running' && !state.thinking && state.human && state.turn === state.human;
      if (humanTurn && this.turnPly !== state.ply) {
        this.turnStartedAt = Date.now();
        this.turnPly = state.ply;
      }
      if (!humanTurn) this.turnPly = -1;
      if (this.flippedByUser == null) this.board.setFlipped(state.human === 'black');

      const signature = [state.status, state.ply, state.thinking, state.result, state.termination, state.stopping,
        state.white.log.length, state.black.log.length, state.error, state.moves.length].join('|');
      if (signature !== this.signature) {
        this.signature = signature;
        this.renderBoard();
        this.renderBars();
        this.renderMoves();
        this.renderBanner();
        this.renderControls();
        this.renderThinking('white', this.thinkWhite, state.white);
        this.renderThinking('black', this.thinkBlack, state.black);
        this.renderInfo();
      }
      this.tick();
    }

    livePly() { return this.state ? this.state.ply : 0; }

    shownFen() {
      const state = this.state;
      if (!state) return this.board.position.fen;
      if (this.browsePly == null || this.browsePly >= state.moves.length) return state.fen;
      if (this.browsePly <= 0) return state.start_fen;
      return state.moves[this.browsePly - 1].fen;
    }

    renderBoard() {
      const state = this.state;
      const browsing = this.browsePly != null && this.browsePly < state.moves.length;
      const moveIndex = browsing ? this.browsePly : state.moves.length;
      const lastMove = moveIndex > 0 ? state.moves[moveIndex - 1].uci : null;
      const interactive = this.mode === 'play' && !browsing && state.status === 'running' && !state.thinking
        && state.human === state.turn && !this.busy;
      this.board.setPosition({
        fen: this.shownFen(),
        lastMove,
        check: browsing ? null : state.check_square,
        legal: interactive ? state.legal_moves : [],
        interactive,
      });
    }

    renderBars() {
      const state = this.state;
      const topColour = this.board.flipped ? 'white' : 'black';
      const bottomColour = this.board.flipped ? 'black' : 'white';
      for (const [bar, colour] of [[this.topBar, topColour], [this.bottomBar, bottomColour]]) {
        const player = state[colour];
        bar.dot.className = `dot ${colour}`;
        bar.who.textContent = player.kind === 'human' ? 'You' : player.label;
        bar.who.title = player.path || '';
        bar.colour = colour;
        let status = '';
        if (state.status === 'starting' && player.kind === 'engine') status = player.init_ms == null ? 'starting' : 'ready';
        else if (state.status === 'running' && state.turn === colour) status = state.thinking ? 'thinking' : 'to move';
        else if (state.status === 'finished' && player.kind === 'engine' && player.init_failure) status = `failed: ${player.init_failure}`;
        bar.status.textContent = status;
        bar.status.className = `player-status${state.status === 'running' && state.turn === colour ? ' active' : ''}`;
      }
    }

    tick() {
      const state = this.state;
      if (!state) return;
      for (const bar of [this.topBar, this.bottomBar]) {
        const colour = bar.colour;
        if (!colour) continue;
        let ms = state.clocks[colour];
        const onTurn = state.status === 'running' && state.turn === colour;
        if (onTurn && state.thinking && state.thinking_since) {
          ms -= Math.max(0, Date.now() - state.thinking_since);
        } else if (onTurn && !state.thinking && state.human === colour && this.turnStartedAt) {
          ms -= Date.now() - this.turnStartedAt;
        }
        bar.clock.textContent = fmt.clock(ms);
        bar.clock.className = `clock${onTurn ? ' active' : ''}${ms < 10000 && onTurn ? ' low' : ''}`;
      }
    }

    renderBanner() {
      const state = this.state;
      const banner = this.banner;
      clear(banner);
      if (state.status !== 'finished') { banner.hidden = true; return; }
      banner.hidden = false;
      const human = state.human;
      let verdict = '';
      if (state.result === 'draw') verdict = 'Draw';
      else if (state.result === 'void') verdict = 'No result';
      else if (human) verdict = state.result === human ? 'You win' : 'You lose';
      else verdict = `${state[state.result].label} wins`;
      let cls = 'banner';
      if (human && state.result === human) cls += ' win';
      else if (human && state.result && state.result !== 'draw' && state.result !== 'void') cls += ' loss';
      if (state.failed) cls += ' failed';
      banner.className = cls;
      let why = state.termination_text || '';
      if (state.failed && state.result && state.result !== 'draw') {
        const loser = state.result === 'white' ? 'black' : 'white';
        why = `${state[loser].label}: ${why.toLowerCase()}`;
      }
      banner.append(h('span', { class: 'score', text: state.result_text || '*' }), h('strong', { text: verdict }), h('span', { class: 'why', text: why }));
      const hint = TERMINATION_HINT[state.termination];
      if (hint) banner.append(h('div', { class: 'hint muted', text: hint }));
      if (state.error) banner.append(h('div', { class: 'error-box', style: { width: '100%' }, text: state.error }));
      if (state.pgn_path) banner.append(h('div', { class: 'path mono', text: `saved to ${state.pgn_path}` }));
    }

    renderControls() {
      const state = this.state;
      const controls = this.controls;
      clear(controls);
      const running = state && state.status === 'running';
      const humanTurn = running && state.human && state.turn === state.human && !state.thinking;
      controls.append(h('button', { type: 'button', class: 'btn-sm', onClick: () => { this.flippedByUser = true; this.board.flip(); this.renderBars(); this.tick(); } }, 'Flip board'));
      if (this.mode === 'play') {
        controls.append(h('button', {
          type: 'button', class: 'btn-sm', disabled: !humanTurn || !state.moves.length || this.busy,
          onClick: () => this.action('takeback'),
        }, 'Take back'));
        controls.append(h('button', {
          type: 'button', class: 'btn-sm', disabled: !state || state.status === 'finished' || this.busy,
          onClick: () => { if (window.confirm('Resign this game?')) this.action('resign'); },
        }, 'Resign'));
      } else {
        controls.append(h('button', {
          type: 'button', class: 'btn-sm', disabled: !state || state.status === 'finished' || this.busy,
          onClick: () => this.action('stop'),
        }, 'Stop'));
      }
      if (state) {
        controls.append(h('a', { class: 'btn btn-sm', href: `/api/games/${state.id}/pgn`, download: '' }, 'Download PGN'));
        controls.append(h('button', {
          type: 'button', class: 'btn-sm',
          onClick: async () => { toast((await copyText(this.shownFen())) ? 'FEN copied' : 'Could not copy; select it from the moves panel'); },
        }, 'Copy FEN'));
      }
      if (state && state.status === 'finished' && state.moves.length) {
        // The analysis engine is a local-only instrument; without it the button says why.
        const engine = cache.analysisEngine;
        if (engine && engine.available) {
          controls.append(h('a', { class: 'btn btn-sm', href: `#/analysis?game=${encodeURIComponent(state.id)}` }, 'Analyse this game'));
        } else {
          controls.append(h('button', { type: 'button', class: 'btn-sm', disabled: true, title: engine ? engine.reason : 'analysis engine status unknown' }, 'Analyse this game'));
        }
      }
      controls.append(h('button', { type: 'button', class: 'btn-sm btn-quiet', onClick: () => this.onNewGame() }, this.mode === 'play' ? 'New game' : 'New match'));
    }

    renderMoves() {
      const state = this.state;
      const box = this.movesBox;
      clear(box);
      if (!state.moves.length) {
        box.append(h('div', { class: 'empty', text: state.status === 'starting' ? 'starting the engine' : 'no moves yet' }));
        return;
      }
      const table = h('table');
      const body = h('tbody');
      const startBoardTurn = sideToMove(state.start_fen);
      const startNumber = Number(state.start_fen.split(/\s+/)[5]) || 1;
      let index = 0;
      let number = startNumber;
      const current = this.browsePly == null ? state.moves.length : this.browsePly;
      const cell = (record, ply) => h('td', {}, h('button', {
        type: 'button', class: `mv${current === ply ? ' current' : ''}`,
        onClick: () => { this.browsePly = ply >= state.moves.length ? null : ply; this.renderBoard(); this.renderMoves(); },
      }, h('span', { text: record.san }), h('span', { class: 'clk', text: fmt.clock(record.clock_ms) })));
      if (startBoardTurn === 'black') {
        body.append(h('tr', {}, h('td', { class: 'n', text: `${number}.` }), h('td', { class: 'muted', text: '...' }), cell(state.moves[0], 1)));
        index = 1;
        number += 1;
      }
      for (; index < state.moves.length; index += 2, number += 1) {
        const white = state.moves[index];
        const black = state.moves[index + 1];
        body.append(h('tr', {}, h('td', { class: 'n', text: `${number}.` }), cell(white, index + 1), black ? cell(black, index + 2) : h('td')));
      }
      table.append(body);
      box.append(table);
      if (this.browsePly != null) {
        box.append(h('div', { class: 'row', style: { marginTop: '0.4rem' } },
          h('button', { type: 'button', class: 'btn-sm', onClick: () => { this.browsePly = null; this.renderBoard(); this.renderMoves(); } }, 'Live position'),
          h('span', { class: 'muted', style: { fontSize: '0.8rem' }, text: 'arrow keys step through the game' })));
      }
      box.scrollTop = box.scrollHeight;
    }

    renderInfo() {
      const state = this.state;
      const tc = state.time_control;
      clear(this.infoBox);
      this.infoBox.append(h('div', {},
        `${fmt.tc(tc.base_ms, tc.increment_ms)} · ply ${state.ply} of ${state.ply_cap}`,
        state.opening ? ` · ${state.opening}` : ''));
      this.infoBox.append(h('div', { class: 'fen', text: this.shownFen() }));
    }

    renderThinking(colour, box, player) {
      clear(box);
      const state = this.state;
      if (player.kind !== 'engine') { box.hidden = true; return; }
      box.hidden = false;
      const active = state.status === 'running' && state.turn === colour && state.thinking;
      let chip = 'idle';
      if (state.status === 'starting') chip = player.init_ms == null ? 'starting' : 'ready';
      else if (active) chip = 'thinking';
      else if (state.status === 'finished') chip = player.alive ? 'stopping' : 'stopped';
      box.append(h('div', { class: 'head' },
        h('h3', { text: `${colour} · engine` }),
        h('span', { class: `chip${active ? ' accent' : ''}`, text: chip })));
      box.append(h('div', { class: 'who', text: player.label, title: player.path || '' }));
      const init = h('div', { class: 'init' });
      if (player.init_failure) init.append(`init failed: ${player.init_failure}`);
      else if (player.init_ms != null) {
        const within = player.init_ms <= player.init_budget_ms;
        init.append(`init ${fmt.seconds(player.init_ms)}, ${within ? `within the ${player.init_budget_ms / 1000} s budget` : 'over budget'}`);
      } else init.append('starting');
      box.append(init);

      const records = player.log || [];
      const latest = records.length ? records[records.length - 1] : null;
      if (!latest) {
        box.append(h('p', { class: 'empty', text: 'no moves yet' }));
      } else if (!latest.raw.length) {
        box.append(h('p', { class: 'empty', text: `no log: nothing printed for ply ${latest.ply}` }));
      } else {
        const known = latest.known || {};
        const dl = h('dl', { class: 'kv' });
        const row = (label, value) => { if (value != null && value !== '') dl.append(h('dt', { text: label }), h('dd', { text: value })); };
        row('move', known.move);
        row('depth', known.depth ? known.depth.replace('/', ' / ') : null);
        row('nodes', known.nodes != null ? fmt.int(known.nodes) : null);
        row('speed', known.nps != null ? `${fmt.int(known.nps)} nps` : null);
        row('time', known.time_ms != null ? fmt.ms(known.time_ms) : null);
        row('budget', known.soft_ms != null || known.hard_ms != null ? `soft ${fmt.ms(known.soft_ms)} · hard ${fmt.ms(known.hard_ms)}` : null);
        row('clock', known.clock_ms != null ? `${fmt.clock(known.clock_ms)} (${fmt.ms(known.clock_ms)})` : null);
        row('measured', `${fmt.ms(latest.spent_ms)} wall time, harness view`);
        if (dl.childElementCount) box.append(dl);
        const unknown = Object.entries(latest.unknown || {});
        if (unknown.length) {
          box.append(h('div', { class: 'unknown' }, unknown.map(([key, value]) => h('span', { text: `${key} ${value}` }))));
        }
        if (!Object.keys(known).length) {
          box.append(h('pre', { style: { marginTop: '0.5rem', fontSize: '0.78rem' }, text: latest.raw.join('\n') }));
        }
      }
      if (records.length) {
        const nodes = records.map((record) => Number(record.known && record.known.nodes));
        const times = records.map((record) => Number(record.spent_ms));
        const sparks = h('div', { class: 'sparks' });
        if (nodes.some((value) => Number.isFinite(value))) sparks.append(sparkline(nodes, { label: 'nodes per move' }));
        sparks.append(sparkline(times, { label: 'time per move', format: (value) => fmt.seconds(value) }));
        box.append(sparks);
      }
      const rawLines = [];
      if (player.init_log) rawLines.push(`[init] ${player.init_log}`);
      for (const record of records) for (const line of record.raw) rawLines.push(`[ply ${record.ply}] ${line}`);
      const raw = h('details', { class: 'raw' }, h('summary', { text: `raw log, ${rawLines.length} line${rawLines.length === 1 ? '' : 's'}` }),
        h('pre', { text: rawLines.length ? rawLines.join('\n') : '(nothing printed)' }));
      if (latest) raw.append(h('pre', { text: JSON.stringify(latest, null, 1) }));
      box.append(raw);
    }

    // -- actions ------------------------------------------------------------------------------

    async submitMove(uci) {
      if (!this.state || this.busy) return;
      const spent = this.turnStartedAt ? Date.now() - this.turnStartedAt : 0;
      this.busy = true;
      this.board.setPosition({ interactive: false });
      try {
        const state = await api.post(`/api/games/${this.gameId}/move`, { uci, spent_ms: spent });
        this.browsePly = null;
        this.turnStartedAt = null;
        this.turnPly = -1;
        this.busy = false;
        this.apply(state);
        if (state.status !== 'finished' && !this.pollTimer) this.startPolling();
      } catch (error) {
        this.busy = false;
        toast(error.message, true);
        this.signature = '';
        if (this.state) this.apply(this.state);
      }
    }

    async action(name) {
      if (!this.gameId) return;
      this.busy = true;
      try {
        const state = await api.post(`/api/games/${this.gameId}/${name}`);
        this.browsePly = null;
        this.busy = false;
        this.signature = '';
        this.apply(state);
        if (state.status !== 'finished' && !this.pollTimer) this.startPolling();
        if (name === 'stop' || name === 'resign') this.startPolling();
      } catch (error) {
        this.busy = false;
        toast(error.message, true);
      }
    }

    onKey(event) {
      if (!this.state || event.target.matches('input, select, textarea')) return;
      const total = this.state.moves.length;
      if (event.key === 'ArrowLeft') {
        const current = this.browsePly == null ? total : this.browsePly;
        this.browsePly = Math.max(0, current - 1);
      } else if (event.key === 'ArrowRight') {
        const current = this.browsePly == null ? total : this.browsePly;
        this.browsePly = current + 1 >= total ? null : current + 1;
      } else if (event.key === 'Home') this.browsePly = 0;
      else if (event.key === 'End') this.browsePly = null;
      else return;
      event.preventDefault();
      this.renderBoard();
      this.renderMoves();
      this.renderInfo();
    }
  }

  // ------------------------------------------------------------------------------------------
  // Setup forms

  function tcSelect(info, id) {
    const select = h('select', { id });
    info.time_controls.forEach((tc, index) => select.append(h('option', { value: String(index), text: tc.label })));
    select.append(h('option', { value: 'custom', text: 'Custom' }));
    const base = h('input', { type: 'number', id: `${id}-base`, min: '1', step: '1', value: '60', 'aria-label': 'Base time in seconds' });
    const inc = h('input', { type: 'number', id: `${id}-inc`, min: '0', step: '0.05', value: '0.5', 'aria-label': 'Increment in seconds' });
    const custom = h('div', { class: 'row', hidden: true },
      h('div', { class: 'field' }, h('label', { for: `${id}-base`, text: 'Base (s)' }), base),
      h('div', { class: 'field' }, h('label', { for: `${id}-inc`, text: 'Increment (s)' }), inc));
    select.addEventListener('change', () => { custom.hidden = select.value !== 'custom'; });
    const stored = storage.get('letal.tc');
    if (stored != null && select.querySelector(`option[value="${stored}"]`)) { select.value = String(stored); custom.hidden = select.value !== 'custom'; }
    return {
      el: h('div', { class: 'field' }, h('label', { for: id, text: 'Time control' }), select, custom),
      value() {
        storage.set('letal.tc', select.value);
        if (select.value === 'custom') {
          return { base_ms: Math.round(Number(base.value) * 1000), increment_ms: Math.round(Number(inc.value) * 1000) };
        }
        const tc = info.time_controls[Number(select.value)];
        return { base_ms: tc.base_ms, increment_ms: tc.increment_ms };
      },
    };
  }

  function positionSelect(openings, id, preselect) {
    const select = h('select', { id });
    select.append(h('option', { value: 'start', text: 'Standard starting position' }));
    if (openings.present && openings.count) {
      const group = h('optgroup', { label: `Curated openings (${openings.path}, ${openings.count})` });
      group.append(h('option', { value: 'next', text: 'Next curated opening' }));
      openings.openings.forEach((opening) => {
        if (opening.valid) group.append(h('option', { value: `c${opening.index}`, text: `${opening.index + 1}. ${opening.name || '(unnamed)'}` }));
      });
      select.append(group);
    }
    const harness = h('optgroup', { label: 'Harness openings (harness/rules.py)' });
    openings.harness.forEach((opening, index) => harness.append(h('option', { value: `h${index}`, text: opening.name })));
    select.append(harness);
    select.append(h('option', { value: 'fen', text: 'Custom FEN' }));
    const fenInput = h('input', { type: 'text', class: 'mono', id: `${id}-fen`, placeholder: 'FEN', spellcheck: 'false', autocomplete: 'off' });
    const fenRow = h('div', { hidden: true }, h('label', { for: `${id}-fen`, text: 'FEN' }), fenInput);
    const preview = h('div', { class: 'row', style: { marginTop: '0.4rem' } });
    const update = () => {
      fenRow.hidden = select.value !== 'fen';
      clear(preview);
      const chosen = resolve(false);
      if (chosen && chosen.fen) preview.append(miniBoard(chosen.fen), h('span', { class: 'muted', style: { fontSize: '0.85rem' }, text: chosen.opening || '' }));
    };
    const resolve = (advance) => {
      const value = select.value;
      if (value === 'start') return { fen: null, opening: null };
      if (value === 'fen') return { fen: fenInput.value.trim() || null, opening: null };
      if (value === 'next') {
        const valid = openings.openings.filter((opening) => opening.valid);
        if (!valid.length) return { fen: null, opening: null };
        const cursor = Number(storage.get('letal.openingCursor', 0)) % valid.length;
        if (advance) storage.set('letal.openingCursor', (cursor + 1) % valid.length);
        const opening = valid[cursor];
        return { fen: opening.fen, opening: opening.name, cursor: cursor + 1 };
      }
      if (value.startsWith('c')) {
        const opening = openings.openings[Number(value.slice(1))];
        return { fen: opening.fen, opening: opening.name };
      }
      if (value.startsWith('h')) {
        const opening = openings.harness[Number(value.slice(1))];
        return { fen: opening.fen, opening: opening.name };
      }
      return { fen: null, opening: null };
    };
    select.addEventListener('change', update);
    fenInput.addEventListener('input', update);
    if (preselect != null && select.querySelector(`option[value="c${preselect}"]`)) select.value = `c${preselect}`;
    update();
    return {
      el: h('div', { class: 'field' }, h('label', { for: id, text: 'Starting position' }), select, fenRow, preview),
      value() { return resolve(true); },
    };
  }

  const ENGINE_GROUPS = [
    ['letal', 'Mikhail LeTal'],
    ['version', 'Versions'],
    ['baseline', 'Baselines'],
    ['stockfish', 'Stockfish'],
  ];

  /** A seat picker: /api/info engines grouped by kind; the option value is the engine id. */
  function engineSelect(info, id, label, preferred, onChange) {
    const select = h('select', { id });
    const byKind = new Map();
    for (const engine of info.engines) {
      const kind = ENGINE_GROUPS.some(([key]) => key === engine.kind) ? engine.kind : 'letal';
      if (!byKind.has(kind)) byKind.set(kind, []);
      byKind.get(kind).push(engine);
    }
    for (const [kind, title] of ENGINE_GROUPS) {
      const engines = byKind.get(kind);
      if (!engines) continue;
      const group = h('optgroup', { label: title });
      for (const engine of engines) {
        // Older servers list engines by path only; the id falls back to it so a stored choice still resolves.
        group.append(h('option', { value: engine.id || engine.path, text: engine.label, dataset: { kind } }));
      }
      select.append(group);
    }
    if (preferred && select.querySelector(`option[value="${CSS.escape(preferred)}"]`)) select.value = preferred;
    const kindOf = () => (select.selectedOptions[0] ? select.selectedOptions[0].dataset.kind : null);
    if (onChange) select.addEventListener('change', onChange);
    return {
      el: h('div', { class: 'field' }, h('label', { for: id, text: label }), select),
      value: () => select.value,
      isStockfish: () => kindOf() === 'stockfish',
      select,
    };
  }

  /**
   * The optional fixed thinking time for Stockfish seats. Hidden unless one of the given pickers
   * has a Stockfish seat; empty means the yardstick plays on the clock like every other agent.
   */
  function movetimeField(id, pickers) {
    const input = h('input', { type: 'number', id, min: '1', max: '60000', step: '1', placeholder: 'on the clock', value: storage.get('letal.movetime', '') });
    const el = h('div', { class: 'field', hidden: true },
      h('label', { for: id, text: 'Stockfish move time (ms)' }), input,
      h('div', { class: 'hint', style: { marginTop: '0.3rem' }, text: 'Leave empty to let Stockfish manage the clock it is handed.' }));
    const update = () => { el.hidden = !pickers.some((picker) => picker.isStockfish()); };
    for (const picker of pickers) picker.select.addEventListener('change', update);
    update();
    return {
      el,
      update,
      value() {
        const raw = input.value.trim();
        storage.set('letal.movetime', raw);
        if (!raw || !pickers.some((picker) => picker.isStockfish())) return null;
        const number = Math.round(Number(raw));
        return Number.isFinite(number) && number > 0 ? number : null;
      },
    };
  }

  function plyCapField(info, id) {
    const input = h('input', { type: 'number', id, min: '1', max: String(info.ply_cap), value: String(info.ply_cap) });
    return { el: h('div', { class: 'field' }, h('label', { for: id, text: `Ply cap (platform: ${info.ply_cap})` }), input), value: () => Number(input.value) || info.ply_cap };
  }

  // ------------------------------------------------------------------------------------------
  // Pages

  const views = { play: null, spectate: null };

  async function pagePlay(main, params) {
    const [info, openings] = await Promise.all([loadInfo(true), loadOpenings(), loadAnalysisEngine(true)]);
    const view = views.play || (views.play = new GameView({ mode: 'play', onNewGame: () => { form.hidden = false; form.scrollIntoView({ block: 'start' }); $('select', form).focus(); } }));

    const engine = engineSelect(info, 'play-engine', 'Engine', storage.get('letal.engine', '.'));
    const movetime = movetimeField('play-movetime', [engine]);
    const colourWhite = h('input', { type: 'radio', name: 'colour', value: 'white', checked: storage.get('letal.colour', 'white') !== 'black' });
    const colourBlack = h('input', { type: 'radio', name: 'colour', value: 'black', checked: storage.get('letal.colour', 'white') === 'black' });
    const position = positionSelect(openings, 'play-position', params.get('opening'));
    const tc = tcSelect(info, 'play-tc');
    const cap = plyCapField(info, 'play-cap');
    const error = h('div', { class: 'error-box', hidden: true });
    const start = h('button', { type: 'submit', class: 'btn-primary' }, 'Start game');
    const form = h('form', { class: 'card stack', 'aria-label': 'New game' },
      h('div', { class: 'row between' }, h('h2', { text: 'New game' }),
        h('span', { class: 'muted', style: { fontSize: '0.82rem' }, text: `${info.engine_slots.used} of ${info.engine_slots.max} engine processes in use` })),
      h('div', { class: 'form-grid' },
        engine.el,
        h('div', { class: 'field' }, h('label', { text: 'Your colour' }), h('div', { class: 'radio-row' },
          h('label', {}, colourWhite, 'White'), h('label', {}, colourBlack, 'Black'))),
        tc.el,
        position.el,
        movetime.el),
      h('details', { class: 'advanced' }, h('summary', { text: 'Advanced' }), h('div', { class: 'form-grid', style: { marginTop: '0.6rem' } }, cap.el)),
      error,
      h('div', { class: 'row' }, start, h('span', { class: 'hint', text: 'The engine runs as a process through the harness. Your clock is shown, not enforced.' })));

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      error.hidden = true;
      start.disabled = true;
      try {
        const chosen = position.value();
        const body = Object.assign({ kind: 'play', engine: engine.value(), human: colourBlack.checked ? 'black' : 'white', ply_cap: cap.value(), fen: chosen.fen, opening: chosen.opening }, tc.value());
        const fixed = movetime.value();
        if (fixed != null) body.stockfish_movetime_ms = fixed;
        storage.set('letal.engine', body.engine);
        storage.set('letal.colour', body.human);
        const state = await api.post('/api/games', body);
        storage.session('letal.playGame', state.id);
        view.flippedByUser = null;
        view.attach(state.id, state);
        form.hidden = true;
        gameHost.hidden = false;
        gameHost.scrollIntoView({ block: 'start', behavior: 'smooth' });
        if (chosen.cursor) toast(`Curated opening ${chosen.cursor}: ${chosen.opening}`);
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
      } finally {
        start.disabled = false;
      }
    });

    const gameHost = h('div', { hidden: true }, view.el);
    main.append(h('div', { class: 'page stack' },
      h('div', { class: 'page-head' }, h('h1', { text: 'Play' }), h('p', { text: 'You against an agent directory, refereed as the platform would.' })),
      form, gameHost));

    const existing = params.get('game') || storage.session('letal.playGame');
    if (existing && params.get('new') == null) {
      try {
        const state = await api.get(`/api/games/${existing}`);
        if (state.kind === 'play') {
          view.attach(state.id, state);
          form.hidden = state.status !== 'finished';
          gameHost.hidden = false;
        }
      } catch (failure) {
        storage.session('letal.playGame', null);
      }
    }
  }

  async function pageSpectate(main, params) {
    const [info, openings] = await Promise.all([loadInfo(true), loadOpenings(), loadAnalysisEngine(true)]);
    const view = views.spectate || (views.spectate = new GameView({ mode: 'spectate', onNewGame: () => { form.hidden = false; form.scrollIntoView({ block: 'start' }); } }));

    const white = engineSelect(info, 'spec-white', 'White', storage.get('letal.specWhite', '.'));
    const black = engineSelect(info, 'spec-black', 'Black', storage.get('letal.specBlack', 'baselines/greedy'));
    const movetime = movetimeField('spec-movetime', [white, black]);
    const position = positionSelect(openings, 'spec-position', params.get('opening'));
    const tc = tcSelect(info, 'spec-tc');
    const cap = plyCapField(info, 'spec-cap');
    const error = h('div', { class: 'error-box', hidden: true });
    const start = h('button', { type: 'submit', class: 'btn-primary' }, 'Start match');
    const swap = h('button', { type: 'button', class: 'btn-sm', onClick: () => { const a = white.select.value; white.select.value = black.select.value; black.select.value = a; movetime.update(); } }, 'Swap colours');
    const form = h('form', { class: 'card stack', 'aria-label': 'New match' },
      h('div', { class: 'row between' }, h('h2', { text: 'New match' }),
        h('span', { class: 'muted', style: { fontSize: '0.82rem' }, text: `${info.engine_slots.used} of ${info.engine_slots.max} engine processes in use` })),
      h('div', { class: 'form-grid' }, white.el, black.el, tc.el, position.el, movetime.el),
      h('div', { class: 'row' }, swap, h('details', { class: 'advanced' }, h('summary', { text: 'Advanced' }), h('div', { class: 'form-grid', style: { marginTop: '0.6rem' } }, cap.el))),
      error,
      h('div', { class: 'row' }, start, h('span', { class: 'hint', text: 'Both agents run as processes. The server plays the game as harness/referee.py does.' })));

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      error.hidden = true;
      start.disabled = true;
      try {
        const chosen = position.value();
        const body = Object.assign({ kind: 'spectate', white: white.value(), black: black.value(), ply_cap: cap.value(), fen: chosen.fen, opening: chosen.opening }, tc.value());
        const fixed = movetime.value();
        if (fixed != null) body.stockfish_movetime_ms = fixed;
        storage.set('letal.specWhite', body.white);
        storage.set('letal.specBlack', body.black);
        const state = await api.post('/api/games', body);
        storage.session('letal.spectateGame', state.id);
        view.flippedByUser = null;
        view.attach(state.id, state);
        form.hidden = true;
        gameHost.hidden = false;
        gameHost.scrollIntoView({ block: 'start', behavior: 'smooth' });
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
      } finally {
        start.disabled = false;
      }
    });

    const gameHost = h('div', { hidden: true }, view.el);
    main.append(h('div', { class: 'page stack' },
      h('div', { class: 'page-head' }, h('h1', { text: 'Spectate' }), h('p', { text: 'Engine against engine, one move at a time, both logs live.' })),
      form, gameHost));

    const existing = params.get('game') || storage.session('letal.spectateGame');
    if (existing && params.get('new') == null) {
      try {
        const state = await api.get(`/api/games/${existing}`);
        if (state.kind === 'spectate') {
          view.attach(state.id, state);
          form.hidden = state.status !== 'finished';
          gameHost.hidden = false;
        }
      } catch (failure) {
        storage.session('letal.spectateGame', null);
      }
    }
  }

  async function pageOverview(main) {
    const info = await loadInfo(true);
    const git = info.git || {};
    const meta = h('dl', { class: 'meta' });
    const row = (label, value) => { if (value != null && value !== '') meta.append(h('dt', { text: label }), h('dd', {}, value)); };
    row('version', info.version ? h('span', { class: 'mono', text: info.version }) : 'unknown');
    row('package', h('span', { class: 'mono', text: info.package }));
    row('branch', git.branch ? h('span', { class: 'mono', text: git.branch }) : null);
    row('commit', git.short ? h('span', { class: 'mono', text: `${git.short}${git.describe && git.describe !== git.short ? ` (${git.describe})` : ''}` }) : null);
    row('working tree', git.dirty == null ? null : (git.dirty ? 'uncommitted changes' : 'clean'));
    row('engine processes', `${info.engine_slots.used} of ${info.engine_slots.max} in use`);

    const results = info.results || {};
    let status;
    if (results.present && results.rows && results.rows.length) {
      const table = h('table', {}, h('thead', {}, h('tr', {}, results.columns.map((column) => h('th', { text: column })))),
        h('tbody', {}, results.rows.map((row) => h('tr', {}, results.columns.map((column) => h('td', { text: row[column] || '' }))))));
      status = h('div', {}, h('p', { class: 'muted', style: { fontSize: '0.85rem' }, text: `last ${results.rows.length} of ${results.total_rows} rows in docs/RESULTS.md` }), h('div', { class: 'table-scroll' }, table));
    } else {
      status = h('p', { class: 'empty', text: results.present ? 'docs/RESULTS.md has no measurements yet. Nothing is claimed until it has been run.' : 'docs/RESULTS.md is not present.' });
    }

    const index = h('ul', { class: 'index-list' },
      h('li', {}, h('a', { href: '#/play', text: 'Play' }), h('span', { text: 'You against the current build, a frozen version or a baseline, with the search log beside the board.' })),
      h('li', {}, h('a', { href: '#/spectate', text: 'Spectate' }), h('span', { text: 'Engine against engine, refereed like a rated game, both logs live.' })),
      h('li', {}, h('a', { href: '#/analysis', text: 'Analysis' }), h('span', { text: 'A finished game graded move by move by a local Stockfish: accuracy, centipawn loss, blunders.' })),
      h('li', {}, h('a', { href: '#/docs', text: 'Docs' }), h('span', { text: 'Design, decisions, results, calibration and provenance, rendered from docs/.' })),
      h('li', {}, h('a', { href: '#/weights', text: 'Weights' }), h('span', { text: 'Piece values and piece-square tables the engine ships, as heatmaps.' })),
      h('li', {}, h('a', { href: '#/openings', text: 'Openings' }), h('span', { text: 'Curated starting positions, each with a board and a way to play it.' })));

    main.append(h('div', { class: 'page stack' },
      h('section', { class: 'title-block' },
        h('h1', { text: info.name || 'Mikhail LeTal' }),
        h('p', { class: 'lede', text: info.tagline }),
        meta),
      h('section', { class: 'card' }, h('h2', { text: 'Sections' }), index),
      h('div', { class: 'grid-2' },
        h('section', { class: 'card prose' },
          h('h2', { text: 'How it works' }),
          h('p', { text: 'The platform sends the engine a position and the time it has left and expects one move back. The engine has four parts.' }),
          h('h3', { text: 'Search' }),
          h('p', { text: 'It looks ahead by trying moves and replies, one ply deeper at a time, until the time budget is used. Lines that cannot change the outcome are skipped (alpha-beta), positions already judged are remembered (a transposition table), and the most promising moves are tried first. That ordering is what makes depth affordable.' }),
          h('h3', { text: 'Evaluation' }),
          h('p', { text: 'At the end of each line it scores the position: material, then where each piece stands, using piece-square tables that blend a middlegame view with an endgame view as pieces leave the board. The tables come from a small set of geometric rules; their provenance ships with the engine.' }),
          h('h3', { text: 'Time management' }),
          h('p', { text: 'Each move gets a soft budget, after which no new iteration starts, and a hard budget, at which the search aborts. Both derive from the clock, the increment and the stage of the game, and always leave a reserve, because running out of time loses.' }),
          h('h3', { text: 'Safety wrapper' }),
          h('p', { text: 'agent.py wraps all of that so nothing can raise. Every move is re-checked for legality on a fresh board, a fast fallback plays when time is short or anything fails, and one compact log line per move records what the search did.' })),
        h('section', { class: 'card' },
          h('h2', { text: 'Competition contract' }),
          h('div', { class: 'table-scroll' }, h('table', {}, h('tbody', {}, (info.contract || []).map((row) => h('tr', {}, h('td', { class: 'muted', style: { whiteSpace: 'nowrap' }, text: row.label }), h('td', {}, row.value, ' ', h('span', { class: 'muted', style: { fontSize: '0.78rem' }, text: row.source }))))))),
          h('p', { class: 'muted', style: { marginTop: '0.8rem', fontSize: '0.82rem' }, text: 'Canonical source: aichessathon.com/docs/rules.md and agent-contract.md. Rows marked harness/rules.py are read from the code.' }))),
      h('section', { class: 'card' }, h('h2', { text: 'Stage status' }), status),
      h('section', { class: 'card' },
        h('h2', { text: 'This server' }),
        h('dl', { class: 'meta' },
          h('dt', { text: 'repository' }), h('dd', { class: 'mono', text: info.root }),
          h('dt', { text: 'saved games' }), h('dd', { class: 'mono', text: info.games_dir }),
          h('dt', { text: 'agents' }), h('dd', {}, info.engines.map((engine, i) => h('span', { title: engine.path }, i ? ' · ' : '', engine.label)))))));
  }

  async function pageDocs(main, params, sub) {
    const documents = await api.get('/api/docs');
    if (!documents.length) {
      main.append(h('div', { class: 'page' }, h('h1', { text: 'Docs' }), h('p', { class: 'empty', text: 'No markdown files under docs/.' })));
      return;
    }
    const current = documents.find((doc) => doc.name === sub) || documents[0];
    const nav = h('nav', { class: 'docs-nav', 'aria-label': 'Documents' }, documents.map((doc) => h('a', { href: `#/docs/${doc.name}`, 'aria-current': doc.name === current.name ? 'page' : null, text: doc.name })));
    const article = h('article', { class: 'card md' });
    article.append(h('div', { class: 'source', text: current.file }));
    const body = h('div');
    body.innerHTML = renderMarkdown(current.content);
    article.append(body);
    main.append(h('div', { class: 'page' },
      h('div', { class: 'page-head' }, h('h1', { text: 'Docs' }), h('p', { text: 'Rendered from docs/ on every load.' })),
      h('div', { class: 'docs-layout' }, nav, article)));
  }

  function heatColour(value, maxAbs) {
    const t = maxAbs ? Math.max(-1, Math.min(1, value / maxAbs)) : 0;
    const root = getComputedStyle(document.documentElement);
    const neg = root.getPropertyValue('--heat-neg').trim() || '#3a6ea5';
    const mid = root.getPropertyValue('--heat-mid').trim() || '#f1eadc';
    const pos = root.getPropertyValue('--heat-pos').trim() || '#9b1c24';
    const mix = (a, b, amount) => {
      const pa = hexToRgb(a);
      const pb = hexToRgb(b);
      return `rgb(${pa.map((channel, index) => Math.round(channel + (pb[index] - channel) * amount)).join(',')})`;
    };
    return t < 0 ? mix(mid, neg, -t) : mix(mid, pos, t);
  }

  function hexToRgb(hex) {
    const clean = hex.replace('#', '');
    const full = clean.length === 3 ? clean.split('').map((char) => char + char).join('') : clean;
    const number = parseInt(full, 16);
    return [(number >> 16) & 255, (number >> 8) & 255, number & 255];
  }

  function heatmap(title, table) {
    const values = Array.isArray(table) ? table.map(Number) : [];
    const maxAbs = Math.max(1, ...values.map((value) => Math.abs(value)));
    const grid = h('div', { class: 'heat', role: 'table', 'aria-label': title });
    for (let row = 0; row < 8; row++) {
      const rank = 8 - row;
      grid.append(h('div', { class: 'lbl', text: String(rank) }));
      for (let file = 0; file < 8; file++) {
        const index = (rank - 1) * 8 + file;
        const value = values[index];
        const background = heatColour(value || 0, maxAbs);
        const strong = Math.abs(value || 0) / maxAbs > 0.55;
        grid.append(h('div', { class: 'cell', style: { background, color: strong ? '#fff' : 'var(--text)' }, title: `${FILES[file]}${rank}: ${value}`, text: value == null ? '' : String(value) }));
      }
    }
    grid.append(h('div', { class: 'lbl' }));
    for (let file = 0; file < 8; file++) grid.append(h('div', { class: 'lbl', text: FILES[file] }));
    const min = values.length ? Math.min(...values) : 0;
    const max = values.length ? Math.max(...values) : 0;
    return h('div', {}, h('div', { class: 'heat-title' }, h('strong', { text: title }), h('span', { class: 'range', text: `${min} .. ${max}` })), grid);
  }

  function renderValue(value) {
    if (value == null) return h('span', { class: 'muted', text: '-' });
    if (Array.isArray(value)) {
      if (value.every((item) => typeof item !== 'object' || item == null)) return h('span', { class: 'mono', text: value.join(', ') });
      return h('div', {}, value.map((item) => renderValue(item)));
    }
    if (typeof value === 'object') {
      const entries = Object.entries(value);
      // A map of uniform records (like _provenance.parameters: name -> {value, why}) reads
      // better as a table with the key as the first column than as nested lists.
      const inner = entries.map(([, item]) => item);
      if (entries.length >= 2 && inner.every((item) => item && typeof item === 'object' && !Array.isArray(item))) {
        const keys = Object.keys(inner[0]);
        if (keys.length && inner.every((item) => Object.keys(item).length === keys.length && keys.every((key) => key in item))) {
          return objectTable(entries.map(([key, item]) => Object.assign({ name: key }, item)));
        }
      }
      const dl = h('dl', { class: 'kv' });
      for (const [key, item] of entries) dl.append(h('dt', { text: key }), h('dd', {}, renderValue(item)));
      return dl;
    }
    return h('span', { class: typeof value === 'number' ? 'mono' : '', text: String(value) });
  }

  function objectTable(rows) {
    const columns = [];
    for (const row of rows) for (const key of Object.keys(row || {})) if (!columns.includes(key)) columns.push(key);
    return h('div', { class: 'table-scroll' }, h('table', {},
      h('thead', {}, h('tr', {}, columns.map((column) => h('th', { text: column })))),
      h('tbody', {}, rows.map((row) => h('tr', {}, columns.map((column) => h('td', {}, renderValue(row ? row[column] : null))))))));
  }

  async function pageWeights(main) {
    const data = await api.get('/api/weights');
    const page = h('div', { class: 'page stack' }, h('div', { class: 'page-head' }, h('h1', { text: 'Weights' }), h('p', { text: 'Evaluation tables the engine ships, read from weights/.' })));
    main.append(page);
    for (const error of data.errors || []) page.append(h('div', { class: 'error-box', text: error }));
    if (!data.present) {
      page.append(h('div', { class: 'card' }, h('h2', { text: 'Not generated yet' }), h('p', { text: 'weights/pst.json does not exist in this checkout. Run tools/gen_pst.py to generate the tables; this page reads the file on every load.' })));
    } else if (data.pst) {
      const pst = data.pst;
      const pieces = ['P', 'N', 'B', 'R', 'Q', 'K'];
      const names = { P: 'Pawn', N: 'Knight', B: 'Bishop', R: 'Rook', Q: 'Queen', K: 'King' };
      const valueRows = pieces.map((piece) => h('tr', {}, h('td', { text: names[piece] }), h('td', { class: 'num mono', text: pst.piece_values_mg ? pst.piece_values_mg[piece] : '' }), h('td', { class: 'num mono', text: pst.piece_values_eg ? pst.piece_values_eg[piece] : '' }), h('td', { class: 'num mono', text: pst.phase_weights && pst.phase_weights[piece] != null ? pst.phase_weights[piece] : '' })));
      const provenance = Object.assign({}, pst._provenance || {});
      const parameters = provenance.parameters;
      delete provenance.parameters;
      page.append(h('div', { class: 'grid-2' },
        h('section', { class: 'card' }, h('h2', { text: 'Piece values and phase weights' }),
          h('div', { class: 'table-scroll' }, h('table', {}, h('thead', {}, h('tr', {}, h('th', { text: 'Piece' }), h('th', { class: 'num', text: 'Middlegame' }), h('th', { class: 'num', text: 'Endgame' }), h('th', { class: 'num', text: 'Phase weight' }))), h('tbody', {}, valueRows))),
          h('p', { class: 'muted', style: { fontSize: '0.85rem', marginTop: '0.6rem' }, text: 'Centipawns. The phase runs from 24 (all non-pawn pieces on the board) to 0 and blends the middlegame and endgame tables.' })),
        h('section', { class: 'card' }, h('h2', { text: 'Mop-up weights and provenance' }),
          renderValue(pst.mopup),
          h('div', { style: { marginTop: '1rem' } }, renderValue(provenance)))));
      if (parameters) page.append(h('section', { class: 'card' }, h('h2', { text: 'Generator parameters' }), renderValue(parameters)));
      const swatches = h('div', { class: 'swatches' }, [-1, -0.5, 0, 0.5, 1].map((t) => h('span', { style: { background: heatColour(t, 1) } })));
      const legend = h('div', { class: 'legend' }, h('span', { text: 'negative' }), swatches, h('span', { text: 'positive, centred on zero, scaled per table' }));
      const heat = h('section', { class: 'card' }, h('h2', { text: 'Piece-square tables' }),
        h('p', { class: 'muted', style: { fontSize: '0.85rem' }, text: 'From White\'s point of view, rank 8 at the top; a Black piece reads the mirrored square. Index a1 = 0 .. h8 = 63 as in python-chess.' }), legend);
      const grid = h('div', { class: 'heat-grid' });
      for (const piece of pieces) {
        const mg = pst.pst_mg ? pst.pst_mg[piece] : null;
        const eg = pst.pst_eg ? pst.pst_eg[piece] : null;
        grid.append(h('div', { class: 'card' }, h('h3', { text: names[piece] }), mg ? heatmap('middlegame', mg) : h('p', { class: 'empty', text: 'no middlegame table' }), eg ? heatmap('endgame', eg) : h('p', { class: 'empty', text: 'no endgame table' })));
      }
      heat.append(h('div', { style: { marginTop: '1rem' } }, grid));
      page.append(heat);
    }
    if (data.provenance_present) {
      const section = h('section', { class: 'card' }, h('h2', { text: 'weights/PROVENANCE.json' }));
      if (Array.isArray(data.provenance)) section.append(objectTable(data.provenance));
      else if (data.provenance) section.append(renderValue(data.provenance));
      page.append(section);
    } else {
      page.append(h('p', { class: 'empty', text: 'weights/PROVENANCE.json is not present.' }));
    }
  }

  async function pageOpenings(main) {
    const data = await loadOpenings(true);
    const page = h('div', { class: 'page stack' }, h('div', { class: 'page-head' }, h('h1', { text: 'Openings' }), h('p', { text: 'Curated starting positions from public games. Rated games start from positions like these.' })));
    main.append(page);
    if (!data.present) {
      page.append(h('div', { class: 'card' }, h('h2', { text: 'No openings file' }), h('p', {}, h('code', { text: data.path }), ' does not exist yet. Run tools/collect_openings.py to collect openings. The eight harness openings below are available meanwhile.')));
    } else {
      page.append(h('p', { class: 'muted', style: { fontSize: '0.9rem' } },
        `${data.count} positions, ${data.names} distinct names`,
        data.invalid ? `, ${data.invalid} invalid FEN${data.invalid === 1 ? '' : 's'}` : '',
        ' · ', h('span', { class: 'mono', text: data.path })));
    }
    const filter = h('input', { type: 'text', class: 'filter', placeholder: 'Filter by name', 'aria-label': 'Filter openings by name' });
    const body = h('tbody');
    const rows = (data.present ? data.openings : []).concat(data.harness.map((opening, index) => ({ index: null, name: opening.name, fen: opening.fen, valid: true, harness: index })));
    const render = () => {
      clear(body);
      const needle = filter.value.trim().toLowerCase();
      let shown = 0;
      for (const opening of rows) {
        if (needle && !(opening.name || '').toLowerCase().includes(needle)) continue;
        shown += 1;
        const target = opening.index != null ? `#/play?opening=${opening.index}&new=1` : `#/play?new=1`;
        body.append(h('tr', {},
          h('td', { class: 'num muted', text: opening.index != null ? String(opening.index + 1) : 'harness' }),
          h('td', {}, h('span', { style: { fontWeight: 500 }, text: opening.name || '(unnamed)' }), opening.valid ? null : h('div', { class: 'chip warn', text: 'invalid FEN' })),
          h('td', {}, opening.valid ? miniBoard(opening.fen) : null),
          h('td', { class: 'fen', text: opening.fen }),
          h('td', {}, opening.valid ? h('a', { class: 'btn btn-sm', href: target, text: 'Play this' }) : null)));
      }
      if (!shown) body.append(h('tr', {}, h('td', { colspan: '5', class: 'empty', text: 'Nothing matches.' })));
    };
    filter.addEventListener('input', render);
    render();
    page.append(h('div', { class: 'card' }, filter, h('div', { class: 'table-scroll', style: { marginTop: '0.75rem' } }, h('table', { class: 'openings-table' },
      h('thead', {}, h('tr', {}, h('th', { class: 'num', text: '#' }), h('th', { text: 'Name' }), h('th', { text: 'Position' }), h('th', { text: 'FEN' }), h('th'))), body))));
  }

  // ------------------------------------------------------------------------------------------
  // Analysis: a finished game graded move by move by the local Stockfish

  const ANNOTATION = { inaccuracy: '?!', mistake: '?', blunder: '??' };
  const JUDGEMENT_TEXT = { best: 'best move', good: 'good move', inaccuracy: 'inaccuracy', mistake: 'mistake', blunder: 'blunder' };
  const GRAPH_CAP_PAWNS = 10; // the eval graph clips here; a forced mate sits on the cap
  const ANALYSIS_POLL_MS = 500;
  const DEPTH_RANGE = [8, 30];
  const MULTIPV_RANGE = [1, 5];

  function ordinal(number) {
    const suffix = number % 10 === 1 && number % 100 !== 11 ? 'st'
      : number % 10 === 2 && number % 100 !== 12 ? 'nd'
        : number % 10 === 3 && number % 100 !== 13 ? 'rd' : 'th';
    return `${number}${suffix}`;
  }

  /** "12. e4 e5 13. Nf3" or "12... e5 13. Nf3 Nc6": a SAN line numbered from where it starts. */
  function numberedLine(sans, moveNumber, mover) {
    const parts = [];
    let number = moveNumber;
    let white = mover === 'white';
    sans.forEach((san, index) => {
      if (white) parts.push(`${number}. ${san}`);
      else parts.push(index === 0 ? `${number}... ${san}` : san);
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

  /** The eval graph's y value in pawns, White's advantage positive, clipped at the cap. */
  function graphValue(ev, fen) {
    const pawns = evalCp(ev, fen) / 100;
    return Math.max(-GRAPH_CAP_PAWNS, Math.min(GRAPH_CAP_PAWNS, pawns));
  }

  /**
   * A ply's evaluation after the move. The wire carries a checkmate on the board as ±1000 cp
   * (a "mate 0" has no sign of its own); here it becomes a mate 0 so the bar and the texts show
   * "#" and the side to move in fen_after, the mated side, settles the sign.
   */
  function evalAfter(ply) {
    return /#$/.test(ply.san) ? { cp: null, mate: 0, pov: 'white' } : ply.eval_after;
  }

  class AnalysisView {
    constructor() {
      this.result = null;
      this.index = 0; // 0 = the starting position, k = after ply k
      this.engineName = '';
      this.keyHandler = (event) => this.onKey(event);
      this.attached = false;

      this.board = new Board({ evalBar: true });
      this.nav = h('div', { class: 'ply-nav' });
      this.detail = h('div', { class: 'detail' });
      this.summaryBox = h('div');
      this.graphBox = h('div');
      this.movesBox = h('div', { class: 'moves analysis' });
      this.title = h('div', { class: 'analysis-title' });
      this.el = h('div', { class: 'analysis-layout', hidden: true },
        h('div', { class: 'analysis-main' },
          h('div', { class: 'board-column with-eval' }, this.board.el, this.nav, this.detail)),
        h('div', { class: 'analysis-side' },
          h('div', { class: 'card' }, h('h3', { text: 'Summary' }), this.title, this.summaryBox),
          h('div', { class: 'card' }, h('h3', { text: 'Evaluation' }), this.graphBox),
          h('div', { class: 'card' }, h('h3', { text: 'Moves' }), this.movesBox)));
    }

    attach() {
      if (!this.attached) document.addEventListener('keydown', this.keyHandler);
      this.attached = true;
    }

    detach() {
      if (this.attached) document.removeEventListener('keydown', this.keyHandler);
      this.attached = false;
    }

    show(result) {
      this.result = result;
      this.index = 0;
      this.el.hidden = false;
      this.board.setFlipped(false);
      this.renderSummary();
      this.renderMoves();
      this.renderGraph();
      this.goTo(0);
    }

    plies() { return this.result ? this.result.plies : []; }

    goTo(index) {
      const plies = this.plies();
      this.index = Math.max(0, Math.min(plies.length, index));
      this.renderBoard();
      this.renderNav();
      this.renderDetail();
      this.updateMoves();
      this.updateGraph();
    }

    onKey(event) {
      if (!this.result || this.el.hidden) return;
      if (event.target.matches('input, select, textarea')) return;
      if (event.key === 'ArrowLeft') this.goTo(this.index - 1);
      else if (event.key === 'ArrowRight') this.goTo(this.index + 1);
      else if (event.key === 'Home') this.goTo(0);
      else if (event.key === 'End') this.goTo(this.plies().length);
      else return;
      event.preventDefault();
    }

    /** The position shown, its evaluation, and the move that led to it (null at the start). */
    current() {
      const plies = this.plies();
      const ply = this.index > 0 ? plies[this.index - 1] : null;
      const fen = ply ? ply.fen_after : this.result.start_fen;
      const ev = ply ? evalAfter(ply) : (plies.length ? plies[0].eval_before : null);
      return { ply, fen, ev, next: this.index < plies.length ? plies[this.index] : null };
    }

    renderBoard() {
      const { ply, fen, ev, next } = this.current();
      this.board.setPosition({ fen, lastMove: ply ? ply.uci : null, check: ply ? checkedKing(fen, ply.san) : null, legal: [], interactive: false });
      this.board.setEval(ev, fen);
      // The arrow is what the engine would play in the position on the board, as lichess draws
      // it, so it always starts from a piece that is there. The move just played is the last-move
      // highlight; what should have been played instead is spelled out in the detail strip.
      this.board.setArrows(next ? [{ from: next.best.uci.slice(0, 2), to: next.best.uci.slice(2, 4), brush: 'green' }] : []);
    }

    renderNav() {
      const nav = this.nav;
      clear(nav);
      const total = this.plies().length;
      const button = (label, target, title) => h('button', { type: 'button', class: 'btn-sm', title, 'aria-label': title, disabled: target === this.index, onClick: () => this.goTo(target) }, label);
      nav.append(
        button('|<', 0, 'First position (Home)'),
        button('<', Math.max(0, this.index - 1), 'Previous move (left arrow)'),
        button('>', Math.min(total, this.index + 1), 'Next move (right arrow)'),
        button('>|', total, 'Last position (End)'),
        h('button', { type: 'button', class: 'btn-sm btn-quiet', onClick: () => { this.board.flip(); } }, 'Flip'),
        h('span', { class: 'pos', text: this.index === 0 ? `start · ${total} plies` : `ply ${this.index} of ${total}` }));
    }

    renderDetail() {
      const box = this.detail;
      clear(box);
      const { ply, ev, fen, next } = this.current();
      const multipv = this.result.engine.multipv;
      if (!ply) {
        box.append(h('div', { class: 'lead' }, h('strong', { text: 'Starting position' }), h('span', { class: 'muted', text: `evaluation ${evalText(ev, fen) || '-'}` })));
        if (next) box.append(h('div', { class: 'line' }, 'engine suggests ', h('span', { class: 'san', text: numberedLine(next.best.line_san || [next.best.san], next.move_number, next.mover) })));
        return;
      }
      const label = `${ply.move_number}${ply.mover === 'white' ? '.' : '...'} ${ply.san}${ANNOTATION[ply.judgement] || ''}`;
      box.append(h('div', { class: 'lead' },
        h('strong', { text: label }),
        h('span', { class: `judgement ${ply.judgement}`, text: JUDGEMENT_TEXT[ply.judgement] || ply.judgement }),
        h('span', { class: 'muted', text: rankText(ply.rank, multipv) })));
      const facts = h('div', { class: 'facts' });
      const fact = (name, value) => facts.append(h('span', {}, `${name} `, h('b', { text: value })));
      fact('eval', `${evalText(ply.eval_before, ply.fen_before)} → ${evalText(evalAfter(ply), ply.fen_after)}`);
      fact(`win% for ${ply.mover}`, `${ply.win_before.toFixed(1)} → ${ply.win_after.toFixed(1)}`);
      fact('cp loss', String(ply.cp_loss));
      fact('accuracy', `${ply.accuracy.toFixed(0)}%`);
      if (ply.clock_after != null) fact('clock', fmt.clock(ply.clock_after * 1000));
      box.append(facts);
      if (ply.rank !== 1) {
        box.append(h('div', { class: 'line' },
          `best was ${ply.best.san} (${evalText(ply.best.eval, ply.fen_before)}): `,
          h('span', { class: 'san', text: numberedLine(ply.best.line_san || [ply.best.san], ply.move_number, ply.mover) })));
      } else if (ply.best.line_san && ply.best.line_san.length > 1) {
        box.append(h('div', { class: 'line' }, 'engine line: ', h('span', { class: 'san', text: numberedLine(ply.best.line_san, ply.move_number, ply.mover) })));
      }
      if (ply.top && ply.top.length > 1) {
        box.append(h('div', { class: 'line muted' }, `top ${ply.top.length}: `, ply.top.map((candidate, i) => `${i ? ' · ' : ''}${candidate.san} ${evalText(candidate.eval, ply.fen_before)}`).join('')));
      }
    }

    renderSummary() {
      const { headers, summary, engine } = this.result;
      clear(this.title);
      clear(this.summaryBox);
      this.title.append(
        h('div', { class: 'players' }, h('strong', { text: headers.White || 'White' }), ' vs ', h('strong', { text: headers.Black || 'Black' }), ' ', h('span', { class: 'num', text: headers.Result || '*' })),
        h('div', { class: 'muted small' },
          [headers.Event, headers.Date, headers.Termination].filter(Boolean).join(' · '),
          ` · ${engine.name}, depth ${engine.depth}, ${engine.multipv} line${engine.multipv === 1 ? '' : 's'}`));
      const ours = (name) => this.engineName && name && name.startsWith(this.engineName);
      const head = (side) => h('th', {},
        h('span', { text: side.name || '' }),
        h('span', { class: `chip ${ours(side.name) ? 'accent' : ''}`, text: ours(side.name) ? 'our engine' : '' }));
      const pct = (value) => `${Number(value).toFixed(1)}%`;
      const rows = [
        ['Moves', (side) => String(side.moves)],
        ['Best move', (side) => `${pct(side.best_move_pct)} (${side.best_moves})`],
        ['Top-3', (side) => (engine.multipv >= 3 ? `${pct(side.top3_pct)} (${side.top3_moves})` : 'needs 3 lines')],
        ['ACPL', (side) => Number(side.acpl).toFixed(1)],
        ['Accuracy (mean)', (side) => pct(side.accuracy)],
        ['Inaccuracies', (side) => String(side.inaccuracies)],
        ['Mistakes', (side) => String(side.mistakes)],
        ['Blunders', (side) => String(side.blunders)],
      ];
      this.summaryBox.append(h('div', { class: 'table-scroll' }, h('table', { class: 'summary-table' },
        h('thead', {}, h('tr', {}, h('th', { text: '' }), head(summary.white), head(summary.black))),
        h('tbody', {}, rows.map(([label, value]) => h('tr', {}, h('th', { scope: 'row', text: label }), h('td', { text: value(summary.white) }), h('td', { text: value(summary.black) })))))));
      this.summaryBox.append(h('p', { class: 'hint', style: { marginTop: '0.6rem' }, text: 'lichess\'s formulas for win%, accuracy and judgements; the side accuracy is a plain mean of the per-move values, not lichess\'s windowed harmonic mean. Mates count as ±1000 cp.' }));
    }

    // -- eval graph -----------------------------------------------------------------------

    renderGraph() {
      const plies = this.plies();
      const box = this.graphBox;
      clear(box);
      if (!plies.length) { box.append(h('p', { class: 'empty', text: 'no moves' })); return; }
      const width = 400;
      const height = 130;
      const pad = { left: 24, right: 6, top: 8, bottom: 8 };
      const innerWidth = width - pad.left - pad.right;
      const innerHeight = height - pad.top - pad.bottom;
      const zeroY = pad.top + innerHeight / 2;
      const values = [graphValue(plies[0].eval_before, plies[0].fen_before)].concat(plies.map((ply) => graphValue(evalAfter(ply), ply.fen_after)));
      const step = innerWidth / Math.max(1, values.length - 1);
      const x = (index) => pad.left + index * step;
      const y = (value) => zeroY - (value / GRAPH_CAP_PAWNS) * (innerHeight / 2);
      const uid = this.board.uid;
      const points = values.map((value, index) => `${x(index).toFixed(1)},${y(value).toFixed(1)}`);
      const area = `M${x(0).toFixed(1)},${zeroY.toFixed(1)} L${points.join(' L')} L${x(values.length - 1).toFixed(1)},${zeroY.toFixed(1)} Z`;
      const graph = svg('svg', { class: 'eval-graph', viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Evaluation over the game, White advantage upwards' },
        svg('defs', {},
          svg('clipPath', { id: `${uid}-above` }, svg('rect', { x: 0, y: 0, width, height: zeroY })),
          svg('clipPath', { id: `${uid}-below` }, svg('rect', { x: 0, y: zeroY, width, height: height - zeroY }))),
        svg('path', { class: 'area-white', d: area, 'clip-path': `url(#${uid}-above)` }),
        svg('path', { class: 'area-black', d: area, 'clip-path': `url(#${uid}-below)` }),
        svg('line', { class: 'grid', x1: pad.left, x2: width - pad.right, y1: y(5).toFixed(1), y2: y(5).toFixed(1) }),
        svg('line', { class: 'grid', x1: pad.left, x2: width - pad.right, y1: y(-5).toFixed(1), y2: y(-5).toFixed(1) }),
        svg('line', { class: 'axis', x1: pad.left, x2: width - pad.right, y1: zeroY.toFixed(1), y2: zeroY.toFixed(1) }),
        svg('line', { class: 'axis', x1: pad.left, x2: pad.left, y1: pad.top, y2: height - pad.bottom }),
        svg('text', { x: pad.left - 4, y: y(GRAPH_CAP_PAWNS) + 4, 'text-anchor': 'end', text: '' }, `+${GRAPH_CAP_PAWNS}`),
        svg('text', { x: pad.left - 4, y: zeroY + 3, 'text-anchor': 'end' }, '0'),
        svg('text', { x: pad.left - 4, y: y(-GRAPH_CAP_PAWNS) + 2, 'text-anchor': 'end' }, `-${GRAPH_CAP_PAWNS}`),
        svg('polyline', { class: 'curve', points: points.join(' ') }));
      // Mistakes and blunders get a mark on the point after the move so the eye finds them.
      plies.forEach((ply, index) => {
        if (ply.judgement === 'blunder' || ply.judgement === 'mistake') {
          graph.append(svg('circle', { class: `mark ${ply.judgement}`, cx: x(index + 1).toFixed(1), cy: y(values[index + 1]).toFixed(1), r: 2.6 }));
        }
      });
      this.cursorLine = svg('line', { class: 'cursor', y1: pad.top, y2: height - pad.bottom });
      this.cursorDot = svg('circle', { class: 'cursor-dot', r: 3 });
      graph.append(this.cursorLine, this.cursorDot);
      values.forEach((value, index) => {
        const label = index === 0 ? 'start' : `ply ${index}, ${plies[index - 1].san}, ${evalText(evalAfter(plies[index - 1]), plies[index - 1].fen_after)}`;
        const hit = svg('rect', {
          class: 'hit', x: (x(index) - step / 2).toFixed(1), y: pad.top, width: step.toFixed(2), height: innerHeight,
        }, svg('title', {}, label));
        hit.addEventListener('click', () => this.goTo(index));
        graph.append(hit);
      });
      this.graphGeometry = { x, y, values };
      box.append(graph);
      box.append(h('div', { class: 'graph-caption' }, h('span', { text: 'White advantage up, ±10 pawns (mates on the cap)' }), h('span', { text: 'click to jump' })));
    }

    updateGraph() {
      const geometry = this.graphGeometry;
      if (!geometry || !this.cursorLine) return;
      const cx = geometry.x(this.index).toFixed(1);
      this.cursorLine.setAttribute('x1', cx);
      this.cursorLine.setAttribute('x2', cx);
      this.cursorDot.setAttribute('cx', cx);
      this.cursorDot.setAttribute('cy', geometry.y(geometry.values[this.index]).toFixed(1));
    }

    // -- move list ------------------------------------------------------------------------

    renderMoves() {
      const plies = this.plies();
      const box = this.movesBox;
      clear(box);
      this.moveButtons = [];
      if (!plies.length) { box.append(h('div', { class: 'empty', text: 'no moves' })); return; }
      const body = h('tbody');
      const cell = (ply) => {
        const annotation = ANNOTATION[ply.judgement];
        const button = h('button', {
          type: 'button', class: 'mv', title: `${JUDGEMENT_TEXT[ply.judgement]}, ${rankText(ply.rank, this.result.engine.multipv)}`,
          onClick: () => this.goTo(ply.ply),
        },
        h('span', {}, ply.san, annotation ? h('span', { class: 'ann', text: annotation }) : null),
        ply.rank === 1 ? h('span', { class: 'ann best', title: 'engine\'s first choice', text: '✓' }) : null,
        h('span', { class: 'ev', text: evalText(evalAfter(ply), ply.fen_after) }));
        this.moveButtons[ply.ply] = button;
        return h('td', {}, button);
      };
      let index = 0;
      if (plies[0].mover === 'black') {
        body.append(h('tr', {}, h('td', { class: 'n', text: `${plies[0].move_number}.` }), h('td', { class: 'muted', text: '...' }), cell(plies[0])));
        index = 1;
      }
      for (; index < plies.length; index += 2) {
        const white = plies[index];
        const black = plies[index + 1];
        body.append(h('tr', {}, h('td', { class: 'n', text: `${white.move_number}.` }), cell(white), black ? cell(black) : h('td')));
      }
      box.append(h('table', {}, body));
      const counts = { inaccuracy: 0, mistake: 0, blunder: 0 };
      for (const ply of plies) if (counts[ply.judgement] != null) counts[ply.judgement] += 1;
      box.append(h('div', { class: 'legend-line', style: { marginTop: '0.5rem' }, text: `?! inaccuracy (${counts.inaccuracy}) · ? mistake (${counts.mistake}) · ?? blunder (${counts.blunder}) · ✓ engine's first choice · eval after the move` }));
    }

    updateMoves() {
      const buttons = this.moveButtons || [];
      buttons.forEach((button, ply) => {
        if (!button) return;
        const current = ply === this.index;
        button.classList.toggle('current', current);
        button.closest('tr').classList.toggle('current-row', current);
        if (current) {
          // Keep the row in view without scrolling the page (scrollIntoView would).
          const box = this.movesBox;
          const top = button.offsetTop - box.clientHeight / 2;
          if (Math.abs(box.scrollTop - top) > box.clientHeight / 3) box.scrollTop = top;
        }
      });
    }
  }

  async function pageAnalysis(main, params) {
    const [engine, info] = await Promise.all([loadAnalysisEngine(true), loadInfo()]);
    const view = views.analysis || (views.analysis = new AnalysisView());
    view.engineName = info.name || 'Mikhail LeTal';
    view.attach();
    let sources = { games: [], files: [] };
    let sourcesError = null;
    try {
      sources = await api.get('/api/analysis/sources');
    } catch (error) {
      sourcesError = error.status === 404 ? 'this server has no analysis API' : error.message;
    }

    // -- engine status -----------------------------------------------------------------------
    const status = h('div', { class: 'engine-status' },
      h('span', { class: `chip ${engine.available ? 'ok' : 'warn'}`, text: engine.available ? 'available' : 'unavailable' }),
      engine.available
        ? [h('strong', { text: engine.name || 'UCI engine' }), h('span', { class: 'mono muted', style: { fontSize: '0.8rem' }, text: engine.path || '' })]
        : h('span', { text: engine.reason || 'no engine' }));
    const engineCard = h('section', { class: 'card' }, h('h2', { text: 'Analysis engine' }), status,
      h('p', { class: 'hint', style: { marginTop: '0.6rem', maxWidth: '72ch' }, text: 'Stockfish is a local-only instrument: it lives outside the repository (YARDSTICK_ENGINE, else ~/.local/opt/stockfish/stockfish, else on PATH), never enters the zip, and never influences a move our engine plays. Here it only grades games already played.' }));

    // -- the form ----------------------------------------------------------------------------
    const finishedGames = sources.games.filter((game) => game.finished);
    const gameSelect = h('select', { id: 'an-game', disabled: !finishedGames.length });
    if (finishedGames.length) finishedGames.forEach((game) => gameSelect.append(h('option', { value: game.id, text: game.label })));
    else gameSelect.append(h('option', { value: '', text: 'no finished games in this session' }));
    const fileSelect = h('select', { id: 'an-file', disabled: !sources.files.length });
    if (sources.files.length) sources.files.forEach((file) => fileSelect.append(h('option', { value: file.path, text: `${file.label}${file.date ? ` · ${file.date}` : ''} · ${file.path}` })));
    else fileSelect.append(h('option', { value: '', text: 'no PGN files under data/webapp_games or data/pgn' }));
    const pgnArea = h('textarea', { id: 'an-pgn', class: 'mono', placeholder: '[Event "..."]\n\n1. e4 e5 2. Nf3 ...', spellcheck: 'false' });
    const kinds = [['game', 'This session', gameSelect], ['file', 'Saved PGN file', fileSelect], ['pgn', 'Paste a PGN', pgnArea]];
    const stored = storage.get('letal.analysisSource', finishedGames.length ? 'game' : 'file');
    const radios = kinds.map(([value, label]) => h('input', { type: 'radio', name: 'an-source', value, checked: value === stored }));
    const sourceRows = kinds.map(([value, label, control]) => h('div', { class: 'field', hidden: true }, h('label', { for: control.id, text: label }), control));
    const updateSource = () => {
      radios.forEach((radio, i) => { sourceRows[i].hidden = !radio.checked; });
    };
    radios.forEach((radio) => radio.addEventListener('change', updateSource));
    updateSource();
    const depth = h('input', { type: 'number', id: 'an-depth', min: String(DEPTH_RANGE[0]), max: String(DEPTH_RANGE[1]), step: '1', value: String(storage.get('letal.analysisDepth', 18)) });
    const multipv = h('input', { type: 'number', id: 'an-lines', min: String(MULTIPV_RANGE[0]), max: String(MULTIPV_RANGE[1]), step: '1', value: String(storage.get('letal.analysisLines', 3)) });
    const error = h('div', { class: 'error-box', hidden: true });
    const analyse = h('button', { type: 'submit', class: 'btn-primary', disabled: !engine.available, title: engine.available ? null : engine.reason }, 'Analyse');
    const form = h('form', { class: 'card stack', 'aria-label': 'Analyse a game' },
      h('h2', { text: 'Analyse a game' }),
      sourcesError ? h('div', { class: 'error-box', text: `sources could not be listed: ${sourcesError}` }) : null,
      h('div', { class: 'field' }, h('label', { text: 'Source' }), h('div', { class: 'radio-row' }, kinds.map(([value, label], i) => h('label', {}, radios[i], label)))),
      sourceRows,
      h('div', { class: 'form-grid' },
        h('div', { class: 'field' }, h('label', { for: 'an-depth', text: `Depth (${DEPTH_RANGE[0]}..${DEPTH_RANGE[1]})` }), depth),
        h('div', { class: 'field' }, h('label', { for: 'an-lines', text: `Lines (${MULTIPV_RANGE[0]}..${MULTIPV_RANGE[1]}, top-3 needs 3)` }), multipv)),
      error,
      h('div', { class: 'row' }, analyse, h('span', { class: 'hint', text: 'Every position is searched once at this depth; the same game and settings are served from the cache.' })));

    // -- progress and jobs -------------------------------------------------------------------
    const progressText = h('div', { class: 'muted' });
    const progressFill = h('div', { class: 'fill', style: { width: '0%' } });
    const cancel = h('button', { type: 'button', class: 'btn-sm' }, 'Cancel');
    const progressCard = h('section', { class: 'card progress', hidden: true }, h('h2', { text: 'Running' }), progressText, h('div', { class: 'track' }, progressFill), h('div', { class: 'row' }, cancel));
    const jobsList = h('ul', { class: 'jobs-list' });
    const jobsCard = h('section', { class: 'card', hidden: true }, h('h2', { text: 'Analyses on this server' }), jobsList);

    let pollTimer = null;
    let currentJob = null;
    const stopPolling = () => { clearInterval(pollTimer); pollTimer = null; };
    view.stopPolling = stopPolling;

    const parameters = () => {
      const clampInt = (input, [low, high], fallback) => {
        const number = Math.round(Number(input.value));
        return Number.isFinite(number) ? Math.max(low, Math.min(high, number)) : fallback;
      };
      const values = { depth: clampInt(depth, DEPTH_RANGE, 18), multipv: clampInt(multipv, MULTIPV_RANGE, 3) };
      storage.set('letal.analysisDepth', values.depth);
      storage.set('letal.analysisLines', values.multipv);
      return values;
    };

    async function refreshJobs() {
      try {
        const payload = await api.get('/api/analysis/jobs');
        clear(jobsList);
        const jobs = payload.jobs || [];
        jobsCard.hidden = !jobs.length;
        for (const job of jobs.slice().reverse()) {
          const progress = job.progress || { done: 0, total: 0 };
          jobsList.append(h('li', {},
            h('span', { class: `job-status ${job.status}`, text: job.status }),
            h('a', { href: `#/analysis?job=${encodeURIComponent(job.job_id)}`, onClick: (event) => { event.preventDefault(); openJob(job.job_id); }, text: job.label || job.job_id }),
            job.status === 'running' || job.status === 'queued'
              ? [h('span', { class: 'muted', text: progress.total ? `${progress.done} of ${progress.total}` : 'waiting' }),
                h('button', { type: 'button', class: 'btn-sm btn-quiet', onClick: () => cancelJob(job.job_id) }, 'Cancel')]
              : null));
        }
      } catch (failure) {
        jobsCard.hidden = true;
      }
    }

    async function cancelJob(jobId) {
      try { await api.del(`/api/analysis/${encodeURIComponent(jobId)}`); } catch (failure) { toast(failure.message, true); }
      refreshJobs();
    }

    function showJob(job) {
      const progress = job.progress || { done: 0, total: 0 };
      if (job.status === 'queued' || job.status === 'running') {
        progressCard.hidden = false;
        progressText.textContent = `${job.label || job.job_id}: ${job.status === 'queued' ? 'queued' : `position ${progress.done} of ${progress.total || '?'}`}`;
        progressFill.style.width = progress.total ? `${(100 * progress.done / progress.total).toFixed(1)}%` : '0%';
        cancel.disabled = false;
        return false;
      }
      progressCard.hidden = true;
      if (job.status === 'done' && job.result) {
        view.show(job.result);
        view.el.scrollIntoView({ block: 'start', behavior: 'smooth' });
      } else if (job.status === 'failed') {
        error.textContent = `analysis failed: ${job.error || 'unknown error'}`;
        error.hidden = false;
      } else if (job.status === 'cancelled') {
        toast('Analysis cancelled');
      }
      return true;
    }

    function openJob(jobId) {
      stopPolling();
      currentJob = jobId;
      history.replaceState(null, '', `#/analysis?job=${encodeURIComponent(jobId)}`);
      let ticks = 0;
      const poll = async () => {
        if (currentJob !== jobId) return;
        let job;
        try {
          job = await api.get(`/api/analysis/${encodeURIComponent(jobId)}`);
        } catch (failure) {
          stopPolling();
          progressCard.hidden = true;
          error.textContent = failure.message;
          error.hidden = false;
          return;
        }
        if (currentJob !== jobId) return;
        const finished = showJob(job);
        ticks += 1;
        if (finished || ticks % 4 === 0) refreshJobs();
        if (finished) stopPolling();
      };
      poll();
      pollTimer = setInterval(poll, ANALYSIS_POLL_MS);
    }
    cancel.addEventListener('click', () => { if (currentJob) { cancel.disabled = true; cancelJob(currentJob); } });

    async function submit(source) {
      error.hidden = true;
      analyse.disabled = true;
      try {
        const body = Object.assign({ source }, parameters());
        const created = await api.post('/api/analysis', body);
        if (created.cached) toast('Served from the analysis cache');
        openJob(created.job_id);
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
      } finally {
        analyse.disabled = !engine.available;
      }
    }

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const kind = radios.find((radio) => radio.checked);
      const value = kind ? kind.value : 'game';
      storage.set('letal.analysisSource', value);
      if (value === 'game') {
        if (!gameSelect.value) { error.textContent = 'no finished game to analyse; play or watch one first'; error.hidden = false; return; }
        submit({ game_id: gameSelect.value });
      } else if (value === 'file') {
        if (!fileSelect.value) { error.textContent = 'no PGN file to analyse'; error.hidden = false; return; }
        submit({ file: fileSelect.value });
      } else {
        const text = pgnArea.value.trim();
        if (!text) { error.textContent = 'paste a PGN first'; error.hidden = false; return; }
        submit({ pgn: text });
      }
    });

    main.append(h('div', { class: 'page stack' },
      h('div', { class: 'page-head' }, h('h1', { text: 'Analysis' }), h('p', { text: 'A finished game graded move by move: evaluation, centipawn loss, accuracy, and what the engine would have played.' })),
      engineCard, form, progressCard, jobsCard, view.el));

    refreshJobs();
    if (params.get('job')) openJob(params.get('job'));
    else if (params.get('game') && engine.available) submit({ game_id: params.get('game') });
    else if (params.get('file') && engine.available) submit({ file: params.get('file') });
    else if (params.get('game') || params.get('file')) {
      error.textContent = `cannot analyse: ${engine.reason}`;
      error.hidden = false;
    }
  }

  // ------------------------------------------------------------------------------------------
  // Router

  const routes = { overview: pageOverview, play: pagePlay, spectate: pageSpectate, analysis: pageAnalysis, docs: pageDocs, weights: pageWeights, openings: pageOpenings };
  let currentRoute = null;

  function parseHash() {
    const hash = location.hash.replace(/^#\/?/, '');
    const [pathPart, query = ''] = hash.split('?');
    const [route, ...rest] = pathPart.split('/');
    return { route: routes[route] ? route : 'overview', sub: rest.join('/') || null, params: new URLSearchParams(query) };
  }

  async function navigate() {
    const { route, sub, params } = parseHash();
    const main = $('#main');
    for (const link of document.querySelectorAll('#nav a')) {
      if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
    // Leaving a game page keeps its view alive but stops polling; coming back re-attaches.
    if (currentRoute === 'play' && route !== 'play' && views.play) views.play.detach();
    if (currentRoute === 'spectate' && route !== 'spectate' && views.spectate) views.spectate.detach();
    if (currentRoute === 'analysis' && route !== 'analysis' && views.analysis) {
      views.analysis.detach();
      if (views.analysis.stopPolling) views.analysis.stopPolling();
    }
    currentRoute = route;
    clear(main);
    document.title = route === 'overview' ? 'Mikhail LeTal' : `${route[0].toUpperCase()}${route.slice(1)} · Mikhail LeTal`;
    try {
      await routes[route](main, params, sub);
    } catch (error) {
      clear(main);
      main.append(h('div', { class: 'page' }, h('div', { class: 'error-box' }, h('strong', { text: 'Could not load this page. ' }), error.message)));
    }
    if (params.get('new') != null && (route === 'play' || route === 'spectate')) {
      history.replaceState(null, '', `#/${route}${params.get('opening') != null ? `?opening=${params.get('opening')}` : ''}`);
    }
  }

  async function renderFooter() {
    try {
      const info = await loadInfo();
      const git = info.git || {};
      $('#footer').append(
        h('span', {}, `${info.name} `, info.version ? h('span', { class: 'mono', text: `v${info.version}` }) : null),
        git.short ? h('span', {}, 'commit ', h('span', { class: 'mono', text: git.short }), git.dirty ? ', modified' : '') : null,
        h('span', { text: 'Local playground. Nothing here is a rated result.' }));
    } catch (error) {
      $('#footer').append(h('span', { text: 'Server not reachable.' }));
    }
    $('#footer').append(h('span', {}, 'Pieces: cburnett set by Colin M.L. Burnett, ',
      h('a', { href: '/static/pieces/cburnett/LICENSE.txt', target: '_blank', rel: 'noopener', text: 'CC BY-SA 3.0' }), '.'));
  }

  window.addEventListener('hashchange', navigate);
  window.addEventListener('beforeunload', () => {
    for (const view of Object.values(views)) if (view) view.detach();
  });
  renderFooter();
  navigate();
})();
