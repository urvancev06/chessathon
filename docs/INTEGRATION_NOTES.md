# Integration notes — Stage 0 (2026-09-06)

Written by the integration pass after the five builders (evaluation, search, wrapper, openings,
arena) finished. Everything below was measured on the WSL2 dev box (16 cores, load ~0.2-0.9), not
on the platform's EPYC core; expect the platform to be slower.

## What changed in integration

One code change, in `agent.py`:

- `_say()` now prints with `flush=True`. The harness runner (and, per the brief, the platform's)
  points fd 1 at a pipe before importing the agent. Python block-buffers a pipe, and the referee
  kills the process the moment the game ends, so without the flush a whole game's log lines
  (init time, per-move depth/nodes/nps/time/budget/clock) sat in the buffer and never reached the
  log. Observed directly: the first `harness.play` game against `baselines/greedy` printed no
  agent output at all; after the fix every line arrives. The calibration protocol
  (`docs/CALIBRATION.md`) reads those lines, so this mattered.

Nothing else needed fixing. All five modules already matched the `docs/DESIGN.md` signatures:
`agent.py` imports `Searcher`, `GameState`, `fallback_move`, `DEFAULT_PARAMS`, `budget` exactly as
the other modules export them, `tests/test_properties.py` ran (44 tests, not skipped) against the
integrated engine, and `ruff check .` / `mypy` were clean before I touched anything.

## Checks run (from the repo root)

| Check | Result |
|---|---|
| `.venv/bin/ruff format --check agent.py mikhail_letal tests tools harness baselines` | 32 files already formatted |
| `.venv/bin/ruff format --check .` | only `docs/DESIGN.md` would change (see below) |
| `.venv/bin/ruff check .` | All checks passed |
| `.venv/bin/mypy` (pyproject file list, `--strict`) | Success: no issues found in 28 source files |
| `.venv/bin/python -m pytest -q` | 143 passed in 32.8 s (test_properties: 44 ran) |
| `python -m harness.arena --opponent baselines/random --games 2 --base-ms 5000` | +2 =0 -0, both by checkmate, 8.9 s wall |
| `python -m harness.play --white . --black baselines/greedy --base-ms 20000 --increment-ms 200` | white (us) by checkmate in 16 of our moves, twice (before and after the flush fix) |
| `python -m harness.package` | zip 23,333 bytes / 66,825 unzipped; both smoke games (120 s + 0.5 s, 20 plies) clean |

`ruff format .` wants to reflow the Python code block inside `docs/DESIGN.md` (ruff 0.16 formats
fenced code in Markdown). I did not touch `docs/DESIGN.md`. `make gate` runs `ruff check`, not
`ruff format`, so nothing fails; if the reflow is unwanted, `extend-exclude = ["docs"]` under
`[tool.ruff]` in `pyproject.toml` is the one-line fix (not mine to make).

## Numbers

Agent log from the `harness.play` game (20 s + 0.2 s, we are White, English Opening FEN):

```
init 33 ms Mikhail LeTal 0.1.0
m c4d5 d 5/16 n 34303 nps 49804 t 689 s 896 h 2689 c 20000
m b2c3 d 5/15 n 136192 nps 51180 t 2661 s 884 h 2652 c 19510
m f3e5 d 6/19 n 108991 nps 52396 t 2081 s 833 h 2500 c 17048
m e5d3 d 5/13 n 42712 nps 55544 t 769 s 785 h 2355 c 15167
m e1g1 d 5/18 n 74063 nps 53268 t 1391 s 780 h 2341 c 14597
m c1b2 d 4/15 n 18630 nps 53237 t 350 s 749 h 2247 c 13406
m d3b2 d 5/19 n 63397 nps 53736 t 1180 s 754 h 2263 c 13256
m d2d4 d 5/18 n 88772 nps 54806 t 1620 s 728 h 2183 c 12275
m c3d4 d 5/18 n 59090 nps 56308 t 1050 s 697 h 2092 c 10855
m b2d3 d 4/15 n 17941 nps 55019 t 326 s 674 h 2021 c 10004
m d1a4 d 5/21 n 92587 nps 55521 t 1668 s 678 h 2034 c 9878
m a4a6 d 5/15 n 35062 nps 60822 t 577 s 636 h 1908 c 8409
m f1c1 d 5/18 n 104307 nps 60388 t 1728 s 632 h 1895 c 8032
m a1b1 d 5/16 n 90126 nps 61074 t 1476 s 587 h 1626 c 6504
m b1b6 d 3/1 n 144 nps 182948 t 1 s 554 h 1307 c 5228
m a6b6 d 1/1 n 44 nps 116691 t 1 s 560 h 1357 c 5427
```

- Node rate: 50-61k nps in the middlegame (the two 1 ms mate moves are TT hits, ignore their nps).
- Depth at the 20 s clock: 4-6 (seldepth 13-21). At the real 120 s clock (zip smoke games):
  depth 5-6, seldepth 18-32, 1.5-7.7 s per move against soft ~3.3 s / hard ~10 s.
- Hard deadline: move 2 ran to `t 2661` against `h 2652`, a 9 ms overshoot inside `get_move`
  (the clock is read every 1024 nodes, ~20 ms at this speed).
- Local harness overhead: referee-measured spend minus self-measured `t` was 0 or 1 ms on every
  move (referee clocks are rounded to 1 ms). The platform's will be larger; calibrate from the
  validation log as the brief says.
- Import time (`python -c "import time; t=time.perf_counter(); import agent; ..."`, three runs):
  0.033 s each, including the depth-2 warm-up search.
- Peak RSS of a 10 s search (`resource.getrusage`, middlegame
  `r1bq1rk1/pp1nbppp/2p1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R1BQ1RK1 w - - 0 9`): 42.4 MB after,
  16.8 MB before; depth 6, seldepth 24, 501,760 nodes, 50,088 nps, 53,640 TT entries. Linear
  extrapolation puts the 400k-entry TT cap near 200 MB, consistent with the search builder's
  <= 540 bytes/entry bound. Measured while a harness game ran on another core (RSS is not
  load-sensitive; the nps figure may be slightly low).

## For the reviewers

1. `Key = Hashable` is defined twice: `type Key = Hashable` in `mikhail_letal/gamestate.py` and
   `Key = Hashable` in `mikhail_letal/search.py`. They are compatible and DESIGN names the alias
   without a home; one import would be tidier. Left alone (not a redesign item).
2. Panic band: for clocks in [1500, ~1650) ms `budget()` returns `soft = hard = 0`, so the search
   gets deadlines equal to `t0` and aborts at its first clock check (1024 nodes, ~20 ms), returning
   the first ordered root move or a completed depth 1. Legal and fast, but a depth-0 move; raising
   `panic_ms` to `overhead_ms + floor_ms` would route that band to the fallback instead. DESIGN's
   values were kept.
3. Time profile at 120 s: because an iteration begun before 0.45 x soft may run to the hard
   deadline, real moves take 1.5-7.7 s against a 3.3 s soft target (average spend in the smoke games
   3.1-3.5 s per move including the increment). Sustainable at 40 moves-to-go, but this is the
   thing to watch in the first validation log.
4. Builder deviations from DESIGN, all deliberate and documented in their modules: the search
   scores checkmate ahead of the ply-cap/fifty-move draw (matches the referee's check order);
   quiescence searches all evasions when in check and checks `any(generate_legal_moves())` on
   capture-less leaves (3-7.5% nps) so stalemate is never evaluated; the evaluation truncates the
   taper toward zero instead of floor division so mirrored positions score exactly opposite, and
   reads piece bitboards directly instead of `pieces_mask` + `scan_forward` (same semantics, 1.7x
   faster). `test_colour_symmetry_under_mirror` asserts `evaluate(b) == evaluate(b.mirror())`
   because `Board.mirror()` also flips the side to move; that is the correct negamax statement.
5. `data/openings.txt` now exists (219 FENs, 34 names), so `tools/arena_openings.py` no longer
   falls back to the harness openings by default.
6. `weights/pst.json` and `weights/PROVENANCE.json` record git commit `56a554a` (HEAD when
   generated); the commit that adds them will differ. Re-running `tools/gen_pst.py` after the
   commit updates only the header (tables are byte-identical and tested against the generator).
7. `submission.zip` was built in the repo root by `harness.package`; it is git-ignored.
