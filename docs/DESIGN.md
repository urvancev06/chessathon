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
agent.py                 SHIPS   entrypoint: safety wrapper + driver (imports ferz only)
mikhail_letal/__init__.py         SHIPS   package marker, version string
mikhail_letal/evaluation.py       SHIPS   tapered material + PST evaluation, mop-up term
mikhail_letal/search.py           SHIPS   iterative deepening alpha-beta searcher
mikhail_letal/timing.py           SHIPS   time budget formula (all constants in one dataclass)
mikhail_letal/gamestate.py        SHIPS   per-game position history (repetition tracking, desync reset)
mikhail_letal/fallback.py         SHIPS   fast always-legal fallback move
weights/pst.json         SHIPS   generated tables with a provenance header
weights/PROVENANCE.json  SHIPS   machine-readable provenance for every shipped number
tools/gen_pst.py                 generates weights/pst.json from a parametric prior
tools/collect_openings.py        collects curated opening FENs from public game pages
tools/arena_openings.py          arena over data/openings.txt, parallel workers, same statistics
tests/                           pytest suite (unit, property, fuzz helpers)
versions/                        frozen copies of uploaded builds
docs/                            DESIGN, DECISIONS, RESULTS, PROVENANCE, CALIBRATION, report.tex
data/                            openings.txt and other collected data
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
def evaluate(board: chess.Board) -> int               # static evaluation, side-to-move perspective
def is_mate_score(score: int) -> bool
```

Behaviour:

- `weights/pst.json` holds `piece_values_mg`, `piece_values_eg` (keyed `P N B R Q K`), `pst_mg`,
  `pst_eg` (64 ints each, index = python-chess square from White's view), `phase_weights`
  (`N B R Q`), and a `_provenance` object (generator script, git commit, parameters, date). The
  file is located as `Path(__file__).resolve().parent.parent / "weights" / "pst.json"` so it works
  from the repo, from `versions/vX.Y/`, and from the extracted zip.
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
- No randomness, no caching keyed on the board (the TT does that).

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
- Piece values start at the textbook 100/320/330/500/900 (recorded as textbook, tuned later).

The script is deterministic, writes `weights/pst.json` and `weights/PROVENANCE.json`, and prints
the tables as 8x8 grids for a human to read. The generated numbers are ours by construction; they
match no published engine's tables.

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

class Searcher:
    def __init__(self, tt_max_entries: int = 400_000) -> None: ...
    def new_game(self) -> None: ...          # clear TT, killers, history heuristic
    def search(
        self,
        board: chess.Board,
        history: Mapping[Key, int],          # keys of every earlier position in the game, incl. root
        soft_deadline: float,                # perf_counter(): do not start an iteration after this
        hard_deadline: float,                # perf_counter(): abort the search when reached
        max_depth: int = 64,
        node_limit: int | None = None,
    ) -> SearchResult: ...
```

Behaviour:

- Iterative deepening from depth 1. After each completed iteration, stop if
  `perf_counter() >= soft_deadline`, if the score is a mate score with the shortest mate already
  found at this depth, or if `depth >= max_depth`. The caller sets `soft_deadline` to
  `start + next_iteration_fraction * soft_ms` (see timing).
- Inside the search every `NODE_CHECK_INTERVAL = 1024` nodes read the clock and raise
  `SearchAborted` past `hard_deadline` or past `node_limit`. On abort, return the best move of the
  last completed iteration, or the current iteration's best if the previously-best move was
  searched first and a later move beat it before the abort.
- Root: order moves by the previous iteration's best move first, then the ordering below. Track
  `best_move` and `best_score` per iteration. Aspiration windows are Stage 1.
- Node: terminal checks in this order: (1) `board.ply() >= 600` → draw; (2) repetition: key in
  `history` or in the search path → `DRAW_SCORE`; (3) halfmove clock ≥ 100 → checkmate or draw;
  (4) TT probe (depth-sufficient, mate scores adjusted by ply); (5) in check → depth += 1 (check
  extension, capped by `MAX_PLY`); (6) depth ≤ 0 → quiescence; (7) generate legal moves; none →
  mated or stalemate.
- Move ordering: TT move, then captures and promotions by MVV-LVA (victim value × 10 − attacker
  value; promotions count the promoted piece as the victim), then the two killers of this ply,
  then quiet moves by the history heuristic `history[colour][from][to]` (bonus `depth * depth` on
  beta cutoffs).
- Quiescence: stand pat with `evaluate`; captures via `board.generate_legal_captures()` plus
  queen promotions, MVV-LVA ordered; delta pruning skipped in Stage 0 (correctness first);
  `seldepth` tracked; quiescence depth capped at `MAX_PLY`.
- Transposition table: `dict[Key, TTEntry]` where `TTEntry = (depth, score, flag, move)` and
  `flag ∈ {EXACT, LOWER, UPPER}`. Stored scores are made ply-independent (`score + ply` for positive
  mate scores, `score - ply` for negative, reversed on probe). Hard cap: when
  `len(tt) >= tt_max_entries` the table is cleared before the next store. The TT persists across
  moves within a game (`new_game` clears it).
- Path repetition: the searcher keeps a `dict[Key, int]` of counts along the current path; a node
  whose key is already present in `history` or in the path is a draw. The root position's key is
  in `history` by construction (the caller includes it), so any return to the root position is a
  draw in search.
- Killers: two per ply, updated on quiet beta cutoffs. Never store captures as killers.
- No null-move pruning, no LMR, no futility in Stage 0 (Stage 1 adds them under measurement).
- The searcher never calls `evaluate` on a position with no legal moves; mates and stalemates are
  scored explicitly.

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
    panic_ms: int = 1500            # below this, skip the engine and play the fallback
    next_iteration_fraction: float = 0.45

@dataclass(frozen=True)
class Budget:
    soft_ms: float
    hard_ms: float

DEFAULT_PARAMS: TimeParams

def budget(time_left_ms: int, own_moves_so_far: int, params: TimeParams = DEFAULT_PARAMS) -> Budget
```

```
moves_to_go = clamp(moves_to_go_max - own_moves_so_far // 2, moves_to_go_min, moves_to_go_max)
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
STATE = GameState(); SEARCHER = Searcher(); PARAMS = DEFAULT_PARAMS

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
            b = budget(time_left_ms, STATE.own_moves)
            result = SEARCHER.search(board, STATE.history,
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
