# The trained evaluation: what tonight's screen can and cannot tell us

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
