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

## 2. Why we pay ~4x what MadChess pays: representation, not sloppiness

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
+62 (MadChess)**. If mobility delivers anything within reach of those numbers here, it clears a
-10 to -23 price comfortably. **"Which makes the term a net loss" is not established by anything
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
