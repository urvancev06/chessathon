# Code map and house rules, for auditing the docs against the code

Written 8 September 2026 by session `chessathon-5a` for `chessathon-64`, which is auditing every
document in the repo. Read-and-describe only; nothing was changed to produce this.

---

## 1. Code map

### What actually runs in a rated game

The platform imports `agent.py` and calls `get_move(fen, time_left_ms)`. That is the only entry
point. Everything reachable from it ships; everything else in the package is reference or is dead
at runtime.

```
agent.py                    the safety wrapper and the driver
 ├── mikhail_letal.warmup           compile budget, deadline for the numba warm-up
 ├── mikhail_letal.fastsearch       THE SEARCH (compiled)   <- the hot path
 │    ├── mikhail_letal.fastboard   board, movegen, make/unmake (compiled)
 │    ├── mikhail_letal.fasteval    evaluation (compiled)
 │    ├── mikhail_letal.search      CONSTANTS ONLY (imported, not executed)
 │    └── mikhail_letal.evaluation  three constants + load_tables (the JSON parser)
 ├── mikhail_letal.gamestate        position history, repetition, desync reset
 ├── mikhail_letal.timing           the time budget
 ├── mikhail_letal.fallback         the always-legal fallback move
 └── mikhail_letal.search           GAME_PLY_CAP only
```

**Runs every move:** `agent.py`, `fastsearch.py`, `fastboard.py`, `fasteval.py`, `gamestate.py`,
`timing.py`, `warmup.py` (at import). `fallback.py` runs only on the panic path, on a guard
rejection, or after an exception.

**Ships but never executes in a rated game:**

- `mikhail_letal/search.py` — the pure-Python engine (`class Engine`). It is two things at once:
  (a) the readable reference implementation of the algorithm, and (b) **the single home of every
  shared search constant**. `fastsearch.py` imports those constants from it (see its import block
  around line 118) precisely so the two engines cannot drift, and `tests/test_fastsearch.py`
  checks the parity. A constant added to `fastsearch.py` alone breaks that contract.
- `mikhail_letal/evaluation.py` — the reference evaluation and the **oracle** for the compiled one.
  `tests/test_fasteval.py` compares `fasteval.evaluate` against `evaluation.evaluate` integer for
  integer on 20,000 positions. **Consequence for auditing: any evaluation term must exist in both
  files.** `fastsearch.py` imports only `DRAW_SCORE`, `MATE_SCORE`, `MATE_THRESHOLD` from it, and
  `fasteval.load_eval_tables` uses its `load_tables` to parse `weights/pst.json`.
- `mikhail_letal/searchboard.py` — used **only** by `search.Engine`. Nothing on the compiled path
  imports it. It is the v0.3 incremental-evaluation speedup for the Python engine.

### Where the Python/compiled boundary sits

The iterative-deepening root loop is **Python**, in `FastEngine.search` (`fastsearch.py`, around
line 1098), with aspiration and the root move loop beside it. Exactly one call crosses into
compiled code per root move per iteration (`negamax`). Compiling the root too was measured and
rejected: it pushed start-up from ~18 s to ~34 s for no gain, because the root runs a handful of
times per move rather than millions. The reasoning is in a block comment near line 951.

### Two engines, one contract

| | Python | Compiled |
|---|---|---|
| board | `chess.Board` (+ `searchboard.SearchBoard`) | `fastboard` 0x88 mailbox |
| evaluation | `evaluation.evaluate` | `fasteval.evaluate` |
| search | `search.Engine` | `fastsearch.FastEngine` |
| constants | defined in `search.py` | imported from `search.py` |
| role | reference, oracle, fallback | ships and plays |

---

## 2. Format and conventions

### `docs/RESULTS.md`

Append-only, chronological. Nothing is ever deleted, including results that came out badly — the
Texel tuning rows recording a 100-Elo loss are deliberately kept.

Arena rows are appended by `tools/arena_openings.py --results docs/RESULTS.md`, never hand-written,
with these columns:

```
| label | agent | opponent | tc | games | +W =D -L | score | 95% interval | Elo (95%) |
  draws | terminations | workers | load start/end | openings |
```

A valid measurement row carries the game count, the confidence interval, the termination counts,
the worker count and the machine load, because a match played while eleven others share the
machine measures something different from one played alone. Other measurements are added by hand
in prose tables under `## Other measurements`, each stating the command that produced it.

**The promotion rule the whole repo runs on:** a version replaces the previous one only when it
wins a match whose 95 % interval is above zero, at the real time control (120 s + 0.5 s), with the
previous version kept in `versions/` as the opponent.

### `docs/PROVENANCE.md`

One row per shipped constant, table, or weight file:

```
| parameter / file | value or shape | produced by (script + commit) | data (path + sha256 + how
  obtained) | run id / date | note |
```

Every generating script must be deterministic and re-runnable. A value adjusted by hand says so in
the note, with the reason. The machine-readable twin that ships in the zip is
`weights/PROVENANCE.json`.

### `docs/DECISIONS.md`

Chronological, newest at the bottom, one `## YYYY-MM-DD — short title` per decision. Each records
**the alternative that was rejected and why**. Negative results get an entry of their own.

### Shipping source

Python 3.12, fully type-annotated, ruff and mypy `strict` clean. Comments say *why*, not *what*;
the shipped code is what a judge reads. Enforced beyond defaults: `line-length = 100`,
`extend-exclude = ["docs"]` (ruff would otherwise reflow the Python inside the Markdown), and
mypy `strict = true` over `agent.py`, `harness`, `mikhail_letal`, `tools`, `tests`.

Numba-specific rules that are easy to get wrong when auditing:

- Every `@njit` function must be listed in its module's `JITTED` and exercised by `warm_up`, or it
  compiles on the clock mid-game. Tests assert no new signature appears during a game.
- `cache=False` everywhere: the platform wipes `/tmp` between games, so an on-disk cache never hits
  and only costs start-up budget.
- No 64-bit bitboard shift tricks in compiled code. Python's arbitrary-precision ints become int64
  under numba, where a signed right shift sign-extends and a left shift silently overflows. This is
  why `fasteval` uses per-file pawn summaries rather than the bitboard fills `evaluation.py` uses.
- The shipped code reads **no environment variables** and contains no randomness.

---

## 3. The uncommitted work in this tree

`agent.py`, `search.py`, `fastsearch.py`, `timing.py`, `tests/test_timing.py`,
`tests/test_fastsearch.py`, five docs, and the untracked `tools/sim_time.py` are **one change in
progress**: a rewrite of time management.

What it does: replaces the fixed `next_iteration_fraction = 0.45` rule with a prediction of what
depth *d+1* will cost, taken from the last two completed iterations; stretches the target when the
root move is unstable and stops early when it is stable; lowers `overhead_ms` from 150 to 50
against a measured 1.1 ms; and re-picks `moves_to_go` using `tools/sim_time.py`, a deterministic
simulator committed so the new numbers have a re-runnable source.

**Not finished and not measured.** No arena screen has run on it. Do not treat any claim about it
as a result. The problem it targets is real and measured: per-move times on the platform are
bimodal (1.5–3.0 s or 8.9–10.1 s, nothing between), and across five rated games the engine finished
with 87.5 s, 4.7 s, 31.6 s, 90.2 s and 6.0 s left of roughly 130–175 s.

`tools/collect_ladder_games.py` is untracked and unrelated: it downloads finished games of the
top-rated ladder teams for scouting, reusing `collect_openings`'s rate-limited cached fetcher.

---

## 4. Known-stale and known-wrong spots

Confirmed, so you need not rediscover them:

1. **`docs/PROVENANCE.md` documents environment-variable feature switches that no longer exist.**
   The row for `feature_flag` switches (`LETAL_NULL_MOVE`, `LETAL_LMR`, …) describes a mechanism
   that was deliberately removed: the shipped engine must not read environment variables the
   platform does not set. `grep feature_flag mikhail_letal/ agent.py` returns nothing. **This row
   is wrong and should go, or be rewritten as plain constants.**
2. **`README.md`, `docs/SUBMISSION_GUIDE.md`, `docs/report.tex` and `docs/PLAN.md` describe the
   interpreted engine.** They still say roughly 2050 Elo, ~50,000 positions per second and depth 9.
   The shipped build is compiled: depth 10–12 on the platform at 330,000–460,000 nodes/s, and the
   rating measurement that replaces 2050 is still running. `SUBMISSION_GUIDE.md` still names
   v0.2.1 as the build to upload; it is v1.0.
3. **`docs/report.tex` has seven `\pending{}` markers**, all for the platform validation log and the
   ladder rating. Its architecture section predates the compiled engine.
4. **`docs/UPLOAD-v0.1.md` and `docs/INTEGRATION_NOTES.md` are historical** records of Stage 0, not
   descriptions of the current build. They are not wrong, but they are not current either.
5. **`fastsearch.py`'s module docstring claimed mate-distance pruning that the code does not have.**
   Being addressed in a separate worktree; if the docstring still claims it, that is the reason.

### Measured versus estimated

**Measured** (games or instrumentation, all in `docs/RESULTS.md`): every arena row; the platform
figures in `docs/CALIBRATION.md` (1.1 ms per-move overhead, 2.3× slower core, depth 5–8 for v0.2,
0.6 s import) read from real validation and rated-game logs; node rates and depths; perft counts;
import and compile times; peak RSS.

**Estimated, and labelled as such**: every rating on a human scale. The CCRL-scale figure comes
from a maximum-likelihood fit against rating-limited Stockfish with a bootstrap interval, plus
±100 for the yardstick's own calibration; the FIDE and chess.com conversions are ranges from a
survey table and are worth ±200 or worse. Also estimated: the projection of start-up time onto the
platform (measured 19 s locally, projected 43–59 s, then observed 35.8 s and 50.7 s in validation).

A useful rule when auditing: if a number describes our engine's *strength* on any human scale, it
is an estimate; if it describes *behaviour* (nodes, depth, milliseconds, game results), it should
name the run that produced it.

---

## 5. Files under active edit — please do not touch

In **this** working tree, a background agent is mid-edit on the time-management change:

- `agent.py`
- `mikhail_letal/timing.py`, `mikhail_letal/search.py`, `mikhail_letal/fastsearch.py`
- `tests/test_timing.py`, `tests/test_fastsearch.py`
- `tools/sim_time.py`
- `docs/CALIBRATION.md`, `docs/DECISIONS.md`, `docs/DESIGN.md`, `docs/PROVENANCE.md`,
  `docs/RESULTS.md`

Audit around those; propose changes for them rather than making them, and I will apply them once
the agent lands and its work is measured.

Two further changes are in **separate worktrees**, so they will not collide with you here but will
land in `main` soon and may invalidate an audit of `fastsearch.py`:
`/home/lkmsdx/dev/ct-zobrist` (incremental Zobrist hashing) and `/home/lkmsdx/dev/ct-pvs`
(principal variation search, mate-distance pruning, cheaper stand-pat legality, depth-aware LMR).

Everything else — `README.md`, `docs/SUBMISSION_GUIDE.md`, `docs/report.tex`, `docs/PLAN.md`,
`docs/WEBAPP.md`, `docs/UPLOAD-v0.1.md`, `docs/INTEGRATION_NOTES.md`, `handoff/`, `app/`,
`tools/webapp/` — is free.
