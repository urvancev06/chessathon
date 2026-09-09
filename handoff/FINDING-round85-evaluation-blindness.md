# Round 85: the engine was wrong about who was winning for 23 consecutive moves

Lost as White to Keresight, checkmate, 52 moves, 103.6 s of 120 + 0.5 used, 42.4 s left at the
end. **Not a time-management loss, not a blunder, and not a search failure.**

## The trace

Our own eval against Stockfish 19 at depth 18, on the position before each of our moves. Both
from White's point of view, in centipawns.

| move | played | ours | Stockfish | error |
|---|---|---|---|---|
| 13 | Nxc4 | +45 | −24 | +69 |
| 14 | Bxc6 | +60 | **−460** | **+520** |
| 16 | f3 | +48 | −338 | +386 |
| 20 | e5 | +177 | −76 | +253 |
| 23 | Qd3 | +185 | −215 | +400 |
| 27 | Bd2 | +201 | −191 | +392 |
| 31 | Qe1 | +258 | −188 | +446 |
| 34 | a3 | +110 | −410 | +520 |
| 36 | Bd2 | +96 | **−674** | **+770** |

From move 14 to move 36 the sign was wrong on all but two moves. **The engine believed it was
winning by one to two pawns while it was losing by two to six.**

## What it was not

**Not the move at 36.** Stockfish's top four at that position are −649, −657, −746, −822: the
game was already lost whatever we played, and `Bd2` was its *second* choice. The 389 ms spent on
it is irrelevant — no amount of time saves a position that is −650 before the move.

**Not a search failure.** Move 13 `Nxc4` was searched to depth 11 over 812,795 nodes and returned
+45. The position it entered is −460. Eleven plies did not reveal a 500 cp error, so this is not
something more depth or better ordering finds.

**Not the two zero-node moves.** Moves 53 and 57 show `0/0`, 0 nodes, 1 ms in the log. Both
positions have **exactly one legal move** and both are in check. That is a correct fast path.

## What it was

The material count is roughly level after `13.Nxc4 dxc4 14.Bxc6 Bd7 15.Bxa8 Qxa8` — rook and two
pawns for knight and bishop. Our evaluation reads that as +60 and climbing. What it cannot read is
what Black has instead: the bishop pair on open diagonals, a knight coming to d5, a passed c-pawn,
and files opening at a king whose shield we spend the middlegame dismantling ourselves with `f3`,
`e4`, `g3`. **Every one of those is an activity term, and the evaluation has no mobility term at
all.**

## The evaluation is identical in v1.0, v1.1 and v1.2

`diff versions/v1.1/mikhail_letal versions/v1.2/mikhail_letal` reports `__init__.py`,
`fastboard.py`, `fastsearch.py`, `search.py` — **`evaluation.py` and `fasteval.py` are byte
identical, and so is `weights/pst.json`.** So which build played this game does not matter to the
diagnosis. It would have been played the same way by any version we have ever uploaded.

## The network, measured on these same 26 positions

Both evaluations, static, no search, against Stockfish depth 18 as ground truth:

|  | mean absolute error | sign correct |
|---|---|---|
| hand-crafted | 335 cp | **5 / 26** |
| network | 137 cp | **20 / 26** |

**Caveat that must travel with this table.** The network was *trained* to predict Stockfish, so
scoring it against Stockfish scores it on its own training objective; the hand-crafted evaluation
was never fit to that target. The mean-error column is therefore biased toward the network and
should not be quoted alone. The sign column is the robust one and the operationally meaningful
one: *did the engine know it was worse?* Twenty-one of twenty-six times, it did not.

Also: 26 consecutive positions from one game are one correlated sample, not twenty-six. This is
evidence about a mechanism, not a measurement of an effect size.

## What it argues for

1. **Mobility.** `ct-mobility` has been sitting unscreened with confirmed weights. This game is
   the failure it is supposed to fix.
2. **The network.** Independent of held-out MSE — which on this project ranked a −100 Elo Texel
   fit highest — the network gets the sign right where the hand-crafted evaluation does not, on
   the actual positions of an actual loss.
3. **Against assuming our losses are search-bound.** The ordering bundle buys ~1.65x effective
   speed. It would not have changed this game.
