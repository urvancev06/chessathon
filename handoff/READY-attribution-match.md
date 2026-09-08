# The timing-alone attribution match, ready to launch

Prepared by `chessathon-64` while the bundle match runs, so that nobody derives it at 04:30. The
pre-registration (`DECISIONS.md`, 2026-09-08) promises this run for the record regardless of what
is uploaded: the bundle confounds the timing refit (`82b20e2`) with the king-danger term
(`897e1e2`), and the confounding was accepted for the *upload* decision only.

**Do not start it while the bundle match is running.** `tools/arena_openings.py:379` resolves the
agent under test to the repo root and `harness/sandbox.py:54` spawns a process per game from that
directory, so two runs sharing the tree contaminate each other.

## The seam

`KING_DANGER_TERM` is a plain module constant at `mikhail_letal/evaluation.py:76`, imported by
`mikhail_letal/fasteval.py:47`, which mirrors it into `misc[E_KING_DANGER_ON]`. **Flipping it in
`evaluation.py` alone switches both engines**, so a timing-alone build is a one-line change. It is
deliberately not an environment variable: the shipped engine must not read variables the platform
does not set, which is why the old `feature_flag` scheme was removed.

## Build it in a worktree, not in the tree

```
git worktree add --detach ~/dev/ct-timing-only main
cd ~/dev/ct-timing-only
sed -i 's/^KING_DANGER_TERM = True$/KING_DANGER_TERM = False/' mikhail_letal/evaluation.py
grep -n '^KING_DANGER_TERM' mikhail_letal/evaluation.py        # must print False
```

A worktree rather than a copy, so the build is a named commit plus one visible edit rather than an
untracked directory nobody can reconstruct later.

## Run it

```
cd ~/dev/chessathon
uv run python -m tools.arena_openings \
    --agent ~/dev/ct-timing-only \
    --opponent versions/v1.0 \
    --real-clock --games 300 --workers 4 \
    --label timing-only-vs-v1.0-real \
    --results docs/RESULTS.md \
    --json data/arena/timing-only-vs-v1.0-real.json \
    --pgn-dir data/pgn/timing-only
```

`--workers 4` is 8 agent processes on 16 cores, so each still gets one and the clock figures stay
faithful; 1 worker buys no fidelity and takes four times as long (`v0.3-vs-v0.2-real`, the repo's
own promotion match, used 4). Memory is about 2.8 GB of 7.8.

## What it answers, and what it does not

It isolates **the timing refit**: same evaluation as v1.0, new time management. It does **not**
isolate the king-danger term. For that, a second run of `main` against `~/dev/ct-timing-only`
measures the term directly with timing held constant on both sides — worth doing if a slot is free,
and the honest way to attribute the bundle rather than subtracting two intervals, which does not
work.

## Reading the row

The expected row is a normal arena row under the label above. Two things to look at beyond the Elo:

- **`low_clock_ms` and the per-game clocks in the JSON.** This is the run where the timing change
  is unconfounded, so it is the best measurement we will have of whether the refit does what it was
  built to do. The safety gate's statistic (share of games under 5 000 ms) should be computed here
  too, whatever the Elo says.
- **Terminations.** A `flag` in this run would be a finding about the timing change specifically,
  which the bundle run cannot give.

## Sample size

At 300 games the 95 % interval resolves about ±37 Elo. If the timing refit is worth less than that
— which is plausible, since its effect is concentrated in the minority of long games — this run
will return "not proven" rather than a number. That is the expected outcome and is not a failure of
the run: it is the same instrument-mismatch argument the pre-registration makes for case 3, and it
should be recorded as such rather than re-run at a larger size we do not have time for.
