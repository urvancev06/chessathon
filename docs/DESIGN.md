# Design — Stage 0 engine (Mikhail LeTal, package `mikhail_letal`)

This is the module contract for the Stage 0 build. Every module below is implemented against these
signatures so the pieces fit together without renegotiation. The brief (`claude code brief.md`) and
the repo's `CLAUDE.md` govern; this file records how they are applied.

The engine is called **Mikhail LeTal** (a pun on Mikhail Tal). Its Python package is
`mikhail_letal`, because package names must be lowercase identifiers. The name shadows nothing
(`python -c "import mikhail_letal"` fails on the bare interpreter, and it is not in
`sys.stdlib_module_names`).

## Layout

```
agent.py                 SHIPS   entrypoint: safety wrapper + driver (imports mikhail_letal only)
mikhail_letal/__init__.py         SHIPS   package marker, version string, `feature_flag` (env-overridable switches)
mikhail_letal/evaluation.py       SHIPS   tapered material + PST evaluation, structural terms (v0.2), mop-up term
mikhail_letal/searchboard.py      SHIPS   the board the search moves on: chess.Board + running evaluation totals (v0.3)
mikhail_letal/search.py           SHIPS   iterative deepening alpha-beta searcher (v0.2: NMP, LMR, aspiration, futility, delta)
mikhail_letal/timing.py           SHIPS   time budget formula (all constants in one dataclass)
mikhail_letal/gamestate.py        SHIPS   per-game position history (repetition tracking, desync reset)
mikhail_letal/fallback.py         SHIPS   fast always-legal fallback move
weights/pst.json         SHIPS   generated tables with a provenance header
weights/PROVENANCE.json  SHIPS   machine-readable provenance for every shipped number
tools/gen_pst.py                 the parametric prior: tables, piece values, structural weights (--out weights/pst.json ships it)
tools/tune_texel.py              Texel-style ridge fit of every weight toward that prior (v0.3 experiment, rejected; not shipped)
tools/collect_openings.py        collects curated opening FENs from public game pages
tools/arena_openings.py          arena over data/openings.txt, parallel workers, same statistics
tests/                           pytest suite (unit, property, fuzz helpers)
versions/                        frozen copies of uploaded builds
docs/                            DESIGN, DECISIONS, RESULTS, PROVENANCE, CALIBRATION, report.tex
data/                            openings.txt, tuning positions and labels (data/tuning/), other collected data
```

Rules: `agent.py` and `mikhail_letal/` import only the standard library and `chess`. Nothing under `mikhail_letal/`
imports `tools/`, `tests/`, `harness/` or `numpy`/`numba` (Stage 1 adds numba). No file in the zip
is named after a stdlib or stack module. No randomness anywhere in the shipped code path.

## Shared conventions

- Scores are integers in centipawns from the perspective of the side to move (negamax).
- `MATE_SCORE = 100_000`. A mate delivered at `ply` from the root scores `MATE_SCORE - ply`; being
  mated scores `-(MATE_SCORE - ply)`. `MATE_THRESHOLD = MATE_SCORE - 1_000` separates mate scores
  from evaluations. `DRAW_SCORE = 0`. `MAX_PLY = 128`.
- Position keys are `board._transposition_key()` (python-chess's own repetition key: piece
  bitboards, turn, castling rights, en passant square). Type alias `Key = Hashable`. It is what
  `Board.is_repetition` uses, so repetition detection agrees with the referee.
- Square indexing follows python-chess (`a1 = 0`, `h1 = 7`, `a8 = 56`). Tables are stored from
  White's point of view; a Black piece on square `s` reads the table at `s ^ 56`
  (`chess.square_mirror`).
- Wall time is `time.perf_counter()` everywhere. Deadlines are absolute `perf_counter()` values.

## `mikhail_letal/evaluation.py`

```python
MATE_SCORE: int
MATE_THRESHOLD: int
DRAW_SCORE: int
PHASE_TOTAL: int                      # 24 when all non-pawn pieces are on the board

def load_tables(path: Path | None = None) -> Tables   # reads weights/pst.json; called once at import
def game_phase(board: chess.Board) -> int             # 0 (bare endgame) .. PHASE_TOTAL (full board)
def material_pst(board) -> tuple[int, int, int]       # (mg, eg, raw phase) from scratch, White's view
def evaluate_running(board, mg, eg, phase) -> int     # everything that is not the per-piece sum
def evaluate(board: chess.Board) -> int               # static evaluation, side-to-move perspective
def is_mate_score(score: int) -> bool
def pawn_structure(white_pawns: int, black_pawns: int) -> tuple[int, int]  # (mg, eg), White's view

STRUCTURE_TERMS: bool                 # feature_flag("LETAL_EVAL_TERMS", True)
STRUCTURE_WEIGHTS: dict[str, int]     # every structural weight, one line of rationale each
```

Behaviour:

- `weights/pst.json` holds `piece_values_mg`, `piece_values_eg` (keyed `P N B R Q K`), `pst_mg`,
  `pst_eg` (64 ints each, index = python-chess square from White's view), `phase_weights`
  (`N B R Q`), and a `_provenance` object (generator script, git commit, parameters, date). The
  file is located as `Path(__file__).resolve().parent.parent / "weights" / "pst.json"` so it works
  from the repo, from `versions/vX.Y/`, and from the extracted zip.
- Where the numbers come from: `tools/gen_pst.py` is the prior (geometric PST formulas, textbook
  piece values, `STRUCTURE_PRIOR`); `tools/tune_texel.py` can refit every weight by closed-form
  ridge regression toward that prior on Stockfish-labelled quiet self-play positions (its
  `features(board) @ weights` reproduces `evaluate()`, which the tests check). The file's
  `_provenance.generator` names whichever produced it and the tests reproduce it from that
  generator. The 2026-09-07 fits lost to v0.2 in the arena (DECISIONS.md), so the shipped tables
  are the prior.
- At load, build combined tables `mg[piece_type][square] = value + pst` and likewise `eg`, so the
  hot loop does one lookup per piece.
- `evaluate` iterates `board.pieces_mask(piece_type, colour)` bitboards with `chess.scan_forward`
  (no `piece_map()`, no `Piece` objects). Tapered:
  `score = (mg * phase + eg * (PHASE_TOTAL - phase)) // PHASE_TOTAL`, then negate for Black to
  move.
- If `board.is_insufficient_material()` return `DRAW_SCORE`.
- Mop-up term (only when one side has a bare king and the other has at least a rook's worth of
  material, or two minors, and there are no pawns): the stronger side gains
  `mopup_edge * centre_manhattan_distance(weak_king) + mopup_close * (14 - manhattan(king, king))`
  where the two weights come from `pst.json` (`mopup`). Derived from the geometric idea (drive the
  king to the edge, bring ours close), not from any engine's constants.
- Structural terms (v0.2, behind `STRUCTURE_TERMS`), all from bitboards, added to `mg`/`eg`
  before the blend so the tapering and the truncation rule apply to them too:
  - passed pawns: a pawn with no enemy pawn ahead on its own or an adjacent file (enemy front
    spans computed with a file fill and two lateral shifts, then complemented) scores
    `passed_pawn_mg`/`passed_pawn_eg` per rank of advancement (2nd rank = 1 ... 7th = 6);
  - doubled pawns: `doubled_pawn` per pawn with an own pawn ahead on its file (a south fill
    counts each extra pawn on a file exactly once);
  - isolated pawns: `isolated_pawn` per pawn on a file whose neighbouring files hold no own pawn
    (files squashed onto rank 1, neighbours by shift, spread back with `* 0x0101...01`);
  - bishop pair: `bishop_pair` when a side has two or more bishops;
  - rooks: `rook_open_file` on a file without pawns, else `rook_semi_open_file` on a file without
    own pawns;
  - king shield (middlegame only): `king_shield` per own pawn on the three files around the king,
    one or two ranks ahead of it (precomputed 64-square masks per colour).
  The pawn-only part is a pure function of the two pawn bitboards and is cached in
  `_PAWN_CACHE` (cap `PAWN_CACHE_MAX_ENTRIES = 50 000`, emptied when full).
- No randomness. `evaluate` itself is a pure function of the board; the searcher caches its
  results by piece placement and side to move (`Engine._evaluate`, below).

## `tools/gen_pst.py` and the parametric prior

Every table entry is a formula of the square's geometry with a handful of named parameters, all
listed in the script's `PARAMETERS` dict and copied into the JSON's `_provenance.parameters`:

- `centrality(sq) = 3 - max(|file - 3.5|, |rank - 3.5|)` in `{-0.5, 0.5, 1.5, 2.5}` shifted so the
  centre four squares are highest; `advancement(sq, colour)` is the rank from the side's own view
  (0..7).
- Pawn: middlegame `adv_mg * advancement + centre_mg * central_file_bonus` (d/e files only,
  ranks 3–5), endgame `adv_eg * advancement ** 2 / 7` (passed-pawn shaped incentive), second-rank
  pawns unmoved get zero.
- Knight: `knight_centre * centrality` in both phases, rim penalty `knight_rim` on the outer ring.
- Bishop: `bishop_centre * centrality` (both phases), small bonus on the two long diagonals.
- Rook: middlegame `rook_seventh` bonus on the 7th rank and `rook_centre_file` on d/e files;
  endgame flat.
- Queen: `queen_centre * centrality * 0.5`, middlegame penalty `queen_early` for leaving the back
  two ranks with the full board (encourages development of minors first).
- King middlegame: `king_shelter` bonus on b1/c1/g1 (castled squares), `king_centre_penalty` for
  the d/e files and for advancement beyond rank 1; king endgame: `king_centre_eg * centrality`.
- Piece values start at the textbook 100/320/330/500/900 (recorded as textbook; the 2026-09-07
  Texel fit of them was rejected in the arena, DECISIONS.md), and `STRUCTURE_PRIOR` holds the
  hand-chosen structural weights with one line of reason each.

The script is deterministic, writes `data/tuning/prior_pst.json` by default (`--out weights/pst.json` writes the shipped
file together with `weights/PROVENANCE.json`), and prints
the tables as 8x8 grids for a human to read. The generated numbers are ours by construction; they
match no published engine's tables.


## `tools/tune_texel.py` (Texel-style fit toward the prior; experiment of 2026-09-07)

Subcommands `positions`, `label`, `fit`, `all`, `check`. The evaluation is linear in its weights,
so the fit is closed-form ridge regression: `features(board)` is one row of counts per weight
(piece values, 64 squares × 6 pieces × 2 phases from the owner's view, the eight structural
counts), each scaled by the phase share so that `features(board) @ weights` equals `evaluate()`
from White's view up to the blend's truncation (asserted on every position). The penalty is
λ·‖w − w_prior‖² toward `gen_pst.py`, the pawn's middlegame value is fixed at 100, λ comes from
5-fold cross-validation on the label MSE, the result is rounded to integers and written to
`weights/pst.json` (`_provenance`: generator, commit, data paths and sha256, labeller, λ, MSE, run
id), `weights/PROVENANCE.json` and the `STRUCTURE_WEIGHTS` values in `evaluation.py` (the
`# tuned-by:` line above the dict). Positions: seeded self-play of `search.Engine` at 2 000
nodes/move from `data/openings.txt`, quiet positions only (quiescence value = static evaluation);
labels: Stockfish at depth 10, White-POV centipawns clipped to ±1500 (local install, never
shipped). `check` refits at the recorded λ and compares with the shipped file; the tests do the
same when `_provenance.generator` is the tuner, and regenerate the prior when it is `gen_pst.py`.

## `mikhail_letal/search.py`

```python
@dataclass
class SearchResult:
    move: chess.Move | None     # None only if the position has no legal moves
    score: int                  # side-to-move perspective, from the last completed iteration
    depth: int                  # last completed iteration depth
    seldepth: int               # deepest ply reached including quiescence
    nodes: int
    elapsed: float              # seconds, measured inside search()
    aborted: bool               # the hard deadline or the node limit stopped an iteration

class Engine:
    def __init__(self, tt_max_entries: int = 250_000) -> None: ...
    def new_game(self) -> None: ...          # clear TT, evaluation cache, killers, history heuristic
    def search(
        self,
        board: chess.Board,
        history: Mapping[Key, int],          # keys of every earlier position in the game, incl. root
        soft_deadline: float,                # perf_counter(): do not start an iteration after this
        hard_deadline: float,                # perf_counter(): abort the search when reached
        max_depth: int = 64,
        node_limit: int | None = None,
    ) -> SearchResult: ...

# v0.2 feature switches, each feature_flag("LETAL_...", True); the arena's --env turns one off.
NULL_MOVE_PRUNING, LATE_MOVE_REDUCTIONS, ASPIRATION_WINDOWS, FUTILITY_PRUNING, DELTA_PRUNING: bool
```

Behaviour (v0.2; the v0.1 searcher is this without the staged generation, the caches and the five
switched features, all of which were added under measurement, see DECISIONS.md):

- Iterative deepening from depth 1. After each completed iteration, stop if
  `perf_counter() >= soft_deadline`, if the score is a mate score with the shortest mate already
  found at this depth, or if `depth >= max_depth`. The caller sets `soft_deadline` to
  `start + next_iteration_fraction * soft_ms` (see timing).
- Inside the search every `NODE_CHECK_INTERVAL = 128` nodes read the clock and raise
  `SearchAborted` past `hard_deadline` or past `node_limit`. On abort, return the best move of the
  last completed iteration, or the current iteration's best if the previously-best move was
  searched first and a later move beat it before the abort.
- Root: order moves by the previous iteration's best move first, then the ordering below; if
  that first move is an under-promotion, the queen promotion of the same pawn is searched before
  it, so the queen wins an exact tie. Track `best_move` and `best_score` per iteration. When the
  best score is exactly `DRAW_SCORE`, at least two root moves tie at it and the root static
  evaluation is ≥ `DRAW_TIEBREAK_MARGIN` (300), the tied move whose child evaluates best (from
  our side, stalemates excluded) is chosen: a rule draw inside the horizon must not stall a
  mop-up (only when the score is exact, i.e. inside the window).
- Aspiration windows (`ASPIRATION_WINDOWS`): from `ASPIRATION_MIN_DEPTH = 4`, once an iteration
  has completed and its score is not a mate score, the root is searched inside
  `previous ± ASPIRATION_WINDOW (40)`. A score on or outside an edge is a bound: the failing edge
  is moved to `bound ∓ window * ASPIRATION_WIDEN (4)` and the iteration repeated (a fail-high move
  is searched first in the repeat); after `ASPIRATION_MAX_FAILS = 2` failures the full window is
  used. `_partial` (the abort salvage) is only set by a root move whose score beat the window's
  alpha, because a score at or below alpha is an upper bound and cannot rank moves.
- Node: terminal checks in this order: (1) `board.ply() >= 600` → draw; (2) repetition: key in
  `history` or in the search path → `DRAW_SCORE`; (3) halfmove clock ≥ 100 → checkmate or draw;
  (4) in check → depth += 1 (check extension, capped by `MAX_PLY`), *before* the probe so that
  probe and store see the same depth; (5) TT probe (depth-sufficient, mate scores adjusted by
  ply); (6) depth ≤ 0 → quiescence; (7) register the position on the path; (8) null-move
  pruning; (9) the futility decision; then the staged move loop with (10) late-move reductions.
  No legal move and nothing pruned → mated or stalemate.
- Null-move pruning (`NULL_MOVE_PRUNING`): when not in check, `depth >= NULL_MOVE_MIN_DEPTH (3)`,
  the previous ply was not a null move, neither window bound is a mate score, the side to move
  has a piece other than king and pawns, and the static evaluation is ≥ beta, the side passes
  (`chess.Move.null()`) and the reply is searched at `depth - 1 - R`, `R = 2 + depth // 6`, with
  the window `(beta - 1, beta)`. A result ≥ beta that is not a mate score cuts the node: the
  node returns `beta` and stores a LOWER bound at `depth` (with the table move as the hint).
  Never in quiescence.
- Futility pruning (`FUTILITY_PRUNING`): at `depth` 1 and 2, not in check and with no mate bound
  in the window, if `static + FUTILITY_MARGINS[depth] (150 / 300) <= alpha`, the quiet moves of
  the node (killer and history stages; never the table move, never captures or promotions) are
  skipped. The node's fail-soft value is then `max(best searched, static + margin)`, an upper
  bound ≤ alpha, and a node that pruned something is never mistaken for mate or stalemate.
- Late-move reductions (`LATE_MOVE_REDUCTIONS`): at `depth >= LMR_MIN_DEPTH (3)`, not in check,
  moves from the quiet (history) stage after the first `LMR_FULL_DEPTH_MOVES (3)` searched moves
  are searched at `depth - 1 - LMR_REDUCTION (1)`; a reduced result above alpha is re-searched at
  full depth before it is believed. Table move, captures, promotions and killers are never
  reduced.
- Staged move generation (`_staged_moves`, exact: the order equals the sorted full list, verified
  move-for-move on 30 openings at a fixed node limit): (1) the table move, without generating
  anything; (2) captures and promotions from `_capture_moves`, sorted by MVV-LVA (victim rank × 10
  − attacker rank, a promotion counting the promoted piece as victim);
  (3) the two killers of this ply if `board.is_legal` says they are legal quiet moves here;
  (4) quiet moves from two masked calls (non-pawns to non-enemy squares, castling included;
  non-promoting pawns to empty non-en-passant squares) sorted by the history heuristic
  `history[colour][from << 6 | to]` (bonus `depth * depth` on beta cutoffs). Each stage is
  generated only if the search asks for more moves, and every move is tagged with its stage so
  the cutoff code knows quiet moves without `is_capture`. The root still sorts its full list.
- Capture generation (`_capture_moves`, v0.3, exact): with no check on the board it walks the
  bitboards itself in python-chess's own generation order — non-pawn pieces from the high square
  down and each piece's targets from the high square down, then pawn captures, then promotion
  pushes by pawns on the promotion rank, then en passant (python-chess's `generate_legal_ep`, which
  is full of corner cases). The branch that says which piece stands on the from-square yields both
  its attack set (from `BB_KNIGHT_ATTACKS` / `BB_KING_ATTACKS` / the occupancy-indexed slider
  tables) and its rank in the MVV-LVA key, so the key is built during generation and no move needs
  a `piece_type_at` afterwards. Legality is `Board._is_safe`'s rule, not a new one: the king may
  not step onto a square the enemy attacks, and a piece shielding the king from a slider may only
  move along `BB_RAYS[king][from]` — the same test as `ray(from, to) & king`, applied once per
  piece as a mask instead of once per move. In check the evasion rules apply instead and the
  previous implementation, kept verbatim as `_capture_moves_in_check`, answers. Ties in the key
  keep the generator's order under a stable sort, so the move list is identical to v0.2's.
  Measured 10.7 → 4.6 µs per call in a busy middlegame.
- Quiescence: stand pat with `evaluate`, tested against beta *before* any move generation (a
  stand-pat cutoff ends most quiescence nodes; a position with no legal move is still scored as
  mate or stalemate, never evaluated); then captures via `board.generate_legal_captures()` plus
  queen promotions, MVV-LVA ordered (`_capture_moves`). In check, every evasion is searched for the first
  `QS_EVASION_PLIES = 4` quiescence plies; deeper checks are handled like any other node so dense
  positions cannot explode. "Is the position over?" is asked through `_has_legal_move` (v0.3,
  exact): with no check on the board, any pseudo-legal move of a piece that is not shielding its
  king is legal, so one pawn that can step forward or one piece with a square to go to answers it;
  when that finds nothing, python-chess's generator does (2.4 → 0.5 µs in the common case). Delta
  pruning (`DELTA_PRUNING`): where the side could stand pat (not
  in check, alpha not a mate score), a capture is skipped if `stand_pat + gain + DELTA_MARGIN
  (200) < alpha`, with `gain` the middlegame value of the captured piece (a pawn for en passant)
  plus queen − pawn for a promotion. `seldepth` tracked; quiescence depth capped at `MAX_PLY`.
- Evaluation cache (`Engine._evaluate`): stand-pat, futility and null-move static evaluations go
  through a dict keyed on `(pawns, knights, bishops, rooks, queens, kings, white occupancy,
  turn)`, which is exactly what `evaluate` depends on. Cap `EVAL_CACHE_MAX_ENTRIES = 100 000`,
  emptied when full and by `new_game`. About half the evaluations of a search hit it. Since v0.3 a
  miss costs only the structural terms and the phase blend, because the per-piece sums come from
  the `SearchBoard`'s running totals; the cache still pays for itself on the rest.
- Transposition table: `dict[Key, TTEntry]` where `TTEntry = (depth, score, flag, move_code)`,
  every field an int (`move_code = from | to << 6 | promotion << 12`, `-1` for none; the
  `chess.Move` is rebuilt at the probe), and `flag ∈ {EXACT, LOWER, UPPER}`. Int-only entries keep
  CPython's generation-2 garbage collections to milliseconds; a table of `chess.Move` objects
  stalled single nodes for 100–175 ms. Stored scores are made ply-independent (`score + ply` for
  positive mate scores, `score - ply` for negative, reversed on probe). Cap: 250 000 entries; at
  the start of every `search` the table is emptied if it holds more than `TT_CLEAR_FRACTION`
  (60 %) of the cap, and when the cap is hit mid-search it is cleared before the next store (the
  backstop). The TT persists across moves within a game (`new_game` clears it; `agent.py` also
  calls it after a desync, because stored draws may rest on the discarded history).
- Path repetition: the searcher keeps a `dict[Key, int]` of counts along the current path; a node
  whose key is already present in `history` or in the path is a draw. The root position's key is
  in `history` by construction (the caller includes it), so any return to the root position is a
  draw in search.
- Graph-history mitigation: a draw found through the *path* is a fact about the line, not the
  position, so a node whose value depended on one (a child returned the path draw, or a child was
  itself so flagged) is not stored with its score; only its move is kept as an ordering hint at
  depth −1, and never over an entry earned without the repetition. Draws from the game history
  are permanent within the game and are stored normally. Implemented as one instance flag saved
  and restored around the child loop (measured cost 0.15 % of the node rate).
- Killers: two per ply, updated on quiet beta cutoffs. Never store captures as killers.
- Every pruning or reduction decision is off when a mate bound is in the window or the side is in
  check; the mate tests (mate in one, mate in two at the same depths) run with every feature on.
- The searcher never calls `evaluate` on a position with no legal moves; mates and stalemates are
  scored explicitly.

## `mikhail_letal/searchboard.py`

```python
class SearchBoard:
    board: chess.Board                    # the position; python-chess still owns the rules
    mg: int; eg: int; phase: int          # running totals, White's view; phase is not clamped
    def __init__(self, board: chess.Board) -> None: ...   # ValueError on a Chess960 board
    def evaluate(self) -> int: ...        # == evaluation.evaluate(self.board), no per-piece loop
    def push(self, move: chess.Move) -> None: ...
    def pop(self) -> None: ...
    def push_null(self) -> None: ...      # the totals do not change
    def pop_null(self) -> None: ...
```

The board the search makes its moves on (v0.3). It owns a `chess.Board` and does nothing to it
python-chess would not do — `push`/`pop` are python-chess's own, and move generation and legality
still come from python-chess — but it keeps three integers beside it: `mg` and `eg`, the
middlegame and endgame sums of the combined material-plus-square tables over every piece from
White's view, and `phase`, the raw phase weight. A move touches at most three squares, so folding
it into the totals is a handful of table lookups where a recompute walks all 32 pieces.

`evaluate()` is then `evaluation.evaluate_running` on those totals, and `evaluation.evaluate` is
the same function on `evaluation.material_pst(board)`: one arithmetic path, so the incremental and
the from-scratch answers cannot differ by construction. The cases the update handles explicitly
are a capture (the victim leaves both sums and the phase), en passant (the victim is not on the
target square), a promotion (the promoted piece replaces the pawn in both sums and adds to the
phase) and castling (the rook moves too). Unmake restores the numbers saved when the move was
made, so nothing can drift. Chess960 is refused because the castling update assumes the standard
king-two-files move. `tests/test_searchboard.py` asserts the totals equal `material_pst` after
every make and every unmake along 40-ply random walks from all 219 openings plus constructed
promotion, castling and en passant positions.

## `mikhail_letal/timing.py`

```python
@dataclass(frozen=True)
class TimeParams:
    increment_ms: int = 500
    overhead_ms: int = 150          # calibrated after the first upload (docs/CALIBRATION.md)
    moves_to_go_max: int = 40
    moves_to_go_min: int = 12
    increment_fraction: float = 0.8
    hard_multiplier: float = 3.0
    hard_fraction: float = 0.25
    floor_ms: int = 1500
    floor_fraction: float = 0.05
    panic_ms: int = 1650            # below this, skip the engine and play the fallback (= overhead + floor)
    next_iteration_fraction: float = 0.45

@dataclass(frozen=True)
class Budget:
    soft_ms: float
    hard_ms: float

DEFAULT_PARAMS: TimeParams

def budget(
    time_left_ms: int,
    own_moves_so_far: int,
    params: TimeParams = DEFAULT_PARAMS,
    plies_to_cap: int | None = None,      # 600 - board.ply(), always passed by agent.py
    fifty_move_room: int | None = None,   # 100 - halfmove_clock, passed only in a mop-up
) -> Budget
```

```
moves_to_go = clamp(moves_to_go_max - own_moves_so_far // 2, moves_to_go_min, moves_to_go_max)
moves_to_go = min(moves_to_go, max(1, (plies_to_cap + 1) // 2))        # if given
moves_to_go = min(moves_to_go, max(1, (fifty_move_room + 1) // 2))     # if given
soft = (time_left_ms - overhead_ms) / moves_to_go + increment_fraction * increment_ms
hard = min(hard_multiplier * soft, hard_fraction * time_left_ms)
floor = max(floor_ms, floor_fraction * time_left_ms)
hard = min(hard, time_left_ms - overhead_ms - floor)    # never plan to leave less than the floor
soft = min(soft, hard)
both clamped to >= 0
```

## `mikhail_letal/gamestate.py`

```python
class GameState:
    def __init__(self) -> None: ...
    def observe(self, board: chess.Board) -> bool
        # Called with the board built from the received FEN before searching.
        # First call: start history at this position. Later calls: expect the position to be
        # reachable by one legal move from the position after our last move; if it is, record it
        # (the opponent's move); if not, reset the history to this position and return False
        # (desync). Always returns True when the history was extended normally.
    def record_own_move(self, board_after: chess.Board) -> None
        # Called with the board after our chosen move was pushed. Adds its key to the history.
    @property
    def history(self) -> Mapping[Key, int]     # counts of every position seen so far in this game
    @property
    def own_moves(self) -> int                 # how many moves we have played this game
    @property
    def desyncs(self) -> int
```

Reconstructing the opponent's move is done by pushing each legal move on a copy of the expected
board and comparing `_transposition_key()`; `board.fen()` equality is not used because the
halfmove clock and move number are not part of repetition identity.

Known gap, benign by design: we only receive positions with our colour to move, so when we play
Black the game's true start position (White to move) is never observed and its count stays one
below the referee's (after Nf3 Nf6 Ng1 Ng8 Nf3 Nf6 Ng1 Ng8 the referee's `is_repetition(3)` is
true while our count is 2). The searcher scores *any* earlier occurrence as a draw, so a count
one short changes nothing; `tests/test_gamestate.py::test_black_never_sees_the_start_position`
pins it.

## `mikhail_letal/fallback.py`

```python
def fallback_move(board: chess.Board, legal: Sequence[chess.Move]) -> chess.Move
```

One ply: play a mate in one if present; otherwise maximise material after the move (piece values
100/320/330/500/900) with captures of the most valuable piece first and promotions to queen
preferred; ties broken by UCI string so the result is deterministic. Must return in a few
milliseconds; never raises when `legal` is non-empty. If `legal` is empty (should never happen —
the referee ends the game first) it raises `ValueError`, and `agent.py` guards for that.

## `agent.py`

```
os.environ.setdefault("OMP_NUM_THREADS", "1"); os.environ.setdefault("NUMBA_NUM_THREADS", "1")
import chess; from mikhail_letal import ...
STATE = GameState(); ENGINE = Engine(); PARAMS = DEFAULT_PARAMS

def get_move(fen, time_left_ms) -> str:
    t0 = perf_counter()
    board = None; legal = []
    try:
        board = chess.Board(fen)
        STATE.observe(board)                        # logs "desync" if it returns False
        legal = list(board.legal_moves)
        if not legal: return "0000"                  # unreachable, referee ends the game first
        if time_left_ms < PARAMS.panic_ms: move = fallback_move(board, legal)
        else:
            b = budget(time_left_ms, STATE.own_moves, PARAMS,
                       plies_to_cap=600 - board.ply(), fifty_move_room=<100 - halfmove_clock in a mop-up, else None>)
            result = ENGINE.search(board, STATE.history,
                                     soft_deadline = t0 + PARAMS.next_iteration_fraction * b.soft_ms / 1000,
                                     hard_deadline = t0 + b.hard_ms / 1000)
            move = result.move if result.move in legal else fallback_move(board, legal)
    except Exception: log one line with the exception class; move = fallback_move(board or chess.Board(fen), legal or list(...))
    board.push(move); STATE.record_own_move(board)
    print one compact line (≤ 120 bytes): move, depth/seldepth, nodes, nps, elapsed ms, soft/hard ms, clock
    return move.uci()
```

A final guard re-validates `chess.Move.from_uci(uci) in board.legal_moves` on a fresh
`chess.Board(fen)` before returning; if that fails, the fallback plays. Nothing in `get_move` can
raise: even the logging is wrapped. A tiny warm-up search (depth 2 from the standard start) runs
at import so module-level state is exercised before the first real move.

## Determinism and logging

- No `random`, no `HARNESS_SEED`, no time-dependent ordering except the deadline itself.
- Each move prints one line, for example
  `m e2e4 d 5/9 n 31240 nps 10413 t 3001 s 3300 h 9900 c 118500` (tokens: move, depth/seldepth,
  nodes, nps, elapsed ms, soft ms, hard ms, clock ms). Init prints one line with the load time.

## Testing hooks

- `tests/conftest.py` inserts the repo root into `sys.path` so `import agent` and `import mikhail_letal`
  work from pytest.
- Property tests call `agent.get_move` directly on the FENs listed in the brief's Stage 0 DoD and
  assert legality and elapsed time within the hard budget.
- `tools/arena_openings.py` uses `harness.referee.play_match` and `harness.sandbox.local` as a
  library; never edits `harness/`.
