# What a screen costs, measured

Nobody had ever recorded this, and both `chessathon-d9` and `chessathon-4c` planned around a
number they had estimated rather than measured — on the same day, in the same direction, by the
same missing term. Written down so the next person planning a screen does not repeat it.

## The measurement

From the 1000-game real-clock screen of 2026-09-09 (`ct-ordering` vs `versions/v1.2`, 120 s + 0.5 s,
12 workers, otherwise idle 16-core box):

```
1.74 - 1.80 games per minute        over the FIRST 33 games   <- cold start, do not plan on this
2.20 games per minute               steady state, at 384 games
~7.6 hours for 1000 games
~346 s mean per game of engine play (from the tool's own per-game line)
```

**Measure the rate after the ramp-up, not during it.** The first figure above and the second are
the same run. Twelve workers all pay their first numba warm-up simultaneously at launch, so the
opening minutes are the slowest the run will ever be, and a rate taken there over-estimates the
total by about a quarter. I planned an ETA from the cold-start number and told the coordinating
session 06:20 when the answer was 04:20 -- in the safe direction, but wrong, and wrong for a
reason that will repeat every time somebody measures a fresh run too early.

## Any ratio across positions is a median of per-position ratios

**A pooled sum is a defect unless a comment argues otherwise.** Not a style preference — this was
found the hard way on 2026-09-09 in two independent benchmark tools written by different people,
and in both cases the *same file* computed one quantity as a paired median and another as a pooled
sum:

- `tools/bench_mobility.py` paired the node rate per position and pooled the tree ratio. The tree
  ratio then came out **0.96, 1.13, 1.58 and 2.19** across position samples, and two sessions
  spent an hour arguing whether that spread was noise or mechanism. It was neither. A ratio of two
  pooled sums is carried by whichever position has the largest tree.
- `tools/bench_conthist.py` pooled the tree ratio *and* took its "median" node rate over three
  **rounds** of a rate already pooled across positions. Node counts are deterministic, so those
  rounds differed only in timing: the median measured whether the clock was steady. It agreed with
  the pooled figure to 0.14% and was reported as precision.

Nobody chose to pool. The paired form appeared where somebody had thought about it and the
language default appeared where they had not — which is why this is a rule and not an anecdote.

**So: pair per position, take the median, print the pair count and the min/max beside it, and
print the pooled figure too so a disagreement between them is visible.** If median and pooled
differ by more than a couple of percent, one position is carrying the answer and neither number
should be quoted.

## Compose tree x rate only for an ordering change, never for an evaluation term

Asserted from mechanism all through the night of 2026-09-09 and then measured. The same tool, the
same estimator, the same depth, on the two kinds of change:

```
ordering change (SEE + continuation history)   12 of 12 positions below 1.0
                                               median 0.5695, min 0.234, max 0.732
evaluation term (mobility)                     positions decisively BOTH ways
                                               median 1.316,  min 0.364, max 4.190
```

An ordering improvement shrinks the tree by a mechanism with a **sign**: better first moves cause
more cutoffs, everywhere. So its nodes-to-depth ratio is a real property of the change, and
multiplying it by the node-rate ratio gives a real time-to-depth figure.

An evaluation term has no such sign. It changes *which* lines look good, so some positions become
easier to search and some harder — and the spread above is not noise around 1.0, it is decisive
movement in both directions. **Its nodes-to-depth ratio is not a property of the change; it is a
property of the sample.** Composing it with the rate produces a number that means nothing, and
that is how a term measured at "1.7x time-to-depth" was carried into two documents as its cost.

**Rule: for an evaluation change, quote the node rate and stop.** If you want its real cost, only
a game screen has it.

## A consistent sign does not imply a well-behaved pooled estimate

This is the non-obvious half and it caught someone who had already found the estimator problem
and fixed the tool.

Having established that the ordering change moved every position the same way, the natural
prediction was that its pooled ratio would therefore be close to its per-position median. **It was
not: 0.4719 pooled against 0.5695 median, 21% apart, with all twelve positions on the same side
of 1.0.**

A pooled sum is a *weighted* average, weighted by tree size. One position with a large tree
carries it regardless of how consistently the others behave. Consistency of sign controls whether
the quantity is meaningful; it does nothing about which sample dominates the arithmetic.

**So the estimator rule is not conditional on the effect being messy.** Pair per position and take
the median even when — especially when — you have just satisfied yourself that the effect is
clean.

## The term everybody forgets

The arithmetic that looks right is `games x seconds-per-game / workers`. It is wrong by about
17%, and the missing term is the same one in every version of the mistake:

**Every game starts two fresh agent processes, and every process pays the numba warm-up.**

Measured on this box: **18 s idle, 31 s under load, per process.** A 1000-game screen therefore
pays that cost **2000 times** and amortises it over nothing. At the fast control it is the
*dominant* term — a 10 s + 0.1 s game is roughly 30 s of chess sitting on 40-60 s of start-up.

Two consequences worth having in front of you before you plan anything:

1. **Game count scales linearly with a cost you cannot reduce.** 3000 fast games is most of a
   night, and most of what you are buying is process start-up rather than chess.
2. **Raising the time control is far cheaper than the clocks suggest.** A real-clock game is about
   **3.6x** a fast one, not the ~12x the clock ratio implies, because the fixed cost does not move.
   Predicted 3.7x from the model above; measured 3.6x on 24 games. That is the finding that moved
   all screening to the real time control, since a fast screen never satisfied the promotion rule
   anyway and the cost that justified the substitute had never been priced.

## Planning numbers

| games | real clock, 12 workers | resolves about |
|---|---|---|
| 300 | ~2.5 h | ±39 Elo |
| 800 | ~7.7 h | ±24 Elo |
| 1000 | ~9.5 h | ±21 Elo |

**Do not run 300 games on something you expect to be worth +20 to +30.** It will straddle zero,
and the row then sits in `RESULTS.md` looking like evidence. A result that cannot resolve the
question is worse than no result once it is written down, because the next reader reads a table
and not an interval.

## If you need the number early

The PGNs are written per game as each finishes, so a truncated run is a valid smaller sample —
score what has been played rather than waiting for the tool's summary, which only writes the
`RESULTS.md` row at the end. Do not restart a run to shorten it: you discard the games *and* the
warm-ups already paid for, which is the one cost you cannot get back.
