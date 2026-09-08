# Handoff: research round 1 — external research, and a code audit that mattered more

Written 2026-09-08. Author: a research session that did web research on chess-engine technique and
then read this repo against it. Nothing in the engine was changed. No measurement was run.

Full material, kept separately because this file is the summary:

- `docs/RESEARCH.md` — the round-1 synthesis in full (~25 000 chars), plus the legality frame.
- `docs/RESEARCH-r1-raw.md` — all 48 raw findings, each with what/why/gain/cost/legality/confidence
  and **the URLs actually read**. Go here before trusting any number quoted below.

## What was actually done

Eight parallel research sweeps, each reading >=6 primary sources (Chess Programming Wiki, arXiv,
engine devlogs, TalkChess threads, open-source engine documentation), on: modern alpha-beta
heuristics; king-safety evaluation models; small self-trained NNUE and its throughput on one core;
time management; tuning methodology and test statistics; endgame/opening knowledge under
curated-FEN starts; numba performance engineering; and competition meta-intelligence. Then one
synthesis pass that ranked findings, cross-checked topics against each other, and screened each
against the competition rules. The synthesis agent also read this repo's source.

**Honest assessment of value.** The web research was largely confirmatory: reverse futility
pruning, PVS, log-formula LMR, history gravity and late-move pruning are standard Chess Programming
Wiki material. Four things earned their cost:

1. The **code audit** below — defects in this repo, not claims about chess.
2. A **folklore filter**: separating *ablation* numbers (a 3500-Elo engine at depth 25+ losing Elo
   when a feature is removed) from *addition* numbers (an engine in our band gaining Elo when a
   feature is added). Only the second kind transfers to us. Most published advice conflates them.
3. One **architecture-killing measurement**: onnxruntime per-position calls reach ~110 k evals/s
   against ~16.9 M/s for a numba incremental accumulator at N=128. That rules out an ORT-based
   learned evaluation before anyone spends a week on it.
4. The **arithmetic on our own promotion rule** (below), which we cannot currently afford.

## The code audit — five findings, each verified independently against the source

Verified by direct grep/read of the working tree at commit `074c7bb`. Line numbers as of that
commit.

| # | Finding | Evidence | Status |
|---|---|---|---|
| 1 | **The clock gate throws away half the budget.** `next_iteration_fraction = 0.45` (`mikhail_letal/timing.py:47`) multiplies `soft_ms` at `agent.py:114`, so no new iteration starts after 45% of the soft target. At a 131 s clock the soft target is ~3.4-3.7 s but the engine stops deepening at ~1.65 s. This is the mechanism behind the round-70 loss where 90 s of 131 s went unspent. | `timing.py:47`, `agent.py:114` | **VERIFIED** |
| 2 | **LMR is a stub, not a tuned feature.** `LMR_REDUCTION` is a flat constant `1`, applied at `fastsearch.py:905` to quiets after `searched >= 3` at `depth >= 3`. No depth x movecount table, no history term, no improving flag, captures never reduced. At depth 12 with 25 quiets a log formula reduces 3-4 plies; we reduce 1. | `fastsearch.py:141,905` | **VERIFIED** |
| 3 | **PVS is absent.** No zero-window scout anywhere in `fastsearch.py` or `search.py`; every move is searched with the full `(-beta,-alpha)` window, including LMR re-searches. | grep for zero-window/scout patterns in `fastsearch.py` returns 0 | **VERIFIED** |
| 4 | **Futility pruning runs after `make_move`.** At `fastsearch.py:885-893` the move is made, then the futility test fires, then it is unmade — so every pruned move pays a full make/unmake, piece-list splice and Zobrist update and returns nothing. The comment explains why (so "no legal move" below still means mate or stalemate). The fix is to gate the prune on `searched > 0`: once one legal move exists, no further make is needed to know the node is not mate. | `fastsearch.py:885-893` | **VERIFIED** |
| 5 | **History has no malus and no gravity.** `value = history + depth*depth`, clamped to `_HISTORY_MAX` (`fastsearch.py:589-590`), cleared each move (`:1037`). Quiets that failed are never punished, so the table only learns positives and saturates toward the clamp. | `fastsearch.py:589-590,1037` | **VERIFIED** |

Also absent and confirmed by grep: **reverse futility pruning / static null-move pruning**. Forward
futility exists (`FUTILITY_MARGINS = (0,150,300)`, depth<3, in the move loop); the static
`eval - margin*depth >= beta` cutoff above the null-move block does not.

### Two corrections to claims made during this round

- **"The engine has no king-safety term" is wrong.** `W_KING_SHIELD = 7` exists
  (`mikhail_letal/fasteval.py:77`) and is applied at `fasteval.py:441` over the king file +/-1,
  ranks +1/+2, midgame only. What is missing is the **attacker side** (enemy piece proximity /
  attack counts) and the **non-linear map**. Mobility is genuinely absent. Treat this as
  "half a king-safety term", not "none".
- **A build lock of "Sep 11 11:00" was asserted by the synthesis and is UNVERIFIED.** That date
  appears nowhere in this repo. The synthesis used it to scope everything to three days and to
  defer the entire NNUE programme. **If no such deadline exists, that deferral should be
  reconsidered.** Confirm the real deadline before accepting the round's prioritisation.
- `TT_BITS = 21` was claimed but grep did not locate that definition. Unverified.

## Ranked actionable list, as the synthesis left it

Ordering is by expected Elo / (cost x risk) **for this engine at ~700 knps and depth 10-14**, not
in general. The important structural point: **items 2-4 and 6 are falsifiable by node counts at
fixed depth across the 219 curated openings in `data/openings.txt` — a deterministic measurement
that needs no games and costs minutes.** Only item 1 requires real-TC games to see at all.

1. **Open the time gate.** `next_iteration_fraction` 0.45 -> ~0.70, and consider
   `moves_to_go_max` 40 -> 30 (`timing.py:37`). Three independent derivations in the packet — a
   pool recurrence fixed point, moves-to-go arithmetic, and six observed platform opponents at
   1.8-4.7 s/move — all converge on 3.2-3.5 s/move at move 1 of 120+0.5, which is what our own
   soft target already computes. The risky half of a time change (aborting mid-iteration and still
   returning a trustworthy move) is already implemented (`_partial_move`).
   *First experiment:* change the constants, add one stderr CSV line per move
   (`ply,clock_in,soft,hard,elapsed,depth,nodes,nps`), run `tools/arena_openings.py` vs
   `versions/v1.0` at **real 120+0.5**. *Falsified if:* mean elapsed does not rise above ~2.5 s
   (something other than the gate is terminating the search — find it first); or any move exceeds
   `hard`; or any game is lost on time.
   *Caveat the synthesis raised against itself:* the "+90 to +180 Elo" figure assumes EBF ~ 2.0.
   With flat LMR, no LMP and no PVS our EBF is plausibly 3-5, in which case 3.4x the time buys
   ~0.9 plies rather than 1.8. Quote **+40 to +70**, and measure real EBF from nodes-per-depth.
2. **Reverse futility pruning.** ~6 lines above the null-move block, reusing the already-computed
   `_cached_eval`: `if depth <= D and not in_check and not mate_bounds: e = eval; if e - M*depth >=
   beta: return e - M*depth` (fail-soft). Best *addition* number in the packet from an engine in our
   band: Blunder (~2600, 10+0.1) measured **+57.1 +/- 16.9, SPRT accepted**. Fires in the last 4-8
   plies, so it is not a deep-search-only feature. Expect null-move cutoffs to fall — that is
   correct, not a bug, since both gate on `eval >= beta`.
3. **A real LMR table.** Generate `_LMR[d][m]` at import from `r = A + ln(d)*ln(m)/B` — write the
   generator in `tools/` like `gen_pst.py` so provenance is a formula, not a table. Then the cheap
   context terms: `+1` when not improving, `-history//HDIV`, and reduce late captures with negative
   SEE (SEE already exists for quiescence). Sweep `A in {0.5,0.75,1.0}`, `B in {2.0,2.25,2.5}` on
   fixed-depth node counts. *Falsified if:* nodes-to-fixed-depth does not fall by >=25%.
4. **Hoist the futility prune before `make_move`, then add late-move pruning.** The hoist makes
   existing futility pruning actually cheap and is the precondition for LMP being worth anything.
   Then `if quiet and depth <= 6 and searched >= (C0 + C1*depth*depth)//256: break`, with separate
   improving / non-improving constants. Blunder measured LMP as an addition at **+21.9 +/- 11.4**.
5. **Add the attacker side of king safety, with a convex map.** Do *not* build a full attack map.
   The attack-free construction: `danger = sum over enemy Q,R of (7 - chebyshev_dist(sq, ksq)) *
   w_piece + w_f * (semi-open files among king file +/-1) + w_s * (3 - shield pawns)`, gated on
   *enemy has a queen* and >=2 attackers, then `mg -= danger**2 // K`. Three independent engines
   converge on exponent ~2 in midgame, linear or zero in endgame. This replaces the linear
   `W_KING_SHIELD` form rather than adding to it.
   **The trap, documented three times independently:** naive Texel-tuned king safety measured
   **-8 to -10 Elo** (TalkChess), Leorik shipped 2.2 without it because MSE improved while Elo did
   not, and iCE measured only **+5 +/- 4 over 16 000 games** for *re*-tuning a working one. The
   diagnosed cause each time was tuning on a position set with no attacking positions — which is
   exactly what a balanced arena set is. Prescription: parameterise with 3-4 scalars, never expose a
   free 64-entry table to a tuner, hand-set the weights first (queen 12, rook 3, **minors 0** —
   MadChess's tuner independently drove minors to zero), measure on the **Sicilian/French subset**
   of the 219 openings separately from the full set, and do not tune it under time pressure.
6. **PVS, and history gravity + malus.** PVS: `(-alpha-1,-alpha)` scout for every move after the
   first, full re-search on `alpha < score < beta`. ~10 lines, no new state, typically 5-15% fewer
   nodes. History: switch to gravity `v += b - v*abs(b)/MAX` with `b = min(1536, 16*d*d)` and apply
   a malus to every quiet already tried at a node that fails high. *Falsified if:* PVS does not cut
   nodes — which would mean move ordering is bad enough that the scout re-searches constantly, so
   fix ordering first.

**Just below the line:** internal iterative reduction (3 lines, ~5-10 Elo, zero risk); razoring
(3 lines); material-keyed endgame scale factors (opposite-coloured bishops ~1/3, lone minor = 0,
rule50 decay — real value but ~90 lines and 5 constants to tune).

**Deferred, with reasons:** NNUE (largest single item available, +200 to +360 in comparable
engines, and the numba throughput result says it is feasible — but it is a multi-week programme:
data generation, trainer, incremental accumulator, quantisation, lazy updates); singular extensions
and ProbCut (scale with depth; worth 3-8 Elo at depth 10-14); correction history and continuation
history (both need a per-ply search stack — but note the static-eval half of that stack is a single
`int32[MAX_PLY]` array and is needed for `improving` and for RFP anyway, so build that half now);
5-man Syzygy (+2 +/- 2, and it does not fit); contempt; opponent modelling; bitboard rewrite.

## Cross-topic signals worth keeping

- **Eval beats search roughly 3:1 in our strength band, from two directions.** MadChess's
  per-release ladder from 2100 to 2513 sums to +321 Elo of evaluation work against +96 of search
  refinement; independently, the search sweep conceded that its expensive items scale with depth.
  Both say: king safety before singular extensions.
- **Four deferred search features share one piece of plumbing** (a per-ply stack carrying static
  eval and (piece, to-square)). Build it once and the marginal cost of all four collapses.
- **Our promotion rule is currently unaffordable.** A 120+0.5 game is ~5 min of one core; a
  +/-10 Elo confidence interval needs ~3 900 games, which is ~27 hours of the whole machine. At
  10+0.1 the same interval costs ~3 hours. The synthesis recommends moving *development and
  acceptance* to 10+0.1 with paired colour-reversed openings and pentanomial variance, reserving
  real TC for item 1 (which fast TC cannot measure at all) and for one final confirmation of the
  frozen build. **This is a deliberate relaxation of a rule in CLAUDE.md and belongs in
  `docs/DECISIONS.md` with the arithmetic, dated — not quietly adopted.**
- **A time-management scaler contradicted itself in its own source:** Triumviratus's TMv2 measured
  **+23.8 +/- 18.2 at 20+0.2 and -22.9 at 10+0.1** in the same period. Treat best-move-stability
  scaling as unproven, distinct from item 1 which is a bug fix.
- **The 4.3 MB in `tb/` may be doing nothing.** 3-4 man Syzygy probes cost ~41 us through
  python-chess (~94 us on-platform, ~66 nodes of search) and the jitted search cannot call them
  without an objmode round trip. This is an audit item: instrument probe count and total probe ms
  per game before deciding.
- `data/openings.txt` already holds 219 scraped curated FENs, so the "find the opening set" task is
  already done.

## Legality

Re-fetched 2026-09-08 from `aichessathon.com/docs/rules.md` and `/docs/agent-contract.md`.
**Nothing in the ranked list above is near the line.** All items are published techniques
reimplemented in our own code with constants we derive — hence the instruction to generate the LMR
table from a formula in `tools/`, as `gen_pst.py` does for the PSTs.

Worth recording because it is wider than the CLAUDE.md summary suggests: the rules state training
data is **"unrestricted, including positions annotated by an existing engine"**, and that training
our own network on engine-labelled positions is allowed. What is banned is shipping a third-party
engine or "any port or translation of one", shipping "a database of another engine's moves or
evaluations ... for lookup at runtime", shipping a published network (including fine-tuned or
re-exported), obfuscation, native binaries, network calls and subprocesses.

The sharp edge, and this repo's own stricter rule: **a tuned constant table lifted verbatim from
another engine's source is data, not an idea.** So any technique that depends on a table is only
actionable once we know how to derive or tune that table ourselves.

## Independent verification (second session, 2026-09-08, at `074c7bb`)

Re-checked against the source rather than taken on trust. **Four of the five audit findings
confirmed; two of the round's own caveats are resolvable and are resolved here.**

| claim | result |
|---|---|
| 3. PVS absent | **confirmed** — zero matches for any zero-window/scout pattern in `fastsearch.py` |
| 2. LMR is a flat constant | **confirmed** — `LMR_REDUCTION` imported as a scalar, no table |
| 4. Futility fires after `make_move` | **confirmed** — `make_move(...)` then the futility test then `unmake_move(...)`, exactly as described. The proposed `searched > 0` gate is sound |
| 5. History has no malus or gravity | **confirmed** — `value = history + depth*depth`, clamped, never decayed, never punished |
| 1. Clock gate | already agreed and in flight on the other side |

**Correction 1 — the deadline is real, so the NNUE deferral stands.** The round flagged the
"Sep 11 11:00" lock as unverified and said the deferral "should be reconsidered" if no such date
existed. It exists: `docs/PLAN.md:3` — *"Uploads close Thursday 11 September, 11:00 London."*
`docs/SUBMISSION_GUIDE.md` repeats it. **Open question 1 is closed and the round's prioritisation
holds.** Do not restart the NNUE programme on the strength of that caveat.

**Correction 2 — `TT_BITS` is 21, at `mikhail_letal/fastsearch.py:169`.** The round reported the
definition as not locatable. It is there. Whether the table is being overwritten inside a single
search (open question 5) is still open and still worth instrumenting.

**On "the engine has no king-safety term":** that phrasing came from this session and the
correction is fair, though what was actually written in `handoff/FINDING-king-safety.md` was
narrower — that `W_KING_SHIELD` is the *only* king term and there is no king-*danger* term. The
substance is unchanged and the research's "half a king-safety term" is the better phrase. Note also
that this session's node-rate costs for king-safety variants (-16 % to -26 %) were measured on the
**interpreted** engine and largely do not transfer: an evaluation costs 8.3 us there and ~204 ns
compiled. Those numbers should not be used to reject the attacker-count design.

**Cheapest next measurements**, both deterministic and needing no games: the futility hoist (same
tree, strictly less work per pruned node — measurable as wall time at fixed depth) and PVS
(measurable as nodes to fixed depth). Either is falsified in minutes across `data/openings.txt`.

## Open questions round 1 could not answer

1. What is the real deadline? The "Sep 11" lock is unverified and it drove the whole prioritisation.
2. What is this engine's actual effective branching factor? It decides whether item 1 is worth
   +40 or +180, and it is measurable from nodes-per-completed-depth in one instrumented run.
3. Are the shipped tablebases ever probed in a real game, and at what total cost?
4. Does the 10+0.1 proxy correlate with 120+0.5 for *this* engine? One paired experiment would tell
   us, and every acceptance decision afterwards depends on the answer.
5. Is `TT_BITS` actually 21, and is the table being overwritten inside a single search?
