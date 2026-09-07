/* Mikhail LeTal web app — the board: 64 <button> squares in an 8x8 grid inside a container-query
   box, click-click and pointer-drag moves, the promotion strip, keyboard access, an arrow layer.
   Two visual styles share the DOM: "studio" (the handoff) and "lichess" (see board.css). */
(() => {
  'use strict';
  const LT = window.LT;
  const PROMOTION_ORDER = ['q', 'r', 'b', 'n'];
  const BRUSHES = { green: '#15781B', red: '#882020', blue: '#003088', yellow: '#e68f00' };
  let uidCounter = 0;

  class Board {
    /**
     * new LT.Board(container, {interactive, flipped, style})
     * style: 'studio' | 'lichess' | undefined (follow LT.boardStyle, the nav bar control)
     */
    constructor(container, options = {}) {
      this.el = container;
      this.uid = `b${(uidCounter += 1)}`;
      this.flipped = !!options.flipped;
      this.fixedStyle = options.style || null;
      this.style = this.fixedStyle || LT.boardStyle.get();
      this.position = { fen: LT.START_FEN, lastMove: null, check: null, legal: [], interactive: !!options.interactive };
      this.moveHandler = null;
      this.selected = null;
      this.legalMap = new Map();
      this.drag = null;
      this.suppressClick = false;
      this.promo = null;
      this.pending = null;
      this.arrows = [];
      this.pieceKeys = new Array(64).fill('');

      this.grid = LT.el('div', { class: 'board-grid', role: 'grid', 'aria-label': 'Chess board' });
      this.cells = [];
      for (let i = 0; i < 64; i++) {
        const cell = LT.el('button', { class: 'sq', type: 'button', role: 'gridcell', tabindex: i === 0 ? '0' : '-1' },
          LT.el('span', { class: 'ov' }));
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
      this.arrowLayer = LT.svg('svg', { class: 'board-arrows', viewBox: '0 0 8 8', 'aria-hidden': 'true' });
      this.grid.append(this.arrowLayer);
      this.box = LT.el('div', { class: 'board-box' }, this.grid);
      this.el.classList.add('lt-board');
      this.el.append(this.box);
      this.unsubscribe = this.fixedStyle ? null : LT.boardStyle.onChange((style) => this.setStyle(style));
      this.applyStyle();
      this.layout();
    }

    destroy() {
      if (this.unsubscribe) this.unsubscribe();
      this.cancelDrag(false);
      this.closePromo();
    }

    onMove(callback) { this.moveHandler = callback; return this; }

    // -- geometry ---------------------------------------------------------------------------------
    squareAt(row, col) { return this.flipped ? row * 8 + (7 - col) : (7 - row) * 8 + col; }
    cellPos(square) {
      const rank = Math.floor(square / 8);
      const file = square % 8;
      return this.flipped ? [rank, 7 - file] : [7 - rank, file];
    }

    layout() {
      for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
          const cell = this.cells[row * 8 + col];
          const square = this.squareAt(row, col);
          cell.dataset.square = LT.squareName(square);
          cell.dataset.dark = (Math.floor(square / 8) + square) % 2 === 0 ? '1' : '';
        }
      }
      this.render();
      this.drawArrows();
    }

    flip() { this.setFlipped(!this.flipped); }
    setFlipped(flipped) {
      if (this.flipped === !!flipped) return;
      this.flipped = !!flipped;
      this.closePromo();
      this.layout();
    }

    applyStyle() {
      this.el.classList.toggle('lt-board--studio', this.style === 'studio');
      this.el.classList.toggle('lt-board--lichess', this.style === 'lichess');
    }
    setStyle(style) {
      if (!LT.boardStyle.STYLES.includes(style) || style === this.style) return;
      this.style = style;
      this.applyStyle();
      this.render();
    }

    // -- state ------------------------------------------------------------------------------------
    /**
     * setPosition(fen, {lastMove: [from, to] | "e2e4", check: "e1" | null, targets|legal: [uci], interactive})
     * Legal moves are the server's; the board never invents one.
     */
    setPosition(fen, options = {}) {
      const previous = this.position;
      const lastMove = Array.isArray(options.lastMove) ? options.lastMove
        : (typeof options.lastMove === 'string' ? [options.lastMove.slice(0, 2), options.lastMove.slice(2, 4)] : options.lastMove === undefined ? previous.lastMove : null);
      const legal = options.targets || options.legal || [];
      const interactive = options.interactive === undefined ? previous.interactive : !!options.interactive;
      this.position = { fen: fen || previous.fen, lastMove, check: options.check === undefined ? previous.check : options.check, legal, interactive };
      const changed = previous.fen !== this.position.fen;
      if (changed || !interactive) this.selected = null;
      if (changed || interactive) this.pending = null;
      this.legalMap = new Map();
      for (const uci of legal) {
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

    /** arrows: [{from, to, brush}] in square names. */
    setArrows(arrows) {
      this.arrows = (arrows || []).filter((arrow) => arrow && arrow.from && arrow.to && arrow.from !== arrow.to);
      this.drawArrows();
    }

    render() {
      const { fen, lastMove, check, interactive } = this.position;
      const squares = LT.parseFen(fen);
      if (this.pending) this.applyPending(squares);
      const lastFrom = lastMove ? lastMove[0] : null;
      const lastTo = lastMove ? lastMove[1] : null;
      const dests = new Set(this.selected && this.legalMap.has(this.selected) ? this.legalMap.get(this.selected).map((entry) => entry.to) : []);
      const dragging = this.drag && this.drag.moved ? this.drag : null;
      const studio = this.style === 'studio';
      for (let row = 0; row < 8; row++) {
        for (let col = 0; col < 8; col++) {
          const index = row * 8 + col;
          const cell = this.cells[index];
          const square = this.squareAt(row, col);
          const name = LT.squareName(square);
          const piece = squares[square];
          const movable = interactive && this.legalMap.has(name);
          const isDest = dests.has(name);
          // Everything but the piece is cheap to rebuild; the piece element survives while the same
          // piece stays on the square so the settle runs only when a piece lands.
          for (const child of Array.from(cell.children)) if (!child.classList.contains('pc')) child.remove();
          const overlay = LT.el('span', { class: 'ov' });
          cell.prepend(overlay);
          const rankHere = studio ? col === 0 : col === 7;
          if (rankHere) cell.append(LT.el('span', { class: 'coord rank', text: String(Math.floor(square / 8) + 1) }));
          if (row === 7) cell.append(LT.el('span', { class: 'coord file', text: LT.FILES[square % 8] }));
          if (isDest) cell.append(LT.el('span', { class: `dot${piece ? ' cap' : ''}` }));
          const key = piece ? `${piece.color}${piece.type}` : '';
          let pieceNode = cell.querySelector('.pc');
          if (key !== this.pieceKeys[index] || (pieceNode == null) !== (key === '')) {
            if (pieceNode) pieceNode.remove();
            pieceNode = piece ? this.pieceNode(piece) : null;
            if (pieceNode) cell.append(pieceNode);
            this.pieceKeys[index] = key;
          }
          if (pieceNode) pieceNode.classList.toggle('faded', !!(dragging && dragging.from === name));
          cell.className = `sq ${cell.dataset.dark ? 'dark' : 'light'}`
            + (lastFrom === name || lastTo === name ? ' last' : '')
            + (this.selected === name ? ' selected' : '')
            + (check === name ? ' check' : '')
            + (movable ? ' movable' : '')
            + (isDest ? ' target' : '')
            + (dragging && dragging.over === name && isDest ? ' over' : '');
          const description = piece ? `${piece.color === 'w' ? 'White' : 'Black'} ${LT.PIECE_NAME[piece.type]} on ${name}` : `${name}, empty`;
          cell.setAttribute('aria-label', description + (isDest ? ', legal target' : '') + (this.selected === name ? ', selected' : ''));
          cell.setAttribute('aria-selected', this.selected === name ? 'true' : 'false');
        }
      }
    }

    pieceNode(piece, extra = '') {
      return LT.el('span', { class: `pc ${piece.color} ${piece.type}${extra ? ` ${extra}` : ''}`, text: LT.GLYPH[piece.type], 'aria-hidden': 'true' });
    }

    /** Show a dropped move at once; the server's position replaces it within a round trip. */
    applyPending(squares) {
      const from = LT.squareIndex(this.pending.uci.slice(0, 2));
      const to = LT.squareIndex(this.pending.uci.slice(2, 4));
      const piece = squares[from];
      if (!piece) return;
      const promo = this.pending.uci.slice(4, 5);
      const wasEmpty = !squares[to];
      squares[to] = promo ? { color: piece.color, type: promo } : piece;
      squares[from] = null;
      if (piece.type === 'k' && Math.abs(to - from) === 2) {
        const rank = Math.floor(from / 8) * 8;
        const [rookFrom, rookTo] = to > from ? [rank + 7, rank + 5] : [rank, rank + 3];
        squares[rookTo] = squares[rookFrom];
        squares[rookFrom] = null;
      }
      if (piece.type === 'p' && from % 8 !== to % 8 && wasEmpty) squares[to + (piece.color === 'w' ? -8 : 8)] = null;
    }

    // -- arrows -----------------------------------------------------------------------------------
    centre(name) {
      const [row, col] = this.cellPos(LT.squareIndex(name));
      return [col + 0.5, row + 0.5];
    }

    drawArrows() {
      const layer = this.arrowLayer;
      LT.clear(layer);
      if (!this.arrows.length) return;
      // chessground's geometry: stroke 10/64 of a square, a triangular marker, the shaft stopped
      // 10/64 short of the destination centre so the tip sits on the centre.
      const width = 10 / 64;
      const margin = 10 / 64;
      const defs = LT.svg('defs');
      const used = new Set();
      for (const arrow of this.arrows) {
        const brush = BRUSHES[arrow.brush] ? arrow.brush : 'green';
        if (used.has(brush)) continue;
        used.add(brush);
        defs.append(LT.svg('marker', { id: `${this.uid}-${brush}`, orient: 'auto', markerWidth: 4, markerHeight: 4, refX: 2.05, refY: 2 },
          LT.svg('path', { d: 'M0,0 V4 L3,2 Z', fill: BRUSHES[brush] })));
      }
      layer.append(defs);
      for (const arrow of this.arrows) {
        const brush = BRUSHES[arrow.brush] ? arrow.brush : 'green';
        const [x1, y1] = this.centre(arrow.from);
        const [x2, y2] = this.centre(arrow.to);
        const angle = Math.atan2(y2 - y1, x2 - x1);
        layer.append(LT.svg('line', {
          x1: x1.toFixed(3), y1: y1.toFixed(3),
          x2: (x2 - Math.cos(angle) * margin).toFixed(3), y2: (y2 - Math.sin(angle) * margin).toFixed(3),
          stroke: BRUSHES[brush], 'stroke-width': width.toFixed(4), 'stroke-linecap': 'round',
          'marker-end': `url(#${this.uid}-${brush})`, opacity: 0.8,
        }));
      }
    }

    // -- interaction ------------------------------------------------------------------------------
    onCellClick(cell) {
      if (this.suppressClick) { this.suppressClick = false; return; }
      this.activate(cell.dataset.square);
    }

    onCellFocus(cell) { for (const other of this.cells) other.tabIndex = other === cell ? 0 : -1; }

    onGridKey(event) {
      if (event.key === 'Escape') { this.selected = null; this.closePromo(); this.render(); return; }
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
      this.selected = this.legalMap.has(name) && this.selected !== name ? name : null;
      this.render();
    }

    commit(from, to, entries) {
      if (entries.some((entry) => entry.promo)) { this.openPromo(from, to, entries); return; }
      this.play(entries[0].uci);
    }

    play(uci) {
      this.selected = null;
      this.pending = { uci };
      this.render();
      if (this.moveHandler) this.moveHandler(uci);
    }

    /** The promotion strip: 4 wide x 1 tall over the target square, paper, 1px ink border. */
    openPromo(from, to, entries) {
      this.closePromo();
      const colour = LT.sideToMove(this.position.fen) === 'white' ? 'w' : 'b';
      const [row, col] = this.cellPos(LT.squareIndex(to));
      const strip = LT.el('div', { class: 'promo', role: 'dialog', 'aria-label': 'Choose the promotion piece', style: { left: `${Math.min(col, 4) * 12.5}%`, top: `${row * 12.5}%` } });
      for (const type of PROMOTION_ORDER) {
        const entry = entries.find((candidate) => candidate.promo === type);
        if (!entry) continue;
        const button = LT.el('button', { type: 'button', class: colour, 'aria-label': `Promote to ${LT.PIECE_NAME[type]}`, onClick: () => { this.closePromo(); this.play(entry.uci); } },
          this.style === 'lichess' ? this.pieceNode({ color: colour, type }) : LT.GLYPH[type]);
        strip.append(button);
      }
      strip.addEventListener('keydown', (event) => { if (event.key === 'Escape') { this.closePromo(); this.selected = null; this.render(); } });
      this.promo = strip;
      this.grid.append(strip);
      const first = strip.querySelector('button');
      if (first) first.focus();
    }

    closePromo() { if (this.promo) { this.promo.remove(); this.promo = null; } }

    onPointerDown(cell, event) {
      if (!this.position.interactive || event.button !== 0) return;
      const name = cell.dataset.square;
      if (!this.legalMap.has(name)) return;
      const rect = this.grid.getBoundingClientRect();
      this.drag = { from: name, cell, startX: event.clientX, startY: event.clientY, moved: false, ghost: null, rect, pointerId: event.pointerId, over: null };
      try { cell.setPointerCapture(event.pointerId); } catch (error) { /* not supported */ }
    }

    squareUnder(event, rect) {
      const col = Math.floor(((event.clientX - rect.left) / rect.width) * 8);
      const row = Math.floor(((event.clientY - rect.top) / rect.height) * 8);
      if (col < 0 || col > 7 || row < 0 || row > 7) return null;
      return LT.squareName(this.squareAt(row, col));
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
        const piece = LT.parseFen(this.position.fen)[LT.squareIndex(drag.from)];
        if (piece) { drag.ghost = this.pieceNode(piece, 'ghost'); this.grid.append(drag.ghost); }
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
      if (!drag.moved) return;
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
  LT.Board = Board;
})();
