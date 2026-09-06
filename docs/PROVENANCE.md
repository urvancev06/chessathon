# Provenance

Human-readable record of where every shipped number comes from. The machine-readable version that
ships in the zip is `weights/PROVENANCE.json` (tables and weights). Search and time-management
constants live in code and are listed here.

| parameter / file | value or shape | produced by (script + commit) | data (path + sha256 + how obtained) | run id / date | note |
|---|---|---|---|---|---|
| piece values (mg, eg) | P 100, N 320, B 330, R 500, Q 900 | `tools/gen_pst.py` | none (textbook values) | 2026-09-06 | universal textbook values, recorded as such; to be tuned in Stage 2 |
| `weights/pst.json` PSTs | 6 pieces × 64 × {mg, eg} | `tools/gen_pst.py` (parametric geometric prior; parameters in the file's `_provenance`) | none (formula) | 2026-09-06 | not copied from any engine; printed and eyeballed |
| mop-up weights | see `pst.json` `mopup` | `tools/gen_pst.py` | none | 2026-09-06 | chosen by hand from the geometric idea |
| phase weights | N 1, B 1, R 2, Q 4 (total 24) | code | none | 2026-09-06 | standard tapered-evaluation phase weighting |
| `MATE_SCORE`, `MATE_THRESHOLD` | 100 000, 99 000 | code | none | 2026-09-06 | arbitrary large constants |
| TT entry cap | `Searcher(tt_max_entries)` default | code | none | 2026-09-06 | bounds memory; measured RSS in RESULTS.md |
| `NODE_CHECK_INTERVAL` | 1024 | code | none | 2026-09-06 | clock read cadence; brief suggests 2048–4096 for the numba engine, lower here because Python nodes are slow |
| history heuristic bonus | `depth * depth` | code | none | 2026-09-06 | textbook |
| time constants | see CALIBRATION.md | code | none | 2026-09-06 | brief §6.2 initial values, to be calibrated |

Rules: every generating script is deterministic and re-runnable; a hand-adjusted value says so in
the note with the reason; a weight file's header names its script and data hash.
