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
mikhail_letal/fastboard.py        SHIPS   Stage 1: 0x88 board, move generation, make/unmake, position key (numba)
mikhail_letal/fasteval.py         SHIPS   Stage 1: evaluation.py ported onto that board (numba)
mikhail_letal/fastsearch.py       SHIPS   Stage 1: search.py ported onto that board (numba); what agent.py plays with
mikhail_letal/warmup.py           SHIPS   the wall-clock budget the import's numba compilation must fit inside
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

Rules: `agent.py` and `mikhail_letal/` import only the standard library, `chess`, and — in
`fastboard.py` and the Stage 1 modules built on it — `numpy` and `numba`. Nothing under
`mikhail_letal/` imports `tools/`, `tests/` or `harness/`. No file in the zip is named after a
stdlib or stack module. No randomness anywhere in the shipped code path.

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
def king_danger(board, white_pawns: int, black_pawns: int) -> int          # mg only, White's view

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
- **King danger** (`king_danger`, middlegame only, behind `KING_DANGER_TERM`). Separate from
  `_structure` because it needs the board rather than bitboards alone, and separate from
  `STRUCTURE_TERMS` so the two groups can be measured apart. For each king: skip entirely while it
  still has `KING_DANGER_SHELTERED_PAWNS` (2) of its own shield pawns; otherwise count each enemy
  knight, bishop, rook or queen whose attacks reach the king's zone (its own square and the up to
  eight around it) once, weighted by `KING_ATTACK_UNITS`, and charge
  `KING_DANGER_SCALE × units²` capped at `KING_DANGER_CAP`. Counted per attacking *piece*, not per
  attacked square. Added to `mg` alone, so the phase blend tapers it out — which is why its test
  positions live in `MIDDLEGAME_TERM_POSITIONS` and must carry non-zero phase to prove anything.
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
        soft_deadline: float,                # perf_counter(): the target the next depth must fit in
        hard_deadline: float,                # perf_counter(): abort the search when reached
        max_depth: int = 64,
        node_limit: int | None = None,
        params: TimeParams = DEFAULT_PARAMS, # the iteration-control constants (timing.py)
    ) -> SearchResult: ...

# v0.2 feature switches, each feature_flag("LETAL_...", True); the arena's --env turns one off.
NULL_MOVE_PRUNING, LATE_MOVE_REDUCTIONS, ASPIRATION_WINDOWS, FUTILITY_PRUNING, DELTA_PRUNING: bool
```

Behaviour (v0.2; the v0.1 searcher is this without the staged generation, the caches and the five
switched features, all of which were added under measurement, see DECISIONS.md):

- Iterative deepening from depth 1. After each completed iteration, stop if
  `timing.should_start_next_depth` says the next depth is not predicted to finish inside the
  target, if the score is a mate score with the shortest mate already found at this depth, or if
  `depth >= max_depth`. The caller sets `soft_deadline` to `start + soft_ms` (see timing); the
  search itself records how long each completed depth took and how settled the root move is.
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
  (4) mate-distance pruning: `alpha = max(alpha, -(MATE_SCORE - ply))`,
  `beta = min(beta, MATE_SCORE - ply - 1)`, return `alpha` if the window closes;
  (5) in check → depth += 1 (check extension, capped by `MAX_PLY`), *before* the probe so that
  probe and store see the same depth; (6) TT probe (depth-sufficient, mate scores adjusted by
  ply); (7) depth ≤ 0 → quiescence; (8) register the position on the path; (9) null-move
  pruning; (10) the futility decision; then the staged move loop with (11) the first move at the
  full window, (12) a null window for every later move and (13) late-move reductions inside it.
  No legal move and nothing pruned → mated or stalemate.
- Principal variation search: only the first move searched at a node gets the full window
  `(alpha, beta)`. Every later one is searched with `(alpha, alpha + 1)`, which asks only whether
  it beats alpha, and is re-searched with the full window when the answer is yes *and* the score
  lands inside `(alpha, beta)` — unsatisfiable when the node itself was given a null window, so
  the re-search never cascades. A late-move reduction inside this composes in a fixed order:
  reduced depth null window → full depth null window → full window. No switch: it changes how the
  tree is proved, not which moves are believed.
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
  are searched at `depth - 1 - lmr_reduction(depth, searched)`. The reduction is
  `LMR_TABLE[depth][searched]`, generated at import from
  `trunc(0.75 + log(depth) · log(move) / 2.25)`, floored at one ply and capped at `depth - 2` so
  the reduced search never falls into quiescence; both indices are clamped to the table's 64 × 64.
  A reduced result above alpha is re-searched at
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
    overhead_ms: int = 50           # calibrated 2026-09-08 (docs/CALIBRATION.md): measured 0-2 ms
    moves_to_go_max: int = 50       # all three from tools/sim_time.py over 1697 ladder games
    moves_to_go_min: int = 20
    moves_to_go_decay: float = 0.7  # divisor moves dropped per move of ours played
    increment_fraction: float = 0.8
    hard_multiplier: float = 3.0
    hard_fraction: float = 0.25
    floor_ms: int = 1500
    floor_fraction: float = 0.05
    panic_ms: int = 1650            # below this, skip the engine and play the fallback
    next_iteration_fraction: float = 0.45   # fallback only: an iteration too short to predict from
    iteration_ratio_default: float = 4.5    # cost of depth d+1 over depth d, before it is measured
    iteration_ratio_min: float = 2.0        # ... and the range the measured ratio is clamped to
    iteration_ratio_max: float = 8.0
    ratio_measurable_s: float = 0.001
    iteration_target_factor: float = 1.35   # how far past soft the next depth may be predicted to end
    unstable_factor: float = 1.5            # a root move that just changed gets a bigger target
    easy_factor: float = 0.7                # a settled one gets a smaller one
    easy_stable_depths: int = 6
    easy_score_drop_cp: int = 30
    cold_finish_fraction: float = 0.25

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
moves_to_go = clamp(moves_to_go_max - int(own_moves_so_far * moves_to_go_decay), moves_to_go_min, moves_to_go_max)
moves_to_go = min(moves_to_go, max(1, (plies_to_cap + 1) // 2))        # if given
moves_to_go = min(moves_to_go, max(1, (fifty_move_room + 1) // 2))     # if given
soft = (time_left_ms - overhead_ms) / moves_to_go + increment_fraction * increment_ms
hard = min(hard_multiplier * soft, hard_fraction * time_left_ms)
floor = max(floor_ms, floor_fraction * time_left_ms)
hard = min(hard, time_left_ms - overhead_ms - floor)    # never plan to leave less than the floor
soft = min(soft, hard)
both clamped to >= 0
```

```python
def should_start_next_depth(
    elapsed_s: float,                    # since the search started
    iteration_times_s: Sequence[float],  # what each completed depth cost, in order
    soft_s: float,                       # the soft budget as a window from the search's start
    hard_s: float,                       # the hard budget, likewise
    stable_depths: int,                  # completed depths that kept the previous best move
    score_drop_cp: int,                  # how far the score fell at the last one
    params: TimeParams = DEFAULT_PARAMS,
) -> bool
```

```
target = soft_s * iteration_target_factor
target *= unstable_factor      if two depths are done and the best move changed at the last one
target *= easy_factor          elif stable_depths >= easy_stable_depths and score_drop_cp <= easy_score_drop_cp
target = min(target, hard_s)                       # a stretch never reaches past the abort point
False                          if target <= 0 or elapsed_s >= target
elapsed_s < next_iteration_fraction * target       if the last iteration is under ratio_measurable_s
ratio = clamp(last / previous, ratio_min, ratio_max), or iteration_ratio_default with no measurable pair
elapsed_s + ratio * last <= target                 otherwise
```

Guarantee: a `True` return implies `elapsed_s < hard_s`, so the rule can never start an iteration
past the abort point. `tests/test_timing.py` asserts it over a grid of histories and windows.

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
    def fast_history(self) -> Sequence[int]    # the same positions under fastboard.position_key
    @property
    def own_moves(self) -> int                 # how many moves we have played this game
    @property
    def desyncs(self) -> int
```

Reconstructing the opponent's move is done by pushing each legal move on a copy of the expected
board and comparing `_transposition_key()`; `board.fen()` equality is not used because the
halfmove clock and move number are not part of repetition identity.

Every position is recorded twice: once under python-chess's key (what `history` returns, and what
the referee's repetition rule uses) and once under `fastboard.position_key`, because the compiled
searcher cannot hash a `chess.Board` inside its tree. The two mean the same thing and are written
in the same three places, so they cannot fall out of step.

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

## `mikhail_letal/fastboard.py` (Stage 1, phase 1)

The compiled position: its own board, its own move generation, its own make and unmake, with no
Python object in the hot path. Phase 1 is this file only; the compiled search and evaluation that
will call it are a later phase, and until they exist nothing in `agent.py`'s move path uses it.

```python
class Position(NamedTuple):        # five preallocated int32 arrays, mutated in place
    board: NDArray[int32]          # 128 entries, 0x88 indexed: piece_type | colour << 3, or 0
    plist: NDArray[int32]          # colour * 16 + slot -> square
    pidx:  NDArray[int32]          # square -> slot in its colour's list, else -1
    meta:  NDArray[int32]          # side, castling, ep, halfmove, fullmove, undo depth, kings, counts
    undo:  NDArray[int32]          # MAX_UNDO x UNDO_N

def new_position() -> Position
def new_move_buffer() -> NDArray[int32]                     # MAX_MOVES
def new_move_stack(max_ply: int = 64) -> NDArray[int32]     # one buffer per recursion level

# compiled (numba njit); every one is called by warm_up() at import
def attacked(board, square: int, by_colour: int) -> int     # 1 or 0
def in_check(pos) -> int
def gen_pseudo(pos, out) -> int                             # writes packed moves, returns the count
def gen_legal(pos, out) -> int                              # filters gen_pseudo in place
def make_move(pos, move: int) -> int                        # 1 if legal; ALWAYS pushes an undo record
def unmake_move(pos) -> None
def has_legal_move(pos, out) -> int
def perft(pos, stack, depth: int, ply: int) -> int
def hash_position(pos, zob) -> int                          # Zobrist key; ZOBRIST at import

# boundary, plain Python
def from_board(board: chess.Board) -> Position;  def from_fen(fen: str) -> Position
def set_from_board(pos, board) -> None;          def to_fen(pos) -> str
def legal_moves(pos) -> list[int]
def move_to_uci(move) -> str;  def move_to_chess(move) -> chess.Move
def move_from_chess(pos, move: chess.Move) -> int
def pack_move(frm, to, promotion=0, flag=FLAG_NORMAL) -> int
def move_from / move_to / move_promotion / move_flag (move) -> int
def sq88(square: int) -> int;  def sq64(square: int) -> int
def check_invariants(pos) -> None                           # tests only
def position_key(board: chess.Board) -> int                 # hash_position for a chess.Board
def warm_up(deadline: float | None = None) -> float         # called at import; WARM_UP_SECONDS
JITTED: tuple[str, ...]                                     # every compiled function here
```

Conventions inside this module, which differ from the rest of the engine and are converted only at
the boundary:

- Squares are **0x88** (`a1 = 0x00`, `h1 = 0x07`, `a8 = 0x70`), not python-chess's 0..63. A square
  is on the board exactly when `sq & 0x88 == 0`, which is the whole reason for the representation:
  every knight hop, king step and slider ray tests the edge with one AND and cannot wrap.
- Colours are `WHITE = 0`, `BLACK = 1`, not python-chess's `True`/`False`. Piece types match
  python-chess (`PAWN = 1 .. KING = 6`) so a promotion code passes straight to `chess.Move`.
- A move is one int32: `from | to << 7 | promotion << 14 | flag << 17`. The flag distinguishes a
  double push, an en passant capture and a castling move, none of which make/unmake can infer
  from the squares alone.
- Every array is int32. One dtype means one numba specialisation per function and no implicit
  casts.

Behaviour:

- Generation is pseudo-legal plus "make, then ask whether the mover's king is attacked". Castling
  is the exception: its "not out of, through or into check" conditions are checked in the
  generator, because they concern squares the king does not end on. En passant discovered check
  needs no special case — the captured pawn has already left the board when the king is tested.
- `make_move` always plays the move and always pushes an undo record, whatever it returns, so the
  caller must `unmake_move` exactly once either way. That is what makes the legality test free in
  a search: the move it wants to keep is already on the board.
- `unmake_move` restores the board, both piece lists, the castling rights, the en passant square
  and both clocks exactly. The captured piece's piece-list slot is stored in the undo record,
  because the swap-with-last removal would otherwise lose it.
- `to_fen` reproduces `chess.Board.fen()` byte for byte, including python-chess's default
  en passant rule: the target square is printed only when a legal en passant capture exists.
- Both fixed-size buffers are guarded at runtime. `gen_pseudo` refuses to start on a piece unless
  `MOVES_PER_PIECE_MAX = 27` slots are free (a queen on an empty board is the widest piece), and
  `make_move` refuses the ply after the last undo slot. Both raise `IndexError`, which `agent.py`
  answers with the fallback; the alternative — writing past the end of a numpy array — is silent
  on the platform and its consequences arbitrary.
- `hash_position` is the Zobrist key of the position: piece placement, side to move, castling
  rights, and the en passant file **only when a pawn of the side to move stands ready to take**.
  It is what the compiled search uses for its table and for repetition, and what `GameState`
  records alongside python-chess's own key so the two sides of the engine agree about which
  positions are equal. python-chess's `_transposition_key` applies the stricter test of a fully
  *legal* en passant capture; the two differ only when that pawn is pinned.
- `warm_up()` compiles every entry point at import with the exact argument types the engine will
  pass, so nothing compiles on the clock. `cache=True` is not used: the platform wipes `/tmp`
  between games and every cache path points there, so a disk cache would never hit. It runs in
  four phases — `generate`, `make_unmake`, `hash`, `perft` — each of which the shared
  `warmup.WarmUpBudget` may skip if it would overrun `deadline`; `perft` is last because only the
  tests call it. See `mikhail_letal/warmup.py`.

Gates (`tests/test_fastboard.py`, python-chess is the oracle throughout; `LETAL_FULL_GATES=1`
runs the full sizes, and `NUMBA_BOUNDSCHECK=1` makes numba check every compiled array index):

1. Perft to depth 4 on the standard public positions and on 58 positions built to break one rule
   each, depth 3 on all 219 curated openings and on 2,000 positions from random playouts.
2. Legal-move-set equality, as sets of UCI strings, on 100,000 positions, with the sample audited
   for en passant, all sixteen castling-rights combinations, check, double check, promotions,
   pawns on the seventh and terminal positions.
3. Make/unmake round trip: FEN with both clocks byte-identical, `meta` unchanged, and
   `check_invariants` green after every make and unmake in a Python-level perft.
4. No jitted function gains a signature under load, so nothing compiles after import.

## `mikhail_letal/fasteval.py` (Stage 1, phase 2)

`evaluation.py` compiled onto `fastboard`. It is a **port, not a redesign**: every term, weight and
rounding decision is the one in `evaluation.py`, which stays in the repository as the specification
and as the oracle the gate compares against.

```python
class EvalTables(NamedTuple):      # eight preallocated arrays, built once at import
    pst_mg, pst_eg: NDArray[int32]        # [colour, piece type, 0x88 square], material folded in
    values_mg, phase_weights: NDArray[int32]
    weights: NDArray[int32]               # the structural weights, indexed by W_*
    misc:    NDArray[int32]               # mop-up scalars and the STRUCTURE_TERMS switch, by E_*
    centre:  NDArray[int32]               # distance to the nearest centre square, by 0x88 square
    scratch: NDArray[int32]               # per-file pawn summary and piece counts, reused per call

def load_eval_tables(path: Path | None = None) -> EvalTables      # plain Python; TABLES at import
def evaluate(pos: Position, ev: EvalTables) -> int                # compiled; the whole evaluation
def evaluate_board(board: chess.Board) -> int                     # boundary helper, tests only
def warm_up(deadline: float | None = None) -> float               # called at import
JITTED: tuple[str, ...]                                           # every compiled function here
```

The one thing that changes is the representation. `evaluation.py` reads bitboards and leans on
Python's arbitrary-precision integers for the pawn-structure fills (`bb >> 8`, `bb << 32`), which
inside numba would be 64-bit machine words where a signed right shift sign-extends and a left
shift silently overflows. So the pawn structure is computed from **per-file summaries** instead —
for each colour and file, how many pawns stand there and the highest and lowest rank they occupy —
and each bitboard fill is restated as a statement about those three numbers. Reading the position
is two passes over the piece lists (at most 32 squares), so no bitboard is built at all.

`load_eval_tables` calls `evaluation.load_tables`, so there is exactly one parser for
`weights/pst.json` and the two evaluations cannot drift apart in how they read it.

Gate (`tests/test_fasteval.py`): the compiled evaluation must equal the Python one **integer for
integer** on 20,000 positions from playouts of the curated openings (`LETAL_FULL_GATES=1`; 2,000
otherwise), on all 219 openings, on the 58 rule-breakers, on a hand-built position per structural
term and per insufficient-material combination, and on 2,000 colour-swapped mirrors. There is no
rounding to excuse a difference: both sides compute the same integer arithmetic.

## `mikhail_letal/fastsearch.py` (Stage 1, phase 2)

`search.py` compiled onto `fastboard` and `fasteval`. Same algorithm, same constants — they are
*imported* from `search.py`, so a change there changes both engines and the two cannot disagree
about what the algorithm is.

```python
class SearchState(NamedTuple):     # every array the search reads or writes; allocated once
    tt_key: NDArray[int64]; tt_data: NDArray[int32]     # (slots, 5): depth, score, flag, move, generation
    killers, history: NDArray[int32]                    # (MAX_PLY+2, 2), (2, 128*128)
    moves, order: NDArray[int32]                        # one move buffer + score buffer per ply
    root_scores: NDArray[int32]; path: NDArray[int64]
    history_keys: NDArray[int64]                        # the game's earlier positions, a hash set
    eval_key: NDArray[int64]; eval_value: NDArray[int32]
    zobrist: NDArray[int64]; ints: NDArray[int64]; flt: NDArray[float64]

def new_state(tt_bits: int = 21, eval_bits: int = 18) -> SearchState

# compiled
def negamax(pos, st, ev, depth, alpha, beta, ply, null_allowed) -> int
def quiescence(pos, st, ev, alpha, beta, ply, in_chk, qs_ply) -> int
def gen_captures(pos, out) -> int          # captures, en passant and queen promotions
def _score_moves(pos, st, ply, count, tt_move) -> None;  def _pick_best(st, ply, index, count)
def _break_draw_tie(pos, st, ev, count, best) -> int
# ... plus the table, clock, null-move and terminal-score helpers; all listed in JITTED

class FastEngine:                  # same interface as search.Engine
    def new_game(self) -> None
    def search(self, board: chess.Board, history: Sequence[int], soft_deadline: float,
               hard_deadline: float, max_depth: int = 64, node_limit: int | None = None,
               params: TimeParams = DEFAULT_PARAMS) -> SearchResult    # search.SearchResult
    node_rate: float               # measured nodes per second; the node cap is derived from it

def warm_up(engine: FastEngine, deadline: float | None = None) -> float   # from agent.py
DEFAULT_NODE_RATE: float       # the rate assumed before any search has been timed
```

What is the same as `search.py`: iterative deepening; aspiration windows from depth 4 (±40 cp,
widen ×4, at most 2 fails); fail-soft negamax alpha-beta; a transposition table probed and stored
with mate scores adjusted by distance from the root; quiescence with stand-pat before any move is
generated and evasions searched for the first four quiescence plies; move ordering by table move,
MVV-LVA capture, two killers per ply and the history heuristic; principal variation search at
interior nodes; null-move pruning (min depth 3,
R = 2 + depth//6, never in check, never without a piece, only when the static evaluation already
holds beta); late-move reductions (quiet non-killer non-table moves after the first three, at
depth ≥ 3); futility pruning at depths 1–2 (150/300); delta pruning in quiescence (200); the check
extension; mate-distance pruning; and draws by repetition against both the game history and the
current line, by the fifty-move rule and at the referee's 600-ply cap.

What had to change:

- **The table is an array, not a dictionary.** Fixed size, a power of two, indexed by
  `fastboard.hash_position`, depth-preferred *within* a move and always-replace across moves (each
  entry records the move of the game that wrote it; without that a slot holding a deep entry from
  move three would refuse every shallower entry for the rest of the game). Entries are replaced rather than accumulated,
  and a key collision is possible (about one in 2⁶⁴ per probe). A collision can hand the search a
  wrong score or a wrong first move to try, never an illegal move: the table move is *matched
  against the generated move list*, never played on trust.
- **The abort is a flag, not an exception.** `I_ABORT` is set by the deadline check and every
  function returns as soon as it sees it, immediately after its `unmake_move`, so the position is
  always left exactly as it was found (`tests/test_fastsearch.py` pins that on five node limits).
- **Moves are generated whole, not in stages.** One `gen_pseudo` call, a score per move, and the
  best remaining one selected on each iteration of the loop — the same order as `search.py`'s four
  stages, reached in the way that suits a compiled generator with nothing to allocate. Illegal
  moves fall out of `make_move` returning 0. The one place that hurts is the "is the position
  over?" test behind the stand-pat cutoff, asked at about a third of all nodes, where a whole
  generation buys one legal move: `_has_unpinned_move` is the compiled twin of
  `search._has_legal_move` and answers it for nearly every position by reading the destinations
  of one unpinned piece, with "not on a rank, file or diagonal through the king" standing in for
  python-chess's exact slider-blocker set.
- **The root is Python.** Iterative deepening, the aspiration window and the loop over the legal
  root moves live in `FastEngine`, not in compiled code (see DECISIONS.md 2026-09-08): they run a
  few hundred times a move, not millions, and compiling them costs fourteen seconds of the
  platform's start-up budget.
- **Two limits, always both.** The wall clock is read inside the tree through `numba.objmode`
  every `NODE_CHECK_INTERVAL = 512` nodes, and a node cap derived from the measured node rate
  (`FastEngine.node_rate`, twice what the hard budget can buy) backs it up in case the clock read
  misbehaves.

Gates (`tests/test_fastsearch.py`): the same behavioural questions `tests/test_search.py` asks of
the Python searcher — mate in one and two, the hanging queen, repetition avoided when ahead and
sought when behind, the fifty-move and 600-ply draws, the root tie-break, the limits, determinism,
`new_game`, the caller's board untouched — plus three that are specific to the compiled build:
every jitted function compiled at import and gaining no specialisation during a game; the position
byte-identical after an aborted `negamax`; and a legal move returned on every sampled position at
three different node limits.

## `agent.py`

```
os.environ.setdefault("OMP_NUM_THREADS", "1"); os.environ.setdefault("NUMBA_NUM_THREADS", "1")
import chess; from mikhail_letal import ...
STATE = GameState(); ENGINE = FastEngine(); PARAMS = DEFAULT_PARAMS

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
            result = ENGINE.search(board, STATE.fast_history,
                                     soft_deadline = t0 + b.soft_ms / 1000,
                                     hard_deadline = t0 + b.hard_ms / 1000, params = PARAMS)
            move = result.move if result.move in legal else fallback_move(board, legal)
    except Exception: log one line with the exception class; move = fallback_move(board or chess.Board(fen), legal or list(...))
    board.push(move); STATE.record_own_move(board)
    print one compact line (≤ 120 bytes): move, depth/seldepth, nodes, elapsed ms, score, soft/hard ms, clock
    return move.uci()
```

A final guard re-validates `chess.Move.from_uci(uci) in board.legal_moves` on a fresh
`chess.Board(fen)` before returning; if that fails, the fallback plays. Nothing in `get_move` can
raise: even the logging is wrapped.

The engine underneath is the compiled one (`FastEngine`), and python-chess is still the legality
oracle and the fallback, so none of the guarantees above depend on the compiled code being right.
At import, `fastsearch.warm_up(ENGINE, _WARM_UP_DEADLINE)` calls every jitted function with the
exact argument types a game will pass and then runs real searches, so nothing compiles on the
clock; `_warm_up` records how many specialisations each one then has, and `get_move` compares
that once a move and logs, in one line, any that appeared.

That warm-up is **bounded**. `agent.py` arms `warmup.arm(_IMPORT_STARTED + WARM_UP_BUDGET_S)`
before the first compiled module is imported, and every phase of every `warm_up()` asks the
shared budget whether it is predicted to finish in time. What does not fit is skipped and
compiles inside the first `get_move` instead — one slow move out of a 120 s clock, against an
init failure that loses every game. `mikhail_letal/warmup.py` carries the arithmetic behind the
70-second budget; the phase order, most important first, is `fastboard.generate`,
`make_unmake`, `hash`, `perft`, `fasteval.evaluate`, `fastsearch.helpers`, `quiescence`,
`negamax`, `tie_break`, `samples`, `node_rate`. If `node_rate` is skipped, `FastEngine.node_rate`
keeps `DEFAULT_NODE_RATE` rather than zero, so the node cap that backs up the clock is still sane.

`get_move` then finishes the job on the first real move, before it searches
(`_finish_warm_up`), because numba cannot be interrupted: a function compiled *inside*
`ENGINE.search` blows through the hard deadline (measured 15.9 s against 10.2 s). The finish is
bounded by `TimeParams.cold_finish_fraction` of the clock and by the same predictive budget; the
search's deadlines are then shifted by what it cost and its budget computed from the clock that
is left, so every search stays inside its hard deadline and the cost is paid once, on the
opening's full clock. Measured import from the extracted zip: 19–29 s, against the platform's 90 s budget.

## Determinism and logging

- No `random`, no `HARNESS_SEED`, no time-dependent ordering except the deadline itself.
- Each move prints one line, for example
  `m e2e4 d 5/9 n 31240 t 3001 e +45 s 3300 h 9900 c 118500` (tokens: move, depth/seldepth,
  nodes, elapsed ms, score, soft ms, hard ms, clock ms). The score is from the side to move, with
  the sign always written, and a mate is `e #+3` or `e #-3` — a distance in moves that cannot be
  read as centipawns. It is left out entirely when no search ran (a forced move, a panic clock or
  an error). The node rate used to sit where the score is: it was `n / t`, and the platform keeps
  only the first and last 4 KB of our output, so a redundant token costs moves off the end of a
  long game's log. Init prints one line with the load time,
  the compile time, the warm-up budget, how many phases it had to skip and the measured node
  rate, and `get_move` adds one `jit:` line if any compiled function gains a specialisation
  after the warm-up.

## Testing hooks

- `tests/conftest.py` inserts the repo root into `sys.path` so `import agent` and `import mikhail_letal`
  work from pytest.
- Property tests call `agent.get_move` directly on the FENs listed in the brief's Stage 0 DoD and
  assert legality and elapsed time within the hard budget.
- `tools/arena_openings.py` uses `harness.referee.play_match` and `harness.sandbox.local` as a
  library; never edits `harness/`.
