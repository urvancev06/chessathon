# The trained evaluation: what tonight's screen can and cannot tell us

> **Outcome, added 11 September 2026.** The screen ran and the network lost: **-67 Elo**
> (interval -106 to -29) over 300 games at the real time control, +111 =21 -168. It does not ship.
> The reading of that outcome is in `docs/DECISIONS.md` under *"The network lost 67 Elo, and four
> metrics said it would win"*, and the row is in `docs/RESULTS.md`.
>
> What is on `main`: this document, `tools/nnue_model.py` (the specification), the trainer and
> the two analysis tools. What is **not** on `main`: the compiled port, the `USE_NETWORK` switch in
> `evaluation.py`, and the parity test that compared them -- all of which live on the
> `ct-nnue-screen` branch, because merging them would put a measured-negative evaluation into the
> shipping engine. Check that branch out to run any of this end to end.

Written **before** the screen runs, so that what follows is a prediction and not a reading of a
result we already have.

## What is being screened

`USE_NETWORK` replaces the hand-crafted evaluation with a 768 -> 128 -> 1 perspective network,
trained on 267 462 positions labelled by Stockfish (242 256 at depth 12 from 3 356 ladder games,
plus the 25 994 depth-10 Texel set, deduplicated). 300 games at 10 s + 0.1 s against `versions/v1.2`.

## The screen measures two things at once, and they pull opposite ways

The network evaluates positions differently **and** costs 15.3 % of the node rate — measured, paired,
on the real engine (`tools/bench_network.py`), which is about 0.11 of a ply at 4.5 nodes per depth.
A screen measures the *net* of those two. So:

- **Positive** — the evaluation is worth more than 0.11 ply. That is the result that changes the
  competition, and it is the only outcome that justifies the remaining hours.
- **Flat** — the better evaluation *exactly paid for* the slower search. It does **not** mean the
  network is worthless; it means the trade is even at this width and this speed. The honest
  follow-up would be the incremental accumulator, which the kernel benchmark says buys the 15 %
  back, rather than a better-trained net.
- **Negative** — either the evaluation is worse in play than on paper, or the speed cost dominates.
  These are not distinguishable from one screen and we should not pretend otherwise.

## Held-out MSE is not evidence of strength, and on this project it is worse than that

On a common held-out split the network scores 34 035 against the hand-crafted evaluation's 86 426
(RMSE 184 cp against 294 cp). **That number should not move anyone's prior about strength.**

The 768-parameter Texel fit was ranked highest by held-out MSE against Stockfish labels, on this
engine, with this label source, and it played **−100 Elo** (`RESULTS.md`). Same metric, same
reasoning — "it predicts Stockfish's numbers better, therefore it evaluates better" — wrong by a
hundred Elo. That is not a general caution about MSE; it is a measured failure of this exact
instrument on this exact engine.

What the MSE comparison is good for is the narrow claim that **the network is not broken**: it has
learned something rather than nothing, its perspectives are the right way round, and its
quantisation survived. That is worth having and it is the whole of what it is worth.

If the screen comes back negative, the MSE will be sitting here inviting the thought "but it must
be better, look at the number". The answer prepared in advance: the last time we accepted that
sentence it cost 100 Elo.

## What has never been tested

Nothing here has watched the engine play. The evidence is a parity gate, a node cost, and a static
error measurement. A network can be far better at predicting a position's number and still choose
worse moves, because it has never been asked which move is good. The property tests with the switch
on are the first thing that would catch gross nonsense, and they are a floor, not a verdict.

## Provenance

- Positions: `tools/label_nnue.py extract`, 3 356 ladder games under `data/pgn` (gitignored, as the
  timing constants' source games are), first 8 plies skipped, side-to-move-in-check positions
  dropped, deduplicated by piece placement and side to move: 242 256 unique.
- Labels: Stockfish 19, depth 12, one thread, White's point of view, clipped to ±1500. 16 minutes at
  253 positions/s on 14 workers. `data/tuning/nnue_labels.csv`, sha256
  `e9a4f7563d3fbb8cad811f7a302c67f70e181caad3107d666f93069454cc514c`.
  Written beside `labels.csv` rather than over it: that file's sha256 is recorded in
  `PROVENANCE.md` as the Texel experiment's input, and overwriting it would falsify a record.
- Training: `tools/train_nnue.py --width 128 --epochs 60 --lr 3e-3 --test 8000`, best held-out epoch
  saved (37 of 60). Weights clipped during training to the range int16 can hold once scaled, so the
  weights the loss is computed on are the weights that ship.
- Nothing of anyone else's network is here. The rules allow training on positions an engine
  labelled; Stockfish labels the data and no part of Stockfish ships.

## Observations recorded during the screen, before its result

Written while the screen was running and 12 of 300 games were in, so that if the result is negative
these are notes made *before* it rather than an explanation constructed after it.

**Game 1 (`game-0001.pgn`), lost as White by checkmate.** Our evaluation stayed roughly level while
v1.2's own score climbed steadily from −0.3 at move 19 to +3.8 by move 27, and at move 27 we played
`Rxe4`, giving rook for bishop. The shape — our score flat while the position deteriorates over ten
moves, then a material concession — is `handoff/FINDING-round85-evaluation-blindness.md` with the
sign reversed: there the hand-crafted evaluation held +100 to +200 while Stockfish had the position
at −139 to −674. One game licenses nothing, and the eleven games beside it are unremarkable. It is
recorded because it is the first place to look if the screen comes back negative, and because a note
written before a result is worth more than the same note written after one.

**The floor, checked before letting it run to 300.** 12 of 12 terminations were checkmate: no flags,
no crashes, no illegal moves, no adjudications. Lowest clock seen across all games 17.8 s of 120 s,
typical low 25–45 s, so the measured 14.6 % node cost is not pushing the time manager into trouble at
this control. Zero draws, so nothing is shuffling its way out of a position. Game lengths 38 to 78
moves. The engine plays real chess with the network; whether it plays *better* chess is what the
screen is for.

**A harness defect, logged rather than fixed.** The PGNs carry `[%eval]` annotations for only one
side — the opponent's. We can see what v1.2 thought of each position and not what we thought, which
is backwards for diagnosing our own evaluation. Every game is therefore half-diagnostic. Not touched
mid-run; it belongs on the list for after the screens.

## The result: −67 Elo. Read against what was written above, before it.

    ct-nnue (quiet-filtered, width 128) vs versions/v1.2, 120 s + 0.5 s, 300 games, 12 workers
    +111 =21 −168, score 40.5% ± 5.4%
    Elo −67, 95% interval −106 to −29
    checkmate 279, threefold 9, fifty-move 9, insufficient material 3; draw rate 7.0%
    lowest agent clock 2 849 ms after its move; no flags, no crashes, no illegal moves

The interval lies entirely below zero. This is the **negative** branch, not the flat one.

**And for once a negative can be decomposed, which the pre-registration said it could not.** The
section above says a negative "does not distinguish a worse evaluation from the speed cost
dominating, and we should not pretend otherwise". That was written before the effect size was known,
and it turns out the arithmetic separates them here: 14.6 % of the node rate is 0.105 of a ply at
4.5 nodes per depth, worth 5–9 Elo at any plausible Elo-per-ply at our depth. The loss is 67. So
roughly 58–62 Elo of it is the evaluation itself choosing worse moves. The incremental accumulator
would have bought back the 15 % and left the great majority of the deficit untouched; proposing it
now would be rescuing the wrong variable.

**Held-out MSE pointed the wrong way for the third time on this project.** The network was 2.6×
better on held-out positions — RMSE 128 cp against 207 — and played 67 Elo worse. After the Texel
fit's −100 Elo and the withdrawn variance figure of this morning, the count of times this metric has
been checked against real games on this engine is three, and the count of times it was right is
zero. The paragraph above predicted exactly this and it is the only reason the number is reportable
rather than embarrassing.

**What the result does *not* say.** It does not say the hand-crafted evaluation is good.
`handoff/FINDING-round85-evaluation-blindness.md` and the round-87 trace stand: the shipped
evaluation is wrong by hundreds of centipawns, in *both* directions within one game, which is noise
rather than a tunable bias. This screen says our network is worse than that, which is a different
and more uncomfortable claim.

### Why, in the order I would test it

1. **The training target is not the engine's problem.** The net predicts what a depth-12 search
   scored a position. The engine needs an evaluation that *orders moves correctly at the leaves of
   its own search*. Nothing in this pipeline optimised the second, and a static evaluator that
   predicts a searcher's output is being asked to imitate the answer rather than to be a good prior
   for finding it.
2. **Data volume.** 186 000 positions for 98 700 parameters, drawn from 3 356 games at about 51
   quiet positions each, so the independent sample is far smaller than the row count. The
   train-to-held-out gap was still 2.8× after filtering.
3. **Capacity.** A single hidden layer with a linear output is what the node budget allows
   (`tools/bench_accumulator.py`: a conventional deep head costs a quarter to a third of the node
   rate). It may simply not be enough to beat even a poor hand-crafted evaluation once tactics are
   searched rather than predicted.

### What is worth keeping regardless

The kernel measurements (accumulator 72 ns, deep head 915 ns, linear head 26 ns at width 128, and
the measured 1.33 make_move and 0.60 evaluate calls per node); the quiet-position filter and the
29.5 % figure; the hash-based held-out split; the parity gate and the mirror test. None of that
depended on the net being good, and all of it would be needed again by any future attempt.

## Two diagnostics after the result

### The distribution hypothesis: partly right, not enough

Do the network's errors explode on the positions a search actually asks about? 1 500 real search
leaves, captured by wrapping `searchboard.evaluate_running` so they are exactly what the search
evaluated, against 1 500 held-out game positions, both labelled Stockfish depth 12:

| | mean \|err\| | median | sign acc |
| --- | --- | --- | --- |
| leaves, hand-crafted | 408 | 342 | 67.9% |
| leaves, network | 381 | 304 | 74.1% |
| game, hand-crafted | 157 | 104 | 75.2% |
| game, network | 114 | 76 | 78.4% |

**The finding here is not about the network. Both evaluations are three to four times worse at
search leaves than at game positions** — median error 304 and 342 cp where the search makes its
decisions, against 76 and 104 where every metric anyone has run was measured. That reframes more
than this branch.

The network's *advantage* does collapse out there: 27 % better in mean error on game positions,
6.6 % better on leaves. So its edge is largely an edge on positions the search does not spend time
in. Against the story: its sign-accuracy advantage *grows* on leaves (+6.2 points against +3.2), so
it is not uniformly worse off-distribution. Recorded because it does not fit.

This narrows the −67 and does not close it: a 6.6 % better evaluation costing 14.6 % of node rate
should be roughly neutral. Caveats — the leaves come from a search running the *hand-crafted*
evaluation, so it is that evaluation's tree and not the network's; 8 openings at one depth is one
correlated sample; and depth-12 labels on wild positions are noisier than on game positions.

### The output-scale hypothesis: killed

Every search margin is an absolute centipawn threshold tuned against the hand-crafted evaluation
(`ASPIRATION_WINDOW` 40, reverse-futility 85, `FUTILITY_MARGINS` up to 750). If MSE on a clipped
target had compressed the network's outputs, those margins would be a larger share of its dynamic
range and the search would over-prune — better by every ranking measure, worse in play, which is
exactly the pattern. Standard deviation of the scores:

| | game positions | search leaves |
| --- | --- | --- |
| hand-crafted | 390 | 279 |
| network | 411 | 333 |
| Stockfish depth 12 | 431 | 611 |

**The network is not compressed; it is 5 % wider than the hand-crafted evaluation on game positions
and 19 % wider on leaves.** If anything the fixed margins fire slightly *less* often in its units.
The hypothesis is dead and the −67 is still unexplained by output scale.

What the same table shows instead: **on search leaves both evaluations are compressed about
two-fold against the truth** — Stockfish's spread is 611 and its median absolute score 599 cp, where
ours say 116 and 167. Leaf positions are far more decisive than either evaluation reports, and the
pruning margins were tuned inside that mismatch. That is a property of the shipped engine, not of
the network, and it is the more useful half of the result.

### A hazard attached to the leaf finding, for whoever picks it up

The measurement above invites one specific change: scale the evaluation, or equivalently scale the
pruning margins, so that the margin-to-evaluation ratio matches the dynamic range the evaluation
actually has at leaves. It is one constant and it has a plausible mechanism. It also has **no
measurement behind it in either direction**, and the margins were never fitted to our evaluation's
range — they were taken at textbook magnitude and screened as a batch, which is a different thing.

**Scaling the evaluation is not free and is not equivalent to scaling the margins.** The evaluation's
output is read by more than the pruning cuts: `MATE_SCORE` and `MATE_THRESHOLD` bound it,
`DRAW_SCORE` sits at zero inside it, `DRAW_TIEBREAK_MARGIN` compares against it, and the time
manager's stability test reads score changes between iterations. Multiplying the evaluation moves
all of those; multiplying the margins moves none of them. If this is tried, scaling the **margins**
is the smaller blast radius, and either version needs a screen rather than an argument.
