# Handoff: Mikhail LeTal — identity and local web app

## Overview
Visual identity (mark, wordmark, palette) and the local web app for the Mikhail LeTal chess engine. Audience: the developer and a competition judge watching a ten-minute session. The app must feel like a precision instrument — Swiss typographic discipline, near-monochrome, one accent.

## About the design files
The `.dc.html` files in this bundle are **design references written in HTML**: interactive prototypes that show the intended look and behaviour. They are not production code. Recreate them in the app's real environment: plain HTML/CSS/JS served locally, talking to the engine over a local pipe. The prototypes already use only inline styles, system fonts and no libraries, so most CSS values can be lifted verbatim. Where the prototype fakes behaviour (the engine reply, clocks, spectate replay), wire the real engine instead.

## Fidelity
**High-fidelity.** Colours, type, spacing and states are final. Recreate pixel-accurately. The one deliberate variable is the platform sans (system-ui), so metrics differ slightly per OS — that is expected.

## Files
- `Identity.dc.html` — three logo directions, the chosen mark with paste-ready SVG, wordmark, lockups, clear space, minimum sizes, palette, favicon test, five sizes on both themes.
- `App.dc.html` — the app: all seven screens, light/dark, responsive. Open it and use the nav; the Play board is clickable.
- `Components.dc.html` — components sheet (logo, type scale, tokens, buttons, fields, table, clock, thinking strip, sparkline, result banner, nav, focus, board square states).
- `Screens.dc.html` — canvas of every screen at 1440 and 390 in light and dark (embeds App).
- `favicon.svg`, `mark.svg` — the mark, ready to ship.
- `tokens.css` — the CSS custom properties for both themes.

## Identity

### Mark ("the knight's move")
24×24 viewBox. Three hairline cells travelled (a column), one filled landing cell to the bottom right — two forward, one across. Cells are 7 units on grid lines x = 5, 12, 19 and y = 1.5, 8.5, 15.5, 22.5; hairline 1.5 units centred on the grid line; the filled square is 8.5 units (cell plus hairline). Single colour via `currentColor`. No outline on the fill, no radius.

```html
<svg viewBox="0 0 24 24" width="24" height="24">
  <path d="M5 1.5h7v21h-7zM5 8.5h7M5 15.5h7" fill="none" stroke="currentColor" stroke-width="1.5"/>
  <path d="M11.25 14.75h8.5v8.5h-8.5z" fill="currentColor"/>
</svg>
```

Sizes used: 16 (favicon), 20 (nav bar), 32 (horizontal lockup), 40 (Overview), 48–200 (identity page). Minimum 16 px. Clear space: one cell (⅓ of the mark height) on all sides.

### Wordmark
"Mikhail LeTal" in the system sans, weight 500, letter-spacing −0.015em, line-height 1, one line, never bold, never in the accent. The **T is drawn**: an inline SVG 0.6em wide × 0.72em tall (`viewBox 0 0 60 72`), stem `M25 0h10v72h-10z`, crossbar `M0 0h138v8.5H0z` — the crossbar overshoots the box (`overflow:visible`) and runs across "al", so "Tal" sits under a rank line. Markup:

```html
<span style="display:inline-flex;align-items:baseline;font-weight:500;letter-spacing:-0.015em;line-height:1;white-space:nowrap">Mikhail Le<svg viewBox="0 0 60 72" style="height:.72em;width:.6em;overflow:visible;margin:0 .02em 0 .04em;flex:none" aria-hidden="true"><path d="M25 0h10v72h-10zM0 0h138v8.5H0z" fill="currentColor"/></svg>al</span>
```

Lockups: horizontal (mark 32 + wordmark 30px, gap 12; min 20 px tall), mark alone (min 16), wordmark alone (min 12).

### Palette
Paper `#f7f6f3` / dark `#222221`. Ink `#1c1b19` / dark `#ebe9e4`. Brick `#a3513b` / dark `#c8735c`. Nothing else in the identity. (Alternate accent, if ever wanted: ochre `#7f6320` / `#c4a04e`.)

## Design tokens (see tokens.css)

| token | light | dark |
| --- | --- | --- |
| --paper | #f7f6f3 | #222221 |
| --ink | #1c1b19 | #ebe9e4 |
| --grey (secondary text) | #6f6d68 | #9a9893 |
| --line (hairline) | rgba(28,27,25,.10) | rgba(235,233,228,.12) |
| --acc | #a3513b | #c8735c |
| --square-light | #e8e6e1 | #3a3a3a |
| --square-dark | #a8a49b | #262626 |
| --piece-white fill / stroke | #f6f4f0 / 0.05em #38362f | #ecebe7 / 0.05em #141414 |
| --piece-black fill / stroke | #1d1c1a / none | #121212 / 0.04em #8c8c8c |
| --coord | rgba(28,27,25,.5) | rgba(235,233,228,.4) |
| --legal-dot | rgba(28,27,25,.35) | rgba(235,233,228,.35) |
| --selected overlay | rgba(28,27,25,.16) | rgba(235,233,228,.18) |
| --last-move overlay | accent at 30 % | accent at 30 % |
| --check wash | rgba(158,66,56,.4) | rgba(205,95,85,.4) |
| --error text | #96473b | #d0847a |
| --code-bg | #efeeea | #2b2b2a |
| --psqt-negative | #8f8c86 | #6a6864 |

Accent usage is limited to: active nav item (text), primary button (background), last-move overlay. Focus outlines also use it.

**Type**: `system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif`. Mono: `ui-monospace, "SF Mono", Menlo, Consolas, monospace` — only for FEN, PGN, commit hashes, provenance, code. Scale: 40/500/−0.02em (clocks, tabular), 24/500/−0.01em, 20/500/−0.01em, 16/400, 14/400 (body, line-height 1.5), 13/400 (UI, buttons, tables, moves), 12/400 (secondary), 11/500/uppercase/+0.08em (section labels), 12 mono, 11 mono (version). `font-variant-numeric: tabular-nums` on every clock, count and statistic.

**Spacing**: page padding 24 (mobile and desktop), content max-width 1100 centred, section gaps 28–40, hairline separators, no cards, no shadows. Radius: 2px on buttons and inputs, 0 elsewhere. Motion: `settle` 120ms ease-out opacity 0→1 when a screen mounts or a piece lands; nothing else.

**Focus**: every interactive element: `outline: 2px solid var(--acc); outline-offset: 2px` (board squares: offset −2px; inputs: 1px). No glow, no ring.

## Layout shell (all screens)
Nav bar, padding 14px 0, hairline below. Left: mark 20px + wordmark 15px, gap 10. Middle: seven quiet text buttons (Play, New game, Spectate, Overview, Docs, Weights, Openings), 13px, gap 20, ink; active = accent, weight 500; hover = grey. Right: `v0.9.3 · a1f4c2e` (11px mono grey) and a theme toggle labelled "Dark"/"Light" (quiet button). The bar wraps on narrow widths: nav items drop to a second row (`flex-wrap`, `min-width: min(440px, 100%)`).

## Screens

### 1. Play
Two-column flex-wrap: board column `flex 1 1 440px; max-width 640` and right column `flex 1 1 320px`, gap 40/48. Under 800px the right column stacks below the board. Board column: 12px grey status line ("White to move" / "Engine is thinking" / "Game over") left, "Flip board" quiet button right; board in a hairline box (`container-type: inline-size`), 8×8 CSS grid, `aspect-ratio 1`; FEN below in 11px mono grey, single line with ellipsis.

Squares: `<button>` per square, background light/dark square colour, overlay span for states, coordinates 8–10px (`max(8px, 1.4cqw)`) — rank digit top-left on the visual left column, file letter bottom-right on the visual bottom row. Piece glyphs ♚♛♜♝♞♟ for both colours, `font-size: 9cqw`, centred with flex; white = near-white fill + `-webkit-text-stroke 0.05em`, black = near-black (dark theme adds a 0.04em grey stroke). Legal-target dot: 22 % of the square, circle, `--legal-dot`. Selected: `--selected` overlay. Last move: accent at 30 % on both squares. Check: king's square gets the red-grey wash (priority: check > selected > last move). Promotion: a strip positioned over the target square, 4 squares wide × 1 tall, paper background, 1px ink border, ♛♜♝♞ buttons, 120ms settle.

Right column, top to bottom, gap 28, hairline above each block after the first:
1. Result banner (only at game end): hairline box, padding 10/14, `1–0` weight 500 + reason in grey. Reasons: checkmate, stalemate, threefold repetition, fifty-move rule, 600-ply cap, flag, resignation.
2. Clocks: two columns. Label "White · you" / "Black · engine" (11px uppercase grey), then 40px/500/−0.02em tabular clock `mm:ss` and "+0.5" in 12px grey. Side to move in ink, other in grey.
3. Thinking strip: label "Last move · 14… a5" and "clock left 01:37" right; 4-column grid of depth (`17/29`), nodes (`3.84 M`), nodes/s (`1.92 M/s`), time (`2.00 s`) — 11px grey caption over 16px/500 value; 2px budget bar: track = hairline (0→hard), soft segment = grey at 45 % (0→soft) with a 1px tick at the soft mark, used = ink (0→used); caption row "2.00 s used · soft 2.83 s · hard 4.9 s".
4. Two sparklines side by side: caption row (name left, last value right, 11px grey), SVG `viewBox 0 0 100 28`, `preserveAspectRatio none`, height 28, 1px ink polyline with `vector-effect: non-scaling-stroke`, no fill/axes/dots. Last 24 engine moves.
5. Move list: label "Moves" + "28 plies"; grid `2.4em 1fr auto 1fr auto`: number (grey), white SAN, clock (11px grey, right), black SAN, clock. Latest ply weight 500. `max-height 260; overflow auto`.
6. Quiet text buttons, gap 20: Takeback (disabled at 35 % when fewer than 2 plies / game over / engine thinking), Resign, New game, Download PGN, Copy FEN (label flips to "Copied" for 1.5 s).

### 2. New game
Inline form, max-width 640, gap 32. Title "New game" 20px/500 + note "Nothing starts until you press Start". Sections with 11px uppercase labels:
- Engine build: option list separated by hairlines; row = 12px square indicator (1px ink border, filled when selected) + name + mono meta. Options: Working tree (a1f4c2e · dirty), Frozen v0.9.3, Frozen v0.9.2 (7c03b91), Baseline · material only 1 ply, Baseline · random mover.
- Your colour: segmented buttons White / Black / Random. Selected = ink text + 1px ink border; unselected = grey text + hairline border. Radius 2, padding 7/12.
- Time control: presets `120 + 0.5` (default), `60 + 0.5`, `30 + 0.3`, `10 + 0.1`, `3 + 0.05`, plus "base … s" / "increment … s" inputs (64px wide, tabular). Editing a field deselects the presets.
- Starting position: Standard / Curated opening by index / Custom FEN. Index shows a 72px numeric input and the opening's name. Custom FEN shows a full-width mono input with a live validation line under it: grey "Valid · white to move · castling KQkq", or an error in `--error` ("Rank 7 has 9 squares", "Each side needs exactly one king", "Side to move must be w or b", "Castling field is malformed", "En passant square is malformed").
- Footer above a hairline: primary "Start game" (accent bg, paper text, 13px/500, padding 9/16, radius 2; 40 % opacity and disabled while the FEN is invalid) + quiet "Cancel".

### 3. Spectate
Single centred column, max-width 560, gap 16. Status line 12px grey tabular: `move 34 · white to move · 00:48 elapsed` (+ ` · stopped`), right: `120 + 0.5 · one core each`. Top agent block (hairline above): name 14px/500 left, clock 24px/500 tabular right, then a 12px grey row `d 18/30 · 3.6 M nodes · 1.9 M/s · 1.9 s`. Board (non-interactive, same square rendering). Bottom agent block (hairline below). Move list (same grid as Play, max-height 220). Buttons: Stop/Resume, Restart. The side to move is in ink, the other in grey.

### 4. Overview
Max-width 720, gap 40. Mark 40 + wordmark 32; one 16px sentence; 12px mono grey `v0.9.3 · a1f4c2e · built 2026-09-04 · C++20, no dependencies`. "Competition contract": 2-column hairline table — Time control / 120 s + 0.5 s per move, per side; Hardware / 1 CPU core, 2 GB RAM; Initialisation / 90 s before the first move; Game length / Draw at 600 plies. "How it works": 2×2 grid (min 280) of heading 14/500 + grey paragraph: Search, Evaluation, Time management, Safety wrapper. "Latest results": hairline table date · opponent · result (500) · reason · moves.

### 5. Docs
Flex-wrap: rail `flex 0 0 180px` of quiet buttons (README, Architecture, Search, Time management, Testing, Changelog; current = ink/500, others grey) and main column `flex 1 1 320px; max-width 70ch; 15px/1.6`. Markdown rendering: h1 24/500/−0.01em, h2 16/500 (margin 32 0 8), h3 14/500, paragraphs 12px margins, lists, inline code (mono 0.86em, code-bg, padding 1/5, radius 2), code blocks (code-bg, padding 12/14, mono 12.5px, `overflow-x auto`), tables inside an `overflow-x: auto` wrapper with hairline rows and 11px uppercase grey headers.

### 6. Weights
Top: 2-column grid (min 280) — left "Piece values and phase weights" hairline table (piece · mg · eg · phase: Pawn 82/94/—, Knight 337/281/1, Bishop 365/297/1, Rook 477/512/2, Queen 1025/936/4, King —) with a 12px grey formula note; right "Provenance" `<pre>` in code-bg, mono 12px. Below: label "Piece-square tables · white's view, rank 8 at the top" with a min/max legend and a 96×6 gradient chip; grid `repeat(auto-fill, minmax(200px,1fr))`, gap 28/24, twelve heatmaps (Pawn…King × middlegame/endgame). Each: title 12/500 + phase grey; 8×8 grid in a hairline box, cells `aspect-ratio 1`, 9px tabular value, background = paper mixed toward the accent for positives (max 62 %) or toward `--psqt-negative` for negatives (max 70 %); file letters a–h under it in 9px grey.

### 7. Openings
Header: "Openings" 20/500 + "219 positions" 12px grey; right: 220px filter input. Rows separated by hairlines, flex-wrap, gap 12/24, padding 10 0: index `000` (mono 12 grey, 2.6em), name 13/500 (`flex 1 1 180px`), 96×96 mini board (8×12px cells, hairline border, glyphs 10px with 0.4px stroke on white), FEN in 11px mono grey (`flex 1 1 300px; overflow-wrap anywhere`), quiet "Play" button (starts a game from that index). Footer 12px grey: "Showing the first 13 of 219 · …" or "N of 219 match “…”".

## Interactions and state
- `theme` light|dark (toggle in nav; persist in localStorage in the real app). `screen`. `flipped`.
- Play game: `board[64]` (FEN chars, index 0 = a8), `turn`, `castling`, `plies[{san, clockAfter, thinkTime, nodes}]`, `lastMove[from,to]`, `selected`, `targets`, `promo`, `result{score, reason}`, `think{depth, seldepth, nodes, nps, time, soft, hard}`, `wClock`, `bClock`, `thinking`.
- Click own piece → select + legal targets (the real app must use the engine's legal-move list); click target → move (pawn to last rank → promotion strip first); then the engine reply arrives with its report; the thinking strip, sparklines and move list update. Clock of the side to move ticks every second; at 0 → result "flag".
- Takeback removes the last two plies. Resign → "0–1 · resignation". Download PGN writes a `.pgn` blob. Copy FEN uses the clipboard.
- Spectate: engine vs engine; a move every ~3 s in the prototype; Stop freezes clocks and status; Restart resets.
- New game → Start builds the position (standard / opening index / validated FEN), sets clocks from the time control, flips the board if you play Black, engine moves first if it is to move.
- Responsive: all layouts are flex-wrap/grid auto-fit; no media queries needed. At 390 the board is 340px (42px squares); the right column stacks under it; the nav wraps onto two rows.
- Motion: only the 120ms opacity settle.

## Assets
Mark and favicon: `mark.svg` / `favicon.svg` (identical geometry, colour set on the root). Pieces: Unicode glyphs ♚♛♜♝♞♟ — no images. No fonts shipped.
