# Results

Every measurement, appended chronologically. Nothing here is claimed unless it was run. Arena rows
are appended by `tools/arena_openings.py --results docs/RESULTS.md`; other measurements are added
by hand with the command that produced them.

Conventions: time control as `base+inc` in seconds; `load` is the 1-minute load average at the
start and end of the run (16-core machine); "solo" means nothing else was running.

## Machine

- Development machine: 16 cores, 7.8 GB RAM, WSL2 on Windows, Python 3.12.14.
- Platform: one core of an AMD EPYC 9V74 at 2.60 GHz, 2 GB RAM. Speed ratio is calibrated after
  the first upload (see CALIBRATION.md).

## Arena runs

| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) | draws | terminations | workers | load start/end | openings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

## Other measurements

### 2026-09-06/07 — Stage 0 integration (dev box, not the platform core)

| measurement | value | how |
|---|---|---|
| node rate, middlegame | 50–61k nps | agent log lines from `harness.play` vs `baselines/greedy` at 20 s + 0.2 s |
| depth at 20 s clock | 4–6 (seldepth 13–21) | same game |
| depth at 120 s clock | 5–6 (seldepth 18–32), 1.5–7.7 s per move vs soft ≈ 3.3 s / hard ≈ 10 s | `harness.package` smoke games from the extracted zip |
| hard-deadline overshoot inside `get_move` | 9 ms worst seen (`t 2661` vs `h 2652`) | clock read every 1024 nodes ≈ 20 ms at this speed |
| local harness overhead (referee-measured − self-measured) | 0–1 ms per move | referee clocks vs the `t` token |
| import time (incl. depth-2 warm-up) | 0.033 s | `python -c "import time; t=time.perf_counter(); import agent; print(...)"`, 3 runs |
| peak RSS after a 10 s search | 42.4 MB (16.8 MB before); 53,640 TT entries | `resource.getrusage`; extrapolates to ≈ 200 MB at the 400k-entry TT cap |
| `evaluate()` cost | 3.4–3.8 µs middlegame, 1.6 µs endgame | 10,000-call loops, `perf_counter` |
| zip | 23,333 bytes, 66,825 unzipped: agent.py, mikhail_letal/*.py, weights/pst.json, weights/PROVENANCE.json | `harness.package`; both platform-style smoke games clean |
| test suite | 143 passed (44 property tests ran) | `pytest -q`, 33 s |
| review nps (3 s search, start position) | 51.7k before → 67.2k after the 2026-09-07 review fixes (+30 %, same move g1f3, depth 6/17) | `scratchpad/nps_bench.py`, median of 3 |
| gen-2 gc pause, 60 s middlegame search | 143 ms max (8 collections, 270k `chess.Move` entries) before → 13.7 ms max (5 collections, int-only entries) after | `gc.callbacks` timing |
| RSS at the TT cap | 120 MB (250k entries, cleared mid-search once, 3.76M nodes, nps 62.7k) after; 143 MB at 270k entries before | `resource.getrusage`, same 60 s search |
| curated openings collected | 219 distinct FENs, 34 names, from 400 game pages (80 of 335 teams sampled) | `tools/collect_openings.py`, one request per second, 6 Sep 21:14–21:30 UTC |

## Known unconverted wins (Stage 2 targets)

Probed with the reviewer's driver (`endgame_probe.py`, 5 000 ms per move, so the hard limit is
1 250 ms per move; the opponent is a second copy of the engine):

| position | outcome at 5 s | note |
|---|---|---|
| Lucena `1K1k4/1P6/8/8/8/8/r7/2R5 w - - 0 1` | not converted | rook-endgame technique beyond a depth-6 horizon; Stage 2 |
| `8/8/8/8/3k4/8/8/4KQ2 w - - 82 60` (KQ vs K, 18 plies of fifty-move room) | **not converted**: draw by fifty moves, mate two moves short | the Syzygy tablebase (lichess, queried by hand) gives mate in 13 plies with 18 plies of room, so it is winnable; after the 2026-09-07 fixes the engine makes steady progress (weak king driven to the edge, `Kg6`/`Qe5` vs `Kf8` at the draw) but not at tablebase pace, and depth 6 at 1 250 ms per move never sees the mate in time; see DECISIONS.md |
| `8/8/8/3K4/8/8/8/q6k b - - 0 291` (KQ vs K, 19 plies before the 600-ply cap) | **converted** (mate in 9 moves, 17 plies) | drawn at the cap before the 2026-09-07 fixes |
