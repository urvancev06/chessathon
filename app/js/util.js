/* Mikhail LeTal web app — shared namespace, formatting, DOM helpers, chess display helpers. */
window.LT = window.LT || {};
(() => {
  'use strict';
  const LT = window.LT;

  // -- formatting -------------------------------------------------------------------------------
  const num = (value) => (Number.isFinite(Number(value)) ? Number(value) : null);
  LT.fmt = {
    /** "mm:ss", floored; minutes grow past 59 rather than showing hours. */
    clock(ms) {
      const value = Math.max(0, num(ms) || 0);
      const total = Math.floor(value / 1000);
      const minutes = Math.floor(total / 60);
      const seconds = total - minutes * 60;
      return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    },
    /** "mm:ss" above ten seconds, "0:09.9" (floored tenths) below. */
    clockTenths(ms) {
      const value = Math.max(0, num(ms) || 0);
      if (value >= 10000) return LT.fmt.clock(value);
      const tenths = Math.floor(value / 100) / 10;
      return `0:0${tenths.toFixed(1)}`;
    },
    /** "3.84 M", "31.7 k", "842". */
    count(n) {
      const value = num(n);
      if (value == null) return '—';
      if (value >= 1e6) return `${(value / 1e6).toFixed(2)} M`;
      if (value >= 1e3) return `${(value / 1e3).toFixed(1)} k`;
      return String(Math.round(value));
    },
    /** "1.92 M/s", "47.9 k/s". */
    rate(nps) {
      const value = num(nps);
      return value == null ? '—' : `${LT.fmt.count(value)}/s`;
    },
    /** "2.00 s" below ten seconds, "12.3 s" above. */
    seconds(ms) {
      const value = num(ms);
      if (value == null) return '—';
      const s = value / 1000;
      return `${s.toFixed(s < 10 ? 2 : 1)} s`;
    },
    /** "63.4%". */
    pct(value, digits = 1) {
      const number = num(value);
      return number == null ? '—' : `${number.toFixed(digits)}%`;
    },
    /** "120 + 0.5" from milliseconds. */
    tc(baseMs, incMs) {
      const base = (num(baseMs) || 0) / 1000;
      const inc = (num(incMs) || 0) / 1000;
      return `${Number(base.toFixed(3))} + ${Number(inc.toFixed(3))}`;
    },
    int(value) {
      const number = num(value);
      return number == null ? '—' : number.toLocaleString('en-GB');
    },
  };

  // -- DOM ---------------------------------------------------------------------------------------
  function append(node, children) {
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      node.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  /** LT.el('div', {class: 'x', onClick: fn, text: '...'}, ...children) */
  LT.el = function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [key, value] of Object.entries(attrs)) {
        if (value == null || value === false) continue;
        if (key === 'class') node.className = value;
        else if (key === 'text') node.textContent = value;
        else if (key === 'html') node.innerHTML = value;
        else if (key === 'dataset') Object.assign(node.dataset, value);
        else if (key === 'style' && typeof value === 'object') Object.assign(node.style, value);
        else if (key.startsWith('on') && typeof value === 'function') node.addEventListener(key.slice(2).toLowerCase(), value);
        else if (value === true) node.setAttribute(key, '');
        else node.setAttribute(key, String(value));
      }
    }
    return append(node, children);
  };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  LT.svg = function svg(tag, attrs, ...children) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) if (value != null) node.setAttribute(key, String(value));
    return append(node, children);
  };
  LT.append = append;
  LT.clear = function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; };
  LT.esc = function esc(text) {
    return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };
  LT.debounce = function debounce(fn, ms) {
    let timer = null;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), ms); };
  };
  LT.storage = {
    get(key, fallback = null) {
      try { const raw = localStorage.getItem(key); return raw == null ? fallback : JSON.parse(raw); } catch (error) { return fallback; }
    },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (error) { /* private mode */ } },
    session(key, value) {
      try {
        if (value === undefined) { const raw = sessionStorage.getItem(key); return raw == null ? null : JSON.parse(raw); }
        if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, JSON.stringify(value));
        return value;
      } catch (error) { return null; }
    },
  };
  LT.copyText = async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (error) {
      const area = LT.el('textarea', { style: { position: 'fixed', left: '-9999px' } });
      area.value = text;
      document.body.append(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (error2) { ok = false; }
      area.remove();
      return ok;
    }
  };
  /**
   * A quiet button that copies what `getText` resolves to (a string or a promise of one); the
   * label flips to "Copied" (or "Copy failed") for 1.5 s, as Copy FEN does.
   */
  LT.copyButton = function copyButton(label, getText, attrs) {
    const button = LT.el('button', { type: 'button', class: 'quiet', text: label, ...(attrs || {}) });
    let timer = null;
    button.addEventListener('click', async () => {
      let ok = false;
      try { ok = await LT.copyText(await getText()); } catch (error) { ok = false; }
      button.textContent = ok ? 'Copied' : 'Copy failed';
      clearTimeout(timer);
      timer = setTimeout(() => { button.textContent = label; }, 1500);
    });
    return button;
  };
  /** The mark, 24-unit viewBox, currentColor. */
  LT.mark = function mark(size) {
    return LT.svg('svg', { viewBox: '0 0 24 24', width: size, height: size, class: 'mark', 'aria-hidden': 'true' },
      LT.svg('path', { d: 'M5 1.5h7v21h-7zM5 8.5h7M5 15.5h7', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.5' }),
      LT.svg('path', { d: 'M11.25 14.75h8.5v8.5h-8.5z', fill: 'currentColor' }));
  };
  /** The wordmark with the drawn T. */
  LT.wordmark = function wordmark() {
    return LT.el('span', { class: 'wordmark' }, 'Mikhail Le',
      LT.svg('svg', { viewBox: '0 0 60 72', 'aria-hidden': 'true' }, LT.svg('path', { d: 'M25 0h10v72h-10zM0 0h138v8.5H0z', fill: 'currentColor' })),
      'al');
  };

  // -- chess display helpers (the server is the rules authority) -----------------------------------
  LT.FILES = 'abcdefgh';
  LT.GLYPH = { k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' };
  LT.PIECE_NAME = { k: 'king', q: 'queen', r: 'rook', b: 'bishop', n: 'knight', p: 'pawn' };
  LT.START_FEN = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
  /** 64 entries a1=0 .. h8=63: {color: 'w'|'b', type: 'p'..'k'} or null. */
  LT.parseFen = function parseFen(fen) {
    const squares = new Array(64).fill(null);
    const ranks = (String(fen || '').split(/\s+/)[0] || '').split('/');
    for (let rankIndex = 0; rankIndex < Math.min(8, ranks.length); rankIndex++) {
      const rank = 7 - rankIndex;
      let file = 0;
      for (const char of ranks[rankIndex]) {
        if (/[1-8]/.test(char)) { file += Number(char); continue; }
        const type = char.toLowerCase();
        if (!LT.PIECE_NAME[type] || file > 7) continue;
        squares[rank * 8 + file] = { color: char === type ? 'b' : 'w', type };
        file += 1;
      }
    }
    return squares;
  };
  LT.squareName = (index) => LT.FILES[index % 8] + (Math.floor(index / 8) + 1);
  LT.squareIndex = (name) => LT.FILES.indexOf(name[0]) + (Number(name[1]) - 1) * 8;
  LT.sideToMove = (fen) => ((String(fen).split(/\s+/)[1] || 'w') === 'b' ? 'black' : 'white');
  /** The king square of the side to move when `san` ends in + or #, else null. */
  LT.checkedKing = function checkedKing(fen, san) {
    if (!san || !/[+#]$/.test(san)) return null;
    const colour = LT.sideToMove(fen) === 'white' ? 'w' : 'b';
    const index = LT.parseFen(fen).findIndex((piece) => piece && piece.type === 'k' && piece.color === colour);
    return index >= 0 ? LT.squareName(index) : null;
  };
  /** A 96x96 mini board (Openings) in the current board style. */
  LT.miniBoard = function miniBoard(fen, style) {
    const squares = LT.parseFen(fen);
    const node = LT.el('span', { class: `mini${style === 'lichess' ? ' lichess' : ''}`, role: 'img', 'aria-label': `Position ${fen}` });
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const piece = squares[(7 - row) * 8 + col];
        node.append(LT.el('span', { class: (row + col) % 2 === 1 ? 'dark' : '' },
          piece ? LT.el('span', { class: `g ${piece.color === 'w' ? 'pc-white' : 'pc-black'} pt-${piece.type}`, text: LT.GLYPH[piece.type] }) : null));
      }
    }
    return node;
  };
  /** The result score in the handoff's typography: "1–0", "0–1", "½–½", "*". */
  LT.score = function score(result) {
    return { white: '1–0', black: '0–1', draw: '½–½' }[result] || '*';
  };
  /** The server's termination names in the spec's words. */
  LT.TERMINATION = {
    checkmate: 'checkmate', stalemate: 'stalemate', insufficient_material: 'insufficient material',
    seventyfive_moves: 'seventy-five-move rule', fivefold_repetition: 'fivefold repetition',
    threefold_repetition: 'threefold repetition', fifty_moves: 'fifty-move rule', ply_cap: '600-ply cap',
    flag: 'flag', illegal: 'illegal move', crash: 'crash', init: 'failed to start', both_failed: 'both failed to start',
    resignation: 'resignation', aborted: 'stopped', abandoned: 'abandoned', error: 'error',
  };
  LT.reason = function reason(state) {
    if (!state || !state.termination) return '';
    if (state.termination === 'ply_cap') return `${state.ply_cap || 600}-ply cap`;
    return LT.TERMINATION[state.termination] || state.termination_text || state.termination;
  };
})();
