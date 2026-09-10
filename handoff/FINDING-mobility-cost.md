# Can mobility be made affordable here?

Asked by `chessathon-d9` on the night of 2026-09-09, after a fourth loss (rounds 85, 87, 88, 90)
to the same activity blindness. Answered from the source, without the box, while the ordering
screen ran.

**Short answer: the cheap route is closed, the implementation is already near-minimal, and the
cost is almost entirely in the search tree rather than the evaluation loop. But the number we have
been calling the cost is measured with a yardstick that only applies to search changes, and it
probably overstates the price of an evaluation change. "Mobility is a net loss at 1.7x" is not
established, and I am the one who gave d9 the arithmetic that made it look established.**

## 1. Reusing move generation: closed, and closed everywhere

The hope was that `gen_pseudo`'s ray walk could be counted instead of repeated. It cannot, because
**every evaluation call in the compiled search happens before any generation at that node.**

| site | `fastsearch.py` | order |
|---|---|---|
| quiescence stand-pat | eval `:1030`, `gen_captures` `:1039` | eval first |
| quiescence in check | `gen_pseudo` `:1026` | generation first (the only one) |
| reverse futility | eval `:1272` | before `gen_pseudo` `:1340` |
| null-move gate | eval `:1285` | before `:1340` |
| futility gate | eval `:1307` | before `:1340` |

This is not incidental: `quiescence`'s docstring records that generating before standing pat
*"threw that work away at seven nodes in ten"*, which is why the order is what it is. So at the
overwhelming majority of evaluation calls there are no attack sets to reuse — they do not exist
yet, and at roughly 70% of quiescence nodes they never will, because the node cuts off first.

Reversing the order to enable reuse would cost more than mobility does.

## 2. We pay what a mailbox engine pays. There is no multiplier.

**The 4x was never real and I should not have repeated the framing.** It compared us to a
*bitboard* engine and called the difference our incompetence. Later research established that
MadChess's claim is explicitly a bitboard property, that it does **not** reuse sets its generator
built — it says it works "without generating any moves or scanning piece arrays" — and that
Fruit 2.1, a mailbox engine whose flagship term was mobility, walks the rays exactly as we do.
There is no multiplier to close. The section below stands as the reason *why*, with the comparison
corrected.

The quoted idiom — *"popcounts attack sets the generator already builds, essentially for free"* —
is a **bitboard** idiom. In a bitboard engine a slider's attack set is one magic-table lookup and
its mobility is one `popcount`: a few nanoseconds, and genuinely nearly free.

We are a **0x88 mailbox** engine. There are no attack sets. `ct-mobility`'s `_mobility` walks each
ray square by square, which is the minimal thing a mailbox board can do, and reading it I found no
waste: no per-square `attacked()` call, no redundant legality test, one pass, early exit on the
first occupied square.

And the bitboard route is not casually available: `fasteval` already documents *why* the compiled
engine avoids 64-bit bitboards — under numba a 64-bit shift sign-extends or overflows silently,
which is the same reason it uses per-file pawn summaries instead of fills. Changing the board
representation is not a Thursday-before-a-freeze project.

**The one structural saving available, quantified rather than hand-waved.** `evaluate` walks the
piece list at `fasteval.py:234`; `_mobility` walks it again at `:314`. Merging them saves one
traversal — the `plist` read, the `board[square]` read, the mask and the dispatch, about four
operations per piece. Against a queen's ray walk (up to 8 rays x 7 squares, ~200+ operations) that
is a couple of percent; against a knight's (~24) it is nearer 15%. Blended, **merging saves maybe
5-10% of the term's cost, and the term costs 8.7% of the node rate — so roughly 0.5-0.9% overall.**
Real, but not the four-fold difference, and not worth doing on its own.

## 3. The cost is 90% tree, and the tree number is measured in the wrong currency

> **Superseded twice — read to the end before quoting anything from this section.** The figures
> below (-10 to -23, "clears that price comfortably") were wrong in two separate ways, and both
> corrections are in the sections that follow. The Elo conversion conflated per-doubling with
> per-ply, and the 1.556 was not quotable in the first place. **The conclusion of this document is
> that mobility's cost is unresolved between roughly 8 and 55 Elo.** This section is kept as it
> stood because the corrections only make sense against it, not because any number in it survives.

The 1.7x splits as **8.7% node rate and 1.556x nodes-to-depth**. The evaluation loop is the small
half. Everything above is optimising the small half.

**The important part: nodes-to-depth is a fair currency only when the evaluation is unchanged.**
For a pure search change — reordering, faster make/unmake — both builds compute the same values,
so "depth 8" is the same commodity in both and comparing node counts to reach it is sound. That is
why the metric is right for the ordering bundle.

**For an evaluation change it compares different things.** The mobility build's depth 6 is not the
baseline's depth 6; it is a depth 6 that knows something the other does not. Charging it 1.556x
for reaching "the same depth" prices the extra nodes and credits none of the extra knowledge.

So the honest reading of my own earlier arithmetic, which d9 is now carrying:

> 1.7x time-to-depth is a **-10 to -23 Elo price the term must overcome**, not a verdict that it
> is a net loss.

Published mobility gains in engines that lacked it are **+27.6 (Blunder), +41 ± 14 (tcheran),
+62 (MadChess)**. [**Wrong as written** — see the two corrections below. The conversion was out by
two to four, and the cost figure it was applied to was one draw from a spread of 0.96 to 2.19.] **"Which makes the term a net loss" is not established by anything
we have measured**, and I should have said so when I supplied the handicap figure rather than now.

### Where the tree growth actually comes from

A positional term should not enlarge a tree by half unless it is moving scores across thresholds.
Two mechanisms, both proportional to how much the term perturbs the evaluation, and one already
measured:

1. **Aspiration misses.** Measured on this branch: the aspiration window's hit rate falls from
   **8/10 to 5/10** with mobility on, over five positions at two depths. The window is 40 cp; the
   term moves scores by tens. Each miss costs a re-search.
2. **Futility and reverse-futility threshold flips.** Reverse futility uses 85 cp per ply, futility
   150/300/500/750. A term that shifts a static evaluation by tens of centipawns flips positions
   across those boundaries in both directions.

Both are magnitude-dependent, which is what makes them testable.

## Correction: the 1.556 was not quotable, and the tool said so

`ct-mobility`'s own DECISIONS entry records the nodes-to-depth ratio as **not quotable**, coming
out **2.19, 1.13, 1.58 and 0.96** across runs differing only in which positions were sampled. The
1.556 above is a fifth draw from that. Pooling all five: mean **1.48**, and a crude interval of
about **0.89 to 2.08** — it includes 1.0, so no-effect is not excluded; it is centred at 1.48, so
no-effect is not established either. **Mobility's cost is unresolved between roughly 8 and 55 Elo.**

And `tools/bench_mobility.py` prints *"a different evaluation searches a different tree; this is
not a speed cost"* in its own output. The number was read off a screen containing that sentence
and quoted as a cost anyway, by two people independently. **A new failure shape for the
collection: not a check that could not fail, but a check that fired and was read past.**

## But it is a mechanism, not noise — and the difference decides the remedy

"Noise" implies expectation zero, averages away with more samples, and licenses ignoring the
effect. What an evaluation term actually has is a **mechanism with no consistent sign**: real and
directional at each position, varying in direction between positions. That allows a non-zero
expectation, is estimable with enough samples, and — the part that matters — **is fixable**.

An *ordering* change is different in kind: better first moves cause more cutoffs, so its tree
effect has a sign, is systematic, and legitimately composes with the node rate. That is why
the composition is sound for the ordering bundle and is not sound here. (The bundle's own figures
have since been re-measured with per-position pairing: **tree 0.5695**, not the pooled 0.472, so
its effective speedup is **1.35x** rather than 1.65x. Final quiet-box figures, 36 pairs each:
rate median **0.7675** (pooled 0.7421), tree median **0.5695** (pooled 0.4719), combined time to
depth 8 **0.7420**. Both quantities trip the median-versus-pooled warning. The pooled estimator had been overstating
the bundle's benefit by 21%, and every position still moved the same way -- 12 of 12 below 1.0,
min 0.234, max 0.732 -- which is the consistent sign that makes the composition legitimate here
and illegitimate for an evaluation term whose positions span 0.36 to 4.19 in both directions.)

**The measured instance, and it is stronger than the ratio it explains** (86's point, which I had
not made): the aspiration window's hit rate falls **8/10 to 5/10** with mobility on — and that is a
**within-build** cost. The window is guessed from the previous iteration's score in the *same*
search, so a term that makes scores less stable across depths pays it on every search it ever
runs. It is not an artefact of comparing two builds. A 40 cp window mis-guessed by a term that
moves scores by tens is a mechanism with a name and a magnitude.

## If the diagnostic shows a mis-firing pruner: scale the MARGINS, never the evaluation

Recorded before anyone tries it, because the obvious move is the wrong one. If reverse futility's
85 cp margin is incoherent with our evaluation's dispersion, the fix is to change the **margins**.
Do not rescale the evaluation to fit them: its output is also read by `MATE_SCORE` and
`MATE_THRESHOLD`, by `DRAW_SCORE` at zero, by `DRAW_TIEBREAK_MARGIN`, and by the time manager's
`easy_score_drop_cp` stability test. Multiplying the margins moves none of those. (Hazard from
86's `NNUE-NOTES.md`.)

## What I would measure next, none of it needing games

1. **Tree cost against term magnitude.** Run `tools/bench_mobility.py` with the weights scaled to
   1.0, 0.5 and 0.25. If nodes-to-depth falls roughly with the scale, the tree cost is threshold
   perturbation and is buyable; if it does not, it is something else and the lead is dead. Ten
   minutes.
2. **Tree cost with the fragile pruners off.** Same measurement with `REVERSE_FUTILITY_PRUNING`
   off. If most of the 1.556x disappears, mobility's cost is an *interaction with a pruner that is
   itself of doubtful value* — several of our margins sit at or below our evaluation's measured
   error of 304-342 cp — and the remedy is not to weaken mobility. Ten minutes.
3. **The one that actually decides it, and it does need games:** mobility at full strength against
   v1.2 at the real control. Everything above tells you what mobility *costs*; only a screen tells
   you what it is *worth*, and the published range says the price is probably affordable.

## Untested idea, recorded so it is not mistaken for a recommendation

The pruning gates (`_cached_eval` at `:1272`, `:1285`, `:1307`) could consult a **mobility-free**
evaluation while leaf scoring uses the full one, keeping the gates' thresholds calibrated to the
distribution they were chosen for. It might remove most of the tree growth. It might also make the
gates inconsistent with the values they gate, which is a good way to produce a subtle disaster.
**Not proposed. Not measured. Written down only so nobody re-derives it and thinks it is new.**
