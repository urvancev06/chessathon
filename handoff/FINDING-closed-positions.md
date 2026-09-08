# Finding: why this engine shuffles in closed positions, and what to add

Written 2026-09-08. **This is analysis, not a literature sweep** — the session ran out of usage
budget before a research round could be spent on it. Code facts below are verified against the
working tree at `074c7bb`. Chess-theory content is standard positional theory, stated so it can be
turned into eval terms; it is not sourced to a paper and should be sanity-checked by a strong
player or a later research round.

## The mechanism, and it is not the search

The obvious suspect was null-move pruning, because null move is unsound in zugzwang and closed
positions are where zugzwang lives. **That suspect is cleared:** `fastsearch.py:845` already gates
null move on `_has_non_pawn_material(pos, side)`, the standard mitigation. (`NULL_MOVE_MIN_DEPTH=3`,
`BASE_REDUCTION=2`, `DEPTH_DIVISOR=6`, `search.py:85-87`.) What it lacks is a **verification
search** — re-searching at reduced depth without null move before trusting a fail-high — which
strong engines add precisely for blocked positions. Worth adding, but it is a second-order fix.

**The real cause is that the evaluation is blind to closed structures.** The complete list of
weights in `fasteval.py` is: `W_COUNT`, `W_SCORE`, `W_DOUBLED`, `W_ISOLATED`, `W_PASSED_MG`,
`W_PASSED_EG`, `W_ROOK_OPEN`, `W_ROOK_SEMI`, `W_BISHOP_PAIR`, `W_KING_SHIELD`. There is
**no mobility term, no space term, no outpost term, no bad-bishop term, no blocked-pawn term, and
no notion of how closed the position is.**

That produces exactly the symptom described. In a locked position:

1. No captures exist, so **quiescence is a no-op** and the eval is called on raw quiet positions,
   where its blind spots dominate instead of being washed out by tactics.
2. Material is fixed and pawns cannot move, so `W_COUNT`, `W_DOUBLED`, `W_ISOLATED`, `W_PASSED_*`
   and `W_ROOK_*` are all **constant across every legal move**.
3. What is left to distinguish moves is the piece-square table alone — a static, position-blind
   prior. Dozens of moves score within a pawn of each other.
4. With a flat gradient, the search returns whichever near-tied move the move ordering happened to
   surface first. **That is the shuffling.** It is not a search failure; the search is faithfully
   optimising a function that does not know what a good closed position looks like.

The fix is therefore to give the evaluation a gradient in exactly the dimensions that still vary
when the pawns are locked: **piece placement quality, space, and the availability of pawn levers.**

## How closed positions are actually won (the theory to encode)

- **A locked structure can only be changed by a pawn lever.** Every real plan is the preparation of
  a break (f4-f5, b4-b5, c4-c5, g4-g5). An engine with no concept of a lever never prepares one and
  never prevents the opponent's.
- **Play where you have more space; create a second weakness.** One weakness is defensible in a
  closed position; two on opposite wings are not, because the defender's pieces cannot travel
  behind a locked chain.
- **Knights beat bishops when pawns are locked**, and a bishop blocked by its own pawns on its own
  colour ("bad bishop") is close to a spectator. The classic adjustment is per-pawn: each pawn on
  the board makes knights slightly better and bishops slightly worse.
- **Outposts decide.** A knight on a square no enemy pawn can ever attack, supported by a pawn, is
  worth far more than the piece-square table says. Long regrouping manoeuvres (Nf1-e3-d5) are how
  strong players reach them — and a 12-ply search will find the route greedily **if and only if the
  destination square is rewarded**, which is the practical reason an outpost term matters more
  here than its raw Elo suggests.
- **The cramped side seeks exchanges; the side with space avoids them.** Trading pieces relieves a
  space disadvantage.
- **King safety inverts.** With the centre locked, kings are safe and a wing pawn storm is the
  standard plan (King's Indian, Closed Sicilian). An engine that fears advancing its own king-side
  pawns will never play the correct plan.
- **Zugzwang and tempo matter more** the more locked the position is.

## What to add, cheapest first

All of these are computable from the piece lists and the per-file pawn summary `_structure` already
builds, so none needs a full board scan.

1. **A closedness scalar `C`.** Count own pawns with an enemy pawn directly in front, plus
   pawn-chain contacts; at most 8 pawns to walk. Normalise to 0..1. `C` is the switch every term
   below is scaled by, and it is the single most important addition because it lets the evaluation
   have *different priorities in closed positions* rather than one blended set.
2. **Minor-piece adjustment by pawn count.** Knight `+k*pawns`, bishop `-b*pawns`. Two multiplies
   on numbers already counted — the cheapest real positional knowledge available.
3. **Bad bishop.** For each bishop, count own pawns on squares of its colour (a precomputed
   colour mask plus the pawn list), penalise, and scale by `C`.
4. **Outposts.** A knight on a square that no enemy pawn can attack (from the per-file pawn
   summary) and is defended by an own pawn: bonus, scaled by `C`.
5. **Lever availability.** Count own pawns that could capture an enemy pawn, or advance to a square
   an enemy pawn guards. Reward having levers, penalise having none while the opponent has some.
   This is what makes the engine *prepare a break* instead of shuffling: a move that creates a
   lever now scores better than a move that does not.
6. **A cheap space term.** Squares on our third and fourth ranks that are not attacked by an enemy
   pawn, multiplied by pawn count. This is the standard cheap proxy for manoeuvring room.
7. **Null-move verification search.** Above some depth, re-search without null move before trusting
   a fail-high. Cheap insurance in exactly the positions under discussion.
8. **Mobility.** Genuinely absent, and it is the term that most directly punishes a passive piece.
   It is also the most expensive here, since a mailbox engine must walk ray directions per piece —
   measure the nps cost before believing it is worth it.

Items 1-5 are the ones that give the engine a gradient where it currently has none. Item 6 helps
choose *which* wing. Item 8 is the honest big one but has a real speed cost.

## How to test it, given that the arena will not show this

**The 219 openings in `data/openings.txt` will mostly not measure this**, and a balanced arena set
is exactly the trap documented for king safety in `handoff/RESEARCH-ROUND1.md` (three engines
measured naive king safety at -8 to -10 Elo because they tuned on sets without the relevant
positions). So:

1. Build a **closed-position test set**: FENs from King's Indian, Closed Sicilian, French Winawer
   and Advance, Stonewall Dutch, Czech Benoni. Take them from the curated 219 where they exist and
   from public game databases otherwise. Score every change on this subset **separately** from the
   full set, and require it not to regress the full set.
2. **Measure the shuffling directly, before any match.** On a locked position, log the top-5 root
   move scores at each iteration. The prediction of this whole analysis is that they are currently
   within a few centipawns of each other. If they are *not* tightly clustered, this diagnosis is
   wrong and the cause is elsewhere — check that first, it costs one instrumented run.
3. A second falsifier: count captures in quiescence during a closed-position search. If it is near
   zero, the eval-is-doing-all-the-work claim holds.

## What is still needed

- **The lost game itself.** `data/pgn/ladder/` stops at round 71, which we **won** by checkmate.
  Download the game that was lost and analyse it move by move (`tools/webapp/analysis.analyse_game`
  was used this way for the round-70 king-safety finding). The specific position where the plan
  went missing is worth more than everything above.
- **A real research round on this topic.** This file is unsourced analysis. The literature on
  engine weaknesses in closed positions, fortress detection, and space/mobility term formulations
  with measured Elo was not read, because the usage budget ran out.
