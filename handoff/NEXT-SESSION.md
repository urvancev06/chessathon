# Start here (fresh session)

Repo: `/Users/notyan/chessathon`. Two jobs: **replay the three losing positions with v1.1**, and
**race v1.1 against v1.0**. Neither needs the working tree merged.

## Setup facts you need

- Python: `/Users/notyan/chessathon/.venv/bin/python` (or `uv run python` from the repo root).
- **Network calls need `SSL_CERT_FILE=/etc/ssl/cert.pem`** — this Mac's Python has no CA bundle.
- The working tree is at v1.0 (`074c7bb`) but GitHub has ~66 more commits including **v1.1**.
  A LaunchAgent fetches every 5 min, so the commits are already in `.git`. **Do not merge just to
  test** — extract instead:

```sh
mkdir -p /tmp/v11 && git -C /Users/notyan/chessathon archive origin/main:versions/v1.1 | tar -x -C /tmp/v11
mkdir -p /tmp/v10 && git -C /Users/notyan/chessathon archive origin/main:versions/v1.0 | tar -x -C /tmp/v10
```

Each gives `agent.py` + `mikhail_letal/` + `weights/` — a runnable agent directory.

- **Import costs ~11-12 s** (numba JIT). Do it once per process, not per position.
- **This Mac is ~2.3x faster than the platform** for search. To reproduce what the engine really
  had, pass `time_left_ms = actual_clock / 2.3`.

## Job 1 as written below is INVALID — read `handoff/FINDING-replay-invalid.md` first

The replay test assumes v1.0 reliably plays the losing move so it can serve as a baseline. **It does
not.** The search is bounded by wall clock, so the node budget moves with machine load, the last
completed iteration changes, and the move changes with it. The same version, same position, same
clock gave `f7e7`, `f7c7` and `f7g7` on three consecutive runs — the blunder and Stockfish's move
both inside the spread. A single replay is a coin flip and **cannot separate two versions.**

Keep the positions below for *reading what the engine thinks*. Do not use them to decide whether a
version is better. To decide that, run Job 2, or first add a fixed-node / fixed-depth switch to the
search so a position becomes replayable at all.

## Job 1 (positions, for inspection only)

Drive the real contract: `agent.get_move(fen, time_left_ms)`. Reset between positions with
`agent.STATE.__init__(); agent.ENGINE.new_game()`.

| game | FEN | we played | Stockfish wants | clock (ms) |
|---|---|---|---|---|
| **R76 move 22** (lost the game) | `r4rkq/ppp2p1p/3pb3/4np1N/2P4R/6P1/PPB2P1P/R2Q2K1 b - - 9 22` | `Nxc4` | `Rae8` | 85719 |
| **R70 move 22** (lost the game) | `2kr1b1r/Q3p1pp/2p1q3/3pNbp1/3P4/2P5/PP2nPPP/R3R2K b - - 1 22` | `Nxd4` | `Nf4` | 94934 |
| **R75 move 47** (threw a win) | `8/5Rp1/k3p1p1/8/Pp5P/6P1/5PK1/1r6 w - - 2 47` | `Rc7` | `Rxg7` | 44574 |

**The question: does v1.1 still play the losing move?** Run each at `clock/2.3` (platform-equivalent)
and at the full clock. v1.0 plays the losing move in all three — that is the baseline to beat.

Why it matters: R76 `22...Nxc4` took the game from **0.00 to -295** and was the *only* decisive error
in 120 moves. R70 `22...Nxd4` went **-169 to -834**. Both are the same defect: the evaluation has no
king-danger term, only `W_KING_SHIELD` (a friendly-pawn count), so the engine grabs material while
the opponent builds against its bare king. Depth does not fix it — v1.0 still blunders at depth 13.

## Job 2: race v1.1 against v1.0

```sh
cd /Users/notyan/chessathon && uv run python -m tools.arena_openings \
  --agent /tmp/v11 --opponent /tmp/v10 --games 300 \
  --base-ms 10000 --increment-ms 100 --workers 10 \
  --label v1.1-vs-v1.0-10s --results handoff/RESULTS-v11.md --json handoff/v11-run.json
```

~30 min, resolves about +/-35 Elo. Check `uptime` first — the machine must be quiet or the numbers
are load, not strength. A `trading-lab` python process (~140 days old) uses about one core; that is
fine, anything larger is not.

**Read the interval, not the score.** The house rule (`CLAUDE.md`) is that a version only replaces
the previous one when the 95% interval is **entirely above zero**. A 300-game run cannot resolve
less than ~35 Elo, so "+20, interval -15 to +55" means *unresolved*, not *better*.

## Reporting back to Sasha

- `sh handoff/push.sh` — pushes changed `handoff/*.md` to branch `yan/findings`, opens or updates a
  PR, notifies him. Safe to run repeatedly; a no-op when nothing changed.
- `sh handoff/status.sh "what I'm working on"` — posts a status note to the open PR.
- Findings already sent: `FINDING-king-safety.md`, `FINDING-flagging.md`,
  `PROPOSAL-move-logging.md`, `RESEARCH-ROUND1.md`.
- **Not yet sent:** the round 75 and 76 analysis, and the four-variant king-safety negative result
  (`sh handoff/ship-kingsafety.sh` sends the latter).

## Known state, so it is not rediscovered

- **Two defects are costing rated games.** King safety (R70 and R76, both losses). Rook endgame
  technique (R71 and R75 — a win nearly thrown, a win drawn).
- **Four king-danger terms were built, gated and measured against v1.0. All four failed** — every
  one still plays all three losing moves. Details and the structural reason in
  `handoff/FINDING-king-safety.md`. Do not rebuild them.
- **Time manager starves long games.** Three of the last five ended under 7 s. `timing.py` was
  byte-identical in v1.0; check whether v1.1 changed it.
- `versions/v1.1/mikhail_letal/__init__.py` still reports `__version__ = "1.0.0"` — probably an
  un-bumped string, but it makes builds indistinguishable in the platform log.
- **Benchmarking trap:** node rates on this machine drift 14% between sequential runs. Always
  interleave base and variant in fresh subprocesses; never compare two numbers taken minutes apart.
