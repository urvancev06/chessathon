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

## Speed factor

Platform node rate ÷ local node rate: **not yet measured** (needs the first validation log).
Local node rate: see RESULTS.md.

## Log of calibrations

(none yet — awaiting the first validation log)

### Procedure when a validation log arrives

1. Extract init time, every per-move time, the clock left after each move, and any stderr.
2. Pair each platform-measured move time with the self-measured `t` from our log line; the
   difference is the platform overhead for that move. Set `overhead_ms = max(difference) + 50`.
3. Compute platform nps from our `nps` log tokens; divide by the local nps from the same build
   and positions to get the speed factor; rescale any node cap.
4. Record init time from the log against the local measurement from the zip.
5. Commit the new constants with the log excerpt in this file.
