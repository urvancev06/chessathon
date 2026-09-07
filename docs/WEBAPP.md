# The web app

A local website for looking at Mikhail LeTal: play it, watch it play, and read what it ships.
It is a development tool — nothing under `tools/` or `app/` goes into the submission zip — and
it loads nothing from the internet, so it works at a judging table without a connection.

## Starting it

```
make web
uv run python -m tools.webapp.server --port 9000 --max-engines 2
```

`make web` runs the second command with its defaults. The server prints its address
(`http://127.0.0.1:8000/` by default), binds only to this machine and never opens a browser. The line after the address says whether a local Stockfish was found.
Ctrl-C stops the server and every engine process it started.

## The screens

- **Play** — you against a seat: the working tree, a frozen version, one of the four baselines
  or (locally) Stockfish at a chosen Elo. Click-click or drag to move; a promotion strip
  appears over the target square. Right of the board: the clocks, the thinking strip, two
  sparklines (time and nodes per engine move), the move list with clocks, and Takeback, Resign,
  New game, Download PGN, Copy PGN, Copy FEN and — for a finished game — Analyse.
- **New game** — the setup form: engine build, your colour (Random included), time control
  presets or your own base/increment, and the starting position (standard, a curated opening by
  index, or a FEN that is validated as you type). Nothing starts until you press Start.
- **Spectate** — engine against engine, played entirely by the server; the browser only
  watches. Pick two seats, a time control, a starting position and a ply cap; Stop pauses the
  game between moves with the clocks standing still, Resume continues, Restart replays the setup,
  Copy PGN copies the game so far (or the finished game) to the clipboard.
- **Overview** — the identity, the real version and commit, the competition contract, how the
  engine works in four paragraphs, and the latest results table from `docs/RESULTS.md`.
- **Docs** — every `docs/*.md` file, rendered here. **Weights** — the piece values, the phase
  weights and the twelve piece-square tables as heatmaps, with their provenance. **Openings** —
  the 219 positions of `data/openings.txt` with mini boards, a filter and a Play link.
- **Analysis** — a finished game graded move by move by the local Stockfish (see below).

The nav bar has a light/dark toggle and a board-style switch; both are remembered.

## How the engine is run

Every seat is a real engine process started the way the competition platform starts one:
through `harness.sandbox.local`, the same runner (`harness/runner.py`) the referee uses, with
`agent.py` at the root of the seat's folder. The game loop mirrors `harness.referee` step by
step: both engines are started and given the initialisation budget, the engine not on move is
suspended, the mover is resumed and handed the position and its remaining clock, the reply is
timed on wall time, checked for legality, and the increment is added; the end-of-game checks run
in the referee's order (checkmate, stalemate, insufficient material, repetition, fifty moves,
the ply cap, the flag rule with its insufficient-material exception). Each engine gets one core.
On Play the engine is suspended while you think, so your thinking never costs it CPU time.
Your own clock is shown and recorded but not enforced; the engine's clock is.

## The thinking strip

After every move the engine prints one line, for example
`m e2e4 d 5/9 n 31240 nps 10413 t 3001 s 3300 h 9900 c 118500`. The strip shows it:

- **depth** `5/9` — the last completed search depth and the deepest line looked at (seldepth).
- **nodes** — positions examined for this move; **nodes/s** — the search speed.
- **time** — milliseconds actually spent, shown in seconds.
- **soft** — the time the engine planned to use for this move (it starts no new depth after
  it); **hard** — the deadline it never crosses. The budget bar runs from 0 to hard: the grey
  segment ends at soft (with a tick), the ink segment is the time used.
- **clock** — the time the engine was told it had left when the move started.

Spectate shows the same numbers in a single row under each agent's name. Baselines that print
nothing show "no log".

## Stockfish, local only

Stockfish is a measuring instrument, never part of the submission. It is looked for at
`YARDSTICK_ENGINE`, then `~/.local/opt/stockfish/stockfish`, then on `PATH`; it is not in the
repository or the zip, and it never influences a move our engine plays. Two uses:

- **Sparring seats** `Stockfish · Elo 1400 … 2600` and `full strength`: the `tools/yardstick`
  agent plays Stockfish's moves at a limited strength through the same harness as any other
  seat. The optional "Stockfish move time" field gives it a fixed time per move instead of the
  clock.
- **Analysis**: every position of a finished game is searched once at the chosen depth and
  number of lines. The eval bar, the eval graph, the `?!` `?` `??` marks, the per-move detail
  (eval before/after, centipawn loss, the engine's rank of the move, the best line) and the
  accuracy summary use lichess's published formulas; the summary counts each side's own
  moves only (best-move and top-3 counts, ACPL, mean accuracy). Copy PGN copies the analysed
  game.

Without a Stockfish binary the seats are simply absent and the Analyse buttons say why.

## The two board styles

- **lichess** (default) — the brown board, coordinates in the squares, lichess's highlights,
  and the cburnett piece set (Colin M.L. Burnett, CC BY-SA 3.0, `app/pieces/cburnett/`).
- **studio** — the design handoff's board: grey squares from the theme tokens, Unicode glyph
  pieces, the accent overlay for the last move.

## Where games are saved

- `data/webapp_games/` — every finished game as a PGN with the referee's headers and `%clk`
  comments, named by date and seats.
- `data/webapp_analysis/` — cached analysis results, so the same game and settings answer at once.

Both folders are ignored by git and are recreated on demand. Both were cleared before this
session. To clear them again:

```
rm -rf data/webapp_games data/webapp_analysis
```

Games in progress live only in the server's memory; stopping the server ends them.
