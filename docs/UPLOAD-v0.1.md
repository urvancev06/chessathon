# Upload note — v0.1 (Stage 0)

Commit `02b1902`, tag `v0.1`. `submission.zip` built by `harness.package` from that tree:
sha256 `5b52e75f03997d8e788663db4869c52c726b320a9348fd8547c24a8aecc3f66e`, 26 951 bytes,
77 712 unzipped. Contents: `agent.py`, `mikhail_letal/{__init__,evaluation,search,timing,gamestate,fallback}.py`,
`weights/pst.json`, `weights/PROVENANCE.json`. Nothing from tools/, tests/, docs/, data/, versions/, app/.

## 1. Bottom line

- v0.1 is a python-chess engine with our own alpha-beta search, tapered PST evaluation, time
  management, repetition tracking and a safety wrapper. It is shippable.
- 500 fuzz games and 43 real-clock games: zero crashes, illegal moves, flags or init failures.
- It replaces nothing (first upload). The ladder rating it earns only seeds the Swiss.

## 2. Results

| version | opponent | tc | games | +W =D −L | score | 95% interval | Elo (95%) | terminations | load | openings |
|---|---|---|---|---|---|---|---|---|---|---|
| v0.1 | baselines/random | 3+0.05 | 300 | +300 =0 −0 | 100% | — | — | 300 checkmate | 12 workers | curated 219 |
| v0.1 | baselines/greedy | 10+0.1 | 200 | +200 =0 −0 | 100% | — | — | 200 checkmate | 12 workers | curated 219 |
| v0.1 | baselines/minimax | 120+0.5 | 40 | +39 =1 −0 | 98.8% | ±2.4% | interval unbounded above (no losses) | 39 checkmate, 1 threefold (pawn down, intended) | 4 workers, load ≈ 3/16 | curated 219 |
| v0.1 | baselines/minimax | 120+0.5 | 3 solo | +3 =0 −0 | 100% | — | — | 3 checkmate | solo | curated |

## 3. Safety status

- Fuzz 500/500 clean; property tests 44 (promotions ×4, en passant, castling, stalemate,
  insufficient material, single legal move, mate in 1, halfmove 99, third repetition, fresh-game
  reset), full suite 203 tests green; ruff and mypy strict clean.
- Solo pass: 71 engine moves, slowest 8 429 ms against a ~10 s cap, worst overshoot 2 ms, lowest
  clock before a move 42 958 ms, import 31–34 ms.
- Zip inspected (`unzip -l`): only the nine files above. Init from the extracted zip 35–40 ms.

## 4. Not verified

- Anything on the platform: init time, per-move overhead, node rate on the EPYC core (expected
  ~3× slower than here), memory under the 2 GB cap in a long game.
- The 40-game run shared the machine with four workers; the solo pass is only three games.
- No perft (python-chess is the move generator in Stage 0).

## 5. What you must do manually

Upload `submission.zip` from commit `02b1902` (tag `v0.1`), sha256 above. Wait for validation.
Paste back the full validation log: init time, every per-move time and clock left, any stderr, and
the two smoke-game results.

## 6. Next step

Calibrate `overhead_ms` and the speed factor from that log (docs/CALIBRATION.md), then start
Stage 1 (the numba engine).
