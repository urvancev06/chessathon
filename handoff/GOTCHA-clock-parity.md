# Every rated game of ours starts with Black to move

Found 8 September 2026 by `chessathon-bb` while building `tools/our_games.py`, and caught only
because `handoff/FINDING-king-safety.md` records round 70's clocks independently.

## The trap

Rated games do not start from the standard position. They start from a **curated opening position**,
and in all five rated games we have played so far the side to move in the starting FEN is **Black**:

```
1e1c9922  r1bqkb1r/pp2pppp/2n2n2/3p4/3P4/2PB3P/PP3PP1/RNBQK1NR b KQkq - 0 6
3ebceb52  r2qkb1r/pp2pppp/2n2n2/3p4/3P1Bb1/1QPB4/PP3PPP/RN2K1NR b KQkq - 4 7
5504d7fa  rn1qkb1r/1p3ppp/p2pbn2/4p3/4P3/1NN1B2P/PPP2PP1/R2QKB1R b KQkq - 3 8
cf4043b1  rn1qkbnr/pp2pppp/2p3b1/8/3P4/6N1/PPP1NPPP/R1BQKB1R b KQkq - 4 6
f43e60b5  r1bqk1nr/pp2ppbp/2np2p1/2p5/4P3/2NP1NP1/PPP2PBP/R1BQK2R b KQkq - 1 6
```

The movetext therefore opens on a Black move — `7... Qd7 { [%clk 0:01:58.195] }` — so **the first
`[%clk]` in the game belongs to Black, not to White**. Any code that walks the clock, eval or move
list in pairs and assumes index 0 is White's has the two sides swapped for the entire game.

This is silent. Nothing raises, nothing looks malformed; you simply get the opponent's numbers under
our name. In the first version of `tools/our_games.py` it turned round 70's "we finished on 90.2 s"
into "we finished on 72.0 s", which is the opponent's clock, and would have made a game where we had
*plenty* of time look like one where we were nearly flagged — the exact opposite of the conclusion.

## The rule

Take the parity from the FEN, never from the assumption that White moves first:

```python
first_is_white = fen.split(" ")[1] != "b"
offset = 0 if ours_is_white == first_is_white else 1
ours = clocks[offset::2]
theirs = clocks[1 - offset :: 2]
```

Note that this is a property of *rated* games. Local arena and webapp PGNs written by
`tools/arena_openings.py` also start from `data/openings.txt`, so they have the same property; games
from the standard position do not, which is what makes the assumption feel safe when it is tested
locally on the wrong kind of game.

## Where it applies

Anything that reads one of our PGNs move by move: the clock summariser in `tools/our_games.py`
(fixed), `tools/webapp/analysis.analyse_game`, and the `[%eval score,depth]` tags that
`tools/arena_openings.py` now stamps (`7080e34`). Check each before trusting a per-side number out
of it.

## How to check a change

`data/pgn/ours/3ebceb52-c84.pgn` is the regression test with a known answer, recorded in
`FINDING-king-safety.md` before this tool existed: we are **Black**, we finished on **90.2 s**, the
opponent on **72.0 s**. If a tool reports those the other way round, it has this bug.
