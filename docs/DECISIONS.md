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
