# The warm-up's degraded path is untested, and its documented bound does not hold

Found 8 September 2026 by `chessathon-64` while auditing the largest open risk in the build. Nothing
was changed; this is analysis and a recommendation for whoever owns `mikhail_letal/warmup.py` and
`agent.py`.

## Why this path matters

The v1.0 platform validation gives two start-up times for identical code on identical hardware:
**35.8 s and 50.7 s** (`docs/CALIBRATION.md`, 2026-09-08). The budget is 90 s and the warm-up deadline
arms at 70 s. Both runs completed every phase, so **the degraded path has never executed** — not on the
platform, and not in the test suite. It is the safety net for the failure that costs the most (an init
overrun loses *every* game), and the first time it runs will be in a rated game.

Two samples 15 s apart is not a distribution. That is the whole reason to look at this now.

## What the code does

`agent.get_move` calls `_finish_warm_up` on the first move when the import skipped phases. That function
re-arms the shared budget with a new deadline:

```python
warmup.arm(t0 + PARAMS.cold_finish_fraction * time_left_ms / 1000.0)
```

`arm` calls `WarmUpBudget.reset`, which sets `self.slowdown = 1.0`.

**So the slowdown measured during the import is discarded — at exactly the moment it is most
informative.** It is the number that made the import skip phases in the first place: the import only
degrades on a machine slow enough for the prediction to bite, so by construction the slowdown was well
above 1.0 when it was thrown away.

Verified directly:

```
slowdown after a 1.0 s-reference phase taking 3.0 s : 3.0
  -> _finish_warm_up calls arm() again:
slowdown after reset                                 : 1.0
  fits a 12 s-reference phase?  True   (predicts 12 s; at the measured 3x it is 36 s)
```

## Why that contradicts the docstring

`_finish_warm_up` states:

> It is bounded twice: by `cold_finish_fraction` of the clock, and by the same predictive budget the
> import used, which will not *start* a phase it does not expect to finish.

It is **not** the same budget: the accounting was reset, so the second bound is computed at 1.0x on a
machine known not to be 1.0x. The predictive bound is wrong by exactly the slowdown factor, and
`cold_finish_fraction` is therefore not enforced. On a 3x machine a phase predicted at 12 s can be
started as late as the deadline and run 36 s past it.

The magnitude scales with the thing the net exists for. At 5x — slower than anything measured, which is
the case the 70 s deadline was designed against — `negamax` alone is 60 s of real time predicted as 12 s,
and can be started up to 30 s into the move. That is up to 90 s spent on the first move of a 120 s clock.

## The part that is not straightforwardly a bug

Fixing it by carrying the slowdown across the re-arm would make **more** phases skip. That is not
obviously better, and may be worse:

- A phase skipped here compiles **inside `ENGINE.search`** on a later move, where numba cannot be
  interrupted and no deadline can stop it. That is the measured 15.9 s against a 10.2 s budget quoted in
  the same docstring — an unaccounted overrun of the *hard* deadline.
- A phase compiled **here** is accounted for: `agent.get_move` does
  `warm_ms = _finish_warm_up(...)` and then `budget(time_left_ms - warm_ms, ...)`, so the search's own
  budget shrinks by what the compilation cost and the clock stays consistent.

So compiling up front is strictly the better place, and the reset — by being optimistic — happens to
push more work into it. **The current behaviour is defensible; it is just not the behaviour that is
written down, and nobody chose it.** That is the actual defect: a safety path whose stated contract and
real contract differ, which has never run, and which no test exercises.

## Recommendation

**Make the cold finish unconditional, and delete the second bound rather than repair it.**

On the first move the clock is at its fullest (120 s), every phase left is one the search would
otherwise compile inside itself, and the cost is already subtracted from the search budget. There is no
case where deferring is better, so there is nothing for a predictive bound to decide. Concretely:
`_finish_warm_up` calls `warmup.arm(None)`, compiles everything, and relies on the `warm_ms` accounting
that already exists; the docstring then describes what the code does.

The one risk that replaces it is a pathological machine spending most of the opening clock compiling.
That is bounded by the fact that it happens once per game on the fullest clock, and it is strictly
preferable to the same compilation happening later inside a three-second move.

If instead the bound is kept, then `arm` needs to carry the measured slowdown forward, and the
consequence — more phases skipped into the search — should be measured before it ships, not assumed.

## What to test either way

There is no end-to-end test of this path. `tests/test_warmup.py` covers the budget mechanics well
(including `test_arm_sets_the_shared_deadline_and_clears_the_accounting`, which deliberately asserts the
reset), but nothing drives `agent.get_move` with phases actually skipped. The gap:

1. Import with a warm-up deadline forced to expire early, then call `get_move` and assert the move is
   legal, the clock accounting is right (`warm_ms` subtracted from the budget), and the search still
   respects its hard deadline **after** the compilation.
2. Assert that after the cold finish, `_signatures()` is complete — i.e. nothing is left to compile
   inside a later search, which is the property the whole path exists to guarantee.

That second one is the real gate: it is the difference between "we degraded gracefully" and "we moved
the explosion to move 40".
