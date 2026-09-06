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
| curated openings collected | 219 distinct FENs, 34 names, from 400 game pages (80 of 335 teams sampled) | `tools/collect_openings.py`, one request per second, 6 Sep 21:14–21:30 UTC |
