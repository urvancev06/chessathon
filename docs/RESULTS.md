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

| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) | draws | terminations | workers | load start/end | openings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fuzz-random-v0.1 | . | baselines/random | 3+0.05 s | 300 | +300 =0 -0 | 100.0% | ±0.0% | - | 0.0% | checkmate 300 | 12 | 0.10 0.27 0.22 / 7.45 2.31 0.93 | data/openings.txt |
| fuzz-greedy-v0.1 | . | baselines/greedy | 10+0.1 s | 200 | +200 =0 -0 | 100.0% | ±0.0% | - | 0.0% | checkmate 200 | 12 | 7.45 2.31 0.93 / 10.55 5.77 2.43 | data/openings.txt |
| v0.1-vs-minimax-real-clock | . | baselines/minimax | 120+0.5 s | 40 | +39 =1 -0 | 98.8% | ±2.4% | - | 2.5% | checkmate 39, threefold_repetition 1 | 4 | 1.48 3.05 2.04 / 2.66 3.91 3.34 | data/openings.txt |

### 2026-09-07 — v0.1 solo real-clock pass (nothing else running; harness.play, engine log captured)

| measurement | value | how |
|---|---|---|
| games | 3 vs `baselines/minimax` at 120 s + 0.5 s (2 as White, 1 as Black), all won by checkmate | `harness.play`, openings 37/74/101 of `data/openings.txt` |
| engine moves logged | 71 | `m … t … h … c …` lines |
| moves over their hard cap | 1, by 2 ms (clock read every 128 nodes) | `t − h` per line |
| slowest move | 8 429 ms (hard cap ≈ 10 s) | max `t` |
| minimum clock before a move | 42 958 ms | min `c` |
| mean time per move / mean soft budget | 2 526 ms / 2 925 ms | mean `t`, mean `s` |
| depth min / median / max | 1 / 5 / 7 | `d` |
| node rate (moves > 200 ms) | median 64 270 nps | `nps` |
| init time | 31–34 ms | `init` line |

The 40-game run above (4 workers, load ≈ 3 on 16 cores) is the strength number; this solo pass is
the time-management check the brief's §7.4 asks for. Both are on the dev box, not the platform core.

| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) | draws | terminations | workers | load start/end | openings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v0.1-vs-sf1400-10s | . | tools/yardstick (YARDSTICK_ELO=1400) | 10+0.1 s | 16 | +15 =1 -0 | 96.9% | ±6.1% | - | 6.2% | checkmate 15, threefold_repetition 1 | 4 | 0.22 0.24 0.95 / 2.67 1.44 1.31 | data/openings.txt |
| v0.1-vs-sf1600-10s | . | tools/yardstick (YARDSTICK_ELO=1600) | 10+0.1 s | 16 | +5 =2 -9 | 37.5% | ±22.8% | -89 (-306 to +73) | 12.5% | checkmate 14, threefold_repetition 2 | 4 | 2.67 1.44 1.31 / 3.31 2.12 1.58 | data/openings.txt |
| v0.1-vs-sf1800-10s | . | tools/yardstick (YARDSTICK_ELO=1800) | 10+0.1 s | 16 | +3 =4 -9 | 31.2% | ±19.8% | -137 (-355 to +7) | 25.0% | checkmate 12, threefold_repetition 4 | 4 | 3.31 2.12 1.58 / 4.21 2.76 1.87 | data/openings.txt |
| v0.1-vs-sf2000-10s | . | tools/yardstick (YARDSTICK_ELO=2000) | 10+0.1 s | 16 | +2 =4 -10 | 25.0% | ±17.9% | -191 (-446 to -50) | 25.0% | checkmate 12, threefold_repetition 4 | 4 | 4.21 2.76 1.87 / 4.08 3.17 2.12 | data/openings.txt |
| v0.2-vs-v0.1-10s | . | versions/v0.1 | 10+0.1 s | 300 | +225 =27 -48 | 79.5% | ±4.2% | +235 (+193 to +285) | 9.0% | checkmate 273, fifty_moves 4, threefold_repetition 18, insufficient_material 5 | 12 | 0.28 0.82 0.66 / 10.34 10.69 6.61 | data/openings.txt |
| v0.2-vs-v0.1-real | . | versions/v0.1 | 120+0.5 s | 60 | +48 =6 -6 | 85.0% | ±8.2% | +301 (+208 to +454) | 10.0% | checkmate 54, threefold_repetition 5, fifty_moves 1 | 4 | 8.75 10.34 6.53 / 1.80 3.15 3.78 | data/openings.txt |
| v0.2-fuzz-random-3s | . | baselines/random | 3+0.05 s | 100 | +100 =0 -0 | 100.0% | ±0.0% | - | 0.0% | checkmate 100 | 12 | 1.80 3.15 3.78 / 3.98 3.58 3.90 | data/openings.txt |
| v0.3-texel-vs-v0.2-10s | . | versions/v0.2 | 10+0.1 s | 300 | +95 =26 -179 | 36.0% | ±5.2% | -100 (-140 to -62) | 8.7% | checkmate 274, fifty_moves 8, insufficient_material 7, threefold_repetition 11 | 12 | 0.49 4.59 4.18 / 10.21 11.37 8.58 | data/openings.txt |
| v0.3-texel-lambda40-vs-v0.2-10s | . | versions/v0.2 | 10+0.1 s | 300 | +126 =28 -146 | 46.7% | ±5.4% | -23 (-61 to +14) | 9.3% | checkmate 272, fifty_moves 6, threefold_repetition 16, insufficient_material 6 | 12 | 4.88 9.58 8.13 / 8.82 11.44 10.42 | data/openings.txt |
| v0.2-vs-sf1600-real | . | tools/yardstick (YARDSTICK_ELO=1600) | 120+0.5 s | 60 | +38 =8 -14 | 70.0% | ±10.7% | +147 (+65 to +249) | 13.3% | checkmate 52, threefold_repetition 8 | 6 | 0.20 3.51 7.07 / 1.85 4.41 5.56 | data/openings.txt |
| v0.2-vs-sf1800-real | . | tools/yardstick (YARDSTICK_ELO=1800) | 120+0.5 s | 60 | +44 =4 -12 | 76.7% | ±10.3% | +207 (+118 to +329) | 6.7% | checkmate 56, threefold_repetition 4 | 6 | 1.85 4.41 5.56 / 1.46 4.05 5.30 | data/openings.txt |
| v0.2-vs-sf2000-real | . | tools/yardstick (YARDSTICK_ELO=2000) | 120+0.5 s | 60 | +25 =4 -31 | 45.0% | ±12.3% | -35 (-125 to +51) | 6.7% | checkmate 56, threefold_repetition 3, insufficient_material 1 | 6 | 1.46 4.05 5.30 / 1.83 3.97 5.22 | data/openings.txt |
| v0.2-vs-sf2200-real | . | tools/yardstick (YARDSTICK_ELO=2200) | 120+0.5 s | 60 | +16 =14 -30 | 38.3% | ±10.8% | -83 (-168 to -6) | 23.3% | checkmate 46, fifty_moves 2, threefold_repetition 12 | 6 | 1.83 3.97 5.22 / 1.20 3.46 4.99 | data/openings.txt |
| v0.2-vs-sf2400-real | . | tools/yardstick (YARDSTICK_ELO=2400) | 120+0.5 s | 60 | +18 =16 -26 | 43.3% | ±10.8% | -47 (-127 to +29) | 26.7% | checkmate 44, threefold_repetition 11, fifty_moves 5 | 6 | 1.20 3.46 4.99 / 2.40 4.55 5.44 | data/openings.txt |

### 2026-09-08 — v0.2 rating estimate from the Stockfish yardstick (real clock, 6 workers, load ≈ 6/16)

| level | games | +W =D −L | score |
|---|---|---|---|
| Stockfish 19 UCI_Elo 1600 | 60 | +38 =8 −14 | 70.0% |
| Stockfish 19 UCI_Elo 1800 | 60 | +44 =4 −12 | 76.7% |
| Stockfish 19 UCI_Elo 2000 | 60 | +25 =4 −31 | 45.0% |
| Stockfish 19 UCI_Elo 2200 | 60 | +16 =14 −30 | 38.3% |
| Stockfish 19 UCI_Elo 2400 | 60 | +18 =16 −26 | 43.3% |

Maximum-likelihood fit over all 300 games, draws as ½: **CCRL-40/4-scale ≈ 2050 (95% interval 1940–2170, bootstrap 2000–2110 plus ±100 yardstick calibration in quadrature); FIDE-equivalent ≈ 1840–2360 (Route A: CCRL−100 lower bound, TalkChess 2800−0.7×(2800−CCRL) upper bound); chess.com Rapid-equivalent ≈ 1820–2340; chess.com Blitz-equivalent ≈ 1730–2700 (ChessGoals table, interpolated). Route B (Sunfish) not run. Estimates built on a rating-limited reference engine and a survey table; honest uncertainty ±200 or more on the human scales.** Caveats: Stockfish's UCI_Elo is calibrated for 120 s + 1 s and anchored to CCRL 40/4; 60 games per level; the 2200 and 2400 scores are not monotonic (limited-strength noise); games shared the machine six at a time; zero flags, lowest clock 1 889 ms.

| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) | draws | terminations | workers | load start/end | openings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v0.3-vs-v0.2-10s | . | versions/v0.2 | 10+0.1 s | 300 | +159 =65 -76 | 63.8% | ±4.8% | +99 (+64 to +136) | 21.7% | checkmate 235, threefold_repetition 40, insufficient_material 17, fifty_moves 7, stalemate 1 | 12 | 0.87 0.97 0.81 / 10.91 11.49 7.26 | data/openings.txt |
| v0.3-vs-v0.2-real | . | versions/v0.2 | 120+0.5 s | 60 | +29 =13 -18 | 59.2% | ±11.0% | +64 (-13 to +149) | 21.7% | checkmate 47, threefold_repetition 9, insufficient_material 3, fifty_moves 1 | 4 | 7.19 10.57 7.06 / 2.84 3.76 4.21 | data/openings.txt |
| numba-fuzz-random | . | baselines/random | 3+0.05 s | 200 | +200 =0 -0 | 100.0% | ±0.0% | - | 0.0% | checkmate 200 | 8 | 0.50 0.60 1.45 / 7.32 7.51 5.22 | data/openings.txt |

### 2026-09-08 — Stage 1 phase 2: the compiled engine against the Python one (dev box, solo)

Same machine, same positions, same three-second budget, both engines started from a cleared table.
Command: a script that calls `fastsearch.FastEngine.search` and `search.Engine.search` in turn with
`soft_deadline = hard_deadline = now + 3.0` (recorded in the commit message of this row).

| position | compiled: depth/seldepth, nodes, nps | Python: depth/seldepth, nodes, nps | ratio |
|---|---|---|---|
| standard start | 12/28, 2 205 699, 735 205 | 9/21, 161 792, 53 886 | 13.6x nodes, +3 plies |
| middlegame (`r4rk1/1pp1qppp/…`) | 10/30, 2 074 624, 691 482 | 6/28, 150 784, 50 232 | 13.8x nodes, +4 plies |
| rook ending (`8/2p5/3p4/KP5r/…`) | 14/26, 2 738 176, 912 598 | 10/19, 206 336, 68 760 | 13.3x nodes, +4 plies |

| measurement | value | how |
|---|---|---|
| import + compile, extracted zip | 18.5 s | `harness.package` smoke games, `init` log line; platform budget is 90 s |
| import + compile, in place | 16.9–17.3 s | `import agent`, `init` log line |
| peak RSS after three moves | 349 MB | `resource.getrusage(RUSAGE_SELF).ru_maxrss`; platform cap is 2 GB |
| compiled evaluation | 204 ns (opening), 129 ns (rook ending) | 500 000 calls inside a jitted loop |
| Python evaluation, same positions | 8 312 ns, 2 666 ns | 20 000 calls |
| `numba.objmode` clock read | 301 ns | 100 000 reads inside a jitted loop; hence `NODE_CHECK_INTERVAL = 512` |
| Python → jitted call boundary | 4.0 µs | 20 000 calls of `negamax` at depth 0; why the root is Python (DECISIONS.md) |
| compile time if the root is compiled too | 34.2 s total | measured per function before the root was moved to Python: `negamax` 13.4 s, `_search_root` 6.3 s, aspiration 2.7 s, deepening loop 5.4 s |

| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) | draws | terminations | workers | load start/end | openings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| numba-vs-v0.2-10s | . | versions/v0.2 | 10+0.1 s | 300 | +279 =19 -2 | 96.2% | ±1.6% | +560 (+495 to +660) | 6.3% | checkmate 281, fifty_moves 1, threefold_repetition 16, insufficient_material 2 | 8 | 0.72 2.63 3.71 / 6.25 7.76 7.59 | data/openings.txt |

### 2026-09-08 — fuzz re-run on the final build, stopped early

The 200-game fuzz row above (`numba-fuzz-random`) was run at commit `4383d28`, one commit before
the transposition table gained its generation field. The re-run on the final build was started and
**stopped at game 25 of 200** to give the machine to the real-clock promotion match, which was
sharing it with a measured match in another checkout. What it did play: **25 games, 25 wins by
checkmate, no failed termination, lowest clock 1 649 ms of 3 000**. The final build's legality is
otherwise covered by the full suite (497 tests, including a legal move required from the compiled
search on 3 000 sampled positions at three node limits, and the property suite driving
`agent.get_move`). Recorded here rather than dropped, because a gate that was not finished should
not read as one that was.

### 2026-09-08 — the recorded unconverted wins, replayed with the compiled engine

Same protocol as the "Known unconverted wins" table above: the opponent is a second copy of the
engine, 1 250 ms per move (5 000 ms for the Lucena, as recorded there), played out with
python-chess. Two of the three are now converted; the third is on a knife edge.

| position | v0.2 (interpreted) | compiled | note |
|---|---|---|---|
| Lucena `1K1k4/1P6/8/8/8/8/r7/2R5 w - - 0 1` | not converted | **converted**, mate in 69–87 plies | not the textbook bridge: it gives the rook back for the promotion and wins queen against rook |
| `8/8/8/8/3k4/8/8/4KQ2 w - - 82 60` (KQ vs K, 18 plies of fifty-move room) | not converted, drawn two moves short | **converted**, mate in 13 plies | the Syzygy tablebase gives mate in 13 with 18 plies of room, so this is now at tablebase pace |
| `8/8/8/3K4/8/8/8/q6k b - - 0 291` (KQ vs K, 19 plies before the 600-ply cap) | converted, 17 plies | **knife edge**: mate delivered exactly at ply 600 in one replay, missed in another and then drawn | the position needs 19 of the 19 remaining plies; which side of the line a run lands on depends on the wall clock, so it is neither a fix nor a regression to claim |

The Python engine was replayed alongside the compiled one on the third position and mated in 19
plies as well, so the two are on the same edge, not on opposite sides of it.

| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) | draws | terminations | workers | load start/end | openings |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| v1.0-vs-sf1800-real | . | tools/yardstick (YARDSTICK_ELO=1800) | 120+0.5 s | 16 | +13 =1 -2 | 84.4% | ±17.3% | - | 6.2% | checkmate 15, threefold_repetition 1 | 5 | 1.11 0.87 1.29 / 1.80 3.75 3.26 | data/openings.txt |
| v1.0-vs-sf2000-real | . | tools/yardstick (YARDSTICK_ELO=2000) | 120+0.5 s | 16 | +11 =2 -3 | 75.0% | ±20.0% | +191 (+35 to +512) | 12.5% | checkmate 14, threefold_repetition 2 | 5 | 1.80 3.75 3.26 / 3.19 5.48 4.85 | data/openings.txt |
| v1.0-vs-sf2200-real | . | tools/yardstick (YARDSTICK_ELO=2200) | 120+0.5 s | 16 | +10 =1 -5 | 65.6% | ±23.2% | +112 (-53 to +360) | 6.2% | checkmate 15, threefold_repetition 1 | 5 | 3.19 5.48 4.85 / 4.45 6.11 5.96 | data/openings.txt |
| v1.0-vs-sf2400-real | . | tools/yardstick (YARDSTICK_ELO=2400) | 120+0.5 s | 16 | +8 =2 -6 | 56.2% | ±23.5% | +44 (-125 to +238) | 12.5% | threefold_repetition 2, checkmate 14 | 5 | 4.45 6.11 5.96 / 5.53 6.35 6.48 | data/openings.txt |
