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
