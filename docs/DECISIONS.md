# Decisions

Every design decision, the alternative rejected, and why. Newest at the bottom. Dates are London
time.

## 2026-09-06 — Repository is a direct clone of upstream, not a fork

The brief assumes a fork. Claude cannot create a fork under the operator's GitHub account (never
touches the operator's accounts), so the repo is a clone of `advitrocks9/aichessathon-starter`
with the starter as the `upstream` remote. At the operator's request (6 Sep, evening) a private
GitHub repository `urvancev06/chessathon` was created with the `gh` CLI and is `origin`; commits
carry the operator's identity and no co-author trailer.

## 2026-09-06 — Engine name "Mikhail LeTal", package `mikhail_letal`

Chosen by the operator (a pun on Mikhail Tal). Python packages must be lowercase identifiers, so
the folder is `mikhail_letal`; `ENGINE_NAME = "Mikhail LeTal"` is the display name. Verified
that `import mikhail_letal` fails on the bare interpreter and the name is not in
`sys.stdlib_module_names`, so the zip-first `sys.path` cannot shadow anything. Rejected: `ferz`
(Claude's first pick, replaced at the operator's request), anything generic like `engine` or
`chess_engine`.

## 2026-09-06 — Stage 0 is a python-chess engine, not a numba engine

Alternative: go straight to the numba engine (Stage 1). Rejected because the brief's first
priority is a valid, non-flagging submission from the first session; python-chess provides a
proven legality oracle and rules implementation, so Stage 0 correctness risk is confined to our
search, evaluation and time management. Stage 1 replaces the hot path and keeps python-chess in
the wrapper as the oracle.

## 2026-09-06 — Position keys are python-chess's `_transposition_key()`

Alternatives: Zobrist hashing via `chess.polyglot.zobrist_hash` or our own Zobrist. Rejected for
Stage 0: `zobrist_hash` walks every piece (slower), and our own Zobrist needs incremental update
inside python-chess's push/pop which we do not control. `_transposition_key()` is a tuple of the
bitboards plus turn, castling rights and en passant square; it is exactly what
`Board.is_repetition` uses, so our repetition detection agrees with the referee by construction.
It is a private name, so a python-chess upgrade could break it; the platform pins 1.11.2, which
has it. Stage 1 replaces it with our own Zobrist keys inside the jitted engine.

## 2026-09-06 — Transposition table is a Python dict with a hard entry cap (Stage 0 only)

The brief's §6.4 asks for fixed-size numpy arrays; that belongs to the numba engine. In pure
Python a dict is far faster than numpy indexing per probe. The cap (`tt_max_entries`) bounds
memory; when reached the table is cleared, which is crude but safe (the alternative, an aging
replacement scheme, is Stage 1 work). Memory is measured, not assumed (see RESULTS.md).

## 2026-09-06 — Piece-square tables come from a parametric geometric prior, never from memory

Risk: a language model writing an engine may reproduce tables it has seen (Sunfish's tables are
famous and Sunfish is a house bot). Decision: `tools/gen_pst.py` computes every entry from named
geometric formulas (centrality, advancement, shelter squares) with a small parameter dict, prints
the tables for inspection and records provenance in `weights/pst.json` and
`weights/PROVENANCE.json`. Piece values start at the textbook 100/320/330/500/900 and are
recorded as textbook values. Any later tuning (Texel, Stage 2) records script, data hash and run.

## 2026-09-06 — Mop-up term instead of tablebases in Stage 0

KX-vs-K must convert without Syzygy. The term rewards pushing the bare king to the edge (its
centre-Manhattan distance) and bringing our king close (14 minus the king distance); the two
weights are ours (`mopup` in `pst.json`). The idea is textbook geometry; the constants were chosen
by us and are not copied. Syzygy 3–4-man is a Stage 2 experiment with its own arena run.

## 2026-09-06 — Two-fold repetition in search is scored as a draw

A search node whose position has occurred before (in the game history from the first FEN, or on
the current search path) scores `DRAW_SCORE`. This makes the engine avoid repeating when its
evaluation says it is ahead and seek repetition when behind, with no separate root rule.
Alternative rejected: only detect true threefold — it wastes the search's ability to steer away
before the third occurrence and is what loses won games in shuffling endgames.

## 2026-09-06 — No null-move pruning or late-move reductions in Stage 0

Both are on the Stage 1 list. Stage 0 optimises for correctness and a measured baseline; every
pruning technique will be added as a separate experiment with an arena result, so the report can
show what each one is worth here.

## 2026-09-06 — Time budget formula and constants are the brief's §6.2, uncalibrated

`overhead_ms = 150` and the other constants are the brief's initial values, held in one dataclass
(`TimeParams`). They are replaced after the first validation log per `docs/CALIBRATION.md`.

## 2026-09-06 — Test suite uses pytest (dev dependency only)

Added `pytest` to the `dev` dependency group in `pyproject.toml` via `uv add --dev`. Nothing in
`tests/` or `tools/` ships. `[tool.mypy] files` was extended to `mikhail_letal`, `tools` and
`tests` so `make gate` type-checks everything we write.

## 2026-09-06 — Opening collection is light-touch and cached

`tools/collect_openings.py` follows the brief's §7.1: one request per second, descriptive
User-Agent, stop on the first error, only paths `robots.txt` allows, every page cached under
`data/cache/` so the run happens once. Sampled ~80 of the 335 teams and capped game pages at 400.

## 2026-09-06 — Parallel development by several agents against a written contract

Stage 0's five modules were written concurrently by separate agents from `docs/DESIGN.md`, then
integrated and reviewed. The contract is the reason the pieces fit; any later change to a
signature is made in DESIGN.md first.

## 2026-09-07 — A local web app (`tools/webapp/`) for playing, spectating and reading the docs

The operator asked for a site to try the engine and read everything about it. A hosted static
page cannot run a Python engine, so the app is a local server (standard library `http.server`,
python-chess, and `harness.sandbox`/`harness.rules` used as a library) with a vanilla HTML/CSS/JS
front end that works offline. It lives under `tools/`, so it never ships. Decisions inside it:

- **The engine is played through the platform's own runner.** Each game starts the agent with
  `harness.sandbox.local`, times moves on wall time, adds the increment after the move, suspends
  the process while the human thinks, and applies the referee's termination order. What the
  operator sees in the app is what the ladder sees. Rejected: importing `agent` in-process
  (module state would leak between games and timing would not match).
- **Engine calls never run inside an HTTP request.** Init and moves run on background threads
  and the browser polls the game state every 500 ms, so a 120 s think cannot block the server.
- **Stopping a game mid-move kills the agent's process group directly**, then runs the sandbox's
  `stop()`; calling `stop()` from another thread races with the in-flight `move()`.
- **Log capture reads the sandbox's kept-stderr view** after each move (the same 4 KB head + 4 KB
  tail the platform keeps), so the thinking panel shows exactly the lines the validation log
  would show.
- **The human clock is informational.** It is counted in the browser and written to the PGN but
  never enforced; the app is a playground, not a referee for the human.
- **Visual direction (operator's instruction):** near-monochrome, hairlines instead of cards, one
  muted brick accent, flat grey board, solid Unicode glyphs for both colours styled with CSS, no
  external fonts or libraries. A Claude Design brief with an identity/logo section was written for
  the operator to refine the look further.
- The web app was built in a separate git worktree on branch `webapp` while the engine was being
  built, then merged; the only conflict was two appended `.gitignore` lines.

## 2026-09-07 — Stage 0 review: what was changed and why

A six-lens adversarial review (legality, search correctness, time/flag risk, memorised code,
performance, draws/endgames) with three independent refuters per finding. Each item below names
the evidence that decided it. Items A–J were decided by the orchestrator; K–M were verified
performance/correctness findings.

- **A. `NODE_CHECK_INTERVAL` 1024 → 128.** `perf_counter` costs ~60 ns; nps is unchanged at
  128; the 1024-node chunk let the search overshoot the hard deadline by 25 ms on average and
  65 ms at worst locally, about 3× that on the platform's slower core.
- **B. Int-only transposition-table entries, cap 400k → 250k, clear above 60 % between moves.**
  `chess.Move` has no `__slots__`; a 270k-entry table of them made CPython's gen-2 garbage
  collections stall a single node for 143 ms (measured, 60 s search; the reviewer saw 105–175 ms),
  invisible to the clock check. With `(depth, score, flag, move_code)` the worst gen-2 pause in
  the same search is 13.7 ms, RSS at the cap is 120 MB, and nps rose from 50.3k to 62.7k on that
  position. The start-of-search clear keeps the cap-hit clear (kept as the backstop) from landing
  mid-iteration.
- **C. Urgency near the draw deadlines.** `budget()` takes `plies_to_cap` (always) and
  `fifty_move_room` (only in a pawnless mop-up) and clamps `moves_to_go` to the moves left before
  the nearer deadline. The reviewer drew two won KQ-vs-K games by the fifty-move rule and the
  600-ply cap because the engine kept its normal budget while the deadline was 9–10 moves away.
  Rejected: a search-side "contempt" for rule draws — it does not buy the time the mate needs.
- **D. Root tie-break when every move scores the rule draw.** With the draw inside the horizon
  all root moves score 0 and the search chose arbitrarily. If the root static evaluation says
  we are ≥ 300 ahead and ≥ 2 moves tie at 0, the move whose child evaluates best is chosen
  (stalemates excluded). After C and D the 600-ply case (`8/8/8/3K4/8/8/8/q6k b - - 0 291`)
  converts (mate in 17 plies); the fifty-move case (`8/8/8/8/3k4/8/8/4KQ2 w - - 82 60`) still
  draws at 5 s per move — the engine now drives the king to the edge and is two moves from
  mate when the clock runs out, but the tablebase mate (13 plies, with 18 of room) is beyond a
  depth-6 horizon and the slack is spent on non-optimal progress. Said plainly: not converted
  at that clock. At 5 s the hard limit (a quarter of the clock) caps every move at 1 250 ms, so
  item C cannot add time there; at the real 120 s clock it can. See RESULTS.md.
- **E. Graph-history mitigation.** A node whose value came from a repetition along the current
  line is not stored with its score (only its move, as a depth −1 hint). Evidence: after a
  depth-7 search of `8/8/8/4k3/8/8/8/R3K3 w` with the root on the path only, the table held a
  depth-5 LOWER 0 for `8/8/8/8/4k3/8/8/R3K3 b`, whose fresh value is −628. Draws from the game
  history are permanent within the game and are still stored; `agent.py` now calls `new_game()`
  after a desync for the same reason. Cost: 0.15 % nps (A/B, three 3 s searches each).
- **F. `Searcher` → `Engine`.** Sunfish, a house bot the organisers know by sight, also has a
  `Searcher.search(...)`. Everything behind ours is different, but the name pair was the one
  surface overlap. Whole-repo grep afterwards: only `versions/` (frozen uploads) keeps the old
  name.
- **G. Black never observes the start position.** Documented in `gamestate.py` and DESIGN.md
  and pinned by a test (Nf3 Nf6 Ng1 Ng8 ×2: referee `is_repetition(3)` true, our count 2). Benign
  because any earlier occurrence already scores a draw; the policy is kept.
- **H. Queen over under-promotion on exact ties.** The reviewer saw `b8=R` chosen over `b8=Q`
  because the table move was searched first and ties go to the first move. Fix: if the first
  root move is an under-promotion, the queen promotion of the same pawn is searched before it.
  Rejected: comparing scores at the root — later scores are only bounds under fail-soft.
- **I. Provenance.** PROVENANCE.md now states the table cap and clearing rule, the phase weights'
  origin, the generator commit (`4109710`), and rows for `MAX_PLY`, the check extension and
  `NODE_CHECK_INTERVAL`. Memorised-code check: a mechanical row-by-row comparison of
  `weights/pst.json` against the CPW "simplified evaluation function" tables finds exactly one
  coincidental row (endgame pawn on the 7th rank = 50, which is the formula 14 × 25 / 7); all
  whole-table and affine comparisons against Sunfish, CPW, Rustic Alpha 3, TSCP and VICE were
  clean.
- **J. Known limitation (docs only).** The Lucena position is not converted at 5 s per move;
  listed in RESULTS.md as a Stage 2 target.
- **K. Stand pat before capture generation in quiescence.** Captures were generated first and
  thrown away at seven quiescence nodes in ten. Search results are identical (the stalemate and
  mate guards moved with the cutoff); the reviewer measured +43 % nps in isolation, the combined
  A–M result is 51.7k → 67.2k nps on a 3 s search from the start position.
- **L. Check extension before the TT probe.** The probe used the unextended depth while the
  store recorded the extended one, so in-check nodes accepted entries one ply too shallow.
- **M. Quiescence evasions capped at four quiescence plies.** Eight queens a side made one
  depth-1 iteration cost hundreds of thousands of nodes; deeper checks now stand pat like any
  other node (33k nodes for depth 1 in that position).

Deferred to Stage 1 (larger performance refactors, not attempted here): staged move generation
(captures before quiet moves without building the full list), a custom `SearchBoard` replacing
python-chess in the hot loop, and quiescence delta pruning (a behaviour change that needs an
arena result).

## 2026-09-07 — v0.2: exact speedups first (staged move generation, evaluation cache)

Before any behaviour change, two speedups that leave the search tree identical, checked by
searching 30 positions from `data/openings.txt` (every 7th line) at `node_limit=60000` before and
after: move, score, depth, node count and seldepth were identical on all 30.

- **Staged move generation at interior nodes.** `_staged_moves` yields the table move, then the
  captures and promotions from a dedicated bitboard-masked generator (`_capture_moves`, shared with
  quiescence, which also computes the MVV-LVA key), then the two killers if `board.is_legal` says
  they are legal quiet moves here, then the quiet moves from two masked generator calls sorted by
  history. Each stage is generated only if the search asks for more moves, so a node that cuts off
  on the table move or a capture never builds or sorts its quiet moves. Every move carries a stage
  tag, which replaces the `is_capture` call at every cutoff. The exactness argument (the
  concatenated stages are a stable sort of python-chess's own generation order, and the killer,
  table and en passant duplicates are removed by integer move code) is in the docstring.
  Measured: 65.8k → 68.3k nps from the start position, 64.5k → 67.6k in the busy middlegame
  (3 s searches). Smaller than hoped: a profile shows python-chess's `push`/`pop` (~25 %), its
  generators (~30 %) and `evaluate` (~22 %) dominate, and the sorting that staging removes was a
  few per cent.
- **Evaluation cache in the searcher.** 27 % (start) to 34 % (middlegame) of the evaluations in a
  3 s search are of a piece placement already evaluated, mostly transpositions inside capture
  sequences. `Engine._evaluate` caches `evaluate` by `(six piece bitboards, white occupancy,
  turn)`, which is exactly what the function depends on, so hits are exact. `evaluate` itself
  stays a pure function (its tests and the flag toggles are unaffected). Cap 100 000 entries,
  emptied when full and by `new_game`: a 20 s search held 70k entries at 82 MB RSS. Measured with
  staging: 68k nps (start), 71k (middlegame), i.e. +3 % and +11 % over v0.1.
- Rejected: reaching into python-chess internals to avoid the second `checkers_mask` computation
  (`is_check` then the generator's own): about 5 % of node time, and it would tie the engine to
  private API.

## 2026-09-07 — v0.2: strength features, one switch each

Every feature is a module-level boolean (`feature_flag`, overridable through the environment so the
arena's `--env LETAL_...=0` can bisect a regression). Node counts below are to a fixed depth with
every other feature on, from `tools`-free scratch runs (opening = a Catalan middlegame, depth 6;
endgame = a rook ending, depth 7; middlegame = the capture-rich `BUSY_MIDDLEGAME` test position,
depth 5). The arena rows are in RESULTS.md.

- **Null-move pruning** (`NULL_MOVE_PRUNING`, R = 2 + depth // 6). Guards: not in check, not two in
  a row, a piece other than king and pawns on the side to move, no mate bound in the window, and
  the static evaluation at or above beta. A fail-high that is a mate score is not trusted. Nodes:
  opening 42.2k → 16.8k, endgame 8.1k → 5.4k. The plan said `depth >= 2`; measured, the depth-2
  null searches (a full quiescence search at nearly every node of the tree's widest layer)
  *tripled* the middlegame's nodes (45k → 127k) while saving nothing elsewhere; from depth 3 the
  middlegame costs 51k and the other savings are unchanged, so `NULL_MOVE_MIN_DEPTH = 3`. Two
  hypotheses were tested and rejected on the way: the static-eval-≥-beta guard (no node change on
  its own, kept as harmless) and path-repetition taint from null subtrees (zero tainted stores).
  A test pins the invariants: no null move is ever played from check or by a side without a piece,
  and a pawn ending searches an identical tree with the feature on or off.
- **Late-move reductions** (`LATE_MOVE_REDUCTIONS`): quiet history-stage moves after the first
  three searched moves, at depth ≥ 3, not in check, searched one ply shallower and re-searched at
  full depth if they beat alpha. Nodes: opening 21.7k → 17.0k, endgame 10.7k → 5.6k, middlegame
  156k → 130k.
- **Aspiration windows** (`ASPIRATION_WINDOWS`): ±40 cp from depth 4, ×4 on a failure, full window
  after two. Nodes: opening 73.5k → 17.0k, endgame 13.6k → 5.6k; in the middlegame the window
  costs (92k → 130k, several re-searches). The abort salvage (`_partial`) is set only by root
  moves that beat the window's alpha, because a fail-low score is an upper bound and cannot rank
  moves; the draw tie-break and the EXACT flag apply only to scores strictly inside the window.
  Tests: depths 1–3 search identical trees with the feature on or off; at depth 6 the aspirated
  search returns the same move and score as the full-window one with fewer nodes; a window of ±1
  (forcing failures) still returns the full-window result.
- **Futility pruning** (`FUTILITY_PRUNING`, margins 150/300 at depth 1/2): quiet moves of the
  killer and history stages are skipped when `static + margin <= alpha`; the table move,
  captures and promotions are always searched; off in check and with a mate bound in the window.
  A node that pruned returns `max(best searched, static + margin)` (a correct fail-soft upper
  bound) and is never mistaken for mate or stalemate. Nodes: opening 20.1k → 17.0k, endgame
  8.1k → 5.6k, middlegame 139k → 130k.
- **Delta pruning** (`DELTA_PRUNING`, margin 200): in quiescence, where the side could stand pat,
  a capture whose captured value (plus queen − pawn for a promotion) plus the margin cannot lift
  the stand-pat score to alpha is skipped. Nodes: middlegame 205k → 130k (this is where the
  quiescence tree is deep, seldepth 27), opening 19.8k → 17.0k, endgame no change.
- **Structural evaluation terms** (`STRUCTURE_TERMS`, weights in `STRUCTURE_WEIGHTS`): passed
  pawns by rank (10 mg / 20 eg per rank), doubled (12) and isolated (15) pawns, bishop pair (30),
  rook on an open (20) or semi-open (10) file, king pawn shield (10 per pawn, middlegame only).
  All bitboard arithmetic: enemy front spans by file fill and lateral shifts for passers, a south
  fill for doubled pawns, files squashed onto rank 1 and spread back with `* 0x0101…01` for
  isolated pawns, precomputed shield masks. The pawn-only part is cached by the two pawn
  bitboards. Cost 3.7 → 4.8 µs per `evaluate` (uncached), symmetric under `board.mirror()` on 300
  random positions. Each term has a test isolating it on a pair of positions.
- **All together**: depth 6 in the opening position costs 17.0k nodes against 238k with every
  feature off (14×); the endgame 5.4k against 34.9k (6×); the capture-rich middlegame 127k
  against 196k (1.5×). From the start position a 3 s search now reaches depth 9 (v0.1: depth 6).
  The node rate with the features on is lower (51k–56k nps in the 3 s benchmarks): the
  evaluation terms cost about a microsecond per evaluation, and the tree has a larger share of
  quiescence and null-move nodes; what matters is the depth per second, which rose by three plies.
- **Sanity match before the validation run**: 48 games at 3 s + 0.05 s against `versions/v0.1`,
  12 workers: +29 =8 −11, 68.8 % ± 11.9 %, Elo +137 (+48 to +248).
- **Validation** (RESULTS.md rows `v0.2-vs-v0.1-10s`, `v0.2-vs-v0.1-real`):
  - 10 s + 0.1 s, 300 games, 12 workers: **+225 =27 −48, 79.5 % ± 4.2 %, Elo +235 (95 % interval
    +193 to +285)**. The interval is entirely above zero, so nothing was bisected and every
    feature ships on.
  - Real clock 120 s + 0.5 s, 60 games, 4 workers: **+48 =6 −6, 85.0 % ± 8.2 %, Elo +301 (95 %
    interval +208 to +454)**, also entirely above zero, so the promotion rule is met at both
    clocks. The first games overlapped the tail of the 10 s run's load (load average 8.75 at
    the start, 1.80 at the end); both sides shared it equally. Lowest own clock after a move:
    3 618 ms, in a 242-ply fifty-move draw (game 24), i.e. the v0.1 time management still
    holds at the real clock.
  - Fuzz: 100 games against `baselines/random` at 3 s + 0.05 s, 12 workers: 100 checkmates,
    no other termination, so no crash, illegal move or timeout in either colour.
  - `harness.package`: passes (smoke game as Black at the real clock, depth 6–9, ~50k nps).
- Not done in v0.2 (candidates for v0.3, each to be measured the same way): tuning any of the
  hand-chosen constants above; check extensions limited by depth; a `SearchBoard` replacing
  python-chess in the hot loop (push/pop is a quarter of the node time); freezing the build
  under `versions/v0.2` once the platform upload is confirmed.

## 2026-09-07 — v0.3 candidate: Texel-style ridge fit of the evaluation weights (negative result, weights unchanged)

**Question.** Can the hand-set evaluation weights (piece values, piece-square tables, structural
terms) be improved by fitting them to an existing engine's evaluations of quiet positions, with the
rules' permission to tune on engine-labelled data and nothing of that engine shipped?

**Method** (`tools/tune_texel.py`, deterministic, seed 2026; the three steps are subcommands).
Our evaluation is linear in its weights once the position is known, so the fit is a closed-form
ridge regression: features are, per (piece, square from the owner's view, phase), the White-minus-
Black count scaled by the phase share, plus the eight structural counts; `features(board) @ weights`
reproduces `evaluate()` to within the phase blend's truncation, and `build_dataset` asserts this on
every position (the loop-based counts in the tuner and the bitboard code in `evaluation.py` check
each other). The penalty λ·‖w − w_prior‖² pulls toward the `tools/gen_pst.py` prior (now also home of
the structural prior `STRUCTURE_PRIOR`), not toward zero; the pawn's middlegame value is held at 100
as the scale anchor; λ is chosen by 5-fold cross-validation on the label MSE over
{1, 3, 10, …, 100 000}; the fit is rounded to integers and written to `weights/pst.json`,
`weights/PROVENANCE.json` and the `STRUCTURE_WEIGHTS` values in `evaluation.py`, each with the data
hashes and run id. `tune_texel.py check` (and `tests/test_evaluation.py`) refit with the recorded λ
and compare.

**Data.**
- Positions: 219 openings × 4 self-play games of `mikhail_letal.search.Engine` at 2 000 nodes per
  move, a move drawn among the near-best (within 30 cp at one ply) with probability 0.2 (seeded
  randomness in the generator only; the shipped engine has none); quiet positions only (side to
  move not in check, the engine's quiescence value equals the static evaluation, pawns on the
  board), at most 30 per game: 26 028, plus 1 065 quiet positions from the 40 archived games under
  `data/pgn/` → **25 994 unique FENs**, `data/tuning/positions.epd`, sha256
  `facd402a03ea7665623cac2b9e09d8a360eddcd468a0087dd4bf2fa80289a9d2` (876 games, 12 workers, 10 min).
- Labels: Stockfish 19 (`~/.local/opt/stockfish`, local only), depth 10, Threads 1, eight
  processes, 48 s; White-point-of-view centipawns clipped to ±1500: `data/tuning/labels.csv`,
  sha256 `947648c20c8950e7a01365af63e1c1caf352a59bddd8d29eaf95ba4a03f1554f`. Mean +52 cp, standard
  deviation 531, 390 clipped, 39 % of positions beyond ±500 — the 2 000-node games are lopsided.

**Fit.** 786 weights (10 piece values less the anchor, 768 table entries, 8 structural).
Validation MSE (cp²), 5-fold: prior 72 177 (rmse 269) → λ = 10: **53 509** (rmse 231), the minimum;
λ = 100: 55 518; λ = 1 000: 60 926; λ = 100 000: 71 025. Training MSE after the λ = 10 fit 50 418
(rmse 224.5), rounding costs 1 cp². The labels are on our scale (least-squares scale of the prior's
prediction 1.04), so this is not a units mismatch. What the fit says: piece values mg
P 100 / N 491 / B 489 / R 675 / Q 1417, eg P 122 / N 227 / B 250 / R 418 / Q 699 — pieces worth
about five pawns in the middlegame and about two in the endgame (a values-only fit with the tables
frozen gives the same picture: mg N 545, Q 1601; eg N 229, Q 642); structural weights
12/13/27/11/56/73/57/42 (prior 10/20/12/15/30/20/10/10); and large single-square entries where the
data is thin or confounded with a won position (rook on f7 mg 20 → 275, queen on h6 mg −14 → 233,
pawn on d7 eg 50 → 258, bishop on a1 mg 3 → −162). With ~20 occurrences of a rare square and label
noise of ~230 cp, a square's standard error is ~50 cp and λ = 10 shrinks it by only half.

**Arena** (`RESULTS.md`, 300 games each, 10 s + 0.1 s, 12 workers, `data/openings.txt`):
- λ = 10 (`v0.3-vs-v0.2-10s`): **+95 =26 −179, 36.0 % ± 5.2 %, Elo −100 (−140 to −62)**.
- λ ×4 = 40, the one fallback the plan allowed (`v0.3-lambda40-vs-v0.2-10s`; validation MSE 54 224,
  mg N 476 / B 478 / R 641 / Q 1310, eg Q 753, structure 12/16/24/12/54/76/59/41, largest table
  entries ~150–190): **+126 =28 −146, 46.7 % ± 5.4 %, Elo −23 (−61 to +14)**; the interval includes zero.

**Decision.** **Not promoted.** Both fits fail the promotion rule (the 95 % interval must lie above zero), so
`weights/pst.json` and `weights/PROVENANCE.json` are reverted byte-for-byte to `versions/v0.2`'s
(pst.json sha256 `b1e2f654…`), `STRUCTURE_WEIGHTS` is back at the prior, `__version__` stays 0.2.0
and the shipped evaluation is unchanged. Kept: the tuner; the position set and labels
(`data/tuning/`, 3 MB, hashes above; not in the zip, which only ever carries `weights/`); both
fit reports (`data/tuning/fit_report_lambda10.json`, `fit_report_lambda40.json`); the arena rows;
and `tools/gen_pst.py` as the documented prior, which now also holds the structural prior
`STRUCTURE_PRIOR` and writes the shipped file only with `--out weights/pst.json` (its default
output is `data/tuning/prior_pst.json`, for inspection). `tests/test_evaluation.py` accepts either
state of `pst.json` — the prior from `gen_pst.py` or a recorded `tune_texel.py` fit — and checks
that the file is reproducible from the generator its `_provenance` names; the tuner's feature
counts are tested against `evaluate()` on random positions.

**Why a better fit of the labels plays worse** (the reading, not a measurement): the objective is
the squared error in centipawns, which the lopsided positions dominate, so the fit spends its
freedom on reproducing Stockfish's scale for decided material imbalances rather than on ranking
the balanced positions a search actually chooses between; the phase-split material values make
every exchange swing the evaluation of the remaining pieces; the pruning margins (futility 150/300,
delta 200, aspiration 40, draw tie-break 300) were set for the prior's scale; and the noisy
single-square entries are actively harmful (a rook is pulled to f7 whatever stands there).
Alternatives rejected for this round and worth trying next: the sigmoid (win-probability)
objective of the original Texel method, which caps the influence of decided positions; a quieter
and more balanced position set (a higher node limit, discard labels beyond ±600); one material
value per piece shared by both phases; fewer table parameters (mirror-symmetric files); and
re-tuning the search margins together with the tables. Each would be a new experiment measured
the same way.

## 2026-09-08 — v0.3: three exact speedups (incremental evaluation, bitboard capture generator, cheap "is there a legal move")

**Question.** How much of a node is work whose answer the search already has? Three candidates,
all required to be *exact* — the search tree has to come out identical, so the only thing measured
is speed. Measured cost per node in a 3 s middlegame search before the change (wrapper timings and
`timeit` on the busy middlegame position, ~19 µs per node):

1. `evaluate()` (4.9 µs, ~0.5 misses per node) walks all 32 pieces to re-sum the
   material-plus-square tables at a position one move away from its parent.
2. `_capture_moves` (10.7 µs, ~0.5 calls per node) asked python-chess for three masked legal-move
   lists and then re-derived the attacker and the victim of every move with `piece_type_at` to
   build the MVV-LVA key.
3. Quiescence asked `any(board.generate_legal_moves())` (2.4 µs) at about a third of all nodes,
   only ever to tell a stand-pat cutoff from a checkmate or a stalemate — and the answer is almost
   always yes.

`chess.Board.push`/`pop` cost 2.3 µs of the same node, but replacing them was **not** attempted:
the components measure `_BoardState` 0.22 µs, `restore` 0.17 µs, `_from_chess960` 0.17 µs,
`is_zeroing` 0.14 µs, so a lean make/unmake that still maintains everything python-chess's
generators read (twelve bitboards, castling rights, en passant, both clocks, the state stack)
could save at most about 1 µs per node, for by far the largest correctness risk of the four. It
stays on the Stage 1 list, where the board stops being a `chess.Board` at all.

**What changed.** No search heuristic, no constant and no evaluation weight moved; `PROVENANCE.md`
is unchanged because v0.3 introduces no number that needed choosing.

- **`mikhail_letal/searchboard.py` (new).** `SearchBoard` owns the `chess.Board` the search moves
  on and keeps three integers beside it: `mg`, `eg` (the material-plus-square sums for both
  phases, from White's view) and `phase` (the raw phase weight). `push` folds the move into them,
  `pop` restores what it saved. python-chess still makes and unmakes every move and still
  generates and rules on every one. The special cases are handled explicitly — an ordinary
  capture, en passant (the victim is not on the target square), a promotion (the promoted piece
  replaces the pawn in both sums and *adds* to the phase), castling (the rook moves too) — and a
  null move changes nothing. Chess960 is refused rather than mis-evaluated, because the castling
  update assumes the standard king-two-files move.
- **`evaluation.py` split in two.** `material_pst(board)` is the from-scratch per-piece sum;
  `evaluate_running(board, mg, eg, phase)` is everything else (insufficient material, structural
  terms, phase blend, mop-up). `evaluate()` is now `evaluate_running(board, *material_pst(board))`
  and `SearchBoard.evaluate()` is `evaluate_running` on the running totals, so the two answers run
  the same arithmetic on the same inputs and cannot drift. 4.9 → 1.0 µs. The evaluation cache
  stays: it still saves the structural terms, and a hit (0.13 µs) is cheaper than the blend.
- **`_capture_moves` rewritten as a bitboard generator.** With no check on the board it walks the
  pieces itself in python-chess's own generation order, and the branch that identifies the moving
  piece yields both its attack set and its rank in the ordering key, so the MVV-LVA key is built
  during generation and no move needs a `piece_type_at` afterwards. Legality is `Board._is_safe`'s
  rule rearranged, not a new one: the king may not step onto a square the enemy attacks, and a
  piece shielding the king from a slider may only move along `BB_RAYS[king][from]` — one mask per
  piece instead of one test per move. In check the previous implementation, kept verbatim as
  `_capture_moves_in_check`, answers instead. 10.7 → 4.6 µs.
- **`Engine._has_legal_move`.** With no check on the board, any pseudo-legal move of a piece that
  is not shielding its king is legal, so one pawn that can step forward or one piece with a square
  to go to settles it; when that finds nothing (in check, or everything pinned or blocked)
  python-chess's generator answers, so the result is always exact. 2.4 → 0.5 µs in the common case.

This is the first place the engine reads python-chess's private API (`_slider_blockers`, and the
`_is_safe` rule reimplemented rather than called) beyond the `_transposition_key()` it already
used. The 2026-09-07 review had rejected exactly that for a 5 % gain; at 40 % it is worth the
coupling, and `agent.py`'s `except Exception` fallback means a future python-chess that moved them
would cost moves, not games. The version is pinned by the platform (python-chess 1.11).

**Exactness, checked before any game was played.**

- **Identical trees.** 30 openings (every 7th line of `data/openings.txt`, the set v0.2 was checked
  with) searched at `node_limit=60000` against `versions/v0.2` run as a separate module: move,
  score, depth, seldepth and node count identical on all 30, **1 800 960 nodes both sides**.
- **Incremental totals.** From 224 starting positions (all 219 openings, the start position and
  four built for promotions, castling and en passant), 40-ply random walks with the running totals
  asserted equal to `material_pst` — and `SearchBoard.evaluate()` equal to `evaluate()` — after
  every move and after every unmake, null moves included: 43 207 checkpoints, 0 mismatches, with
  1 992 captures, 431 promotions, 66 castlings and 1 867 null moves along the way. A dedicated
  sweep adds all 28 en passant captures (both colours, every file pair), 40 promotions of every
  piece plain and capturing, and all four castlings. Pinned as `tests/test_searchboard.py`.
- **Capture generator.** 31 766 lists compared move-for-move against the implementation it
  replaces, 0 differ, including 414 in-check positions, 937 with an en passant square and 1 455
  with a pinned piece. The tie argument (two MVV-LVA keys can only be equal when the attackers are
  the same piece type, so a stable sort leaves ties where the old generation order left them) is in
  the docstring.
- **Has-a-legal-move.** 18 356 positions compared with `any(board.generate_legal_moves())`
  including exhaustive sweeps from stalemate and checkmate roots, 0 disagreements, 39 of them with
  no legal move.

**Speed** (`bench2.py`: nps from a 400 000-node search, best of 3, both versions back to back on an
idle machine; depth from a 3 s search):

| position | v0.2 nps | v0.3 nps | ratio | nodes in 3 s | depth in 3 s |
|---|---|---|---|---|---|
| start | 52 405 | 77 284 | **1.48×** | 165 376 → 234 624 | 9 → 9 (seldepth 21) |
| busy middlegame | 49 913 | 70 833 | **1.42×** | 155 648 → 219 008 | 6 → 6 (seldepth 26) |
| rook endgame | 72 054 | 84 869 | **1.18×** | 218 496 → 253 952 | 12 → 12 (seldepth 20) |

The endgame gains least, as expected: few captures for the new generator to speed up and few
pieces for the incremental sums to save. The same-work check across the 30-position exactness set
is 34.5 s → 25.3 s for the identical 1 800 960 nodes (**1.37×**). Three seconds is not enough for
another whole ply anywhere, which is what the games are for.

**Arena** (`RESULTS.md`, `data/openings.txt`). Note that an earlier, unrelated and rejected v0.3
candidate (the Texel weight fit above) also has a row labelled `v0.3-vs-v0.2-10s`; this one is the
later of the two, the one that scores above 50 %.

- 10 s + 0.1 s, 300 games, 12 workers: **+159 =65 −76, 63.8 % ± 4.8 %, Elo +99 (+64 to +136)**.
- REAL_CLOCK_ROW

**Decision.** DECISION_LINE
## 2026-09-08 — Stage 1 board is a 0x88 mailbox with piece lists, not bitboards

`mikhail_letal/fastboard.py` is the compiled foundation of the numba engine (`docs/PLAN.md`
priority 1). The representation had to be picked before anything else, and the choice was made on
how fast it could be made *provably* right, not on peak throughput.

**Chosen: 0x88 mailbox, piece lists per colour, pseudo-legal generation, legality by
make-then-test-the-king.** An off-board test is `(sq & 0x88) == 0`, one AND, so the classic
mailbox bug — a rook on h4 sliding east onto a5 — cannot be written. Legality by playing the move
and asking whether the mover's king is attacked gets en passant discovered check, a king walking
along the checking slider's ray, and castling out of or through check for free, with no special
case to forget; it is also nearly free inside a search, where the move being kept has to be
played anyway.

**Rejected: bitboards.** Several times faster, and the right target once the whole engine is
green, but they need magic multipliers or kindergarten tables, careful 64-bit unsigned arithmetic
(where Python's arbitrary-precision ints leak into numba and silently overflow), and a separate
correct-by-construction pin analysis. With three days left, a generator that is fast and subtly
wrong loses more games than one that is merely fast.

**Rejected: legality by pin analysis** (compute pinned pieces and checkers, generate only legal
moves). Faster than make-and-test, but it is the part of a generator that is easiest to get
wrong, and its failures are rare positions rather than common ones — exactly the shape of bug
that survives a test suite and shows up in a rated game.

**Rejected: `numba.experimental.jitclass`** for the position. Nicer to read, but slower to
compile and awkward under mypy. A `NamedTuple` of five preallocated int32 arrays is a first-class
numba type, costs nothing on a call, and keeps every mutation visible to the caller.

**Rejected: `cache=True`.** The platform wipes `/tmp` between games and every cache path points
there, so the cache would never hit and would only add a write to the start-up budget.

Measured on this laptop (`tools/bench_fastboard.py`, 13.5 M nodes over four positions):
10–13 M nodes/s against python-chess's 1.0–1.3 M nodes/s with bulk counting at the last ply
(9–15x), or 32–40x when python-chess is made to make and unmake every leaf move as the compiled
side does. Compilation at import is 2.5–3.2 s, well inside the 90 s budget even on a core three
times slower. All three correctness gates pass, with and without `NUMBA_BOUNDSCHECK=1`; the full
run is 143 tests in 168 s, or 171 s with bounds checking on.

Not yet done, and deliberately: nothing calls this module at runtime. The compiled search and
evaluation are the next phase, and `agent.py` keeps the python-chess engine until they exist and
win a match under the promotion rule.

## 2026-09-08 — Stage 1 phase 2: the compiled evaluation is a port gated on exact equality

`mikhail_letal/fasteval.py` is `evaluation.py` rewritten for the 0x88 board, and the only
acceptance test is that the two return **the same integer** on 20,000 positions from playouts of
the curated openings, on all 219 openings, on the 58 rule-breakers, on one hand-built position per
term, and on 2,000 colour-swapped mirrors. Both compute the same integer arithmetic on the same
weights, so there is no rounding to blame a difference on, and one centipawn of drift would change
which move the search picks.

**Chosen: per-file pawn summaries instead of bitboard fills.** `evaluation.py` computes passed,
doubled and isolated pawns with `bb >> 8`, `bb << 32` and friends on Python's arbitrary-precision
integers. Inside numba those are 64-bit machine words, where a signed right shift sign-extends and
a left shift silently overflows — the classic way to get an evaluation that is right in Python and
wrong when compiled. So each fill is restated as a statement about three numbers per colour and
file (how many pawns, their highest rank, their lowest rank), which the mailbox already knows.
**Rejected: uint64 bitboards inside numba**, which would have matched `evaluation.py` line for
line and needed `np.uint64(...)` on every literal to avoid numba's silent promotion of
`uint64 + int64` to `float64`. That is a bug waiting in every arithmetic expression, checked only
by the same gate; the summaries are checkable by reading.

**Chosen: one scratch buffer in `EvalTables` rather than `np.zeros` per call.** An 8×2 array
allocated per evaluation cost 730 ns of the 930 ns the first version spent — four fifths of the
evaluation. The evaluation cannot recurse and the engine is single-threaded by rule, so one shared
buffer is safe. Measured after: 204 ns from the opening position, against 8.3 µs for the Python
evaluation (40x).

## 2026-09-08 — Stage 1 phase 2: fixed-size transposition table, Zobrist keys, depth-preferred

`search.py` keys a Python dict on `Board._transposition_key()`, which is *exact*: two different
positions are never the same key, and the table only ever grows until it is cleared. A compiled
search cannot afford a dict, so `fastsearch` uses a fixed 2²¹-entry array indexed by a Zobrist key
(`fastboard.hash_position`, numbers drawn from numpy's PCG64 with a recorded seed), with
depth-preferred replacement.

Two consequences the Python version does not have, and why both are acceptable: entries are
**replaced** rather than accumulated, which changes which nodes prune but never what is legal; and
a key **collision** is possible, about one in 2⁶⁴ per probe. A collision can hand the search a
wrong score or a wrong first move to try — never an illegal move, because the table move is
matched against the generated move list rather than played on trust, and because `agent.py`
validates the final move against python-chess whatever happens.

**Rejected: keeping the exact dict.** It is the single most expensive thing in the Python engine's
node cost and cannot be compiled at all. **Rejected: always-replace.** Depth-preferred keeps the
expensive deep entries that the shallow iterations of the next move would otherwise evict.

## 2026-09-08 — Stage 1 phase 2: the search aborts by flag, not by exception

`search.py` raises `SearchAborted` at the deadline and unwinds through `board.pop()` in `finally`-
shaped code. In `fastsearch` the deadline sets `I_ABORT` and every function returns as soon as it
sees it, always immediately *after* its `unmake_move`, so the position is left exactly as it was
found. `tests/test_fastsearch.py::test_negamax_leaves_the_position_exactly_as_it_found_it` pins
that on five node limits by comparing all four arrays byte for byte.

**Rejected: numba exceptions.** They work, but an exception raised through a deeply recursive
compiled call stack is the part of numba least covered by its own tests, and a half-unmade
position is exactly the failure that produces an illegal move. The flag costs one predictable
branch a node.

## 2026-09-08 — Stage 1 phase 2: the root runs in Python, everything below it is compiled

Compiling iterative deepening, the aspiration window and the root move loop cost **fourteen
seconds** of the platform's 90-second start-up budget, measured function by function: numba links
a callee's whole compiled module into its caller and optimises the result again, so every layer
stacked on `negamax` (which already contains the evaluation, the generator and make/unmake) pays
for the entire engine to be optimised once more — 6.3 s for `_search_root`, 2.7 s for the
aspiration wrapper, 5.4 s for the deepening loop.

Running them in Python costs one boundary crossing per root move per iteration, measured at 4.0 µs
(numba has to unbox thirteen arrays). With forty root moves and fifteen iterations that is under
three milliseconds a move, against seconds bought back at start-up. Total import from the
extracted zip fell from 34 s to 17 s. Everything that runs millions of times a move is still
compiled; only the part that runs a few hundred times is not — and that part now mirrors
`search.Engine` almost statement for statement, which is what makes the port checkable by eye.

**Rejected: merging the three root functions into one compiled function.** Saves the same time and
costs the readability the project's own rules ask for. **Rejected: `NUMBA_OPT=1`,** which cut
compile time by 15 % and node rate by rather more; **`NUMBA_OPT=0`** compiled in 23 s and searched
at 57k nodes/s, no faster than the interpreted engine. **Rejected: `cache=True`,** for the reason
already recorded: `/tmp` is wiped between games.

## 2026-09-08 — Stage 1 phase 2: two independent limits inside the compiled search

The wall clock is read inside the tree through `numba.objmode` every 512 nodes (a read costs
300 ns, so the cadence is under one percent of node cost at a million nodes a second, and bounds
the overshoot past the hard deadline to about half a millisecond). A node cap derived from the
**measured** node rate — twice what the hard budget can buy, `FastEngine.node_rate` updated after
every move long enough to measure — backs it up. Both mechanisms, always: the clock is what the
referee cares about, the cap is what still stops the search if a clock read stops working.

**Rejected: the clock alone.** `objmode` drops into the interpreter, which is the one place inside
the compiled search where something outside our control can go wrong. **Rejected: the cap alone.**
It is a guess about speed, and the platform's core is not this one.

## 2026-09-08 — Runtime guards on the two fixed-size buffers

Phase 1 left `gen_pseudo`'s 256-move buffer and the 512-ply undo stack unguarded: the sizes are
comfortably above anything a legal position produces (218 legal moves is the known maximum, and
the referee caps a game at 600 plies with search nesting far below that), but "comfortably above"
is not a check. On the platform an out-of-bounds numpy write is silent and its consequences
arbitrary, so both now raise `IndexError`, which `agent.py` answers with the fallback move.

The move-buffer guard is one integer comparison **per piece**, not per move: the widest piece a
generator can produce moves for is a queen on an empty board with 27 destinations, so reserving
`MOVES_PER_PIECE_MAX = 27` slots before starting on a piece is sufficient and costs nothing
measurable (perft throughput unchanged at 13 M nodes/s). Nothing in either guard is derived from a
compile-time constant, so the compiler cannot prove it away.

**Rejected: truncating the move list instead of raising.** Silently dropping legal moves would
make the engine play a wrong move in a position it had every chance to get right; the exception is
caught one frame up and costs a fallback move at worst.

## 2026-09-08 — The warm-up gets a wall-clock deadline (v1.0.0)

The compiled engine's import costs about 28.7 s from the extracted zip here, and the platform is
measured at 2.3x slower (docs/CALIBRATION.md), which projects to ~66 s against a **hard 90 s**
init budget. An import that overruns it is not a bad move: the platform records an init failure
and *every* game is lost. Twenty-four seconds of margin on a machine we cannot benchmark before
we ship is not a margin worth betting the entry on.

So the compilation is bounded. `agent.py` arms `warmup.arm(_IMPORT_STARTED + WARM_UP_BUDGET_S)`
(70 s) before the first jitted module is imported; `fastboard`, `fasteval` and `fastsearch` cut
their `warm_up()` into eleven phases ordered by how much the search needs them, and each phase
asks the shared budget whether it still fits. What does not fit is skipped and numba compiles it
inside the first `get_move` instead — part of one move out of a 120 s clock, and the hard
deadline still holds afterwards because the search's own clock checks are unaffected (measured:
with the budget forced to 2 s the first move takes 15.4 s of a 30 s hard budget and is legal).
`agent.py` logs one line naming how many phases were skipped, and the per-move signature check
now logs one summary line rather than one line per function, so the log stays readable.

**Why the check predicts rather than just tests the clock.** The phases are lumpy — compiling
`negamax` alone is 12.5 s here — so "stop once the deadline has passed" would still let one
phase start at 69 s and run to 107 s. Each phase declares its development-machine cost
(docs/PROVENANCE.md), the budget scales that by the slowdown it has measured from the phases that
already ran, and a phase starts only if it is predicted to finish in time. The worst case is then
the deadline plus one phase's *prediction error*, not plus a whole phase.

**Why 70 s and not less.** At the platform's measured 2.3x the whole warm-up ends at ~65 s, so 70
does not bite where we actually play: the engine still arrives fully compiled. At 3x the sequence
reaches `negamax` at ~39 s needing ~37 s more, is not started, and the import ends at ~40 s
instead of the ~85 s an unbounded warm-up would take there. Rejected: **35–40 s**, which would
cut `negamax` on the platform itself and hand away one slow move in every game for a danger that
has not been measured; **no bound at all**, which is the current shipping state and is a coin
flip on a machine 3x slower; **shrinking the warm-up** by dropping phases outright, which pays
the same cost unconditionally instead of only when the machine is slow.

**Why the phases sit where they do.** `fastboard.perft` is last in its module because only the
tests call it. `fastsearch.samples` (the sample searches that compile the aspiration re-search,
the null move, the reductions and the abort path) costs 0.1 s now that `negamax` is compiled, so
it is cheap insurance rather than a candidate for cutting, and it is skipped outright when
`negamax` was skipped, since running it would compile `negamax` anyway. `fastsearch.node_rate`,
the seeding search, is last: if it is skipped, `FastEngine.node_rate` keeps the new
`DEFAULT_NODE_RATE = 400 000`, deliberately above anything measured, so the node cap that backs
up the clock is loose rather than zero or unset — a cap that never binds is safe where one that
binds early would cut a search short.

**Where the leftover compiling happens.** Measured first, then decided: with the budget forced to
2 s, the first move took 15.9 s against a 10.2 s hard budget, because numba compiled `negamax`
*inside* `ENGINE.search` and no deadline the search checks can interrupt a compile. So the first
real move now finishes the outstanding warm-up **before** it searches (`agent._finish_warm_up`),
bounded by `cold_finish_fraction` (0.25) of the clock and by the same predictive budget, and the
search's soft and hard deadlines are shifted by what that cost while its budget is computed from
the clock that is left. Two things follow: every search, including the first, is back inside its
hard deadline, and the compiling is paid once on the opening's 120-second clock instead of
dribbling into a middlegame move whose whole budget is three seconds. Rejected: leaving the
compile inside the search, which is where the 15.9 s came from and which leaves single functions
to compile at unpredictable moments later in the game; and refusing to search at all while the
jit is cold, which never compiles anything and so plays fallback moves for the whole game.

## 2026-09-08 — Principal variation search at interior nodes

`negamax` searched every child of every interior node with the full window `(-beta, -alpha)`.
Only the first child needs that. Once the ordering's first move has raised alpha, the question
asked of every later move is not "how good is it?" but "is it better than alpha?", and a null
window `(alpha, alpha + 1)` answers that at the first refutation in every subtree. Only a move
that answers yes is measured, with a re-search inside the real window. Both engines now do it —
`search._negamax` as the readable version, `fastsearch.negamax` as the compiled one.

**The interaction with late-move reductions, which is where the classic bug lives.** A late quiet
move can now be searched three times, and the order is fixed: reduced depth with the null window,
then full depth with the null window, then full depth with the real window. The middle step is
the one that is easy to drop, and dropping it pays full depth *and* the full window for a move
that only a shallow search has hinted at. Two guards make the chain terminate: the full-depth
null-window repeat runs only when a reduction was applied, and the full-window re-search runs
only when `alpha < score < beta`, which is unsatisfiable when the caller already handed down a
null window (`beta == alpha + 1`), so a null-window node never re-searches at all.

**Measured, compiled engine, nodes to a fixed depth** (`FastEngine`, fresh table per position).
Depth 10: standard start 228 763 → 199 510 nodes (0.51 s → 0.37 s); Kiwipete middlegame
3 007 599 → 3 193 943 (5.76 s → 6.21 s); rook ending 161 025 → 165 683 (0.21 s → 0.25 s). Over
fifteen positions (those three plus twelve openings drawn from `data/openings.txt`, seed
20260908) at depth 9: 8 521 852 → 8 313 522 nodes, −2.4 %.

**Why the saving is small here, honestly.** Isolated, principal variation search is worth much
more than 2 %: with late-move reductions, null-move pruning and futility pruning switched off,
the Python engine's four-position depth-6 total falls 690 628 → 579 103 nodes, −16 %. With those
heuristics on they have already taken most of the same tree, and what is left is partly spent on
the extra re-searches. The change is kept because the two effects are not the same tree — the
window is exact where the heuristics are approximations — and because the strength screen, not
the node count, is the verdict.

**Search instability, and the test that had to change.** At a fixed depth the root move and score
are no longer bit-identical to the old search: the middlegame above answers d5e6/−83 where it
answered e2a6/−87. Nothing there is unsound. Delta pruning's floor, the futility bound, the
null-move threshold and the reduced-search re-search test are all comparisons against alpha, so a
narrower window prunes a different tree and returns a different (still valid) fail-soft bound.
`test_aspiration_windows_start_at_depth_four_and_keep_the_score_exact` asserted that the aspirated
and full-window searches return the *same score*; that was always a property of the heuristics
rather than of aspiration, and it stopped holding. It is now two tests: the move must still match,
and — the invariant actually worth pinning — with the four window-dependent heuristics switched
off the two searches agree exactly, which is what says the aspiration re-searches lose nothing.

**Rejected: principal variation search at the root as well.** The root loop still gives every
move the full window, and that is where the largest single subtree saving would be. It is left
alone for now because `root_scores` feeds `_break_draw_tie`, which counts moves scoring exactly
`DRAW_SCORE`, and a null-window root search returns bounds rather than values there; the mop-up
behaviour that depends on it is tested and would need re-establishing first.

## 2026-09-08 — Mate-distance pruning, which the docstrings already claimed

`fastsearch`'s module docstring and `docs/DESIGN.md` both listed mate-distance pruning among the
things the search does. Neither engine had it. This adds it, in both, as step (4) of the node —
after the draw checks, before the check extension and the table probe, so the probe and the store
still see the same depth.

A node `ply` plies from the root is worth at least `-(MATE_SCORE - ply)` (being mated right here)
and at most `MATE_SCORE - ply - 1` (mating on this very move). Clamping `alpha` and `beta` to that
removes only values the node could never return, so when the clamped window closes the node can
answer `alpha` immediately: in the fail-high case `alpha` is `-(MATE_SCORE - ply)`, a true lower
bound; in the fail-low case `alpha` is at or above the ceiling, a true upper bound. Two
comparisons per node, and it stops a search that has already found a mate in n from spending the
rest of the iteration proving a mate in n + 2 somewhere else.

**Measured, compiled engine.** Ordinary positions are untouched, as they should be — depth 10
from the standard start, the Kiwipete middlegame and the rook ending give byte-identical node
counts (199 510 / 3 193 943 / 165 683) because the clamp only bites once a mate bound is in the
window. Where it does bite: a mate in three to depth 5, 13 052 → 2 914 nodes (−78 %, 25 ms →
4 ms); KR vs k to depth 12 unchanged at 1 365 801; KQ vs k to depth 12 3 472 742 → 3 595 700
(+3.5 %, the mop-up tie-break searching a different tree, same move and same score).

**Rejected: clamping after the table probe** instead of before it. It would let a probe return a
score from outside the window the node can actually be worth, and it is one comparison later for
no gain.

**Rejected: also clamping in `quiescence`.** Quiescence has no depth left to shorten and its
stand-pat score is never a mate score, so the clamp could only ever cost the comparison.

## 2026-09-08 — The compiled quiescence gets the cheap legality test the Python one already had

`search.Engine._has_legal_move` (v0.3) answers "does the side to move have a move at all?" without
generating one: with no check on the board, a piece that is not shielding its king cannot expose
it by moving, so any pseudo-legal move of such a piece is legal, and one pawn that can step
forward settles it. The compiled port never got that. `fastsearch._has_legal` ran a full
`gen_pseudo` plus a make/unmake, and the quiescence stand-pat cutoff asks it at **36 % of all
nodes** in the Kiwipete middlegame (1 155 753 calls in a 3.19 M-node depth-10 search) — the most
common path in the whole tree, and it exists only so that a mate or a stalemate is never scored as
a stand-pat.

`_has_unpinned_move` is the compiled twin. It differs from the Python original in two ways: the
caller passes `in_chk` in rather than the function recomputing it, and "not shielding the king" is
the cruder test that the piece is not on a rank, file or diagonal *through* the king, because an
0x88 board has no bitboard to compute python-chess's exact slider-blocker set from. The crude test
is the generous one on purpose — a piece wrongly called "possibly pinned" costs the scan of one
more piece, a piece wrongly called free would be a stalemate scored as a stand-pat. En passant is
left out, being the one move that can uncover a check from a piece the mover never stood in front
of. Each "yes" costs reading one piece's destinations: no make/unmake, no attack scan. How often
it can say yes, counted inside a depth-10 search: **100 %** of the calls from the standard start,
**99.9 %** in the Kiwipete middlegame, **86.6 %** in the rook ending, where there is much less
material to find an unpinned piece among. Over a 76 000-position random playout, 97 %.

**Measured, best of four runs each, alternating between the two builds** (the box was busy, so
absolute times drift; the pairs were taken back to back). Depth 10: standard start 0.271 s →
0.247 s; Kiwipete middlegame **5.282 s → 4.791 s, −9.3 %**; rook ending 0.195 s → 0.185 s. Node
counts are unchanged to the last node (199 510 / 3 193 943 / 165 683), which is the point: this is
the same search, done faster. An unsound build with the test deleted outright ran the middlegame
in 5.213 s against 6.250 s in the same session, so the probe recovers essentially all of the
available saving.

**Rejected: probing the king's moves instead**, with `attacked()` on each square the king could go
to and the king lifted off the board. It is sound and it hits 98.7 % of the time, but `attacked()`
scans eight rays to the edge of the board, so one or two calls cost about what the whole
`gen_pseudo` cost: measured 6.313 s against 6.250 s, i.e. nothing.

**Rejected: hoisting the call so it runs once per node.** It already does — the stand-pat branch
returns immediately either way. The cost is that the branch is taken at a third of all nodes, not
that it is taken twice at any of them.

**Rejected: skipping the test when the side to move has little material.** There is no material
bound on stalemate: the six named stalemates in `tests/test_fastsearch.py` run from a bare king to
a side with every piece still on the board and none of it mobile.

## 2026-09-08 — Late-move reductions become depth- and move-aware

`LMR_REDUCTION = 1` took one ply off every late quiet move, so the fortieth move of a twenty-ply
node was reduced exactly as much as the fourth move of a three-ply node. Those are not the same
bet. The deeper the node, the more a ply is worth skipping; the later a move sorts, the less the
ordering believes in it, and that belief decays like the logarithm of the move number rather than
linearly. The reduction is now a table, generated at import in `search._lmr_table` from

    trunc(LMR_BASE + log(depth) * log(move) / LMR_DIVISOR)   with 0.75 and 2.25

floored at one ply (a reduction of zero is not a reduction) and capped at `depth - 2`, so the
reduced search is never shallower than depth 1: a reduced search that lands in quiescence proves
nothing about a *quiet* move. It runs from 1 at (depth 3, move 3), the old flat value, to 8 at the
table's far corner. Both engines read the same table; the compiled one indexes a numpy view of it
and clamps both indices to its 64 × 64 edges.

**Measured, compiled engine, nodes to depth 10** (the pairs taken back to back on a busy box).
Standard start 199 510 → 141 701 (−29 %, 0.253 s → 0.193 s); Kiwipete middlegame
3 193 943 → 1 657 996 (**−48 %**, 4.801 s → 2.450 s); rook ending 165 683 → 94 970 (−43 %,
0.185 s → 0.113 s).

**What that number is and is not.** It is a much smaller tree to the same nominal depth, which is
what late-move reductions are for. It is not, on its own, a stronger engine: a reduction is a bet
that a late quiet move is not the best one, and a bigger reduction is a bigger bet. All three
positions answer differently at depth 10 than the flat version did (the rook ending plays e2e3
where it played b4f4), so the verdict is the strength screen at the real time control, not this
table. Recorded here as a measurement of the tree, with the games still to come.

**Where the numbers are recorded.** `docs/PROVENANCE.md` and, for the first time for a search
constant, `weights/PROVENANCE.json` — the only provenance file inside the zip, which until now
covered the evaluation tables alone. The table ships as the formula that generates it, not as a
list of numbers, which is the same argument `tools/gen_pst.py` makes for the piece-square tables:
its origin is provable from the source.

**Rejected: tuning `LMR_BASE` and `LMR_DIVISOR`.** They are textbook magnitudes taken as they
stand. Tuning them against anything other than games would be fitting to the wrong objective, and
tuning them against games costs the arena time the strength screen needs first.

## 2026-09-08 — The compiled futility prune stops making the move it is about to throw away

`fastsearch.negamax` made every move before it decided whether to futility-prune it, then unmade
it: a full `make_move`/`unmake_move` bought nothing at every pruned move. The comment said why —
"no legal move below" has to keep meaning mate or stalemate, and a node that has pruned everything
must not be mistaken for one that has nothing to play. That reasoning holds only until the node
has seen one legal move; after that it is neither mate nor stalemate whatever the rest of the list
does. So the prune now happens before `make_move` as soon as `legal_seen` is set, and only the
first legal move of a futility node is still made and thrown away.

`search._negamax` never had the problem: `_staged_moves` yields legal moves only, so the Python
engine could always prune before pushing. This is the compiled port catching up.

**Measured, depth 10, best of three, pairs back to back.** Node counts are identical to the last
node (141 701 / 1 657 996 / 94 970), which is the check that matters: the same moves are pruned
and the same tree is searched. Time: 0.203 s → 0.203 s from the start, 2.562 s → 2.493 s in the
Kiwipete middlegame (−2.7 %), 0.163 s → 0.111 s in the rook ending; totals 2.929 s → 2.808 s.
Small, because futility only fires at depths 1 and 2, and free.

**One deliberate imprecision.** A quiet move pruned before it is made has not been tested for
legality, so an illegal one can now set `pruned_any`. That can only raise the node's fail-soft
score to `futility_bound`, which is at most `alpha_original`, so the node still stores an UPPER
bound and the bound is still true — a looser upper bound is always sound. Nothing in the three
measured positions changed by a single node.

## 2026-09-08 — Rejected: a history malus, and history gravity

Tried, measured, and not shipped. The history heuristic only ever *rewards* a quiet move that
causes a beta cutoff, and an audit suggested the two standard additions: a **malus** that lowers
the score of the quiet moves the same node tried and which failed to cut off, and **gravity**,
which scales each update by how close the entry already is to `_HISTORY_MAX` so that scores
approach the limit instead of piling up against it. Both were implemented in both engines — the
compiled loop marking the slots it skipped so the malus could tell a move that was searched and
beaten from one that was never given the chance — and then measured over fifteen positions
(the three benchmark positions plus twelve openings from `data/openings.txt`, seed 20260908) at a
fixed depth 10.

| build | nodes to depth 10, fifteen positions |
|---|---|
| shipped (bonus only) | 8 634 847 |
| gravity, no malus | 8 634 847 |
| gravity + malus | 9 624 902 (**+11.5 %**) |
| gravity + malus, bonus and malus capped at 400 | 9 624 902 |

**Gravity is exactly a no-op here, to the node**, and the third row says the cap is too. Both
answers have the same cause and it is worth writing down: the bonus is `depth * depth`, so at
depth 10 it never exceeds 100, while `_HISTORY_MAX` is 999 999 and the whole table is halved at
the start of every move. Entries never get near the limit, so there is nothing for gravity to
scale down and nothing for a cap to cut. The saturation the audit predicted does not happen in
this engine, and adding code that measurably changes nothing is not worth the lines.

**The malus costs 11.5 % more nodes at the same depth.** That is the wrong sign for a
move-ordering change, which is the one kind of change whose node count at fixed depth is a fair
verdict on its own: better ordering cuts off sooner, and nothing is traded away for it. The
likely reason is the asymmetry between the two updates at this bonus shape — a node hands out one
bonus and up to thirty maluses, each as large as the bonus and each scaled by `depth * depth`, so
a quiet move that is tried and beaten in a deep node is driven far more negative than the same
move is ever raised by cutting off in a shallow one. What the table then ranks is "how often was
this move tried near the root", not "how often did it work". Making that work would need a
different bonus shape, and that is a tuning exercise against games, not something to bolt on.

Kept for the record rather than deleted: the numbers above are the reason the shipped engine still
has a reward-only history table, and anyone who reads the audit and reaches for the same two ideas
should start from here.

## 2026-09-08 — Sanity match for the batch above (not a strength verdict)

Twenty games against `versions/v1.0` at 10 s + 0.1 s, two workers, openings from
`data/openings.txt`. The point is that nothing crashes, no clock goes negative and no game ends in
a failed termination — not who is stronger, which needs the real time control and many more games
than this.

+7 =7 −6, score 52.5 % ± 18.1 %, Elo +17 (−112 to +152). Terminations: checkmate 13, threefold
repetition 5, fifty moves 1, insufficient material 1 — every game ended on a rule, none on a
flag, a crash or an illegal move. Lowest agent clock 1 647 ms after a move and before the
increment, in the 247-ply game 12. Load average 4.8 → 6.2 throughout, because the box was busy
with another measurement, so the clock figures measure the load as much as the engine.

The interval spans zero by a wide margin at twenty games, as it must. **This row is not evidence
that the batch is an improvement**; the strength screen at the event time control is.
## 2026-09-08 — The next depth is started on a prediction, not on a fixed share of the budget

The platform's rated logs for **v0.2.1** show per-move times in two lumps and nothing between:
1.5–3.0 s when an iteration finished and the engine stopped with a third of its budget unspent, or
8.9–10.1 s when it started a depth that ran into the hard ceiling (`docs/CALIBRATION.md`, the four
rated games of rounds 67–70). `next_iteration_fraction = 0.45` is the direct cause: iteration costs
grow by 4–5x a depth, so a depth begun at 0.45 of the budget cannot finish inside it, and the rule
has no way to tell the two cases apart.

The build matters here and this entry named the wrong one when it was written. The measurement is
the **interpreted** v0.2.1, not the compiled v1.0 — corrected in place rather than appended,
because it was an error at the time rather than something that later became stale. It does not
weaken the argument: `timing.py` was byte-identical in v1.0, so the flaw shipped unchanged
(`handoff/FINDING-flagging.md`), and v1.0's own platform validation independently reproduced the
pattern — three moves at 8.9–10.1 s against a soft target of 3.4 s while six others finished under
it (`docs/CALIBRATION.md`, the v1.0 validation). Two builds, sixteen times apart in node rate, both
bimodal, which is stronger evidence for a structural cause than either alone. But the reasoning
below is built on the v0.2.1 numbers and the record has to say so.

So the decision to start depth d+1 is now a prediction: `ratio × time(d)`, with the ratio measured
from the last two completed iterations, clamped to 2.0–8.0 and defaulting to 4.5 before there is
data, started only if it is predicted to end inside the target (`timing.should_start_next_depth`,
called by both engines so the compiled one and the reference one cannot drift). The target is the
soft budget times `iteration_target_factor`, stretched by half again when the root move changed at
the last completed depth and cut to 0.7 when it has been stable for six iterations with a score
that is not falling. Every target is clamped to the hard window, so the abort path and the flag
invariant are untouched; the measurements are in docs/CALIBRATION.md.

**Rejected: a target equal to the soft budget.** It is the obvious reading of "do not overrun the
budget", and it spends 0.70 of the budget for 10.83 mean depth where 1.35 spends 0.80 for 11.17,
because with geometric iteration costs a rule that insists the next depth *finish* by the target
must stop a factor of `ratio` short of it. **Rejected: 1.75**, which reached the hard ceiling on
the same positions — the behaviour being removed. **Rejected: the first easy-move rule** (stable
for 4 iterations, half the target), which fired on nearly every move and spent 0.41 of the budget,
less than the fixed rule it replaced; 6 iterations at 0.7 costs 0.17 of a ply and banks 16 %.

**The divisor is refitted to how long games actually are.** Our five rated games under v1.0
(`data/pgn/ours`, clocks verified against the platform's log) are the whole argument:

| game | colour | result | plies | our moves | clock left |
|---|---|---|---|---|---|
| `1e1c9922` | W | win | 36 | 18 | 87.5 s |
| `3ebceb52` | B | loss | 46 | 23 | 90.2 s |
| `cf4043b1` | W | win | 102 | 51 | 31.6 s |
| `f43e60b5` | W | win | 210 | 105 | 6.0 s |
| `5504d7fa` | B | draw, fifty moves | 226 | 113 | 4.7 s |

The two games that ended near the flag are the two longest, and the longer of them is the draw, so
the tail of a long game is where the dropped half point actually is; the two shortest ended with
roughly 90 s unspent. `moves_to_go = clamp(40 − moves // 2, 12, 40)` is wrong at both ends because
it is calibrated for a game half the length of a real one: across the 1 697 finished ladder games
collected by 2026-09-08 the
median is 67 of our moves, and the median still to play is 67 at the start, 47 at our move 20, 31
at 40 and about 25 from 50 on. The new line is that measured curve scaled by 0.70 — the share of
its soft budget a move actually spends under the prediction rule — so that realised spending is
the even split of the clock over the moves really left: `clamp(50 − 0.7 × moves played, 20, 50)`.
Simulated over all 1 697 games (`tools/sim_time.py`), it moves the lowest clock any game reaches
from 3.3 s to 5.9 s and the spend from our move 80 on from 0.68 s to 0.79 s, for 0.32 s a move
less in the opening.

**Rejected: 30 / 24 with the halving kept**, which was this change's first attempt, made against
our four games before the ladder data existed: it front-loads the opening at 2.86 s a move and
starves everything after move 50 (1.09 s), because a maximum that low reaches the floor after a
dozen moves. **Rejected: a minimum of 16**, which is what the median remaining moves imply. Two
criteria say 20. The soft formula alone balances the increment at
`overhead_ms + moves_to_go_min × increment_ms × (1 / usage − increment_fraction)`, which at a full
spend of the budget is exactly `panic_ms` = 1650 ms for 16 — a long game would settle on the clock
at which the agent gives up searching — and 2050 ms for 20; and in the deep tail the
remaining-moves distribution is skewed (median 27, mean 40 at our move 100), so the median
under-states what is left in the games that get there. Over the ladder games of at least 90 of
our moves, 20 keeps the lowest clock at 5.9 s against 4.6 s, and at 3.3 s against 2.6 s if a move
spends 0.85 of its budget instead of the measured 0.70. What actually stops the clock falling
further is neither constant: `floor_ms` and `hard_fraction` mean the plan never leaves less than
the reserve after a move, so the clock cannot settle below about 2.05 s whatever the divisor is —
the divisor decides how fast it gets there, not where it stops.

**Rejected: any use of the opponent's clock.** Estimating it to play for a flag was investigated
and the arithmetic kills it: with a 0.5 s increment the opponent's net drain was 0.063 s a move,
so flagging from 10 s needs about 157 moves and the referee's 600-ply draw lands first.

`overhead_ms` drops from 150 to 50 in the same change: the platform charges 0–2 ms (mean 1.1) over
25 measured moves, and CALIBRATION.md's own rule is the maximum plus 50 ms. `panic_ms` deliberately
stays at 1650 even though `overhead_ms + floor_ms` is now 1550, so that nothing within a second and
a half of the flag behaves differently from the version that was measured.

Every constant above is now also in `weights/PROVENANCE.json`, which is the only provenance
artefact that ships (docs/ does not). Its rows are generated from `TimeParams` itself by
`tools/gen_pst.py:timing_rows`, and `tests/test_timing.py` fails if the shipped file and the
constants disagree, so the record cannot go stale the next time one of them is tuned.

## 2026-09-08 — A king-danger term, counting attackers rather than open files

The evaluation had exactly one king term, `king_shield`, and nothing that knew what an attack
looked like. Round 70 was lost by castling long into a queen already standing on b3
(`handoff/FINDING-king-safety.md`, Yan): the search was not short of depth — Yan re-ran the
critical positions with sixteen times the node rate and four to five extra plies and none of the
three decisions changed — it was short of a reason to dislike the position.

**Chosen:** attack units into the king's 3×3 zone. Each enemy knight, bishop, rook or queen whose
attacks reach the zone contributes a weight once, however many zone squares it touches; the
penalty is `KING_DANGER_SCALE × units²`, capped, middlegame only, and skipped entirely while the
king still has two of its own shield pawns.

**Rejected: the open-file term** (Yan's `ks1`), which was the cheaper option and the one the
compiled evaluation could compute almost for free, because `fasteval` already builds per-file pawn
summaries. Two reasons. It had the wrong polarity in Yan's own measurement — after `cxd4` the
c-file still held our pawn on c6, so "no own pawn on the king's file" never fired — and, decisively,
**it would not have fired in the game it was meant to explain.** Round 70 was not lost down an open
file; it was lost to pieces arriving. A term that is cheap and silent on the one position we have
evidence for is worse than a dearer term that speaks.

**Rejected: counting attacked squares** rather than attackers. What decides a king hunt is how many
pieces arrive, not how much of the box each one covers; counting squares would let one long-range
bishop outweigh a knight and a queen together.

**Why the cost objection no longer holds.** Yan measured four variants and rejected three on node
rate, the textbook attacker-count shape (`ks5`) worst at −22 %/−26 %. Those figures were taken on
the interpreted engine, where an evaluation cost **8.3 µs**; it now costs **204 ns**, so evaluation
went from roughly half the cost of a node to about a fifth of it. Re-measured on the compiled
engine at a **fixed node count** (so search shape cannot confound it), median of five runs: −0.6 %
from the start position, +2.4 % in a quiet middlegame, −2.0 % in the round-70 position and
**+11.0 % with both kings open**. The first and third are inside the noise. The term is free where
the shelter gate skips it and costs about a tenth of the node rate where it actually runs, which is
the trade the gate exists to make.

**Kept from Yan's work:** the shelter gate, which was his one transferable result, as a named
constant (`KING_DANGER_SHELTERED_PAWNS`) rather than an inlined 2 — whether its blindness is still
worth paying for at 204 ns is a question for the arena, not for a comment.

**Status: unmeasured in games.** On the three round-70 positions the compiled engine now declines
`8...O-O-O` and plays `h6` instead; it still plays `Ne2+` at move 20 and `Nxd4` at move 22. This
earns a promotion match against `versions/v1.0`, not a place in the zip, and the term sits behind
`KING_DANGER_TERM` / `E_KING_DANGER_ON` so the match can switch it off.

**Correction, same day, from Yan's PR #4.** This entry first called the move-20 and move-22
blunders "tactical losses rather than king-safety ones". That was wrong, and the mistake was to
infer a cause from a term's silence. Yan built four king-danger variants -- `expo` (king virtual
mobility plus queen proximity), `units` (weighted attackers, quadratic: the same family as the term
above), `files` (open lines toward the king) and `storm` (shield deficit plus pawn storm) -- all
parity-checked, all cheap (-0.6 % to +4.9 % nps), and **every one reproduces all three blunders**.

His diagnosis is structural, not a weight wanting tuning. For the black king on c8 the virtual
mobility is **6, the floor, before `22...Nxd4`, after it, and after the correct `22...Nf4` alike**:
the king's own rook on d8 blocks east, its own pawn on c6 blocks south, its own queen on e6 blocks
the diagonal. The c-file opens *behind* the c6 pawn as the king sees it, so no exposure count moves,
and what remained was a queen-distance term identical for every candidate. **A king's own crowding
pieces suppress every exposure measure exactly when the danger is worst.** So these were king-safety
failures that this whole family of terms cannot see, not tactical oversights -- the danger was a
half-open file an enemy rook could arrive down, which is a fact about enemy access rather than about
where the king could walk.

The consequence for the term above: keep it and screen it **on general merit** -- king safety is
something engines have and ours did not -- but it must not be claimed to address round 70. It
declines the losing castle at move 8 and nothing more, which is exactly what Yan's result predicts.
And if the screen comes back inside the noise, the next step is not a fifth exposure variant.

## 2026-09-08 — Pre-registered: what the bundle match result will mean

Written at 21:2x, while the match is running and **before any result exists**. That timing is the
whole value of this entry: a promotion rule decided after seeing the number is not a rule, it is a
rationalisation, and the deviation below would be indefensible if it were invented to fit an
awkward result. The operator delegated the decision ("do the best idk"); it is recorded here in his
name and with the reasoning exposed, so a judge can disagree with the judgement rather than wonder
whether one was made.

The match: `v1.1-bundle-vs-v1.0-real`, 300 games in three chunks of 100, real clock, against
`versions/v1.0`. It measures **two** changes together — the timing refit (`82b20e2`) and the
king-danger term (`897e1e2`) — which is the right thing for the shipping question ("is what we
would upload better than what is uploaded") and cannot attribute the result to either half.

**The rule, fixed in advance:**

1. **Interval above zero** → promote. This is CLAUDE.md's rule, unchanged, and needs no argument.
2. **Point estimate negative, or lower bound at or below the non-inferiority margin** → revert both
   changes; v1.0 ships. The margin is **−40 Elo at the full 300 games**, scaled by `sqrt(300 / n)`
   if fewer games are played (−49 at 200, −69 at 100).

   The scaling is not a loophole, it is the correction that keeps the margin meaning one thing. A
   *genuinely neutral* change returns `elo_low` of −35.3 at 300 games, **−43.4 at 200 and −61.9 at
   100** (computed from `tools.arena_openings.statistics` at a 20 % draw rate). A fixed −40 would
   therefore pass a neutral result at 300 games and reject the same neutral result at 200 — turning
   "did a chunk survive" into a verdict on the engine. −40 was chosen to sit just outside the width
   of a neutral 300-game interval: wide enough not to reject a change that is genuinely level,
   tight enough to catch a real regression.

   Consequence worth stating plainly: at 300 games this margin is **not the binding constraint** —
   any non-negative point estimate clears it. The conditions that actually decide case 3 below are
   the non-negative point estimate and the clock.
3. **Interval straddles zero, point estimate at or above zero, lower bound above the margin, *and*
   the safety condition below holds** → promote, and record in `RESULTS.md` and the report that it
   shipped on the **safety** criterion, not the Elo rule.

   **The safety condition, stated in what this match actually records.** The first draft of this
   entry said "the lowest-clock figure improves against v1.0". That cannot be evaluated:
   `arena_openings` records `agent_low_clock_ms`, "the lowest clock **the agent** had", and in a
   v1.1-versus-v1.0 match the agent is v1.1. The opponent's clock is never written down, so there
   is no v1.0 figure in the run to compare against, and v1.0's existing rows were played against
   Stockfish at different game lengths and are not comparable. A criterion that cannot be computed
   is not a criterion, and discovering that after the number arrived would have meant choosing an
   interpretation to fit it.

   So the condition is absolute rather than comparative, which is arguably what it should have been
   from the start — the risk being reduced is running out of clock, not being relatively better at
   not running out:

   - **no game lost on time**: `flag` appears in no chunk's terminations (it is in
     `harness.referee.FAILED_TERMINATIONS`, so it is recorded), **and**
   - **`low_clock_ms` stays above 5 000 ms** across all 300 games — three times `panic_ms` (1 650),
     the clock below which `get_move` abandons the search and plays a fallback. A run that never
     comes within three times that of the panic floor did not survive by luck.

   A v1.0 comparison would need its own run and is **not** a condition of this decision.

**Why case 3 is a deviation worth making.** The strict rule assumes the change is trying to buy
Elo. The timing refit is not: it exists because two of our seven rated games finished on 4.7 s and
6.0 s, and a flag loses the game outright. A 300-game match measures that badly, because most games
never reach the tail where the constant bites — the effect is concentrated in the minority of long
games and diluted across the rest. Refusing to ship a measured risk reduction because a
badly-matched instrument returned "not proven" would be following the rule's words against its
purpose. `low_clock_ms` is recorded by the arena already, so case 3 is decided on a measurement
rather than on the argument above.

**What case 3 does not license.** Not a positive point estimate alone; not "the simulation says so";
not king safety, which has no independent safety argument and rides along on the bundle. If the
bundle ships under case 3, the king-danger term ships unproven and the record must say so.

**Attribution, either way.** The confounding is accepted for the upload decision, not for the
record. Once the calendar correction is accounted for there are roughly nine six-hour slots left
before the Friday 11:00 cutoff, so a timing-alone match against `versions/v1.0` runs afterwards for
the report regardless of what is uploaded. Shipping fast and knowing why are not in competition
here; there is room for both.

### Amendment 4, and the operative rule restated in full

Two structural defects, found by `chessathon-64` auditing the entry above, both fixed **before any
result exists**. The rule has now been amended four times in one evening; patching it a fifth time
would leave a decision procedure nobody could state without reading the diffs, so the whole of it
is restated here and **this section supersedes the numbered cases above**. Those remain as written,
unedited, because how the rule got here is part of the record.

**Defect A: optional stopping.** The rule permitted deciding after chunk A, B or C, and calibrated
the margin at each. Fixing the interval's *width* at each `n` does nothing about the multiplicity
of *looks*, which is a different failure. Simulated over 20 000 matches, a genuinely level change
at a 20 % draw rate:

| truly level change | one look at pooled 300 | promote at first favourable chunk |
|---|---|---|
| case 1 fires (interval above zero) | 2.60 % | **5.71 %** |
| case 3 gate fires (point estimate ≥ 0) | 51.22 % | **70.35 %** |

64 quantified the first row. The second is the one that matters, because case 3 is the path most
likely to fire, and there best-of-three turns a coin flip into a 70 % chance of promoting a change
worth nothing. A pre-registration that says "decided in advance" while permitting best-of-three is
performing the ritual and skipping the substance.

**Defect B: the rule was not exhaustive, and the safety condition gated the wrong case.** A
straddling interval with a non-negative point estimate, a lower bound above the margin, *and* a
failed safety condition matched no case at all — which is exactly the situation a pre-commitment is
for, because it is the one where "the Elo is fine, ship it" is tempting. Worse, case 1 promoted on
the interval alone with **no** safety condition, so a build that flagged a game would have shipped
on strength — in a change whose entire rationale is that a flag loses the game outright.

**The operative rule.**

**Step 1 — the safety gate, applied first and to every case.** Over all games actually completed:
no `flag` termination in any chunk, and `low_clock_ms` above 5 000 ms (three times the 1 650 ms
`panic_ms` floor). **If this fails, nothing is promoted, whatever the Elo shows**, and the failure
is recorded in `RESULTS.md` as the reason. A flag in 300 games is disqualifying on its own.

> **Superseded, 9 September, by amendment 7 below — read that before applying this step.** The
> clock half of this condition is no longer operative. A minimum over `n` is an extreme-value
> statistic: it can only worsen as games are added, so this rule got strictly harder to pass the
> larger the sample it also demanded. Amendment 7 replaces it with a rate — at most 2 % of games
> below 5 000 ms — authored blind by `chessathon-64` and adopted as written. **The flag half stands
> unchanged**, and it is the half with a direct consequence.
>
> This note exists because the section it sits in announces that it "supersedes the numbered cases
> above" and restates the rule whole, which invites reading it alone as operative. Found by
> `chessathon-2c` re-deriving the v1.1 verdict from the surviving PGNs: applied as written, this
> step **fails** on a single game at 3 729 ms and returns "nothing is promoted"; applied with
> amendment 7, the same match **passes** at 2 of 200. A restatement that goes stale is worse than
> the patchwork it replaced, because it tells the reader not to look further.

**Step 2 — one look, on the pooled total.** The Elo decision is taken **once**, on every game
completed, whatever that number turns out to be. The chunks exist to bound the cost of a crash, not
to provide three chances. An early chunk may **stop** the match for futility — a disaster visible at
100 games costs nothing to act on, and stopping early can only make the decision more conservative —
but **no chunk may promote**. Asymmetric stopping needs no alpha-spending arithmetic because it
errs in the safe direction.

**Step 3 — the Elo decision, exhaustive over what remains.** With `margin = −40 × sqrt(300 / n)`:

| pooled result | outcome |
|---|---|
| lower bound above zero | promote |
| point estimate < 0, **or** lower bound ≤ margin | revert both changes; v1.0 ships |
| otherwise (straddles, point estimate ≥ 0, lower bound > margin) | promote, recorded as shipping on the **safety** criterion and not the Elo rule |

The three rows are mutually exclusive and cover every case, given step 1 has passed. King safety
still has no independent safety argument: if the bundle ships by the third row, the king-danger
term ships unproven and the record says so.

### Amendment 5: the futility stop gets a number

`chessathon-5a` pointed out that "stop if chunk A is a disaster" had no threshold, and that picking
one after seeing chunk A would be a discretionary stop dressed as a rule — the same species as
defect A above, even though it errs safe. Proposed by 5a blind, at 21:4x, before chunk A landed;
accepted here after checking what it does.

**The rule: stop the match if and only if chunk A's 95 % interval has an upper bound at or below
50 %** — that is, the *optimistic* end of the interval is still a regression. That works out at a
score of **≈41 % at n = 100 and a 20 % draw rate; derived from the upper-bound rule, not an
independent threshold**, and it moves with the draw rate. The upper-bound form is the rule and the
only one in the code; the percentage is quoted because the derivation makes it legible, and labelled
as derived so nobody later treats 41 % as a second condition to satisfy.

Simulated over 20 000 chunk-A runs:

| true strength of the change | probability the rule stops the match |
|---|---|
| level (0 Elo) | 2.56 % |
| −35 Elo | 20.95 % |
| −70 Elo | 62.72 % |
| −140 Elo | 99.39 % |

It stops nearly every catastrophe, most large regressions, and a level change one time in forty.
It **can only reject, never promote**, so it spends no alpha against the promotion decision, and a
false stop costs machine time and reverts to v1.0 — which is the safe default and a build we
already have. Applied at chunk A only: by chunk B two thirds of the games are already played and
the saving no longer justifies another look.

**Tree freeze, recorded because it is not obvious and it constrains everyone.** `arena_openings`
resolves the agent under test to the **repo root** (`settings.agent.resolve()`), and
`harness/sandbox.py` spawns a fresh subprocess per game from that directory. **The working tree is
the live agent for the whole run.** So while a match is up: no merge to `main`, no edit to
`agent.py` or `mikhail_letal/`, or the pooled result becomes a mixture of two engines with no record
of which game ran which. `docs/` is safe apart from `RESULTS.md`, which each chunk appends to as it
finishes. This is also why the three chunks run sequentially rather than at once: 24 processes on 16
cores would manufacture exactly the flags the safety gate exists to detect.

## 2026-09-08 — What actually gates `main`, and what does not

Recorded because it was nearly recorded the other way round. A session checked CI, found only
other teams' fork pull requests sitting in `action_required`, and concluded that nothing runs on
pushes to `main` — that the suite gating the repository was a fiction and the real gate was
somebody remembering to run `pytest`. That would have been a strange and false thing for a judge
to read, and it was wrong for a reason worth writing down.

**`gh` resolves to the wrong repository here.** `gh repo view` returns
`advitrocks9/aichessathon-starter` — upstream, the starter kit — because this repository is a
clone of upstream rather than a fork (see the 2026-09-06 entry) and `gh` picks the remote it
finds. Every run it lists is another team's fork PR against the starter, awaiting approval, which
is exactly what "nothing of ours ever runs" looks like. Anyone verifying CI here has to pass
`--repo urvancev06/chessathon`; the bare command answers a question about somebody else's project.

**With the right repository, CI runs on every push to `main`, and it works.** It caught tonight's
failure: the merge of pull request #1 went red at 18:10:55 with eight ruff errors in
`handoff/probe.py`, and `564e88e` fixed it at 18:19:12. The suite is not a fiction. What is true
is that nobody was watching it for those nine minutes, which is a different problem with a
different fix.

**The real gap, which is larger than the one that was nearly recorded.** At the time of writing,
`main` is **14 commits ahead of `origin/main`**. Everything after the 19:09 merge is local only,
including `82b20e2` (the timing refit) and `897e1e2` (the king-danger term) — *both halves of the
build the bundle match is measuring, and of the build we would upload*. CI has never seen either.
Not because the gate is broken, but because nothing has been pushed to it.

So the accurate statement of the verification story is: the suite gates `main` on push and caught
a real failure today; the gap is that the commits that matter most have not reached it. The fix is
a push, which is safe during a match because it touches `origin` rather than the working tree that
the arena spawns each game from. It is an outward-facing action on the operator's repository and
is left to the operator.

**Why this is in the decision record at all.** The claim was checked before it was written down,
by looking at the one field — the repository name — that the conclusion depended on. A verification
story is exactly the kind of claim a reader cannot check for themselves and therefore has to trust,
which makes it the kind most worth getting right.

### Amendment 6: the safety gate is n-dependent, and how that is being handled

**The defect.** The gate says `low_clock_ms` above 5 000 ms over all completed games. `low_clock_ms`
is a **minimum over the games played**, and a minimum is monotonically non-increasing in `n`: 300
games can only ever score worse on it than 100, never better. So the gate becomes strictly harder
as the sample grows, while the same rule requires the decision to be taken on the pooled 300. We
mandated the larger sample and then wrote a criterion the larger sample can only fail harder. It is
the optional-stopping defect pointed the other way: there, more looks made promotion too easy;
here, more games make it impossible. The 5 000 was chosen as three times `panic_ms` without a
distributional model, which is the root of it.

**Who found it, and why that matters more than the fix.** `chessathon-5a` raised it partway through
chunk A, having seen partial results, and said so unprompted: that it was proposing a change to a
pre-registered gate at the moment it looked like failing, that this is exactly the move a
pre-registration exists to prevent, and that it would rather lose the change than launder it through
an amendment. It declined to make the change itself. That is the correct instinct and it is recorded
here because the reasoning deserves to survive whatever is decided.

**This session is compromised too.** 5a reported the figures before the structural flaw was
understood, so `chessathon-bb` cannot claim to be authoring a replacement blind either. Worth
stating plainly: had the observed clocks been comfortable, nobody would have noticed this defect at
all. That asymmetry — a rule is examined precisely when it bites — is the bias, and no amount of
good faith removes it from the person who has seen the data.

**The process being used instead.** `chessathon-64` has not seen the match output. It has been asked
to author a scale-free replacement **blind**: the request states the structural problem and what the
gate was trying to buy, withholds every figure, and tells it explicitly that "keep the original" is
an acceptable answer. It was also told not to infer the direction from the framing.

**The commitment, which is the part that makes this defensible.** Whatever gate is adopted, the
pooled result will be recorded in `RESULTS.md` against **both** the original gate and the
replacement, with the dates each was written. A judge can then apply either and see exactly what the
amendment changed rather than taking anyone's word that it was principled. If the two disagree, that
disagreement is the finding and goes in the report.

**If 64 declines, or does not answer before the pooled result exists, the original gate stands and
the bundle fails it.** Losing the change is an acceptable outcome. A rule amended by people who
already knew the answer is not.

### Amendment 7: the safety gate, authored blind and adopted as written

`chessathon-64` authored the replacement without having seen `RESULTS.md`, the match output or any
chunk figure, and without knowing whether either gate passes. **Adopted verbatim:**

> **(A) No game lost on time.** No game's termination is `flag`. Any occurrence disqualifies, at any
> sample size.
>
> **(B) At most 2 % of completed games have `agent_low_clock_ms` below 5 000 ms**, over the pooled
> games the decision is taken on — 2 of 100, 4 of 200, 6 of 300.

**Why this shape is right.** The intent was "the time manager is not habitually operating near the
panic floor". That is a statement about the *body* of a distribution and it was encoded as a
statement about its *extreme*. A proportion is what "habitually" means, is comparable across sample
sizes, and improves with more data rather than tightening — the precise inversion of the defect.
(A) stays absolute because a flag is a **categorical** harm rather than a quality measure: no rate
of losing on time is acceptable, so "never" is the correct encoding there and was the wrong one for
the clock condition.

**The trade-off, stated by its author rather than discovered later.** 64 was asked for a rule no
more permissive than the original at 300 games and answered that **no such rule exists**: the
original said "no game below 5 000 ms", so any rate above zero admits games the original excluded,
and every scale-free replacement is therefore strictly more permissive at n = 300. That is inherent
in fixing the defect, not a concession chosen to help. A 0 % rate is the original rule wearing a
percentage sign.

**Why 2 % and not the 1 % also offered.** 64 gave 2 % as its proposal and said 1 % was defensible.
**This session did not choose between them**, because it has seen partial data and any selection
between two offered thresholds is a selection made knowing which way it cuts. The blind author's
primary recommendation is taken as authored. That discretion was declined deliberately, and this
paragraph exists so that a judge can see it was declined rather than exercised quietly.

**Computability, checked before adoption** — the failure mode of the third amendment. `low_clock_ms`
in the `RESULTS.md` row is a run minimum and **cannot** settle a rate. `GameRecord.agent_low_clock_ms`
is recorded per game and `write_json` serialises the whole `results` list, so (B) is evaluated from
the run's `--json` file. Verified the running match writes one per chunk (`chunk0`, `chunk100`,
`chunk200`), so the data will exist.

**What gets published regardless of which gate is used.** The pooled result against **both** gates
with the date each was written, plus the underlying distribution: the count below 5 000 ms, the
count below `panic_ms`, the lowest clock and the game it occurred in, and the terminations. A judge
can then apply any threshold they prefer instead of trusting ours. 64 asked not to be told which way
its rule lands until this is recorded, and if the replacement flips the decision, that fact goes in
this file too.

## 2026-09-08 — The recurring defect of the evening: the check existed and did not check

Three separate failures tonight had one shape, and the shape is worth more than any of them
individually. In each case a safeguard was present, correctly described, and passed by an
implementation it should have rejected. Recorded together because someone auditing this repository
will find each fix in isolation and miss what they have in common.

**1. The per-term parity positions proved nothing** (`chessathon-64`). `tests/test_fasteval.py`
kept a position per evaluation term so that "a term that is simply never exercised by the playouts
cannot slip through". All four `king_shield` entries were kings and pawns only, so `phase = 0`;
`king_shield` is middlegame-only, and the phase blend multiplies the middlegame half by zero. The
four positions compared **0 against 0** and would have passed with the term deleted from one
implementation.

**2. The cold-finish test passed against the unfixed code** (`chessathon-bb`). The gate for the
warm-up's degraded path drove `get_move` with a 120 s clock. The bound it was meant to catch was
`cold_finish_fraction × time_left`, which at 120 s is 30 s — enough to compile everything on this
machine — so the test passed whether or not the defect was present. Only at a six-second clock does
it discriminate: 9 phases left uncompiled without the fix, 0 with it.

**3. The verdict tool routed around the rule** (`chessathon-bb`). `docs/DECISIONS.md` amendment 4
makes interim looks reject-only, because three looks inflate the false-promotion rate from 2.60 % to
5.71 % and the case-3 gate from 51.22 % to 70.35 %. The first version of `tools/promotion_verdict.py`
printed **PROMOTE** when run on a single chunk. **This is the worst of the three**, because the rule
still reads correctly: an auditor would have found a defensible pre-registration and a working script
that between them did the forbidden thing. The tool now refuses to emit a promotion verdict below
300 games.

**What the three have in common.** In none of them was the *stated* safeguard wrong. The parity
requirement was right, the warm-up gate was the right gate, the reject-only rule was correctly
derived. What failed was the step from the statement to the thing that runs — and each passed
silently, which is why none was found by running the suite.

Two related failures the same evening have the same root. One is a safety criterion written in
terms of a quantity the run does not record (amendment 3, uncomputable). The other happened twice,
to both sessions independently: `mypy 2>&1 | tail -1 && <next step>`. A pipeline's exit status is
the *last* command's, and `tail` succeeds whenever it prints a line, so the `&&` was gated on
nothing. `chessathon-bb` committed `tests/test_submission_contents.py` this way **while mypy was
actually failing** — an implicit re-export of `MAX_UNZIPPED_BYTES` — and the red commit stood until
a follow-up fixed it. `chessathon-64` chained the same construction before committing
`tools/freeze_version.py` and got away with it only because it read the output on screen rather
than trusting the chain. Its own description is the right one: the check was real and the *gate*
was theatre, and the safety would have evaporated the moment the output scrolled.

**A fourth variant, one level up: a test can compare two things that moved together.** Found by
`chessathon-64` while checking whether `ct-zobrist`'s "behaviour-preserving" claim — worth six hours
of machine against five minutes — had any evidence. `test_running_key_matches_a_key_built_from_scratch`
compares the incrementally carried key against that branch's `hash_position` over 100 000+ make/unmake
pairs, with an audited sample. It is a thorough test and it establishes only half of what the claim
needs. `make_move` and `hash_position` were changed **together**, so the test proves they agree with
each other, not that either agrees with `main`. Had the branch *introduced* its en-passant rule
rather than extracted it, keys would have differed from `main`'s, positions that used to hash apart
would collide, different transposition entries would hit and the search would return different
moves — a behavioural change invisible to that test **by construction**, and invisible to the parity
gates and the node rate too.

The claim holds, on two grounds that both had to be checked separately: the carried key equals the
from-scratch key (verified by that test), **and** the from-scratch key's semantics are unchanged from
`main` — verified by reading `main`'s `hash_position`, which already gates the en-passant term on an
adjacent enemy pawn being able to take. The branch extracted that rule into `ep_key_index` so the two
sites cannot drift; it did not invent it.

The general form: **when a test compares two things that changed in the same commit, the fixed point
has to be something that did not move.** `chessathon-bb` had asserted the behaviour-preserving claim
from the category without checking anything, and was right by luck; a claim worth six hours of machine
should carry its evidence at the moment it is made.

**The practice that follows, and it is cheap.** *Verify that a check fails when it should.* Every
one of the three was caught the same way: run the test against the broken code and confirm it goes
red; run the tool on the input it must refuse and confirm it refuses. A test that has never failed
is a claim, not a check.

**Cheaper still, from 64: ask at authoring time what input makes this fail.** All three cases had an
answer available before any code ran. The phase-0 positions had *none* — every candidate scored zero
on both sides, which is the defect stated in one sentence. The warm-up test's answer was "a clock too
small for the old bound", which is exactly the fix. The verdict tool's answer was "fewer than 300
games", which is now its refusal. **A check whose author cannot name its failing input has not been
designed, only written.** That question is the standard for anything added here that exists to catch
something; running the check against broken code is how it is confirmed.

### The attribution run's expected outcome, recorded before it runs

The bundle match confounds two changes deliberately, because the shipping question is "is what we
would upload better than what is uploaded". `handoff/READY-attribution-match.md` holds the runbook
for separating them afterwards: `KING_DANGER_TERM` is a plain constant at `evaluation.py:76`
imported by `fasteval.py:47`, so flipping it in one file switches both engines, and a timing-alone
build is one visible edit on a named commit in a worktree.

**What that run is expected to return, written down now so it cannot be reinterpreted later: "not
proven", and that is not a failure of the run.** At 300 games the interval resolves to about
±37 Elo. The timing refit's effect is concentrated in the minority of games long enough for
`moves_to_go` to bite — the ladder games that ran 210 and 226 plies, not the ones that ended in 36.
An effect that lives in a subset of games is diluted across the whole sample, so the instrument is
mismatched to the quantity in exactly the way the pre-registration already argues for case 3.

**Two claims must be kept apart when that number arrives**, because they will be easy to conflate at
five in the morning:

- *the instrument cannot resolve an effect of this size and shape* — supportable, and the expected
  result;
- *the change is worth nothing* — a different claim, and one this run cannot support at any sample
  size we can afford before the cutoff.

Writing this down beforehand is the only thing that keeps them separate afterwards. A null result
read as the second claim would revert a change whose justification was never Elo: two of our first
eight rated games finished on 4.7 s and 6.0 s, and a flag loses the game outright.

**Attributing the king-danger half needs its own run**, not arithmetic. Subtracting two confidence
intervals does not give the interval of the difference, so "bundle minus timing-alone" is not a
measurement of king safety. It is a second match of `main` against the timing-only worktree, and
whether there is a slot for it depends on what the bundle result requires first.

## 2026-09-08 — Round 73: four explanations, none of them confirmed

Recorded as a negative result, deliberately and at length, because the alternative is that someone
re-derives one of these tomorrow. The game is a loss the whole team can remember, which makes it the
position most likely to attract a fifth theory.

**What was proposed, and what happened to each.**

1. **Time management** (`chessathon-bb`). Stated as "every blunder landed under 15 s — 14.8 s at
   move 60, 8.0 s at 65, 9.0 s at the mate". **Those numbers were wrong, and the claim is retracted
   entirely.** The clock list was indexed by *our move ordinal* and the Stockfish blunder list by
   *fullmove number*; they were matched as though they were the same index. Re-extracted with the
   clock, the legal-move count and the move on one row, the three flagged blunders were played at
   **26.7 s, 20.8 s and 14.8 s** — not time pressure at any per-move budget. The single-digit clocks
   belong to moves 68–70, which had **two legal moves each**, and move 75 was **forced**: one legal
   move, in check. Verified against the platform log (`handoff/LOG-round-73-*.md`, committed at
   `c5fbe5e` after an evening of arguing about the game without it) which shows the last search
   returning `t 1 h 0 d 0/0 n 0` — a forced move played instantly, which is correct.

   So there is no "endgame collapse under time pressure" to explain. The moves that lost the game
   had 18–28 legal alternatives and comfortable clocks; the moves played on a low clock had no
   alternatives. Both halves of the original claim fail, and the second one fails on data that was
   available all evening.
2. **King safety** (`chessathon-bb`). Refuted by measurement: the king-danger term scores `Ka1` and
   the saving `Qxf4+` at **50 apiece**, so it returns the same number for the losing move and the
   move that holds, and cannot change the choice. Consistent with Yan's PR #4, where four variants
   across the exposure family all reproduce every blunder.
3. **A flat evaluation in a locked position** (the operator). The mechanism — with pawns fixed,
   every structural term is constant, quiescence is a no-op with no captures, so dozens of root
   moves tie and the engine shuffles — is coherent, and the shuffling was verified: 8 returns within
   six moves, 17 king moves in 68, `g1-f1-e2-d1-c1` undoing our own castling. **Its quantitative
   prediction fails.** Shuffle rate against blocked pawns, pooled over 278 middlegame moves from
   seven rated games: open 8/107, locked 7/66, **Fisher exact p = 0.580**; binning-free,
   point-biserial **r = +0.045, permutation p = 0.45**. `chessathon-5a` established that the
   bucketed 7.5 % → 12.9 % trend was mostly an artefact of boundaries chosen after seeing the data.
4. **Unconcentrated shuffling** (`chessathon-5a`), the salvage: the defect is real but structure-
   independent, so it is fixable by a cheap root tie-break and measurable with the ordinary
   instrument. **Killed by a baseline that took one command over PGNs already on disk:**

| returns a piece within 6 middlegame moves | rate |
|---|---|
| us, 7 rated games | 27/278 = **9.7 %** |
| our opponents, the same 7 games | 27/281 = **9.6 %** |
| top-5 ladder teams, 250 games | 2654/22739 = **11.7 %** |
| top-50 ladder teams, 400 games | 4110/35907 = **11.4 %** |

**The strongest teams in the field shuffle more than we do.** `Nf3-d2-f1-g3` is a textbook
manoeuvre and the metric counts it as waste, so one middlegame move in ten is what playing chess
looks like, not a defect. A tie-break that pushed us below 9.7 % would move us *away* from the field.

5. **King wandering, and a PST that makes it free** (`chessathon-bb`). The surviving anomaly looked
   like king moves: 0.125 non-castling king moves per middlegame move at ≥24 men, the 94th
   percentile of 939 field sides. A code mechanism was found for it — the king middlegame table
   scores `b1` and `c1` **identically to `g1`** (absolute values `a1=0 b1=25 c1=25 d1=-10 e1=-10
   f1=0 g1=25 h1=0`), so round 73's walk runs 25 → 0 → −10 → −10 → **25**: net zero on arrival,
   three cheap squares in transit, and nothing in the evaluation knows the king dismantled its own
   castle. **The mechanism is real; the anomaly it explains is not.** The field's kings wander
   **7.3× more** in locked positions than open ones (1.51 % at zero rams to 10.98 % at 4+), because
   a king march is a real plan when the centre cannot open. Closedness-matched, our 10 king-wander
   moves against an expectation of 6.87 give **obs/exp = 1.46, Poisson P(X ≥ 10) = 0.157**. The
   94th-percentile figure had been computed against field sides *without matching on structure*, and
   our games skew closed — round 73 alone had eight rams.

   The PST property stays on the candidate list with an honest label: **plausible defect, no measured
   harm, would need its own screen.** Not as an explanation of round 73.

**The transferable lesson, and it is now three for three: the fix was a matched baseline, never more
analysis of our own games.** Shuffling looked like a defect until it was compared against the field
(9.7 % against 11.4–11.7 %). Locked-position shuffling looked absent until the field showed a
five-fold dose-response our seven games could not resolve. King wandering looked like the 94th
percentile until it was matched on closedness and became p = 0.157. Each time the corrective was a
comparison, cost one command over PGNs already on disk, and arrived after several rounds of deeper
analysis of the same seven games. **Analysing our own data harder never once produced the
correction.**

**A rate is not a finding.** 9.7 % looked damning with nothing standing
next to it. This is the control-arm problem one level up — 5a controlled for position structure,
correctly, and that killed explanation 3; neither of us controlled for what *good play* scores on
the metric itself. The baseline was the cheapest analysis available and the fourth or fifth one run.

**What survives, stated narrowly on purpose.** The evaluation lacks mobility, space, outpost and
lever terms — a code fact, not in question. The king walk was bad. The endgame was played at
7.6–9.5 s. We lost. **The bridge between those has gone**, and round 73 has no confirmed diagnosis.
Also worth keeping: round 71 was nearly as locked (median 6 blocked pawns against round 73's 8) and
we **won** it.

**What this forbids.** The bundle match measures the timing refit and king safety. Neither addresses
any of the above, so whatever `RESULTS.md` records, it must not read as a fix for round 73. And if
the root-clustering falsifier returns thirty-way ties, that is a fact about our evaluation and
**not** an explanation of this game — we have no baseline for a good engine's root distribution and
no way to obtain one before the cutoff. The lesson above is exactly what that would be repeating.

## 2026-09-08 — `root_scores` holds bounds, not values

Found by `chessathon-5a` while instrumenting the root to test whether locked positions cluster.
Recorded on its own because it will mislead the next person who instruments this engine, and it
misleads in the most dangerous direction: **it confirms whatever you already believe.**

Reading `st.root_scores` (`fastsearch.py:1247`) after an ordinary aspirated search gives
**spread(top1 − top5) = 0 cp in every position, locked and open alike** — including one where a
capture is genuinely +150 clear — with 24–39 moves apparently "within 5 cp of best". The cause is
fail-hard alpha-beta: the null-move cutoff at `fastsearch.py:861` does `return beta`, and root moves
searched on a null window after alpha has risen come back at exactly alpha. **Those numbers are
bounds, not evaluations.** The array is not at fault — its own comment at line 213 says it exists
for the draw tie-break, a use for which bounds are correct. The fault is reading it as analysis.

Anyone investigating "the evaluation is flat" who instruments the root the obvious way gets a
spectacular confirmation, manufactured entirely by the search's bound discipline. If either
operator document's "dozens of root moves tie" came from that array, the observation was worthless.

**The correct measurement is a full window with alpha never raised at the root**, and it says
something different and real: locked positions cluster about **sevenfold** tighter than open ones
(median top-5 spread 9.5 cp against 67 cp), with the top two moves exactly tied in three of six
locked positions.

**Two reconciliations worth keeping.** That result and `chessathon-bb`'s finding — that static
evaluation gives a *uniquely* best move in 95.5 % of middlegame positions — are compatible rather
than contradictory: the evaluation does discriminate one ply out, and the differences wash out by
depth 8 because the lines transpose into each other. So the clustering is a property of locked
*positions*, not of our tables, and the quantisation framing was the wrong explanation for a real
effect. And "quiescence is a no-op in locked positions" is false: 710 000–1 350 000 captures entered
quiescence in exactly these positions. Root captures were 0–2, so the documents generalised from the
root to the tree.

**Nothing is being changed on the strength of it before the cutoff.** A tighter root spread in
closed positions may simply be what closed positions are; we have established that we shuffle
normally for how locked our positions are and that the field's kings wander the same way. Acting
needs a change that is measurably better, and there is not one.

### Interim, chunk A: futility says continue, and a warning about how thin the gate is

At 95 of 100 games in chunk A the pre-registered futility test was evaluated and **does not fire**:
+40 =23 −32, score 54.2 %, 95 % interval 45.5 % to 63.0 %. The rule stops the match only if the
upper bound is at or below 50 %; it is 63.0 %. Reproduced independently from
`tools.arena_openings.statistics`. **No promotion is read from this and none is available**: chunk
looks are reject-only (amendment 4), and the interval above exists solely to evaluate futility.

Terminations so far: checkmate 72, threefold 19, insufficient material 3, fifty moves 1, **flag 0**.
Clock: minimum 3 729 ms, p10 11 962, median 28 043, **2 games below 5 000 ms, none below
`panic_ms`**.

**The warning, recorded before the pooled result exists because it cannot be said credibly
afterwards.** The adopted gate allows 2 % of games below 5 000 ms — **six** of 300. The observed
rate is 2 of 95, which projects to **6.3** of 300. So the safety gate may be decided by a single
game either way.

That has a consequence for how the verdict should be read, and it is not a reason to change
anything: **whichever side of the line it falls, the gate's outcome carries little information.**
A pass at 6 and a fail at 7 differ by one game out of three hundred and by nothing else. If the
bundle promotes on a 6, nobody should treat the safety condition as having been demonstrated
robustly; if it fails on a 7, nobody should treat the build as having been shown unsafe. The
figure to weigh in both cases is the one that is not marginal: **no game below `panic_ms`**, and
**no flag** — which is the floor the safety argument actually rests on, and it is not close.

This is stated now so that it constrains the write-up in either direction rather than being
available afterwards to whichever side needs it.

## 2026-09-08 — Reading this file: the defects were in the checking, not the engine

`chessathon-64`'s framing, adopted because a reader arriving at this file tomorrow will otherwise
draw the opposite conclusion from its length. Tonight produced roughly eight findings and they read
like a build in trouble. **That is not what we have.**

Sort them by where the fault was:

**In the checking, not the engine** — a per-term parity test whose positions scored zero on both
sides; a warm-up gate that passed against the code it was written to catch; a promotion rule that
could not be evaluated from what the run records; a verdict tool that made the forbidden action
easy; a shipped provenance record naming the wrong constant and the wrong module; a `mypy` check
gated on `tail`'s exit status; a `root_scores` array whose contents confirm whatever the reader
already believes; a "behaviour-preserving" claim resting on a test comparing two things that changed
together.

**In the engine** — none of the eight. The candidate defects that survived the evening are
`rook_eg` identically zero across 64 squares, a king table scoring `b1` and `c1` the same as `g1`,
and a missing family of mobility, space, outpost and lever terms. All three are **plausible defects
with no measured harm**, and none is shipping.

**What the engine actually did, in the same period.** 5 wins, 1 draw, 2 losses over rated rounds
67–74. **100 real-clock games in chunk A with no `flag`, no crash and nothing below `panic_ms`.**
Start-up, from five samples rather than the two that made it look bimodal: 34.1, 35.2, 35.6, 35.8
and one outlier at 50.7 s, against a warm-up deadline armed at 70 s and a 90 s budget — a 19.3 s
margin at the worst observed, with zero warm-up phases skipped in every sample.

**The recurring shape, five times in one evening: an unmatched number is uninterpretable, and the
correction was always a comparison that already existed on disk.** Our shuffle rate looked damning
until the field's was 11.4–11.7 % against our 9.7 %. Locked-position shuffling looked absent until
the field showed a fivefold dose-response seven games could not resolve. King wandering looked like
the 94th percentile until it was matched on closedness and became p = 0.157. Root-move clustering
looked like nothing until an open control made it sevenfold. Start-up variance looked bimodal until
three more `init` lines were read from logs already stored. It cut in **both** directions — twice
making a defect vanish, once making a real effect appear — so it is not a bias toward comfort.
Analysing our own seven games harder never once produced the correction.

**The other half of the frame, which `chessathon-64` supplied and without which this entry is
self-congratulatory: almost every defect was in the checking — and we found them mostly by checking
each other's checks, not our own.** Every item in the list above was caught by a session other than
the one that wrote it, or by its author only after another session asked a question. The phase-0
positions, the `mypy` pipe, the void-counting bug, the unverified behaviour-preserving claim, the
n-dependent gate, the misaligned clock indices — each was found by someone who had not written it.
Where a defect *was* caught by its author, it was because a question from elsewhere prompted the
re-reading. **The takeaway is that checking needs checking, not that our checking was bad**, and
the mechanism was three participants none of whom deferred.

**The practical reading.** A long findings list is what a team looks like when it is checking its
checks. The engine's own record over the same hours is the thing to weigh, and it is unremarkable
in the way a shippable build should be.

**A note on the decision machinery, since it bears on trusting the pooled result.** `64` verified
the adopted gate against inputs **constructed to break it** rather than against whatever the match
happened to produce — both sides of the n=100 boundary (2 below passes, 3 fails), the non-integer
allowance at n=150, a flag disqualifying despite a clean clock, and 300 games containing two voids
correctly refused as an interim look at 298. Real data exercises a boundary only by luck. Separately
the tool ran on chunk A's real output and behaved as designed, including the two fixes applied hours
earlier: **a fix applied at 22:00 and first exercised at 04:00 is a fix nobody has tested.**
## 2026-09-08 — The position key is carried forward by `make_move`, in the undo stack

`fastboard.hash_position` walks both piece lists and XORs up to thirty-two numbers, and the
compiled search called it once at every node (`quiescence` and `negamax` on entry, twice more at
the root). That rebuilds from scratch what a move changes in at most five places. `make_move` now
carries the key forward instead: it XORs out the piece that left its origin and any captured
piece on its *real* square (which is not the destination for en passant), XORs in the piece that
arrived (a different piece after a promotion), does the same pair for the rook of a castling
move, swaps the rights-combination term whenever a right is actually lost, flips the side-to-move
term, and takes out the old en passant term and puts in the new one. `hash_position` stays as the
reference implementation: `set_from_board` seeds the key with it, `check_invariants` and the new
gate 4 check the carried key against it, and no search node calls it.

**Where the key lives, and why that was the interesting question.** The first version put it in a
sixth array in the `Position` tuple, `key[K_CURRENT]` with a saved value per ply for `unmake_move`
to restore. It was exact and it was *slower*: perft dropped 14–17%, and a fixed-node search of a
rook ending lost 6.7%. The ablation says why — a `Position` with a sixth array, allocated but
never read, already costs 8–10% of perft on its own, because every compiled function taking a
`Position` passes one more array descriptor through the call. Measured on this machine, perft
from the standard position and Kiwipete, best CPU time of seven runs in each of three processes:

| | start depth 5 | Kiwipete depth 4 |
|---|---|---|
| before | 0.364 s | 0.311 s |
| + a sixth array, never touched | 0.394 s (0.92x) | 0.340 s (0.92x) |
| + the key carried in the undo stack | 0.382 s (0.95x) | 0.321 s (0.97x) |
| + the key in a sixth array | 0.439 s (0.83x) | 0.361 s (0.86x) |

So the key rides in the undo stack, which every position already has, and `undo` becomes int64 to
hold it. `U_KEY` is the one column that describes the position *at* that ply rather than the move
played from it: `make_move` reads row `ply` and writes row `ply + 1`, so `unmake_move` restores
nothing at all — dropping a ply uncovers the key that position already had. That also removes the
save-and-restore the first version needed, and with it the only place a delta could have been
undone wrongly.

**Measured.** Exactness first: the carried key equals `hash_position` after every make and every
unmake over 1,092,414 comparisons — forty-ply walks from 397 starts (the 219 curated openings, 58
hand-built rule-breaking positions, 120 random-playout positions), every pseudo-legal move made
and unmade at every ply, with the walk audited for 1,012 promotions, 256 capture-promotions, 47
en passant captures, 1,637 castling moves and all sixteen castling-rights combinations. Then
identity: a fixed 200,000-node search from thirty positions returns the same move, score, depth,
seldepth and **node count** (6,005,770 in total) as the previous build, so the tree is unchanged.
Then speed, as CPU time for a fixed 600,000 nodes, best of sixty runs across five interleaved
processes: standard position 0.808 → 0.784 s (1.03x), middlegame 0.865 → 0.814 s (1.06x), rook
ending 0.713 → 0.668 s (1.07x); at the tenth percentile, 1.045x, 1.044x and 1.042x. In three
seconds of wall clock the depth reached is unchanged (12, 11 and 14). A rating measurement was
running on the same machine throughout, which is why the fixed-node CPU comparison is the one
quoted and the wall-clock nodes-per-second numbers are not.

**Rejected: passing the Zobrist table into `make_move`.** It would change `gen_legal`, `perft`,
`has_legal_move` and every call site in the search and the tests, and buy nothing: numba freezes
a module-level array as a compile-time constant and reads it exactly as fast as an argument.

**Rejected: reversing the deltas in `unmake_move`.** Twice as much code that has to be right, in
the direction that is harder to reason about, and slower than reading a row that is already
there.

**Rejected: two int32 halves in `meta`.** It avoids the int64 undo stack and keeps "every array is
int32" intact, but every read and write of the key becomes a shift-and-mask pair, on a value the
search reads at every node, to save a dtype.

## 2026-09-09 — Three pruning techniques, chosen by published Elo rather than by plausibility

> **This batch measured −21 Elo and has not shipped. Read to the end of the file before acting on
> anything below.** Screened head-to-head against the identical build without it, 300 games:
> +120 =42 −138, 47.0 % ± 5.2 %. Two defects were found in it afterwards — late move pruning had
> no principal-variation guard, and the justification quoted below describes an ordering
> (captures sorted by static exchange evaluation) that exists only on a branch. This guard is here
> because `DECISIONS.md` reads newest-at-the-bottom, so a reader in a hurry meets the published
> +116 in this entry and would have to keep reading to find that it did not transfer. Pointed out
> by `chessathon-86`, which found the same defect in its own entry first.

A four-lane research pass read the literature for techniques with **measured** Elo, then checked
each against this code, then had a separate pass try to refute it. The ranking criterion was not
"is this a good idea" but **"is the published effect large enough for a 300-game screen resolving
±39 Elo to detect"** — because an improvement we cannot measure is a coin flip we cannot justify.

Adopted: reverse futility pruning (+57.1 ± 16.9 over 1209 games), futility margins extended from
two plies to five (+37.4 ± 13.4 over 1780 games), late move pruning (+21.9 ± 11.4 over 2000
games). All three from Blunder 8.0.0, whose evaluation at the time of measurement was material +
tuned piece-square tables + tapering — **strictly weaker than ours**, which is the closest
published base we could find to our own.

**Rejected, each with its number, so none is rebuilt on enthusiasm:** razoring (+7.9 ± 7.4 over
4550 games), ProbCut (+6.36 ± 4.59 over 10928 games), singular extensions (Weiss's author reports
his first attempt failing, "possibly due to poor eval"), the improving heuristic, bucketed
transposition tables, opening books, and any change to the time manager. All sit below what 300
games can resolve.

**Contempt is rejected on two independent grounds**, which is the one worth recording. Published
at +7.1 ± 3.9, with the gain scaling with the strength gap in the wrong direction for us. And
separately, measured here: across 63 threefold draws in the field corpus, the side that was
materially **ahead** played the repeating move in only 22% of them. Contempt only helps where we
choose the repetition; where the opponent forces it, it buys nothing.

**Why reverse futility is expected to transfer when most pruning does not.** Its trigger is
material-sized — 255 cp at depth 3 — so it fires on material imbalance, which this evaluation
computes exactly, rather than on positional judgement, which is where the missing mobility term
hurts. The contrast is the improving heuristic, which is a *difference* of two static evaluations
two plies apart: with piece-square tables quantised to five distinct middlegame queen values and
an identically-zero endgame rook table, that difference is zero across most quiet move pairs, so
the flag degenerates toward constant and its published gain cannot transfer.

**Two defects found in the implementation after it was written, both by something other than the
author.** The research specified a guard against running at principal-variation nodes that was not
implemented: returning a static bound where the caller wants a real score corrupts what reaches
the root, and **nothing would have caught it** — no test fails, and the cost appears later as a
screen that comes back flat for no visible reason. And
`test_aspiration_windows_keep_the_score_exact_without_the_window_heuristics` failed by 8 cp,
correctly: both new techniques read the window, and neither had been added to the list of
window-dependent heuristics that test switches off. It detected that a window-dependent heuristic
had been introduced without being declared, which is not something the author notices.

**Not claimed:** any Elo for this engine. The published numbers come from a different engine, and
three static-margin pruners overlap heavily, so they do not add. The screen decides.

## 2026-09-09 — One-ply continuation history, and deliberately not two

The plain history heuristic credits a quiet move by its from- and to-square alone, so everything
it knows about `Ng1-f3` is summed over every position in which that move was ever a cutoff. That
is a lot of evidence about a move and none at all about *when* the move is good, and the answer is
usually "as a reply to something specific". `CONTINUATION_HISTORY` adds one previous move of
context: a second table indexed by (side to move, the piece the previous move moved, where it
moved to, the piece this move moves, where it moves to), carrying the same `depth * depth` credit
on the same cutoffs, read beside the plain table when quiet moves are ordered.

Why this and not another ordering idea: it is the one candidate with a published SPRT-quality
number large enough for a 300-game screen to resolve, and — the reason it was chosen over the
others — it contains no evaluation term at all. It is a pure ordering signal, so the weak static
evaluation that discounts most published gains for us does not apply to it.

**Rejected: a plain counter-move table.** A single stored refutation per previous move is the
rank-1 special case of the same information, has no comparable public measurement, and would have
to be torn out again the moment this was added.

**Rejected: two plies of context (follow-up history) as well.** A separate technique with a
separate number; both at once would leave a screen unable to say which one paid.

**Rejected: history gravity** (`entry += bonus - entry * |bonus| / MAX`), which is what the
reference engines pair this with. It is a different *update rule* for both tables, not a new
context channel, and bundling it would mean a screen measuring two changes. The new table
therefore reuses the plain one's saturating addition and its halving between moves exactly.

**Rejected: giving each table half the ordering band.** The sum of two tables that each saturate
at `_HISTORY_MAX` reaches nearly twice `_ORDER_KILLER_SECOND`, so a quiet move could outrank first
a killer and then a capture — silently, because nothing else in the search checks the bands.
Halving `_HISTORY_MAX` would have fixed it by changing when the *plain* table saturates, which is
a second behavioural change riding along. The sum is clamped instead: the plain table's dynamics
are untouched and the bands cannot be crossed by construction.

The table introduces no tuned number of its own. The bonus, the cap and the ageing are the plain
table's; the shape is the board's (piece types × squares, twice, plus side to move). The compiled
engine sizes the square dimension 128 rather than 64 because it indexes 0x88 squares, exactly as
the two `history` tables already differ; that is a relabelling of the same five coordinates and
neither engine ever reads the other's table.

Two things this had to get right that a test would not otherwise reach. The node directly under a
**null move** has no previous move — passing refutes nothing — and without an explicit reset it
would inherit the row a sibling left in that slot and credit its cutoffs to a move never played on
that line. And the **root** has no previous move either: the position arrives as a FEN and the
opponent's last move is not part of it.
`tests/test_search.py::test_every_node_knows_the_move_that_led_to_it_and_a_null_move_leads_to_none`
checks both at every node of a real search, and counts the nodes it saw in each case so it cannot
pass vacuously on a position that never reaches one of them.

No Elo claim here: the screen decides.
