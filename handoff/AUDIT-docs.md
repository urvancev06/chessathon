# Documentation audit, 2026-09-08

By session `chessathon-64`, against the working tree at `96b9a9f` plus the uncommitted timing work.
Read-only: **nothing in the tree was changed to produce this.** Every item below is a proposal.

Scope: every Markdown document in the repo, `docs/report.tex`, and the uncommitted diff they
describe. Ordered by what it costs to leave it alone, not by where it sits in the tree.

---

## A. Blocking — these change what ships or what we believe

### A1. The timing change is not measured, and cannot ship under the repo's own rule

`docs/RESULTS.md` has no row for it. The labels stop at `v1.0-vs-sf2400-real`. Everything behind
the new constants is either a simulation (`tools/sim_time.py` replaying the budget formula over
635 ladder games) or a position probe (6–10 middlegame positions). Neither is a game.

AGENTS.md: *"A version replaces the previous one only when it wins a match whose 95% confidence
interval is above zero, at the real time control, with the previous version kept in `versions/` as
the opponent."* `versions/v1.0` exists, so the match is runnable.

This is the single most important item in this document. The change is plausible and carefully
argued, and none of that is a measurement. **Proposal:** run
`tools.arena_openings --opponent versions/v1.0` at 120+0.5 before the change is committed, and
append the row. If the interval straddles zero, the honest outcome is to keep the change only for
the long-game safety it buys and say so, not to claim strength.

### A2. `DECISIONS.md` documents constants that are not the ones shipping

The new entry (line ~696 onward) argues for, and concludes, `moves_to_go` **30 / 24**:

> `tools/sim_time.py` iterates the budget formula over a whole game and picks 30 / 24. ...
> **Rejected: 28 for the minimum** ... and **rejected: lowering the maximum below 30**, which the
> same simulation shows changes almost nothing once the minimum is 24, since the divisor reaches
> it after 2 × (max − min) of our moves.

The code ships **50 / 16 / 0.7**. `docs/CALIBRATION.md` lists `30 / 24 / 0.5` in its comparison
table as *"the first attempt ... the one the length data rejected"*. So within one uncommitted
change, DECISIONS records the superseded answer as the decision, and rejects nothing that was
actually rejected.

The tell is `2 × (max − min)`: that is the arithmetic of the **halving** decay (`k // 2`), which
this change removes. With `decay = 0.7` the divisor reaches its minimum after `(max − min) / 0.7`
of our moves — 49, not 12. The paragraph was written against the first attempt and never rewritten.

**Proposal:** rewrite the paragraph against 50 / 16 / 0.7, and record 30 / 24 as the rejected
alternative it now is — the repo's decision format wants exactly that.

### A3. The platform log is attributed to two different builds

- `docs/CALIBRATION.md:40` — *"first platform measurements, from rated rounds 67, 68 and 69
  **(build v0.2.1)**"*
- `docs/DECISIONS.md:702` — *"The platform's log for **v1.0** shows per-move times in two lumps"*

Same four rated games, two builds. `handoff/FINDING-flagging.md` settles it: it analyses rounds
67–70 and notes that `timing.py` *"is byte-identical in v1.0 ... so the flaw shipped unchanged into
the compiled engine"* — which only needs saying if those games were played by the **interpreted**
build. So DECISIONS is wrong.

This is not cosmetic. The bimodal per-move times (1.5–3.0 s / 8.9–10.1 s) and the "4–5x per depth"
iteration ratio are the entire evidential basis for replacing `next_iteration_fraction`, and both
were measured on an engine that runs ~16x slower with a different Python/compiled split. The
conclusion may well survive — iteration costs grow geometrically in both — but the document must
say which engine produced the numbers.

**Proposal:** correct DECISIONS to v0.2.1, and state explicitly that the ratio is assumed to carry
over to the compiled build, with `iteration_ratio_min/max` as the guard if it does not.

### A4. `weights/PROVENANCE.json` does not satisfy brief §10, and it is the only provenance that ships

Brief §10 governs both provenance files and is explicit:

> `docs/PROVENANCE.md` (human-readable) and `weights/PROVENANCE.json` (machine-readable, ships)
> record for **every** parameter, table and weight file ... Piece values, PSTs, evaluation weights,
> search margins (null-move R, LMR table, futility margins, aspiration window), time-management
> constants, TT size: **all of them**.

`docs/PROVENANCE.md` is close to compliant: 34 rows, covering the null-move, LMR, futility,
aspiration, delta and cache constants. **`weights/PROVENANCE.json` has 16 entries and every one is
an evaluation table** — `piece_values_mg/eg`, the fourteen `pst_mg.*` / `pst_eg.*` arrays,
`phase_weights`, `mopup`. No search margin, no time-management constant, no TT size.

`docs/` never ships. So the zip contains exactly one provenance artefact, and it is the one missing
the constants a judge is most likely to challenge — `NULL_MOVE_BASE_REDUCTION`, `LMR_REDUCTION`,
`FUTILITY_MARGINS`, `ASPIRATION_WINDOW`, `DELTA_MARGIN`, `EVAL_CACHE_MAX_ENTRIES`,
`TT_CLEAR_FRACTION` and the whole of `TimeParams`. Those are precisely the numbers that look copied
from another engine if nothing says where they came from, and answering that is what the log is
for. Roughly 18 of the MD's rows have no machine-readable twin.

**Proposal:** extend `tools/gen_pst.py`'s record writer, or add a sibling generator, so the shipped
JSON carries the same rows as the MD. **Sequencing:** the `TimeParams` values are being changed
right now by the timing work in A1–A3, so the time-management entries must be filled from the final
constants, not today's. The search margins and TT size are stable and can be written immediately.

Related, cheap, and worth doing at the same time: `gen_pst.py` stamps the **running** HEAD into
`pst.json`'s header, so re-running it to verify always produces a two-line diff (`git_commit`,
`date`) even when nothing changed. A future checker could read that as the weights having drifted.
`docs/PROVENANCE.md` should say: verify by diffing the tables, not the file.

**Verified sound, for the record:** the existing attribution holds. Every JSON entry cites
`tools/gen_pst.py @ 4109710`, and that generator was modified afterwards (`2856138`, "weights
unchanged"). Re-running HEAD's generator reproduces `weights/pst.json` with every table
byte-identical — only the header stamp differs. So the claim is true and the "deterministic and
re-runnable" rule holds under the check a judge would actually run.

---

## B. Claims that do not survive checking

### B1. The settling-clock argument mixes the old and new overhead, and rejects the shipped value

`DECISIONS.md` rejects `moves_to_go_min = 12` with:

> the clock settles at `moves_to_go_min × (1 − increment_fraction) × increment_ms + overhead_ms`,
> which at 12 is 1.35 s ... and at 24 is 2.45 s

The formula is right (steady state is where a move's spend equals the 0.5 s increment). The
arithmetic is not self-consistent: `12 × 100 + 150 = 1350` uses the **old** `overhead_ms = 150`,
while `24 × 100 + 50 = 2450` uses the **new** 50. One sentence, both values.

Worse, applied to the shipped `min = 16` it gives `16 × 100 + 50 = 1650 ms` — **exactly
`panic_ms`**, the threshold below which `agent.get_move` skips the engine entirely. By the
criterion this paragraph uses to reject 12, the shipped constant lands precisely on the line.

It survives in practice because a move really spends ~0.70 of its soft budget, which puts the true
settling point near 5.1 s — and `tests/test_timing.py::test_default_params_match_design` now
asserts exactly that, with the `usage = 0.70` factor in it. So the test is right and the prose is
wrong.

**Proposal:** restate the criterion in DECISIONS in realised-spend terms, the way the test does.
As written it is an argument against the change it accompanies.

### B2. The `next_iteration_fraction` fallback is not the rule it is said to be

`timing.should_start_next_depth`, fallback branch:

```python
return elapsed_s < params.next_iteration_fraction * target
```

`target` at that point is already `soft_s × 1.35`, and may have been multiplied again by
`unstable_factor` (1.5) or `easy_factor` (0.7). So the fallback threshold is **0.61 × soft**
normally, and up to **0.91 × soft** on an unsettled root — not 0.45 × soft.

Three documents call it the old rule:

- `timing.py`: *"fall back to the fixed fraction that preceded this rule"*
- `CALIBRATION.md`: *"The fraction remains as the fallback"*
- `DESIGN.md` pseudocode: `elapsed_s < next_iteration_fraction * target`  (this one is accurate)

**Proposal:** pick one. Either apply it to `soft_s` and the claim becomes true, or keep the code and
stop describing it as the preceding rule. The branch only fires when an iteration took under 1 ms,
so the behavioural stake is small — the stake is that the docs say something checkably false.

### B3. The same measurement has two sample sizes

| where | sample |
|---|---|
| `timing.py`, `iteration_target_factor` comment | "measured over **ten** middlegame positions" |
| `docs/PROVENANCE.md`, same constant | "**6** middlegame positions from `data/pgn`" / "the same six positions" |
| `docs/CALIBRATION.md` | "Measured on **ten** middlegame positions from `data/pgn`, **6** positions at 120 s and 20 s" — both, in one sentence |

**Proposal:** state the real n once, and say how many positions × how many clocks the table
averages over. PROVENANCE is the file that has to be right here.

### B4. `CALIBRATION.md` says the speed factor is unmeasured, 10 lines above the measurement

Line 35: *"Platform node rate ÷ local node rate: **not yet measured** (needs the first validation
log)."* Line 45, same file: *"platform is **2.3x slower**."*

**Proposal:** replace the stale section with the measured factor, and note the build it came from
(see B5).

### B5. The 2.3x factor was measured on the interpreted engine and is used on the compiled one

Every platform/local pair in the CALIBRATION table — 21.6–27.3k vs ~55k nps, depth 5–8 vs 8–9 — is
build v0.2.1. The factor derived from it is then used to convert platform time to local time for
the **compiled** engine, in `handoff/FINDING-king-safety.md` ("platform-equivalent divides that
clock by the 2.3x speed factor") and implicitly throughout the new timing work.

The interpreted engine's speed is dominated by the Python interpreter; the compiled one's is not.
There is no reason the same ratio holds, and it has not been checked. The king-safety document is
the only place that flags this, in its caveats; `CALIBRATION.md`, where the factor lives and where
people will read it, does not.

**Proposal:** carry the caveat into CALIBRATION beside the factor, and re-measure it from the next
v1.0 rated log — step 3 of that file's own procedure already describes how.

---

## C. Format and hygiene

### C1. `RESULTS.md`'s newest rows will not render, and the cause is systemic

The four `v1.0-vs-sf*-real` rows are appended after a prose paragraph with no table header above
them, so Markdown renders them as literal text. Not a one-off: `arena_openings.append_results_row`
does `with path.open("a")` and writes to end-of-file, so a row lands wherever the file happens to
end. Lines 52–54 have the same defect, stranded under a 3-column table.

**Proposal:** have `append_results_row` insert under a named anchor (a `<!-- arena-rows -->`
comment or the `## Match results` heading) instead of appending to EOF, and re-file the orphaned
rows under the header at line 18. This is a five-line change in the tool and it stops the file
degrading with every future match.

Minor, same file: `v1.0-vs-sf1800-real` has `-` in the Elo column where the other three have a
figure — worth a word in the row, since a reader will assume it failed rather than saturated.

### C2. `make check` is red on `main`

8 ruff errors, all in `handoff/probe.py` (committed in `d7eefa0`): four unused `# noqa: E402` and
four lines over the 100-char limit; `ruff format --check` also wants to reformat it. mypy is clean
(50 files).

`handoff/` never ships, and mypy's `files` list already excludes it. **Proposal:** either add
`handoff` to ruff's `extend-exclude` beside `docs` — consistent with mypy, one line — or wrap the
four FEN lines and drop the four dead directives. Prefer the exclude: the directory is scratch by
design and will keep collecting probes.

### C3. `PROVENANCE.md` documents a mechanism that was deliberately removed

The `feature_flag` row describes `LETAL_NULL_MOVE`, `LETAL_LMR` etc. Verified: `grep feature_flag
mikhail_letal/ agent.py` is empty. It survives only in PROVENANCE, DESIGN and DECISIONS. The row is
false as a description of what ships. (Found by `chessathon-5a`; confirmed here.)

**Proposal:** delete the PROVENANCE row; keep the DECISIONS mention, since *why they were removed*
— the shipped engine must not read variables the platform does not set — is a decision worth
having on record.

---

## D. A correction to the handoff I was given

`handoff/CODE_AND_FORMAT.md` lists `README.md` among four documents that "still say roughly 2050
Elo, 50,000 nodes per second and depth 9". **README does not have that defect.** Lines 7–17 label
2050 / 50k nps / depth 9 explicitly as *the interpreted build (v0.2)*, give the compiled build
separately at 700,000–900,000 nps and depth 12, and then say outright that no rating is claimed for
the compiled build. That is the correct treatment and should not be "fixed".

The real defect in those lines is different and smaller: **neither node-rate figure names the
machine.** "On one core it searches over 50,000 positions per second" reads as the competition
core, and the competition core is ~2.3x slower. The repo now carries three node rates for the
compiled engine — 700–900k (README, dev box), ~1.0–1.08M (`FINDING-king-safety.md`, a faster Mac)
and 330–460k (platform) — which are consistent only once you know which machine each came from.

**Proposal:** put the machine in the sentence in README, and give the platform figure, since that
is the one that decides games.

`docs/SUBMISSION_GUIDE.md` and `docs/PLAN.md` *do* have the defect as described — the guide still
names v0.2.1 as the build to upload, which is the one that matters most before Thursday.

---

## E. Smaller code observations, for whoever owns `timing.py`

- **`iteration_times[0]` is not an iteration time.** `iteration_start = start` is set before the
  loop, so the first entry includes root move generation and setup. It is the denominator of the
  first measured ratio, which is therefore biased low, making the engine slightly too willing to
  start depth 3. Bounded by `iteration_ratio_min`, so the effect is small — but the docstring says
  "how long each completed depth took", and for the first entry that is not true.
- **`panic_ms`'s comment overstates its provenance.** *"Deliberately left at the value the platform
  measured under v1.0"* — 1650 was never measured; it was `overhead_ms + floor_ms` under the old
  overhead. CALIBRATION's phrasing, "kept at v1.0's value", is the accurate one.
- **The `moves_to_go` derivation checks out.** `0.7 × 68 ≈ 47.6 → 50`, decay `0.7`, floor
  `0.7 × 24 ≈ 16.8 → 16`, minimum reached at move 49 — all internally consistent, and the code's
  `int()` truncation matches the test. The derivation does ignore the `+ 0.8 × increment` term,
  which is an approximation rather than an error, and worth one clause in CALIBRATION.
- **The `should_start_next_depth` guarantee holds.** `target = min(target, hard_s)` before the
  `elapsed_s >= target` test means a `True` return does imply `elapsed_s < hard_s`, as claimed.

---

## Suggested order of work

1. **A3, A2, B1** — three prose fixes inside the uncommitted change, before it is committed. They
   cost minutes and they are the ones a judge would catch.
2. **A1** — the promotion match against `versions/v1.0`. Long-running; start it first if the machine
   is free, since everything else can proceed while it plays.
3. **C2** — one line, un-reds the gate.
4. **D (SUBMISSION_GUIDE)** — it names the wrong build to upload, three days before uploads close.
5. **B2–B5, C1, C3, E** — correctness of the record, not of the engine.
