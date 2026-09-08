# Finding: the round-73 loss, with the shuffling visible in our own move list

Written 2026-09-08 from `aichessathon-round-72-keresight.pgn` and
`aichessathon-round-73-aggiequant.log`. Supersedes the evidence section of
`handoff/FINDING-closed-positions.md`; the mechanism proposed there is now confirmed against a
real rated game.

## The two games

| | round 72 vs Keresight | round 73 vs AggieQuant |
|---|---|---|
| colour | Black | White |
| result | **won**, checkmate on move 62 | **lost**, checkmate |
| opening | Italian/Scotch-ish, open | **French Winawer, locked centre** |
| structure | pieces traded off by move 25, queen endgame | c3/d4/e5 against c5/d5/e6, nothing traded |

**Round 72 matters as a control.** We won it, and the *opponent* shuffled: Keresight played
`30.Qe8 31.Qf8 32.Qg8 33.Qe8 34.Qg8` and later `36.Qc3 37.Qd4 38.Qd3 39.Qb5 40.Qe2`. So aimless
piece shuffling is endemic to this field, not a defect unique to us — which also means fixing it is
worth more than its raw Elo, because it is a differentiator against the whole ladder.

## Round 73: the shuffling, quoted from our own moves

Start FEN `rnbqk2r/pp2nppp/4p3/2ppP3/3P4/P1P5/2P2PPP/1RBQKBNR b Kkq - 2 7` — a textbook locked
Winawer. Our move list contains, in order:

- moves 10-11 `Bf1, Bg2` — bishop out and back
- moves 12,13,14,17 `Kf1, Ke2, Kd1, Kc1` — **we castled O-O on move 4 and then walked the king
  back across the board by hand**, four tempi, into the wing Black was attacking
- moves 15,24,25,27 `Rh1 ... Rh2, Rh3, Rh1` — rook returns to its own square
- moves 20-23 `Qe2, Qd1, Qe1, Qd2` — **queen returns to its own square, four tempi**
- moves 26,33 `Bg2, Bf3`; moves 44,46 `Bg4, Bf3`
- moves 43,45,47 `Qh1, Qh2, Qh1`
- moves 60-61 `Ka1, Ka2`

Roughly **15-20 tempi spent on moves that changed nothing.**

**The plan direction was actually correct.** `g4, g5, h4, h5, Rxh5, f4, gxh6, h7, Rxg6` is the right
kingside expansion in this structure. We lost because Black's queenside break (`b4, b3, a-pawns`)
arrived first, and it arrived first because we gave Black fifteen free moves. This is not an engine
that does not know what to do. It is an engine that **knows the plan and cannot stay on it**,
because between two good plan moves it repeatedly finds a null move that scores the same.

## Why: the eval has no gradient when pawns are locked

The complete weight list in `fasteval.py` is material, PSTs, doubled, isolated, passed, rook-open,
rook-semi, bishop pair, linear king shield, mop-up. In a locked position:

1. No captures exist, so **quiescence is a no-op** and the raw eval decides everything.
2. Pawns cannot move and nothing is traded, so material, doubled, isolated, passed and both rook
   terms are **constant across every legal move**.
3. The only term that varies is the **piece-square table** — a static prior with no idea of this
   structure. `Qd1` and `Qe2` differ by a few centipawns of PST and nothing else.
4. So dozens of root moves tie, and the engine returns whichever the move ordering surfaced first.
   Next move the ordering differs slightly and it goes back. **That is the shuffle.**

The search is working correctly. It is faithfully optimising a function that cannot tell a plan
from a pointless queen move.

## What the log also proves (unrelated to closed positions, but measured)

- **The time gate from `handoff/RESEARCH-ROUND1.md` is confirmed on the platform.** The stderr
  fields are `t` = time used, `s` = soft budget ms, `h` = hard budget ms (`h` is exactly `3*s`),
  `c` = clock left. Nearly every move spends **~45-60% of its soft budget**: `t 1850 s 3396`,
  `t 1520 s 3362`, `t 1593 s 3356`, `t 1540 s 3373`. That is `next_iteration_fraction = 0.45`
  (`mikhail_letal/timing.py:47`) doing exactly what round 1 predicted, now visible in a rated game.
- **Platform nps is 440-560 k, not the ~700 k measured locally.** Every local depth estimate should
  be scaled down accordingly.
- **Init is 35.2 s of the 90 s budget** (`jit 34.1s`), so there is ~55 s of unused import time
  available for precomputed tables.
- Depth in this closed position was **10-13** on ~1 M nodes per move.
- The clock was *not* the proximate cause here: 144.5 s used of ~154 s available, 9.5 s left. The
  gate cost depth, not a flag.

## Falsifier, and it costs one run

Everything above predicts that in a locked position **the top root moves are tied within a few
centipawns**. Instrument the root to print the top-5 move scores per iteration and replay the
round-73 position. If the scores are tightly clustered, the diagnosis holds and the fix is
evaluation. If one move is clearly best and we played a different one, the diagnosis is wrong and
the fault is in move ordering or the aspiration window — check that before writing any eval code.

A second, cheaper check: count captures entering quiescence in that position. Near zero confirms
that the static eval is doing all the work.
