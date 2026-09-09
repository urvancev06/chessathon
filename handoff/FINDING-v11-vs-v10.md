# v1.1 loses to v1.0 at 10 s — and that disagrees with the real clock

Two matches, both at 10 s + 0.1 s, 300 and 100 games, on `data/openings.txt`. Rows are in
`handoff/RESULTS-v11.md`; raw JSON in `handoff/v11-run.json` and `handoff/roleswap-run.json`.

| match | games | +W =D −L | score | Elo (95%) |
|---|---|---|---|---|
| `versions/v1.1` vs `versions/v1.0` | 300 | +56 =42 −202 | 25.7% | **−185 (−228 to −146)** |
| role-swapped: `v1.0` vs `v1.1` | 100 | +56 =15 −29 | 63.5% | **+96 (+34 to +166)** |

The second match exists because the first is a strange enough result to suspect the instrument. It
was run with the versions in the opposite argument slots, to check that the harness does not
favour whichever directory is passed as `--agent`. It does not: both matches put v1.0 ahead, and
the intervals overlap between +146 and +166. **v1.0 beats v1.1 at this time control**, somewhere
around +150 Elo, and the 300-game interval is entirely clear of zero.

## The part that matters more than the number

The repository has already measured this pair at the **real** time control:

| label | games | Elo (95%) |
|---|---|---|
| `v1.1-bundle-vs-v1.0-real-c0` (120 + 0.5 s) | 100 | +31 (−29 to +93) |
| `v1.1-bundle-vs-v1.0-real-c100` (120 + 0.5 s) | 100 | −14 (−73 to +44) |

At 120 s + 0.5 s the two versions are indistinguishable. At 10 s + 0.1 s one of them is ~150 Elo
ahead of the other. **The fast screening control and the real control do not merely differ in
precision — they disagree about which version is better, by an amount neither interval can absorb.**

That is a fact about the measuring instrument, and it costs more than this one comparison. The row
`v1.2-pvs-zobrist-vs-v1.1-screen`, +35 (−2 to +73), was screened at 10 s + 0.1 s. If 10 s can
invert a 150-Elo gap, it cannot be trusted to rank two versions 35 Elo apart, and that screen
should be treated as telling us nothing about v1.2 until it is re-run at the real clock.

`CLAUDE.md` already requires the real time control for a promotion. The finding here is the
sharper one: the fast proxy is not a noisy version of the real measurement, it is a different
measurement, and using it to *screen* candidates before spending real-clock time will select the
wrong ones.

## Why 10 s punishes v1.1 specifically — mechanism, measured but not isolated

v1.1 overruns its own soft budget; v1.0 comes in under it. Same three positions, same process,
budget the manager set against time actually spent:

| clock given | v1.0 soft → spent | v1.1 soft → spent |
|---|---|---|
| 10 s | 646 → 405 ms | 599 → **866 ms** |
| 120 s | 3396 → 2623 ms | 2799 → **3461 ms** |
| 120 s (a quiet opening position) | 3396 → 2779 ms | 2799 → **6080 ms** |

v1.1 sets a *smaller* soft budget than v1.0 (`overhead_ms` 150 → 50, `moves_to_go_max` 40 → 50,
`moves_to_go_min` 12 → 20, with the new `moves_to_go_decay`) and then spends past it, in one case
by more than twice. The new `should_start_next_depth` decides whether to open another iteration
from measured iteration times rather than from a fixed fraction of the soft target, and an
iteration it chooses to start it must finish.

Overspending is survivable on a 120 s clock and is not on a 10 s one, where the reserve is a few
hundred milliseconds and `floor_ms` is 1500 — 15% of the entire clock rather than 1.25% of it. Both
matches bottomed out near that floor (lowest clocks 1533 ms and 1634 ms) and neither produced a
single flag loss, so v1.1 is not losing on time; it is arriving at every later move with less of it.

**This is a hypothesis consistent with the measurements above, not an isolated cause.** Testing it
means one variant — v1.1 with v1.0's timing constants — raced against v1.1. That was not run.

I also checked and discarded the obvious rival explanation, that v1.1 is depth-starved at a short
clock. It is not: given a 10 s clock it reached depths 9, 8, 10 on the three positions where v1.0
reached 8, 8, 9. v1.1 searches *deeper* per move at 10 s and still loses the match.

## What this says about shipping

Neither time control has ever shown v1.1 ahead of v1.0. The real-clock runs straddle zero and the
fast runs are strongly negative. By the house rule in `CLAUDE.md` — promote only on an interval
entirely above zero — **v1.1 has not earned the place it holds in `versions/`**, and the case for
it resting on a 10 s screen is now evidence against it rather than for it.

One caveat on identity, worth resolving before acting: the real-clock rows are labelled
`v1.1-bundle` with the agent recorded as `.`, the working tree of the day, and there are two of
them (`c0` and `c100`). Which of those two became `versions/v1.1` is not recorded. Both
`versions/v1.0` and `versions/v1.1` also print `Mikhail LeTal 1.0.0` at init, so nothing in a
platform log distinguishes them either.
