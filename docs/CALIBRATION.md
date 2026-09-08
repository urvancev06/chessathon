# Calibration

How the time-management constants in `mikhail_letal/timing.py` (`TimeParams`) are tied to the
platform's measurements. Updated after every upload from the validation log the operator pastes.

## Current values (calibrated against the rated games of 2026-09-08)

| constant | value | origin |
|---|---|---|
| `increment_ms` | 500 | agent contract |
| `overhead_ms` | 50 | measured 0–2 ms (mean 1.1) over 25 rated moves; this file's rule is max + 50 |
| `moves_to_go_max` / `_min` / `_decay` | 50 / 20 / 0.7 | `tools/sim_time.py` against 1 697 finished ladder games |
| `increment_fraction` | 0.8 | brief |
| `hard_multiplier` / `hard_fraction` | 3.0 / 0.25 | brief |
| `floor_ms` / `floor_fraction` | 1500 / 0.05 | brief |
| `panic_ms` | 1650 | kept at v1.0's value; `overhead_ms + floor_ms` is now 1550, and nothing near the flag changes |
| `next_iteration_fraction` | 0.45 | brief; now only the fallback when no iteration is long enough to predict from |
| `iteration_ratio_default` / `_min` / `_max` | 4.5 / 2.0 / 8.0 | the measured cost of depth d+1 over depth d, clamped |
| `iteration_target_factor` | 1.35 | measured: see "Iteration control", below |
| `unstable_factor` | 1.5 | hand-chosen; a root move that just changed gets half a budget more |
| `easy_factor` / `easy_stable_depths` / `easy_score_drop_cp` | 0.7 / 6 / 30 | measured against 0.5 / 4 / 30, which spent less than the rule it replaced |

## Observations before the first validation log (dev box, 2026-09-07)

- Iteration cost ratio `T(d) / T(d-1)`: median 4.3–5.2, maximum about 10, over middlegame
  searches on the dev box. `next_iteration_fraction = 0.45` is therefore optimistic: an
  iteration begun at 0.45 × soft usually runs to 2–2.5 × soft and is cut by the hard limit.
- At clocks below about 20 s the hard limit (`hard_fraction` × clock) binds every move: moves
  run to the hard limit, not the soft target.
- The constants stay at the brief's values until the first validation log; both observations
  are inputs to that calibration, not changes made ahead of it.

## Speed factor

Platform node rate ÷ local node rate: **not yet measured** (needs the first validation log).
Local node rate: see RESULTS.md.

## Log of calibrations

### 2026-09-08 — first platform measurements, from rated rounds 67, 68 and 69 (build v0.2.1)

| quantity | platform | local | note |
|---|---|---|---|
| per-move overhead (referee-charged minus self-measured) | 0–2 ms, mean 1.1 ms over 25 moves | 0–1 ms | `overhead_ms = 150` is ~100x more conservative than needed |
| node rate, middlegame | 21 600–27 300 nps | ~55 000 nps | platform is **2.3x slower** |
| node rate, late endgame | up to 64 000 nps | — | rises as the board empties |
| depth reached, middlegame | 5–8 | 8–9 | about 2–3 plies less |
| import time | 0.6 s | 0.033 s | mostly fixed container and interpreter cost, not compute |
| clock left at end, 113-move game | 4.7 s | — | survived, but thin (round 68) |

Read from the `m … d … n … nps … t … s … h … c …` lines the agent prints, paired with the
platform's own per-move clock column. Overhead is `(clock before − clock after) + increment − t`.

**What this changes.** The 150 ms overhead reserve is far larger than the measured 1.1 ms, so the
budget is leaving time unused on every move; it is kept for now because it is cheap insurance and
was not the thing that cost points. The real time-management finding is round 68: 113 moves left
4.7 s on the clock, because `moves_to_go` starts at 40 and floors at 12, which spends too freely
early in a long game. The speed factor of 2.3 is the number to scale any local depth expectation
by, and it is the figure the compiled engine's start-up cost must be judged against.

### 2026-09-08 — iteration control, from the five rated games and the ladder's own game lengths

**What the platform showed.** Per-move times were bimodal: 1.5–3.0 s (an iteration finished, a
third of the budget unspent) or 8.9–10.1 s (an iteration started that could not finish before the
hard ceiling), with nothing in between. The cause is `next_iteration_fraction = 0.45` against
iteration costs that grow by 4–5x a depth: at 0.45 of the budget the engine either stops, or
starts a depth that costs several times what is left.

Our five rated games (`data/pgn/ours`, clocks verified against the platform's own log) show the
budget is wrong in both directions, and where the damage lands:

| game | colour | result | plies | our moves | clock left |
|---|---|---|---|---|---|
| `1e1c9922` | W | win | 36 | 18 | 87.5 s |
| `3ebceb52` | B | loss | 46 | 23 | 90.2 s |
| `cf4043b1` | W | win | 102 | 51 | 31.6 s |
| `f43e60b5` | W | win | 210 | 105 | 6.0 s |
| `5504d7fa` | B | draw, fifty moves | 226 | 113 | 4.7 s |

The two games that finished near the flag are the two longest, and the longer of them is the draw:
the tail of a long game is not a hypothetical risk, it is where the half point went. The two
shortest games ended with roughly 90 s unspent.

**Iteration control.** The fixed fraction is replaced by a prediction
(`timing.should_start_next_depth`): the cost of depth d+1 is estimated as `ratio × time(d)`, with
the ratio measured from the last two completed iterations, clamped to 2.0–8.0, defaulting to 4.5
before there is data, and the depth is started only if it is predicted to end inside the target.
The fraction remains as the fallback for an iteration too short to measure (< 1 ms), where it
applies to the soft budget itself, exactly as the rule it replaced did.

The target is the soft budget times `iteration_target_factor`, stretched by `unstable_factor` when
the root move changed at the last completed depth and cut by `easy_factor` when it has been stable
for `easy_stable_depths` iterations with a score that is not falling. Every target is clamped to
the hard window, so nothing here can plan past the abort point.

**Measured on six middlegame positions from `data/pgn`, each searched at 120 s and at 20 s (12
moves a variant, one process). `t/soft` is the share of the soft budget actually spent:**

| variant | mean depth @120 s | t/soft @120 s | max t/hard |
|---|---|---|---|
| target 1.0 × soft, easy 4 iterations / 0.5 | 10.33 | 0.41 | 0.22 |
| target 1.0 × soft, no easy rule | 10.83 | 0.70 | 0.47 |
| target 1.35 × soft, no easy rule | 11.17 | 0.80 | 0.42 |
| target 1.75 × soft, no easy rule | 11.83 | 1.48 | **1.00** (ran to the ceiling) |
| **target 1.35 × soft, easy 6 / 0.7 (shipped)** | 11.00 | 0.68 | 0.39 |

1.75 reaches the hard ceiling, which is the behaviour being removed; the first easy rule (4
iterations, half the target) fired on nearly every move and spent less than the fixed rule it
replaced. 1.35 with the gentler easy rule is the one that ships. The 0.70 of the soft budget a
move spends under it is the number the budget constants below are calibrated with.

**Before and after, ten middlegame positions at six clocks (60 moves a variant), same process**,
with v1.0's rule reproduced inside the new code (an unreachable `ratio_measurable_s` forces the
fallback branch, with v1.0's constants). `t/soft` is the share of the budget the move spent:

| clock (our moves played) | v1.0 soft / mean t / t/soft / depth | new soft / mean t / t/soft / depth |
|---|---|---|
| 120 s (0) | 3396 / 1940 / 0.57 / 10.50 | 2799 / 2408 / 0.86 / 10.40 |
| 60 s (20) | 2395 / 1472 / 0.61 / 10.20 | 2065 / 1614 / 0.78 / 10.10 |
| 20 s (40) | 1392 / 956 / 0.69 / 9.50 | 1307 / 1042 / 0.80 / 9.40 |
| 5 s (60) | 804 / 632 / 0.79 / 8.80 | 648 / 541 / 0.83 / 8.50 |
| 2 s (70) | 350 / 251 / 0.72 / 7.50 | 450 / 299 / 0.67 / 7.30 |
| 1.7 s (80) | 50 / 42 / 0.84 / 5.10 | 150 / 69 / 0.46 / 5.80 |

The budget is used far more fully where the clock is large (0.57 → 0.86 at 120 s, 0.61 → 0.78 at
60 s), which is the bimodality closing up, and no move exceeded its hard budget in either run
(worst overshoot 1 ms, the clock-read granularity). Mean depth is unchanged inside the noise of a
shared machine. The soft budget itself is smaller at a full clock on purpose: that time is moved
into the rest of the game by the divisors below, which a per-position probe cannot show and the
whole-game simulation can.

**Budget.** `overhead_ms` 150 → 50 (the measured maximum plus this file's 50 ms margin).

`moves_to_go` 40 / 12 → 50 / 20, with a new `moves_to_go_decay` of 0.7 replacing the halving, from
the **1 697 finished ladder games** collected by 2026-09-08 (`data/pgn/ladder-top`, the five
highest-rated teams, and `data/pgn/ladder-top50`; the simulator re-reads whatever is on disk, so
the counts below move as more land). Those games say how many of our moves are *left* at each point, given
the game reached it — which is exactly what `moves_to_go` is estimating:

| at our move | 0 | 10 | 20 | 30 | 40 | 50 | 60 | 80 | 100 |
|---|---|---|---|---|---|---|---|---|---|
| games still going | 1697 | 1684 | 1651 | 1581 | 1461 | 1252 | 1004 | 522 | 308 |
| median of our moves left | 67 | 57 | 47 | 39 | 31 | 25 | 22 | 27 | 27 |
| mean | 74 | 65 | 56 | 48 | 42 | 38 | 36 | 39 | 40 |

The median is 67 at the start and falls by about one a move to roughly 25. `40 − k // 2` starts at
40 against 67 and falls at half the rate: too free early, far too free late. The fit is that curve
**scaled by 0.70**, the share of the soft budget a move actually spends, so realised spending is
the even split of the clock over the moves really left: `clamp(50 − 0.7 × moves played, 20, 50)`.

Simulated over all 1 697 games at that spending rate (`tools/sim_time.py`), against v1.0
(mean seconds a move by phase; "low" is the lowest clock any game reached after a move):

| constants | used | s @0–19 | s @20–49 | s @50–79 | s @80+ | low | median left |
|---|---|---|---|---|---|---|---|
| 40 / 12 / 0.5 (v1.0) | 83 % | 2.30 | 2.11 | 1.58 | 0.68 | 3.3 s | 15.7 s |
| **50 / 20 / 0.7 (new)** | 77 % | 1.98 | 2.06 | 1.45 | 0.79 | 5.9 s | 26.2 s |
| 30 / 24 / 0.5 (first attempt) | 82 % | 2.86 | 1.81 | 1.09 | 0.71 | 7.1 s | 22.4 s |

Over the games of at least 90 of our moves — the class both near-flag games belong to — the
lowest clock is 5.9 s against v1.0's 3.3 s, and 3.3 s against 1.9 s if a move spends 0.85 of its
budget rather than the measured 0.70.

The model is checked against our own five games before it is used: under v1.0's constants it gives
87.0 / 78.4 / 34.3 / 4.7 / 4.2 s where the platform measured 87.5 / 90.2 / 31.6 / 6.0 / 4.7 s.

**Why 20 and not the 17 the median implies.** Two criteria, and the median-based fit fails both.
The soft formula alone balances the increment at
`overhead_ms + moves_to_go_min × increment_ms × (1 / usage − increment_fraction)`: at a full spend
of the budget that is 1650 ms for a minimum of 16 — exactly `panic_ms`, the clock at which the
agent stops searching — and 2050 ms for 20. And in the deep tail the remaining-moves distribution
is skewed (median 27, mean 40 at our move 100), so the median under-states what is left in the
games that get there. What actually holds the clock up in the end is neither: `floor_ms` and
`hard_fraction` mean the plan never leaves less than the reserve after a move, so the clock cannot
settle below about `overhead + floor + increment` ≈ 2.05 s whatever the divisor is. The divisor
sets how fast the clock approaches that, not where it stops.

Depth grows like the logarithm of time, so the simulator also reports the geometric mean of time a
move over every move of every game, the quantity that stands in for mean depth. It is flat across
this whole region — 1.62 s at 40 / 12, 1.56 s at 50 / 20, 1.48 s at 30 / 24 — so the choice is
made by the measured remaining-moves curve and by the margin in long games, not by a metric that
cannot tell them apart. The first attempt, 30 / 24, is kept in the table because it is the one the
length data rejected: it front-loads the opening at 2.86 s a move and starves everything after
move 50.

### Procedure when a validation log arrives

1. Extract init time, every per-move time, the clock left after each move, and any stderr.
2. Pair each platform-measured move time with the self-measured `t` from our log line; the
   difference is the platform overhead for that move. Set `overhead_ms = max(difference) + 50`.
3. Compute platform nps from our `nps` log tokens; divide by the local nps from the same build
   and positions to get the speed factor; rescale any node cap.
4. Record init time from the log against the local measurement from the zip.
5. Commit the new constants with the log excerpt in this file.

### 2026-09-08 — v1.0 validation on the platform (the compiled engine)

Upload `aichessathon-v2-8f98cb73400f`, matching `submission.zip` sha256 `8f98cb73…`. Verdict at
the end of the log: **valid**. Two smoke games, 20 plies each, one per colour, from curated
positions. This is the first and so far only platform run of the compiled build; every earlier
platform figure in this file is the interpreted v0.2.1.

| quantity | smoke game 1 (white) | smoke game 2 (black) |
|---|---|---|
| ready in | **35.8 s** of the 90 s budget | **50.7 s** of the 90 s budget |
| of which numba compilation | 34.8 s | 49.4 s |
| warm-up phases skipped | 0 | 0 |
| node rate reported at import | 459 460 | 329 618 |
| per-move depth | 10–12 | 8–11 |
| per-move node rate | 456 733 – 493 209 | 290 923 – 568 917 |
| slowest move | 3.0 s | 10.1 s |

**What this settles.** The compiled engine reaches **depth 10–12 at 330 000–460 000 nodes/s on the
platform**, against v0.2.1's depth 5–8 at 21 600–27 300. The warm-up deadline (`WARM_UP_BUDGET_S`,
70 s) never fired: both games completed every phase, so the degraded path has still never run in
anger.

**What it leaves open.** The two start-up times differ by **15 seconds for identical code on
identical hardware**, 35.8 against 50.7. That variance, not the mean, is the risk: the budget is
90 s, the deadline is armed at 70 s, and a run slower than the worse of these two would start
skipping phases. Watch the `init` line in every rated log.

**Time management, unchanged from the v0.2.1 finding.** Game 2 shows three moves at 8.9–10.1 s
against a soft target of 3.4 s, running to the hard ceiling, while six others finished under it —
the bimodal distribution the in-flight timing change targets.

Raw log: pasted by the operator into the working session on 8 September; the platform keeps only
the first and last 4 KB, so the figures above are the whole of what survives.
