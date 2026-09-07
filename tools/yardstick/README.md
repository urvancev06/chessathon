# Yardstick

A harness-compatible agent (`get_move(fen, time_left_ms) -> uci`) that plays the moves of a
local UCI engine, normally Stockfish with `UCI_LimitStrength`. It exists so the referee can put
our engine against a known strength (brief, section 8.2) and so the web app can offer Stockfish
seats and game analysis.

Stockfish is a **local-only instrument** (brief, section 2.2). It lives outside the repository at
the path in `YARDSTICK_ENGINE`, it never enters the repository or the submission zip, it never
influences a move our engine plays, and nobody reads its source. `tools/` is never packaged;
keep it that way. Numbers measured against it are yardsticks for our own comparison, not ratings:
Stockfish's Elo scale is documented as calibrated at 120 s + 1 s against CCRL 40/4, so report
them as "CCRL-40/4-scale estimate" with an interval, never as a bare rating.

## Environment

| variable                | meaning                                                                 |
|-------------------------|-------------------------------------------------------------------------|
| `YARDSTICK_ENGINE`      | path to the binary; else `~/.local/opt/stockfish/stockfish`, else `stockfish` on PATH |
| `YARDSTICK_ELO`         | sets `UCI_LimitStrength=true`, `UCI_Elo=<n>` (Stockfish: 1320..3190); unset = full strength |
| `YARDSTICK_MOVETIME_MS` | fixed thinking time per move; unset = play on the clock the harness hands us |
| `YARDSTICK_INC_MS`      | increment told to the engine when playing on the clock (default 500)    |

The harness points `HOME` at a scratch directory for every agent (as the platform does), so the
conventional path is also looked up under the account's real home from the password database;
`YARDSTICK_ENGINE` is still the explicit, reliable choice.

The engine is opened once at import (`Threads=1`, `Hash=16`, `Move Overhead=100`) so its start-up
lands in the init budget, not on the clock. Each move is validated against the position; if the
engine fails, the first legal move in UCI order is played instead, so a broken yardstick loses
loudly rather than crashing the match. One log line per move goes to stderr:
`yardstick <elo|full> <uci> <ms>`.

## Running a match

From the repository root, with the main virtualenv:

```
YARDSTICK_ELO=1600 .venv/bin/python tools/arena_openings.py --opponent tools/yardstick \
    --real-clock --games 60 --label v0.3-vs-sf1600 --results docs/RESULTS.md \
    --json data/arena/v0.3-sf1600.json
```

or with the flag that records the setting in the results row:

```
.venv/bin/python tools/arena_openings.py --opponent tools/yardstick --env YARDSTICK_ELO=1600 \
    --real-clock --games 60
```

`--env KEY=VALUE` is repeatable and is applied to the process environment before any agent
starts; the harness copies that environment into every agent it launches. The pairs are written
into the JSON record and appended to the opponent cell of the Markdown results row.

Play one game by hand:

```
YARDSTICK_ELO=1400 .venv/bin/python -m harness.play --white . --black tools/yardstick
```

The brief's protocol: levels 1400, 1600, 1800, 2000, 2200 (extend upward while the agent scores
above 70%), at least 60 games per level at 120 s + 0.5 s, colours alternated, openings from
`data/openings.txt`, run alone on the machine or with the load noted next to the result.
