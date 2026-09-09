# Round 78 vs TortureFish — LOST — the first rated game played by v1.1

Transcribed from the operator's paste. **The raw platform log has not been downloaded**, so unlike
`LOG-round-71/73/74/75` this file is not the artefact itself and the `m …` lines are not present.
Treat it as second-hand until the real log is on disk.

Match 40375ec9-8294-4259-aca9-2b963185a5ee, machine w-978b07, finished 2026-09-09 09:17:18 UTC.
Sicilian Najdorf, we were White. 59 of our moves, 111.3 s used, **38.2 s left**. Lost by checkmate.

The two `0/0 … s 0 h 0` entries (our moves 46 and 58) are the single-legal-move fast path, verified
by replaying the game: `8/4k3/5p2/8/7p/1KR5/rr6/8 w - - 2 53` and `8/8/8/8/2k5/8/6q1/4K3 w - - 10 65`
each have exactly one legal move. Not a budget defect.

## Absolute thinking time, the build-independent comparison

`t/s` is NOT comparable across these builds: v1.1 changed the denominator (`moves_to_go_max` 40→50,
`_min` 12→20, `overhead_ms` 150→50), so soft at a 120 s clock is 3396 ms under v1.0 and 2799 ms
under v1.1. A ratio whose denominator moved cannot be compared. Raised by `chessathon-cd`; the
correct comparison is milliseconds.

| game | build | our moves | mean t, first 20 | median t, all | total |
|---|---|---|---|---|---|
| round 71 | v1.0 | 105 | 2160 ms | 1616 ms | 166.3 s |
| round 73 | v1.0 | 68 | 2529 ms | 1964 ms | 144.5 s |
| round 74 | v1.0 | 70 | 2538 ms | 1738 ms | 145.1 s |
| round 75 | v1.0 | 54 | 2317 ms | 1953 ms | 124.8 s |
| **round 78** | **v1.1** | **57** | **1714 ms** | 1765 ms | 111.2 s |

**v1.1 thinks 28 % less over the first twenty moves** than the v1.0 mean of 2386 ms, and its
median over the whole game sits inside the v1.0 range. So the difference is concentrated in the
opening and early middlegame, which is where the clock is fullest and where the larger
`moves_to_go` bites hardest.

**That is the refit doing what it was designed to do.** v1.0's measured failure was long games
finishing on 4.7 s and 5.4 s; banking early time is the intended trade. What this single game
cannot say is whether the trade is net positive.

## What it does not establish

Our move 13 (`d2g5`) was searched to **depth 7** on 1055 ms with 104 s on the clock, and the
evaluation went +46 → 0 → −59 → −69 over moves 12–15, which is where the game was lost. That is
suggestive and it is not evidence: n=1, and no counterfactual was run. The 200-game match measured
the whole refit at **+8.7 Elo, interval −33 to +51** — no evidence either way, which is the honest
state.

The test that would settle it needs no machine: `tools/sim_time.py` over the ladder game-length
distribution with both constant sets, comparing **absolute per-move budgets at matched game
lengths**.

## Per-move t / soft / hard, as pasted

     t     s     h
  1016  2799  8397
  1052  2789  8366
  3797  2826  8478
  1194  2808  8424
   947  2793  8380
  1499  2835  8505
  2622  2866  8598
  2192  2820  8460
  4057  2836  8508
  2203  2811  8432
   514  2827  8481
   598  2827  8480
  1055  2882  8646
  2320  2929  8787
   975  2885  8654
  2685  2935  8804
   788  2944  8831
  3181  2936  8809
   567  2932  8797
  1017  2999  8997
  1331  3057  9171
  1697  3034  9101
  3541  3075  9224
  1821  3064  9192
   587  3025  9075
   771  3102  9306
  1071  3178  9534
  2281  3160  9480
  1984  3192  9575
  1185  3235  9705
  2973  3309  9928
  1370  3224  9672
  2760  3294  9881
  2989  3317  9951
  2889  3225  9675
  2254  3242  9725
  9856  3285  9855
  1765  2911  8732
  2948  2963  8888
  3460  2968  8903
  3900  2950  8849
  2959  2795  8385
  1132  2792  8376
  2104  2880  8640
   711  2800  8399
  1607  2814  8442
  1039  2759  8276
  2436  2732  8195
  2413  2635  7904
  1824  2539  7617
   909  2473  7418
  2022  2452  7357
  3023  2376  7128
  1277  2250  6750
    41  2211  6633
     8  2234  6702
     2  2283  6850
