# Provenance

Human-readable record of where every shipped number comes from. The machine-readable version that
ships in the zip is `weights/PROVENANCE.json` (tables and weights). Search and time-management
constants live in code and are listed here.

| parameter / file | value or shape | produced by (script + commit) | data (path + sha256 + how obtained) | run id / date | note |
|---|---|---|---|---|---|
| piece values (mg, eg) | P 100, N 320, B 330, R 500, Q 900 | `tools/gen_pst.py` | none (textbook values) | 2026-09-06 | universal textbook values, recorded as such; to be tuned in Stage 2 |
| `weights/pst.json` PSTs | 6 pieces × 64 × {mg, eg} | `tools/gen_pst.py` at commit `4109710` (parametric geometric prior; parameters in the file's `_provenance`) | none (formula) | 2026-09-06 | not copied from any engine; printed and eyeballed; mechanical row comparison against the CPW simplified tables finds one coincidental row (see DECISIONS.md 2026-09-07) |
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
| `STRUCTURE_WEIGHTS` | passed pawn 10 mg / 20 eg per rank, doubled 12, isolated 15, bishop pair 30, rook open file 20, semi-open 10, king shield 10 per pawn (mg) | code (`evaluation.py`, one dict with a one-line rationale each) | none | 2026-09-07 | hand-chosen at textbook magnitudes (a pawn = 100), untuned; every term computed from bitboards, verified symmetric on 300 random positions |
| `feature_flag` switches | `LETAL_NULL_MOVE`, `LETAL_LMR`, `LETAL_ASPIRATION`, `LETAL_FUTILITY`, `LETAL_DELTA`, `LETAL_EVAL_TERMS`, all default on | code | none | 2026-09-07 | structural: bisection switches for arena runs (`--env`); the shipped agent never sets them |

Rules: every generating script is deterministic and re-runnable; a hand-adjusted value says so in
the note with the reason; a weight file's header names its script and data hash.
