/* Mikhail LeTal web app — the move list: grid "2.4em 1fr auto 1fr auto" (number, white SAN, clock,
   black SAN, clock); the latest ply weight 500. Also used by Analysis with marks and evaluations. */
(() => {
  'use strict';
  const LT = window.LT;
  /**
   * LT.moveList(container, plies, options)
   * plies: [{san, clock: "mm:ss" | "", mark?: "?!", best?: bool, after?: "+0.3", ply?: n}]
   * options: {latestBold: true, maxHeight: 260, startFen, current: plyIndex|null, onSelect(plyIndex), marginTop}
   * Returns {update(current)} to move the highlight without a rebuild.
   */
  LT.moveList = function moveList(container, plies, options = {}) {
    const box = container;
    LT.clear(box);
    box.className = `movelist${options.onSelect ? ' selectable' : ''}`;
    if (options.maxHeight != null) box.style.maxHeight = `${options.maxHeight}px`;
    if (options.marginTop != null) box.style.marginTop = `${options.marginTop}px`;
    const latestBold = options.latestBold !== false;
    const startFen = options.startFen || LT.START_FEN;
    let number = Number(String(startFen).split(/\s+/)[5]) || 1;
    const blackFirst = LT.sideToMove(startFen) === 'black';
    const buttons = [];
    const cell = (ply, index) => {
      const latest = latestBold && index === plies.length - 1;
      const san = ply ? ply.san : '';
      const content = [san];
      if (ply && ply.mark) content.push(LT.el('span', { class: 'ann', text: ply.mark }));
      if (ply && ply.best) content.push(LT.el('span', { class: 'ann best', title: "the engine's first choice", text: '✓' }));
      if (ply && ply.after != null) content.push(LT.el('span', { class: 'ev', text: ply.after }));
      let node;
      if (options.onSelect && ply) {
        node = LT.el('button', { type: 'button', class: `san${latest ? ' latest' : ''}`, onClick: () => options.onSelect(index + 1) }, content);
        buttons[index + 1] = node;
      } else {
        node = LT.el('span', { class: `san${latest ? ' latest' : ''}` }, content);
      }
      return node;
    };
    const clock = (ply) => LT.el('span', { class: 'clk', text: ply && ply.clock ? ply.clock : '' });
    let index = 0;
    if (plies.length && blackFirst) {
      box.append(LT.el('span', { class: 'no', text: `${number}.` }), LT.el('span', { class: 'san grey', text: '…' }), clock(null), cell(plies[0], 0), clock(plies[0]));
      index = 1;
      number += 1;
    }
    for (; index < plies.length; index += 2, number += 1) {
      const white = plies[index];
      const black = plies[index + 1] || null;
      box.append(LT.el('span', { class: 'no', text: `${number}.` }), cell(white, index), clock(white), black ? cell(black, index + 1) : LT.el('span'), clock(black));
    }
    const update = (current) => {
      buttons.forEach((button, ply) => {
        if (!button) return;
        const on = ply === current;
        button.classList.toggle('current', on);
        if (on) {
          const top = button.offsetTop - box.clientHeight / 2;
          if (Math.abs(box.scrollTop - top) > box.clientHeight / 3) box.scrollTop = Math.max(0, top);
        }
      });
    };
    if (options.current != null) update(options.current);
    else if (latestBold) box.scrollTop = box.scrollHeight;
    return { update };
  };
})();
