# Web app

A local web app for playing against the engine, watching it play, and inspecting what it ships.
It is a development tool: `tools/` never enters the submission zip.

```
uv run python -m tools.webapp.server            # http://localhost:8000/
uv run python -m tools.webapp.server --port 9000 --max-engines 2 --idle-minutes 10
make web
```

The server binds `127.0.0.1` unless `--host` says otherwise, prints the URL, and never opens a
browser. Nothing is loaded from the network, so it works offline at a judging table.

## What it does

- **Play**: you against any agent directory (the working tree, every `versions/*/`, the four
  baselines), from the standard start, a curated opening in `data/openings.txt` (by index or
  "next"), one of the harness openings, or a custom FEN; time-control presets or custom. The
  engine runs as a real process through `harness.sandbox.local`, is suspended while you think
  and timed on wall time exactly as `harness/referee.py` times it. Click or drag to move,
  promotion picker, takeback, resign, flip, PGN download, copy FEN, and a thinking panel that
  shows the engine's per-move log line with sparklines of nodes and time per move.
- **Spectate**: engine against engine, played by the server in a background thread with the
  referee's loop (start both, suspend, resume the mover, time the move, legality, increment,
  end checks in the referee's order, flag rule with the insufficient-material exception). The
  browser polls every 500 ms; Stop kills both agents.
- **Overview**, **Docs** (`docs/*.md` rendered client-side), **Weights** (`weights/pst.json` as
  heatmaps plus `weights/PROVENANCE.json`), **Openings** (`data/openings.txt` with board previews
  and a "play this" link).

Every finished game is saved as PGN under `data/webapp_games/` (ignored by git) with the same
headers and `%clk` comments the referee writes.

## Layout

```
tools/webapp/server.py      http.server (ThreadingHTTPServer) + JSON API, argparse main
tools/webapp/games.py       registry, games, seats (agent processes), log capture, repo info
tools/webapp/static/        index.html, app.js, style.css (vanilla, no build step)
tests/test_webapp.py        end-to-end tests over HTTP against the baselines
```

Python side: standard library, `chess`, and the harness used as a library (never modified).
The one liberty taken with the sandbox is reading `Agent._output()` (the stderr it keeps) to
show the engine's log line, and sending SIGKILL directly to the agent's process group when a
game is stopped mid-move, because `Agent.stop()` races with a `move()` in flight on another
thread.

## API

```
GET  /api/info                    engine identity, git state, RESULTS.md tail, contract, engines
GET  /api/engines | /api/docs | /api/weights | /api/openings | /api/games
POST /api/games                   {kind: play, engine, human, base_ms, increment_ms, fen, ply_cap, opening}
                                  {kind: spectate, white, black, ...}
GET  /api/games/<id>              full state (moves with SAN and clocks, legal moves, logs, result)
GET  /api/games/<id>/pgn          PGN download
POST /api/games/<id>/move         {uci, spent_ms}   spent_ms is the browser-measured human time
POST /api/games/<id>/takeback | /resign | /stop
DELETE /api/games/<id>
```

Errors are JSON `{"error": ...}` with 400/404/409/429/500.

## Notes

- The human clock is displayed and recorded (the browser reports how long you took) but never
  enforced. Reloading the page mid-turn restarts your turn timer.
- At most `--max-engines` agent processes run at once (default 4); a spectate game uses two.
  Games idle for `--idle-minutes` are stopped. Ctrl-C and normal exit stop every agent; after a
  `kill -9` of the server, look for stray `harness/runner.py` processes.
- The engine log format follows docs/DESIGN.md (`m e2e4 d 5/9 n 31240 nps ... t ... s ... h ... c ...`);
  unknown tokens are shown raw, and baselines that print nothing show "no log".
