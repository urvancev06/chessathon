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
