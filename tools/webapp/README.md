# Web app

A local web app for playing against the engine, watching it play, analysing finished games, and
inspecting what it ships. It is a development tool: `tools/` never enters the submission zip.

```
uv run python -m tools.webapp.server            # http://localhost:8000/
uv run python -m tools.webapp.server --port 9000 --max-engines 2 --idle-minutes 10
make web
```

The server binds `127.0.0.1` unless `--host` says otherwise, prints the URL, and never opens a
browser. Nothing is loaded from the network, so it works offline at a judging table.

## What it does

- **Play**: you against any seat (the working tree, every `versions/*/`, the four baselines, and
  Stockfish at a chosen Elo when it is installed locally), from the standard start, a curated
  opening in `data/openings.txt` (by index or "next"), one of the harness openings, or a custom
  FEN; time-control presets or custom. The engine runs as a real process through
  `harness.sandbox.local`, is suspended while you think and timed on wall time exactly as
  `harness/referee.py` times it. Click-click or drag-and-drop to move (a ghost piece follows the
  pointer, drops snap), a lichess-style promotion strip, takeback, resign, flip, PGN download,
  copy FEN, and a thinking panel that shows the engine's per-move log line with sparklines of
  nodes and time per move.
- **Spectate**: engine against engine, played by the server in a background thread with the
  referee's loop (start both, suspend, resume the mover, time the move, legality, increment,
  end checks in the referee's order, flag rule with the insufficient-material exception). The
  browser polls every 500 ms; Stop kills both agents.
- **Analysis**: a finished game (from this session, a saved PGN under `data/webapp_games/` or
  `data/pgn/`, or a pasted PGN) graded move by move by the local Stockfish at a chosen depth and
  number of lines. The result view has the board with an eval bar and the engine's arrow for the
  position shown, an eval graph over plies (click to jump), the move list annotated `?!`, `?`,
  `??` and a tick for engine-first-choice moves, a detail strip per move (eval before and after,
  centipawn loss, the engine's rank of the move, the best line) and a summary per side. Finished
  games on Play and Spectate have an "Analyse this game" button. Jobs run one at a time on a
  worker thread with a progress line and a cancel button; results are cached under
  `data/webapp_analysis/` (ignored by git), so the same game and settings come back at once.
- **Overview**, **Docs** (`docs/*.md` rendered client-side), **Weights** (`weights/pst.json` as
  heatmaps plus `weights/PROVENANCE.json`), **Openings** (`data/openings.txt` with board previews
  and a "play this" link).

Every finished game is saved as PGN under `data/webapp_games/` (ignored by git) with the same
headers and `%clk` comments the referee writes.

## The board

The board is drawn the way lichess draws it, because that is what a chess player's eye is
calibrated to: the "brown" theme (`#f0d9b5` / `#b58863`, unchanged in dark mode), coordinates
inside the squares, lichess's colours for the last move, the selected piece, legal destinations,
captures, hover and check, arrows in chessground's geometry, and a vertical eval bar. The pieces
are the **cburnett** set by Colin M.L. Burnett, CC BY-SA 3.0, used unmodified from
`tools/webapp/static/pieces/cburnett/` (see `LICENSE.txt` there). Everything else on the page
keeps the near-monochrome UI.

## Stockfish, the local-only instrument

Stockfish is a measuring instrument, never a submission (brief, sections 2.2 and 8.2). The binary
lives outside the repository; it is found through `YARDSTICK_ENGINE`, else
`~/.local/opt/stockfish/stockfish`, else `stockfish` on `PATH`. It never enters the repository or
the zip, it never influences a move our engine plays, and nobody reads its source. When no binary
is found, the analysis page says why, the "Analyse" buttons are disabled, and the Stockfish seats
are simply absent from the seat lists.

Setup: download an official Stockfish build for this machine, put the executable at
`~/.local/opt/stockfish/stockfish` (or anywhere else and `export YARDSTICK_ENGINE=/path/to/it`),
and start the server; the line after the URL says either `analysis and Stockfish seats:
Stockfish 19 at ...` or `analysis off: <reason>`. `GET /api/analysis/engine` answers the same
question at run time, and a binary fixed while the server runs is picked up within ten seconds.

- Seats: `stockfish:<elo>` for 1400 .. 2600 and `stockfish:full` run `tools/yardstick` with
  `YARDSTICK_ELO=<elo>` (omitted for full strength) and, when the form's "Stockfish move time"
  is filled, `YARDSTICK_MOVETIME_MS`; otherwise the yardstick plays on the clock it is handed.
  The variables travel with the seat (that agent's environment), never through the server's own.
  The same agent serves the arena: `tools/arena_openings.py --opponent tools/yardstick --env
  YARDSTICK_ELO=1600`; see `tools/yardstick/README.md`.
- Analysis: every position is searched once at the requested depth with `multipv` lines, on one
  thread (`Threads=1`, `Hash=64`, a fresh engine per job). The evaluation after a move is the
  evaluation of the next position, so a game costs one search per position; a game that ended on
  the board is not searched at the end, the outcome decides (checkmate ±1000 cp, shown as `#`,
  draw 0). Cancelling stops the running search within a fraction of a second. For scale: a
  20-ply game takes about 2 s at depth 12 and 17 s at depth 18 with three lines on one core.

The analysis uses lichess's published formulas because they are the de-facto standard for this
kind of report: win% `= 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)`, mates counted as
±1000 cp; per move, from the mover's point of view, `cp_loss = max(0, best - played)`
(capped at 1000) and the win% drop `d` decides the judgement (blunder `d >= 30`, mistake
`>= 20`, inaccuracy `>= 10`, best when the engine's first choice was played or nothing was lost,
good otherwise); per-move accuracy `= 103.1668 * exp(-0.04354 * d) - 3.1669`, clamped to
0..100. A side's accuracy is the plain mean of its per-move accuracies (lichess uses a windowed
harmonic mean; the UI says "mean"). ACPL is the mean centipawn loss, best-move % counts rank 1,
top-3 % counts rank <= 3 and so needs at least three lines.

## Layout

```
tools/webapp/server.py      http.server (ThreadingHTTPServer) + JSON API, argparse main
tools/webapp/games.py       registry, games, seats (agent processes), log capture, repo info
tools/webapp/analysis.py    analysis jobs: sources, one worker, the report, the cache
tools/webapp/static/        index.html, app.js, style.css (vanilla, no build step)
tools/webapp/static/pieces/ the cburnett piece set (SVG) and its licence
tools/yardstick/            the harness-compatible agent that plays a UCI engine's moves
tests/test_webapp.py        end-to-end tests over HTTP against the baselines
tests/test_analysis.py      the formulas and the analysis API (engine-backed tests skip without Stockfish)
tests/test_yardstick.py     the yardstick agent's environment handling and fallback
```

Checks, from the repository root with the main virtualenv:

```
.venv/bin/ruff format --check . && .venv/bin/ruff check . && .venv/bin/mypy
.venv/bin/python -m pytest tests/test_webapp.py tests/test_analysis.py tests/test_yardstick.py -q
```

Python side: standard library, `chess`, and the harness used as a library (never modified).
The one liberty taken with the sandbox is reading `Agent._output()` (the stderr it keeps) to
show the engine's log line, and sending SIGKILL directly to the agent's process group when a
game is stopped mid-move, because `Agent.stop()` races with a `move()` in flight on another
thread. Stockfish seats override `Agent._environment()` so the yardstick's settings travel with
the seat rather than through the server's own environment.

## API

```
GET  /api/info                    engine identity, git state, RESULTS.md tail, contract, engines,
                                  analysis {available, name}, time controls, ply cap, engine slots
GET  /api/engines | /api/docs | /api/weights | /api/openings | /api/games
POST /api/games                   {kind: play, engine, human, base_ms, increment_ms, fen, ply_cap, opening,
                                   stockfish_movetime_ms?}
                                  {kind: spectate, white, black, ...}
GET  /api/games/<id>              full state (moves with SAN and clocks, legal moves, logs, result)
GET  /api/games/<id>/pgn          PGN download
POST /api/games/<id>/move         {uci, spent_ms}   spent_ms is the browser-measured human time
POST /api/games/<id>/takeback | /resign | /stop
DELETE /api/games/<id>

GET  /api/analysis/engine         {available, path, name, reason}
GET  /api/analysis/sources        {games: [...this session's games with moves, finished first...],
                                   files: [...*.pgn under data/webapp_games and data/pgn, newest first...]}
POST /api/analysis                {source: {game_id} | {file} | {pgn}, depth (8..30, default 18),
                                   multipv (1..5, default 3)} -> 202 {job_id, cached}
                                  (the same game and settings answer at once with cached: true)
GET  /api/analysis/jobs           {jobs: [{job_id, status, progress: {done, total}, label}]}
GET  /api/analysis/<job_id>       {status: queued|running|done|failed|cancelled, progress, error, result}
DELETE /api/analysis/<job_id>     cancel -> 204
```

A result carries `engine {name, depth, multipv}`, the PGN headers, `start_fen`, one entry per ply
(`san`, `uci`, the FENs before and after, `eval_before` / `eval_after`, the engine's `best` line,
the `top` candidates, `rank`, `cp_loss`, `win_before` / `win_after`, `accuracy`, `judgement`,
`clock_after`) and a `summary` per side (`moves`, `best_moves`, `best_move_pct`, `top3_moves`,
`top3_pct`, `acpl`, `accuracy`, `inaccuracies`, `mistakes`, `blunders`).

Seats are named by id: `.` (working tree), `versions/<name>`, `baselines/<name>`,
`stockfish:<elo>`, `stockfish:full`; `/api/info` lists them with `{id, label, kind, path}` and
`kind` in `letal | version | baseline | stockfish`. Evaluations on the wire are always from
White's point of view (`{cp, mate, pov: "white"}`; `mate: 3` means White mates in three).

Errors are JSON `{"error": ...}` with 400/404/409/429/500/503.

## Notes

- The human clock is displayed and recorded (the browser reports how long you took) but never
  enforced. Reloading the page mid-turn restarts your turn timer.
- At most `--max-engines` agent processes run at once (default 4); a spectate game uses two.
  Games idle for `--idle-minutes` are stopped. Ctrl-C and normal exit stop every agent; after a
  `kill -9` of the server, look for stray `harness/runner.py` processes.
- The engine log format follows docs/DESIGN.md (`m e2e4 d 5/9 n 31240 nps ... t ... s ... h ... c ...`);
  unknown tokens are shown raw, and baselines that print nothing show "no log".
- Keyboard: on Play, Tab reaches the board, arrows move between squares and Enter selects or
  moves; on the move list and on Analysis, left/right, Home and End step through the game.
