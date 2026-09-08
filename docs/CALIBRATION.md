# Calibration

How the time-management constants in `mikhail_letal/timing.py` (`TimeParams`) are tied to the
platform's measurements. Updated after every upload from the validation log the operator pastes.

## Current values (uncalibrated, from the brief §6.2)

| constant | value | origin |
|---|---|---|
| `increment_ms` | 500 | agent contract |
| `overhead_ms` | 150 | brief's initial guess; replaced by max over a game of (platform-measured move time − self-measured) + 50 |
| `moves_to_go_max` / `moves_to_go_min` | 40 / 12 | brief |
| `increment_fraction` | 0.8 | brief |
| `hard_multiplier` / `hard_fraction` | 3.0 / 0.25 | brief |
| `floor_ms` / `floor_fraction` | 1500 / 0.05 | brief |
| `panic_ms` | 1650 | overhead_ms + floor_ms: below it the formula has no time to plan with (brief suggested ~1500) |
| `next_iteration_fraction` | 0.45 | brief; to be replaced by the measured iteration-cost ratio |

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

### Procedure when a validation log arrives

1. Extract init time, every per-move time, the clock left after each move, and any stderr.
2. Pair each platform-measured move time with the self-measured `t` from our log line; the
   difference is the platform overhead for that move. Set `overhead_ms = max(difference) + 50`.
3. Compute platform nps from our `nps` log tokens; divide by the local nps from the same build
   and positions to get the speed factor; rescale any node cap.
4. Record init time from the log against the local measurement from the zip.
5. Commit the new constants with the log excerpt in this file.
