# Syzygy tablebases: measured, and not worth shipping

Found 8 September 2026 by `chessathon-64`. `tb/` holds a complete 3-4-man Syzygy set (4.4 MB, 65
tables, committed 8 Sep 16:54) that nothing in the repo references. This is the measurement of
whether to wire it in. **The answer is no**, and the reasoning is worth keeping so nobody spends
Wednesday on it.

## What is there

A complete 3- and 4-man set: every `K?vK` and `K?vK?` combination, 65 WDL tables and 65 DTZ. It
works — `chess.syzygy.open_tablebase("tb")` loads all 65 and probes correctly. Tablebases are
explicitly permitted, and `chess.syzygy` is in the platform's fixed stack.

It is **tracked in git** but **not in the zip**: `harness.package` includes only `weights/` plus
whatever the root modules import, so `tb/` has never shipped. It is 4.4 MB of committed binary that
does nothing, and `AGENTS.md`'s list of what never ships does not mention it either way.

## Does it fix the recorded endgame failures?

Two of the three, and they are the two already fixed:

| position | tablebase | status without it |
|---|---|---|
| `8/8/8/8/3k4/8/8/4KQ2 w - - 82 60` (KQvK, 18 plies of fifty-move room) | **win, DTZ 13** — five plies to spare | already converted by v1.0 |
| `8/8/8/3K4/8/8/8/q6k b - - 0 291` (KQvK, 19 plies to the 600-ply cap) | **win, DTZ 17** — two plies to spare | **knife edge**: mate at exactly ply 600 in one replay, missed in another |
| Lucena `1K1k4/1P6/8/8/8/8/r7/2R5 w` | **not covered** — five men | converted by v1.0 |

So the one case where it would add certainty is the 600-ply knife edge, which is a constructed
position rather than a game, and the one endgame weakness that a tablebase cannot reach is the
five-man Lucena — 5-man Syzygy is far too big for the 50 MB cap.

## Would it have won us anything? 1 001 games say no

Every PGN in `data/pgn` was replayed to the first position with four men or fewer, and the
tablebase verdict there compared with how the game actually ended.

| | our games | the ladder's top teams |
|---|---|---|
| games | 351 | 2 750 |
| reached ≤ 4 men | **16 (4.6 %)** | 722 (26.3 %) |
| tablebase win, actually drawn | **0** | 7 |
| tablebase draw, actually lost | 0 | 1 |
| tablebase loss, actually drawn (escaped) | 3 | 11 |

**In 351 of our own games there is not one position a tablebase would have converted.** The
sixteen four-man endings we reached, we already played correctly: one win won, eight draws drawn,
four losses lost, and three positions that were theoretically lost salvaged into draws — which a
tablebase would not have improved, and which a tablebase-equipped *opponent* would have taken off us.

## The honest caveat, and the number it produces

Our 351 games are biased toward short decisive games: most are arena games against weak baselines
that end in an early checkmate, which is why we reach four-man endings at 4.6 % against the ladder's
26 %. Against Swiss-level opposition games will run longer and reach these endings more often, so
the right rate to plan with is theirs, not ours.

Even taking their rate: 26.3 % of games reach a four-man ending, and 0.97 % of those endings (7 of
722) were tablebase wins that got drawn. That is **0.26 % of games**, or about **0.03 points across a
13-round Swiss**. For comparison, the king-danger term is being built because of a single lost game
that cost a full point.

## Recommendation

**Do not wire it in before Thursday.** It is a real feature with a real (if small) effect, and the
work is not free: probing inside the compiled search means crossing the numba boundary or restricting
probes to the root, both of which need design, measurement and a promotion match — on a deadline where
the measurement queue is already the bottleneck and two changes are waiting on it.

Two cheap things worth doing instead:

1. **Say what `tb/` is.** Either delete it or add a line to `AGENTS.md` saying it is an experiment
   that does not ship. A 4.4 MB directory of binaries with no references is the kind of thing a judge
   asks about, and "we measured it and it was not worth 0.03 points" is a much better answer than a
   shrug.
2. **Keep this measurement.** If there is time after the Swiss, the root-only version — probe at the
   root when the position has four men or fewer, and play the DTZ-optimal move — is perhaps twenty
   lines and cannot slow the search, because it replaces it. That is the version to build, and it is
   a Stage 2 item, not a Thursday one.
