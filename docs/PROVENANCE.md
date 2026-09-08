# Provenance

Human-readable record of where every shipped number comes from. The machine-readable version that
ships in the zip is `weights/PROVENANCE.json` (tables and weights). Search and time-management
constants live in code and are listed here.

| parameter / file | value or shape | produced by (script + commit) | data (path + sha256 + how obtained) | run id / date | note |
|---|---|---|---|---|---|
| piece values (mg, eg) | P 100, N 320, B 330, R 500, Q 900 | `tools/gen_pst.py` | none (textbook values) | 2026-09-06 | universal textbook values, recorded as such; to be tuned in Stage 2; Stage 2 tuning tried 2026-09-07 (`tools/tune_texel.py`, DECISIONS.md) and rejected in the arena, so still the textbook values |
| `weights/pst.json` PSTs | 6 pieces × 64 × {mg, eg} | `tools/gen_pst.py` at commit `4109710` (parametric geometric prior; parameters in the file's `_provenance`) | none (formula) | 2026-09-06 | not copied from any engine; printed and eyeballed; mechanical row comparison against the CPW simplified tables finds one coincidental row (see DECISIONS.md 2026-09-07); the 2026-09-07 Texel fits toward this prior lost to v0.2 (Elo −100 and −23, RESULTS.md), so the file is byte-identical to `versions/v0.2`'s |
| mop-up weights | see `pst.json` `mopup` | `tools/gen_pst.py` | none | 2026-09-06 | chosen by hand from the geometric idea |
| phase weights | N 1, B 1, R 2, Q 4 (total 24) | `tools/gen_pst.py` → `weights/pst.json` (`evaluation.py` only validates them) | none | 2026-09-06 | standard tapered-evaluation phase weighting |
| `MATE_SCORE`, `MATE_THRESHOLD` | 100 000, 99 000 | code | none | 2026-09-06 | arbitrary large constants |
| TT entry cap | 250 000 entries (`Engine(tt_max_entries)` default); dict, cleared when full and at move start above 60 % (`TT_CLEAR_FRACTION`) | code | none | 2026-09-07 | bounds memory: 120 MB RSS at the cap (RESULTS.md); int-only entries keep gen-2 gc pauses ≤ 14 ms |
| `NODE_CHECK_INTERVAL` | 128 | code | none | 2026-09-07 | clock read cadence; structural. 1024 gave 25 ms mean / 65 ms max overshoot locally; a `perf_counter` read costs ~60 ns so 128 is free |
| `MAX_PLY` | 128 | code | none | 2026-09-06 | structural: recursion bound for search + quiescence + extensions |
| check extension | +1 ply when in check | code | none | 2026-09-06 | textbook; applied before the TT probe |
| `QS_EVASION_PLIES` | 4 | code | none | 2026-09-07 | quiescence searches all evasions this deep; chosen so eight-queens-a-side positions keep depth 1 under 100k nodes |
| `DRAW_TIEBREAK_MARGIN` | 300 | code | none | 2026-09-07 | root tie-break threshold: "clearly ahead" = at least a minor piece |
| history heuristic bonus | `depth * depth` | code | none | 2026-09-06 | textbook |
| time constants | see CALIBRATION.md | code | none | 2026-09-06 | brief §6.2 initial values, to be calibrated |
| `EVAL_CACHE_MAX_ENTRIES` | 100 000 | code (`search.py`) | none | 2026-09-07 | v0.2 exact speedup; cap chosen so a 20 s search stays under 100 MB RSS (measured 82 MB with 70k entries) |
| `PAWN_CACHE_MAX_ENTRIES` | 50 000 | code (`evaluation.py`) | none | 2026-09-07 | pawn-structure cache cap; hand-chosen, small keys |
| `NULL_MOVE_MIN_DEPTH` | 3 | code | none | 2026-09-07 | hand-chosen after measurement: 2 tripled the nodes to depth 5 in a capture-rich middlegame (null searches landing in quiescence at the widest layer), 3 kept the savings elsewhere (DECISIONS.md) |
| `NULL_MOVE_BASE_REDUCTION`, `NULL_MOVE_DEPTH_DIVISOR` | 2, 6 (R = 2 + depth // 6) | code | none | 2026-09-07 | textbook-magnitude null-move reduction, untuned |
| null move only when static eval ≥ beta | rule | code | none | 2026-09-07 | textbook guard; measured no node change on four test positions, kept because it only removes null searches that would fail |
| `LMR_MIN_DEPTH`, `LMR_FULL_DEPTH_MOVES`, `LMR_REDUCTION` | 3, 3, 1 | code | none | 2026-09-07 | textbook-magnitude late-move reduction, untuned |
| `ASPIRATION_MIN_DEPTH`, `ASPIRATION_WINDOW`, `ASPIRATION_WIDEN`, `ASPIRATION_MAX_FAILS` | 4, 40 cp, ×4, 2 | code | none | 2026-09-07 | textbook-magnitude aspiration window, untuned |
| `FUTILITY_MARGINS` | 150 (depth 1), 300 (depth 2) | code | none | 2026-09-07 | textbook-magnitude margins (a minor piece and two), untuned |
| `DELTA_MARGIN` | 200 | code | none | 2026-09-07 | textbook-magnitude quiescence delta margin, untuned |
| `STRUCTURE_WEIGHTS` | passed pawn 10 mg / 20 eg per rank, doubled 12, isolated 15, bishop pair 30, rook open file 20, semi-open 10, king shield 10 per pawn (mg) | code (`evaluation.py`, one dict with a one-line rationale each) | none | 2026-09-07 | hand-chosen at textbook magnitudes (a pawn = 100), untuned; every term computed from bitboards, verified symmetric on 300 random positions; prior recorded in `tools/gen_pst.py` `STRUCTURE_PRIOR`; the 2026-09-07 fit (12/13/27/11/56/73/57/42 at λ = 10) was rejected with the tables |
| `feature_flag` switches | `LETAL_NULL_MOVE`, `LETAL_LMR`, `LETAL_ASPIRATION`, `LETAL_FUTILITY`, `LETAL_DELTA`, `LETAL_EVAL_TERMS`, all default on | code | none | 2026-09-07 | structural: bisection switches for arena runs (`--env`); the shipped agent never sets them |
| `data/tuning/positions.epd` | 25 994 FENs (not shipped) | `tools/tune_texel.py positions` at commit `d28a755` (seed 2026, deterministic) | self-play of `mikhail_letal.search.Engine` at 2 000 nodes/move from `data/openings.txt`, 4 seeded games per opening, a near-best move (within 30 cp at one ply) drawn at random with probability 0.2; quiet positions only (not in check, quiescence = static evaluation, pawns on board), ≤ 30 per game, plus the quiet positions of `data/pgn/**/*.pgn`; sha256 `facd402a03ea7665623cac2b9e09d8a360eddcd468a0087dd4bf2fa80289a9d2` | texel-2026-09-07 | tuning data for the v0.3 experiment |
| `data/tuning/labels.csv` | 25 994 White-POV centipawn labels clipped to ±1500 (not shipped) | `tools/tune_texel.py label` at commit `d28a755` | Stockfish 19 (`~/.local/opt/stockfish`, local only), depth 10, Threads 1, over `positions.epd`; sha256 `947648c20c8950e7a01365af63e1c1caf352a59bddd8d29eaf95ba4a03f1554f` | texel-2026-09-07 | engine-labelled data, as the rules allow; nothing of it is in the zip |
| `data/tuning/fit_report_lambda10.json`, `fit_report_lambda40.json` | fitted weights, CV curve, MSE before/after, biggest changes (not shipped) | `tools/tune_texel.py fit` and `fit --lambda-scale 4` at commit `d28a755` | the two files above | texel-2026-09-07-lambda10, -lambda40 | validation MSE 72 177 → 53 509 / 54 224, yet Elo −100 (−140 to −62) and −23 (−61 to +14) against v0.2 over 300 games each, so no shipped number changed (DECISIONS.md 2026-09-07) |
| `fastboard.ZOBRIST_SEED` | 20260908 | code (`fastboard.zobrist_keys`, numpy PCG64) | none | 2026-09-08 | the 1 817 random 64-bit numbers behind the position key; generated from the seed at import, never a table copied from anywhere. Any key drawn as exactly 0 is replaced by 1, because 0 marks an empty table slot |
| `fastboard.MOVES_PER_PIECE_MAX` | 27 | code | none | 2026-09-08 | structural: the most destinations one piece can have (a queen on an empty board), which is how much room `gen_pseudo`'s overflow guard reserves per piece |
| `fastboard.MAX_MOVES`, `MAX_UNDO` | 256, 512 | code | none | 2026-09-06 | structural, now guarded at runtime (DECISIONS.md 2026-09-08): 218 legal moves is the known maximum for a position, and the referee caps a game at 600 plies |
| `fastsearch.TT_BITS`, `EVAL_BITS` | 21, 18 | code | none | 2026-09-08 | 2 097 152 table entries (8 B key + 16 B data = 50 MB) and 262 144 evaluation-cache entries (3 MB); sized so a three-second search never fills the table and the whole process stays at 349 MB RSS, measured, against the platform's 2 GB |
| `fastsearch.NODE_CHECK_INTERVAL` | 512 | code | none | 2026-09-08 | clock-read cadence inside the compiled search. An `objmode` read costs ~300 ns (measured), so 512 nodes is well under 1 % of node cost at a million nodes a second and bounds the overshoot past the hard deadline to about half a millisecond |
| node cap multiplier | 2 x (measured nodes/s x hard budget) + 100 000 | code (`FastEngine.search`) | none | 2026-09-08 | the second, deterministic limit that backs up the clock; the rate is measured from real searches (`FastEngine.node_rate`, exponential average, seeded by the warm-up search) rather than assumed |
| every search constant in `fastsearch` | imported from `search.py` | code | none | 2026-09-08 | the compiled searcher imports NMP/LMR/aspiration/futility/delta/quiescence constants from the Python one, so there is exactly one place each number lives and the two engines cannot drift apart |
| every evaluation weight in `fasteval` | read through `evaluation.load_tables` | `tools/gen_pst.py` -> `weights/pst.json` | none | 2026-09-08 | the compiled evaluation has no numbers of its own: it re-indexes what `evaluation.py` already parsed, and the gate is exact integer equality with it on 20 000 positions |

Rules: every generating script is deterministic and re-runnable; a hand-adjusted value says so in
the note with the reason; a weight file's header names its script and data hash.
