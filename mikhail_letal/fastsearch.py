"""Compiled iterative-deepening alpha-beta search: ``mikhail_letal.search``, on ``fastboard``.

This is a port of the searcher in ``search.py``, which stays in the repository as the readable
specification of the algorithm and as the thing whose docstrings explain *why* each part is
there. Read that file first; this one repeats the structure and the constants (they are imported
from it, so the two cannot drift apart) and only says what had to change to compile.

What is the same
----------------
Iterative deepening with aspiration windows from depth 4; fail-soft negamax alpha-beta; a
transposition table probed and stored with mate scores adjusted by distance from the root;
quiescence with stand-pat before any move is generated and evasions searched for the first four
quiescence plies; move ordering by table move, MVV-LVA capture, two killers per ply, then the
history heuristic; principal variation search at interior nodes; null-move pruning, late-move
reductions, futility pruning, delta pruning, a check extension and mate-distance pruning; and
draws by repetition (against both the game history and the current line), by the fifty-move rule
and at the referee's 600-ply cap. Every constant is the one in ``search.py``.

What had to change, and why
---------------------------
*The table is an array, not a dictionary.* ``search.py`` keys a Python dict on
``Board._transposition_key()``, which is exact: two different positions are never the same key.
A compiled search cannot afford a dict, so this one is a fixed-size, power-of-two, depth-preferred
table indexed by a Zobrist key (``fastboard.hash_position``, which ``make_move`` keeps up to
date so that no node here has to recompute it). That brings two consequences the
Python version does not have: entries are *replaced* rather than accumulated, and a key collision
is possible (about one in 2**64 per probe). A collision can only ever hand the search a wrong
score or a wrong first move to try, never an illegal move, because the table move is matched
against the generated move list rather than played on trust -- and ``agent.py`` validates the
final move against python-chess regardless. The same table backs the static-evaluation cache.

*The abort is a flag, not an exception.* ``search.py`` raises ``SearchAborted`` and unwinds. Here
the deadline sets ``I_ABORT`` and every function returns as soon as it sees it, immediately after
its ``unmake_move``, so the board is always left exactly as it was found. The root then throws
the unfinished iteration away and answers with the previous one, which is what the exception
achieved. Two mechanisms stop the search, always both: the wall clock, read through
``numba.objmode`` every ``NODE_CHECK_INTERVAL`` nodes, and a node cap derived from the measured
node rate, which bounds the search even if the clock read misbehaves.

*Moves are generated whole, not in stages.* ``search.py`` yields the table move, then captures,
then killers, then quiet moves, generating each stage only when the search asks for it. Here one
call to ``gen_pseudo`` produces every pseudo-legal move, a score is computed for each, and the
best remaining one is selected on each iteration of the loop -- the same order, reached in a way
that suits a compiled generator with no Python objects to allocate. Illegal moves fall out of
``make_move`` returning 0, which is how this board representation tests legality anyway.

*The root is Python; the tree is not.* Iterative deepening, the aspiration window and the loop
over the legal root moves live in ``FastEngine`` (see the note above that section, and
DECISIONS.md 2026-09-08): they run a few hundred times a move, and compiling them cost fourteen
seconds of the platform's 90-second start-up budget, because numba re-optimises a callee's whole
compiled module in every caller. Below the root nothing crosses back into Python: one ``negamax``
call per root move per iteration is the only boundary the search ever crosses.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Final, NamedTuple

import chess
import numpy as np
import numpy.typing as npt
from numba import njit, objmode

from mikhail_letal import warmup
from mikhail_letal.evaluation import DRAW_SCORE, MATE_SCORE, MATE_THRESHOLD
from mikhail_letal.fastboard import (
    _KING_DIRS,
    _KNIGHT_DIRS,
    _SLIDER_DIRS,
    _SLIDER_N,
    BISHOP,
    BLACK,
    COLOUR_SHIFT,
    EMPTY,
    FLAG_CASTLE,
    FLAG_EN_PASSANT,
    FLAG_MASK,
    FLAG_SHIFT,
    KING,
    KNIGHT,
    M_COUNT,
    M_EP,
    M_FULL,
    M_HALF,
    M_KING,
    M_PLY,
    M_SIDE,
    MAX_MOVES,
    MOVES_PER_PIECE_MAX,
    NO_MOVE,
    NO_SQ,
    OFF_BOARD_MASK,
    PAWN,
    PIECE_TYPE_MASK,
    PIECES_PER_SIDE,
    PROMO_MASK,
    PROMO_SHIFT,
    QUEEN,
    ROOK,
    SQ_BITS,
    SQ_MASK,
    U_KEY,
    WHITE,
    Z_SIDE,
    ZOBRIST,
    Position,
    attacked,
    ep_key_index,
    gen_legal,
    gen_pseudo,
    hash_position,
    in_check,
    make_move,
    move_to_chess,
    new_position,
    position_key,
    set_from_board,
    unmake_move,
)
from mikhail_letal.fasteval import TABLES as EVAL_TABLES
from mikhail_letal.fasteval import EvalTables
from mikhail_letal.fasteval import evaluate as static_evaluate

# Every feature switch and constant comes from the Python searcher, so a change there changes both
# engines and the two can never disagree about what the algorithm is. See search.py for what each
# one means and why it has the value it has.
from mikhail_letal.search import (
    _HINT_DEPTH,
    _HISTORY_MAX,
    _INFINITY,
    _ORDER_CAPTURE,
    _ORDER_KILLER_FIRST,
    _ORDER_KILLER_SECOND,
    _ORDER_TT,
    ASPIRATION_MAX_FAILS,
    ASPIRATION_MIN_DEPTH,
    ASPIRATION_WIDEN,
    ASPIRATION_WINDOW,
    ASPIRATION_WINDOWS,
    DELTA_MARGIN,
    DELTA_PRUNING,
    DRAW_TIEBREAK_MARGIN,
    EXACT,
    FUTILITY_MARGINS,
    FUTILITY_PRUNING,
    GAME_PLY_CAP,
    LATE_MOVE_REDUCTIONS,
    LMR_FULL_DEPTH_MOVES,
    LMR_MIN_DEPTH,
    LMR_TABLE,
    LMR_TABLE_DEPTHS,
    LMR_TABLE_MOVES,
    LOWER,
    MAX_PLY,
    NULL_MOVE_BASE_REDUCTION,
    NULL_MOVE_DEPTH_DIVISOR,
    NULL_MOVE_MIN_DEPTH,
    NULL_MOVE_PRUNING,
    QS_CHECK_PLIES,
    QS_EVASION_PLIES,
    UPPER,
    SearchResult,
)
from mikhail_letal.timing import DEFAULT_PARAMS, TimeParams, should_start_next_depth

# The margins as an array: numba indexes an array with a runtime integer, a Python tuple only
# with a constant one.
_FUTILITY = np.array(FUTILITY_MARGINS, dtype=np.int32)
_FUTILITY_DEPTHS: Final = len(FUTILITY_MARGINS)

# The late-move reduction table, as an array so the compiled code can index it with two runtime
# integers. `search.LMR_TABLE` is the definition; nothing is recomputed here.
_LMR = np.array(LMR_TABLE, dtype=np.int32)

# How often the search reads the clock and the node cap. Compiled nodes are some twenty times
# cheaper than interpreted ones, so the Python engine's 128 would read the clock twenty times as
# often for the same wall time; 512 keeps the overshoot past the hard deadline under a
# millisecond at a million nodes a second, and an objmode clock read costs about 300 ns, which
# over 512 nodes is well under one percent.
NODE_CHECK_INTERVAL: Final = 512

# Entries in the transposition table and in the static-evaluation cache. Both are powers of two
# so the index is a mask rather than a modulo. 2**21 entries cost 8 bytes of key plus 16 of data,
# 50 MB in all, which is nothing against the platform's 2 GB and far more than a three-second
# search fills.
TT_BITS: Final = 21
EVAL_BITS: Final = 18

# The node rate a fresh engine assumes before any search has been timed. The warm-up replaces it
# with a measurement, and every real search refines it, but it has to start somewhere and it must
# never be zero or unset: `FastEngine.search` derives the node cap that backs up the clock from
# it. 400 000 is deliberately above anything measured (about 500 000 nodes/s here, so roughly
# 220 000 on the platform) and the cap doubles it again, so the assumed rate errs towards a cap
# that never binds. That is the safe direction: the clock is the real limit, and the cap only has
# to catch a clock read that has stopped working.
DEFAULT_NODE_RATE: Final = 400_000.0

# ----------------------------------------------------------------------------- state layout

# Scalars of the search, in one int64 array so numba sees a single mutable object.
I_NODES: Final = 0
I_NODE_LIMIT: Final = 1  # 0 for "no limit"
I_ABORT: Final = 2  # set by _check_limits; every function returns as soon as it sees it
I_SELDEPTH: Final = 3
I_ROOT_PLY: Final = 4  # board.ply() at the root, for the referee's 600-ply cap
I_PATH_DRAW: Final = 5  # a score below here depended on a repetition of the current line
I_NULL_MOVES: Final = 6  # a statistic the tests read
I_TT_MASK: Final = 7
I_EVAL_MASK: Final = 8
I_HISTORY_MASK: Final = 9  # of the game-history hash set
I_GENERATION: Final = 10  # which move of the game wrote a table entry (see _tt_store)
I_COUNT: Final = 11

# The soft deadline is the Python root's business; the compiled tree only ever needs the hard one.
F_HARD: Final = 0  # perf_counter() at which the search aborts wherever it is
F_COUNT: Final = 1


class SearchState(NamedTuple):
    """Every array the compiled search reads or writes. Allocated once by `new_state` and reused
    for the whole game, so no node ever allocates."""

    tt_key: npt.NDArray[np.int64]  # Zobrist key of each table slot; 0 means never written
    tt_data: npt.NDArray[np.int32]  # (slots, 5): depth, score, flag, move, generation
    killers: npt.NDArray[np.int32]  # (MAX_PLY + 2, 2): two quiet cutoff moves per ply
    history: npt.NDArray[np.int32]  # (2, 128 * 128): cutoff credit by colour and from-to
    moves: npt.NDArray[np.int32]  # (MAX_PLY + 2, MAX_MOVES): one move buffer per ply
    order: npt.NDArray[np.int32]  # (MAX_PLY + 2, MAX_MOVES): the ordering score of each
    root_scores: npt.NDArray[np.int32]  # the search score of each root move, for the draw tie-break
    path: npt.NDArray[np.int64]  # keys of the ancestors of the current node, by ply
    history_keys: npt.NDArray[np.int64]  # open-addressed set of the game's earlier positions
    eval_key: npt.NDArray[np.int64]  # static-evaluation cache
    eval_value: npt.NDArray[np.int32]
    zobrist: npt.NDArray[np.int64]
    ints: npt.NDArray[np.int64]  # the scalars above
    flt: npt.NDArray[np.float64]  # the two deadlines


def new_state(tt_bits: int = TT_BITS, eval_bits: int = EVAL_BITS) -> SearchState:
    """Allocate the search's memory. Sizes are powers of two so indexing is a mask."""
    tt_size = 1 << tt_bits
    eval_size = 1 << eval_bits
    # The history set holds one key per position of the game so far. The referee draws at 600
    # plies, so it never holds more than about 601 keys; 2048 slots keep it under a third full at
    # the worst, which keeps linear probing to a step or two and leaves room to spare.
    history_size = 2048
    ints = np.zeros(I_COUNT, dtype=np.int64)
    ints[I_TT_MASK] = tt_size - 1
    ints[I_EVAL_MASK] = eval_size - 1
    ints[I_HISTORY_MASK] = history_size - 1
    return SearchState(
        tt_key=np.zeros(tt_size, dtype=np.int64),
        tt_data=np.zeros((tt_size, 5), dtype=np.int32),
        killers=np.full((MAX_PLY + 2, 2), NO_MOVE, dtype=np.int32),
        history=np.zeros((2, 128 * 128), dtype=np.int32),
        moves=np.zeros((MAX_PLY + 2, MAX_MOVES), dtype=np.int32),
        order=np.zeros((MAX_PLY + 2, MAX_MOVES), dtype=np.int32),
        root_scores=np.zeros(MAX_MOVES, dtype=np.int32),
        path=np.zeros(MAX_PLY + 2, dtype=np.int64),
        history_keys=np.zeros(history_size, dtype=np.int64),
        eval_key=np.zeros(eval_size, dtype=np.int64),
        eval_value=np.zeros(eval_size, dtype=np.int32),
        zobrist=ZOBRIST,
        ints=ints,
        flt=np.zeros(F_COUNT, dtype=np.float64),
    )


# ----------------------------------------------------------------------------- limits and clock


@njit(cache=False)
def _clock() -> float:
    """`time.perf_counter()` from inside compiled code. objmode drops back into the interpreter
    for the call, which costs about 300 ns; NODE_CHECK_INTERVAL is set so that is negligible."""
    with objmode(now="f8"):
        now = time.perf_counter()
    return now


@njit(cache=False)
def _check_limits(st: SearchState) -> None:
    """Set the abort flag past the node cap or the hard deadline. Both mechanisms, always: the
    node cap is deterministic and bounds the search even if the clock read fails, the clock is
    what actually matters to the referee."""
    ints = st.ints
    limit = ints[I_NODE_LIMIT]
    if limit > 0 and ints[I_NODES] >= limit:
        ints[I_ABORT] = 1
        return
    if _clock() >= st.flt[F_HARD]:
        ints[I_ABORT] = 1


# ----------------------------------------------------------------------------- tables


@njit(cache=False)
def _tt_probe(st: SearchState, key: int) -> int:
    """The slot holding `key`, or -1. A key of zero marks an unwritten slot and is never stored,
    so a match is always a real entry."""
    # The annotation narrows numpy's element type back to `int` for mypy; numba ignores it.
    index: int = key & st.ints[I_TT_MASK]
    if key != 0 and st.tt_key[index] == key:
        return index
    return -1


@njit(cache=False)
def _tt_store(st: SearchState, key: int, depth: int, score: int, flag: int, move: int) -> None:
    """Depth-preferred within the move, always-replace across moves.

    A slot is overwritten when it is empty, when it holds this same position, when it was written
    for an earlier move of the game, or when the new entry was searched at least as deeply as the
    old one. The generation test is what keeps a fixed-size table usable over a long game: without
    it a slot holding some deep entry from move three would refuse every shallower entry for the
    rest of the game, and the table would slowly stop accepting anything at all. It is the
    equivalent of `search.py` emptying its dictionary between moves once it passes
    `TT_CLEAR_FRACTION`, except that it throws away only the entries a new one wants the room for.
    """
    if key == 0:
        return
    index = key & st.ints[I_TT_MASK]
    stored = st.tt_key[index]
    if (
        stored != 0
        and stored != key
        and st.tt_data[index, 4] == st.ints[I_GENERATION]
        and depth < st.tt_data[index, 0]
    ):
        return
    st.tt_key[index] = key
    st.tt_data[index, 0] = depth
    st.tt_data[index, 1] = score
    st.tt_data[index, 2] = flag
    st.tt_data[index, 3] = move
    st.tt_data[index, 4] = st.ints[I_GENERATION]


@njit(cache=False)
def _store(
    st: SearchState, key: int, depth: int, score: int, flag: int, move: int, ply: int, tainted: int
) -> None:
    """Write a table entry with the score made independent of the node's distance from the root.

    A `tainted` score -- one that depended on a repetition of the *current line* -- is not stored
    at all; only its move is kept, at _HINT_DEPTH, as an ordering hint, and even that does not
    displace an entry whose score was earned without the repetition. Same rule as search._store.
    """
    if tainted != 0:
        index = _tt_probe(st, key)
        if index >= 0 and st.tt_data[index, 0] > _HINT_DEPTH:
            return
        _tt_store(st, key, _HINT_DEPTH, DRAW_SCORE, EXACT, move)
        return
    if score >= MATE_THRESHOLD:
        score += ply
    elif score <= -MATE_THRESHOLD:
        score -= ply
    _tt_store(st, key, depth, score, flag, move)


@njit(cache=False)
def _in_history(st: SearchState, key: int) -> int:
    """1 if `key` is a position the game has already visited. An open-addressed set, so the probe
    is one masked index and, with the table under a third full at worst, almost never a second.
    The 64-probe bound cannot be reached at that load factor and is there so a full table could
    not spin here."""
    mask = st.ints[I_HISTORY_MASK]
    index = key & mask
    for _ in range(64):
        stored = st.history_keys[index]
        if stored == 0:
            return 0
        if stored == key:
            return 1
        index = (index + 1) & mask
    return 0


@njit(cache=False)
def _cached_eval(pos: Position, st: SearchState, ev: EvalTables, key: int) -> int:
    """`fasteval.evaluate` behind a direct-mapped cache keyed on the position.

    The key identifies the position exactly, so a hit returns precisely what the evaluation would
    have computed. About a third of the evaluations in a search are of a position already seen
    (capture sequences transpose), which is what makes the cache worth its 3 MB.
    """
    index = key & st.ints[I_EVAL_MASK]
    if key != 0 and st.eval_key[index] == key:
        value: int = st.eval_value[index]
        return value
    score: int = static_evaluate(pos, ev)
    if key != 0:
        st.eval_key[index] = key
        st.eval_value[index] = score
    return score


# ----------------------------------------------------------------------------- the null move


@njit(cache=False)
def _make_null(pos: Position) -> tuple[int, int, int]:
    """Pass the move: flip the side, clear the en passant square, advance the clocks.

    Exactly what `chess.Board.push(Move.null())` does. It touches no piece, so it needs no undo
    record; the three values it changes are returned for `_unmake_null` to put back.

    The position key is one of the three. A pass adds no ply, so it rewrites the key in place in
    this ply's undo row rather than pushing a new one. Nothing moves, so only two of its terms
    can change: the side-to-move term, which always flips, and the en passant term, which the
    pass clears. Getting this wrong would not be caught by `fastboard`'s make/unmake tests,
    because the null move lives here; `tests/test_fastsearch.py` checks it against
    `hash_position`.
    """
    meta = pos.meta
    ep = meta[M_EP]
    half = meta[M_HALF]
    ply = meta[M_PLY]
    key = int(pos.undo[ply, U_KEY])
    passed = key ^ ZOBRIST[Z_SIDE]
    if ep != NO_SQ:
        index = ep_key_index(pos.board, ep, meta[M_SIDE])
        if index >= 0:
            passed ^= ZOBRIST[index]
    pos.undo[ply, U_KEY] = passed
    meta[M_EP] = NO_SQ
    meta[M_HALF] = half + 1
    if meta[M_SIDE] == BLACK:
        meta[M_FULL] += 1
    meta[M_SIDE] = 1 - meta[M_SIDE]
    return ep, half, key


@njit(cache=False)
def _unmake_null(pos: Position, ep: int, half: int, key: int) -> None:
    meta = pos.meta
    meta[M_SIDE] = 1 - meta[M_SIDE]
    if meta[M_SIDE] == BLACK:
        meta[M_FULL] -= 1
    meta[M_EP] = ep
    meta[M_HALF] = half
    pos.undo[meta[M_PLY], U_KEY] = key


@njit(cache=False)
def _has_non_pawn_material(pos: Position, side: int) -> int:
    """1 if `side` has a piece that is neither pawn nor king. Null-move pruning rests on "a move
    is better than no move", which is exactly what fails in a pawn ending."""
    base = side * PIECES_PER_SIDE
    for slot in range(pos.meta[M_COUNT + side]):
        kind = pos.board[pos.plist[base + slot]] & PIECE_TYPE_MASK
        if kind != PAWN and kind != KING:
            return 1
    return 0


# ----------------------------------------------------------------------------- generation


@njit(cache=False)
def gen_captures(pos: Position, out: npt.NDArray[np.int32]) -> int:
    """Write every pseudo-legal capture, en passant capture and queen promotion into `out`.

    These are the moves quiescence looks at: `search._capture_moves(board, quiescence=True)`
    produces the same set, including the quiet push that promotes and excluding under-promotions,
    which are almost never the point of a capture sequence.
    """
    board = pos.board
    side = pos.meta[M_SIDE]
    them = 1 - side
    ep = pos.meta[M_EP]
    room = out.shape[0]
    n = 0

    for slot in range(pos.meta[M_COUNT + side]):
        if n + MOVES_PER_PIECE_MAX > room:  # the same overflow guard as gen_pseudo
            raise IndexError("gen_captures: move buffer too small")
        frm = pos.plist[side * PIECES_PER_SIDE + slot]
        kind = board[frm] & PIECE_TYPE_MASK

        if kind == PAWN:
            if side == WHITE:
                forward = 16
                promo_rank = 7
            else:
                forward = -16
                promo_rank = 0

            to = frm + forward
            if (to & OFF_BOARD_MASK) == 0 and board[to] == EMPTY and (to >> 4) == promo_rank:
                out[n] = frm | (to << SQ_BITS) | (QUEEN << PROMO_SHIFT)
                n += 1

            for side_step in range(2):
                to = frm + forward + (1 if side_step == 0 else -1)
                if (to & OFF_BOARD_MASK) != 0:
                    continue
                target = board[to]
                if target != EMPTY:
                    if (target >> COLOUR_SHIFT) == them:
                        if (to >> 4) == promo_rank:
                            out[n] = frm | (to << SQ_BITS) | (QUEEN << PROMO_SHIFT)
                        else:
                            out[n] = frm | (to << SQ_BITS)
                        n += 1
                elif to == ep:
                    out[n] = frm | (to << SQ_BITS) | (FLAG_EN_PASSANT << FLAG_SHIFT)
                    n += 1

        elif kind in (KNIGHT, KING):
            for i in range(8):
                to = frm + (_KNIGHT_DIRS[i] if kind == KNIGHT else _KING_DIRS[i])
                if (to & OFF_BOARD_MASK) != 0:
                    continue
                target = board[to]
                if target != EMPTY and (target >> COLOUR_SHIFT) == them:
                    out[n] = frm | (to << SQ_BITS)
                    n += 1

        else:
            for i in range(_SLIDER_N[kind]):
                direction = _SLIDER_DIRS[kind, i]
                to = frm + direction
                while (to & OFF_BOARD_MASK) == 0:
                    target = board[to]
                    if target != EMPTY:
                        if (target >> COLOUR_SHIFT) == them:
                            out[n] = frm | (to << SQ_BITS)
                            n += 1
                        break
                    to += direction

    return n


# ----------------------------------------------------------------------------- lines and checks
#
# Whether one square attacks another along a line depends only on the difference between the two
# in the 0x88 layout -- that is what the layout is for -- so "which way does this square lie from
# that one" is a table lookup rather than a search. `gen_checks` leans on it hard: it asks "does
# this move give check?" of every quiet move in the position, so the answer has to cost a few
# nanoseconds or the feature is not worth having.


def _build_line_tables() -> tuple[npt.NDArray[np.int32], npt.NDArray[np.int32]]:
    """The two geometry tables, indexed by `to - frm + 128`.

    `_DIR_TABLE` holds the 0x88 step from one square towards another, or zero when the two share
    no rank, file or diagonal. `_KNIGHT_HOP` holds 1 when the difference is a knight's move.
    Built at import from the direction tables the move generator already uses, so the geometry
    exists once rather than twice.
    """
    directions = np.zeros(256, dtype=np.int32)
    hops = np.zeros(256, dtype=np.int32)
    for frm in range(128):
        if (frm & OFF_BOARD_MASK) != 0:
            continue
        for step in _KING_DIRS:
            to = frm + int(step)
            while (to & OFF_BOARD_MASK) == 0:
                directions[to - frm + 128] = step
                to += int(step)
        for hop in _KNIGHT_DIRS:
            to = frm + int(hop)
            if (to & OFF_BOARD_MASK) == 0:
                hops[to - frm + 128] = 1
    return directions, hops


_DIR_TABLE, _KNIGHT_HOP = _build_line_tables()


@njit(cache=False)
def _diagonal(step: int) -> int:
    """Is this 0x88 direction a diagonal? The four straight steps are the ones that are not."""
    if step == 16 or step == -16 or step == 1 or step == -1:
        return 0
    return 1


@njit(cache=False)
def _first_occupied(
    board: npt.NDArray[np.int32], origin: int, step: int, vacated: int, filled: int
) -> int:
    """First occupied square walking from `origin` along `step`, on the board as it *would* look
    after a move: `vacated` counts as empty and `filled` counts as occupied. `origin` itself is
    not examined. Returns NO_SQ if the ray leaves the board without meeting one."""
    sq = origin + step
    while (sq & OFF_BOARD_MASK) == 0:
        if sq == filled:
            return sq
        if sq != vacated and board[sq] != EMPTY:
            return sq
        sq += step
    return NO_SQ


@njit(cache=False)
def _direct_check(
    board: npt.NDArray[np.int32], kind: int, side: int, frm: int, to: int, ksq: int
) -> int:
    """Would a `side` piece of type `kind` standing on `to` attack the king on `ksq`, once `frm`
    has been vacated? Returns 1 or 0. This is the check the moving piece gives itself; a check
    uncovered behind it is `_discovered_slider`'s business."""
    if kind == PAWN:
        # A white pawn on `to` attacks to+15 and to+17, a black one the two squares below.
        if side == WHITE:
            return 1 if (to + 15 == ksq or to + 17 == ksq) else 0
        return 1 if (to - 15 == ksq or to - 17 == ksq) else 0
    if kind == KNIGHT:
        return 1 if _KNIGHT_HOP[to - ksq + 128] != 0 else 0
    if kind == KING:
        # A king can only attack the enemy king by standing next to it, which is illegal, so no
        # legal king move gives check directly. (A pseudo-legal one can, and `make_move` rejects
        # it; a king move that uncovers a slider is a discovered check and is found below.)
        return 0
    step = _DIR_TABLE[to - ksq + 128]
    if step == 0:
        return 0
    diagonal = _diagonal(step)
    if kind == BISHOP and diagonal == 0:
        return 0
    if kind == ROOK and diagonal != 0:
        return 0
    # The queen needs no direction test: it moves every way the table can point. What is left is
    # whether the line is clear, which is true exactly when the piece itself is the first thing
    # the king sees along it.
    return 1 if _first_occupied(board, ksq, step, frm, to) == to else 0


@njit(cache=False)
def _discovered_slider(board: npt.NDArray[np.int32], side: int, frm: int, ksq: int) -> int:
    """Square of the `side` slider that would attack the king on `ksq` once `frm` is vacated, or
    NO_SQ when leaving `frm` uncovers nothing.

    Anything standing between the king and `frm` blocks the line and is met first, so the whole
    test is "the first piece behind `frm`, seen from the king, is ours and slides this way". It
    cannot wrongly find a slider in *front* of `frm`: that would be the side to move already
    checking a king it is not to move against, which no legal position holds.
    """
    step = _DIR_TABLE[frm - ksq + 128]
    if step == 0:
        return NO_SQ
    behind = _first_occupied(board, ksq, step, frm, NO_SQ)
    if behind == NO_SQ:
        return NO_SQ
    piece = board[behind]
    if (piece >> COLOUR_SHIFT) != side:
        return NO_SQ
    kind = piece & PIECE_TYPE_MASK
    if kind == QUEEN:
        return behind
    if _diagonal(step) != 0:
        return behind if kind == BISHOP else NO_SQ
    return behind if kind == ROOK else NO_SQ


@njit(cache=False)
def _discovery_survives(to: int, ksq: int, slider: int, step: int) -> int:
    """Does an uncovered check still stand once the mover lands on `to`? It does not if the mover
    has stepped onto the very line it opened, between the king and the slider."""
    if _DIR_TABLE[to - ksq + 128] != step:
        return 1
    if _DIR_TABLE[slider - to + 128] != step:
        return 1  # on the line, but past the slider rather than in front of it
    return 0


@njit(cache=False)
def _check_is_safe(pos: Position, move: int) -> int:
    """Is this quiet checking move worth a quiescence node? Returns 1 or 0.

    The whole check filter lives here, so tightening it is a change to this function and to
    nothing else. The rule is cheap and blunt on purpose: a quiet check that puts a piece on a
    square the opponent defends usually just loses the piece, because nothing was captured to pay
    for it, and searching those is exactly what makes a checking quiescence explode. A pawn check
    is always kept -- it risks a pawn and it is the cheapest way to force a king to move.

    Two known inaccuracies, both accepted for the cost: the opponent's defenders are counted on
    the board *before* the move, so a defender whose line the mover itself unblocks is missed;
    and a square defended only by the enemy king counts as defended, which drops a few real
    checks. A static exchange evaluation answers the question properly -- keep the check when the
    exchange on the destination does not lose material, so a defended square is still searched
    when we have the attackers to win it. This body becomes `see(pos, move) >= 0` when `see`
    lands; see docs/DECISIONS.md for why that needs a SEE that scores quiet moves.
    """
    if (pos.board[move & SQ_MASK] & PIECE_TYPE_MASK) == PAWN:
        return 1
    to = (move >> SQ_BITS) & SQ_MASK
    return 1 if attacked(pos.board, to, 1 - pos.meta[M_SIDE]) == 0 else 0


@njit(cache=False)
def gen_checks(pos: Position, out: npt.NDArray[np.int32]) -> int:
    """Write the quiet moves that give check, and survive `_check_is_safe`, into `out`.

    Captures, en passant and queen promotions are `gen_captures`'s list; this is the quiet half of
    the forcing moves, so the two lists are disjoint and quiescence can search one after the other
    without searching anything twice.

    The moves come from `gen_pseudo` and are filtered in place. Generating them directly would
    save the writes but not the work -- finding a rook's quiet destinations *is* the ray walk
    `gen_pseudo` already does -- and it would put a second copy of the move rules in the engine to
    keep correct. Castling and under-promotions are left out: a castling check and a
    knight-promotion check are rare enough not to be worth a special case in either generator.
    """
    board = pos.board
    side = pos.meta[M_SIDE]
    ksq = pos.meta[M_KING + (1 - side)]
    count = gen_pseudo(pos, out)

    n = 0
    slider_from = NO_SQ  # square the hoisted discovery answer below was computed for
    slider = NO_SQ
    slider_step = 0
    for i in range(count):
        move = out[i]
        frm = move & SQ_MASK
        to = (move >> SQ_BITS) & SQ_MASK
        if board[to] != EMPTY or ((move >> PROMO_SHIFT) & PROMO_MASK) != 0:
            continue  # a capture or a promotion: gen_captures owns both
        flag = (move >> FLAG_SHIFT) & FLAG_MASK
        if flag in (FLAG_EN_PASSANT, FLAG_CASTLE):
            # En passant lands on an empty square but is a capture; castling moves two pieces, so
            # the from-to reasoning below would not see the rook that delivers the check.
            continue

        if frm != slider_from:
            # Whether *leaving* a square uncovers a slider depends only on the square left, and
            # `gen_pseudo` emits one piece's moves together, so this costs once per piece.
            slider_from = frm
            slider = _discovered_slider(board, side, frm, ksq)
            slider_step = _DIR_TABLE[frm - ksq + 128]

        gives = _direct_check(board, board[frm] & PIECE_TYPE_MASK, side, frm, to, ksq)
        if gives == 0 and slider != NO_SQ:
            gives = _discovery_survives(to, ksq, slider, slider_step)
        if gives == 0 or _check_is_safe(pos, move) == 0:
            continue
        out[n] = move  # n <= i always, so the compaction cannot overwrite an unread move
        n += 1
    return n


# ----------------------------------------------------------------------------- move ordering


@njit(cache=False)
def _victim(pos: Position, move: int) -> int:
    """Piece type this move captures, 0 for a quiet move. En passant takes a pawn that does not
    stand on the destination square, which is the one case the board cannot be asked directly."""
    if ((move >> FLAG_SHIFT) & 7) == FLAG_EN_PASSANT:
        return PAWN
    kind: int = pos.board[(move >> SQ_BITS) & SQ_MASK] & PIECE_TYPE_MASK
    return kind


@njit(cache=False)
def _score_moves(pos: Position, st: SearchState, ply: int, count: int, tt_move: int) -> None:
    """Fill `st.order[ply][:count]` with the ordering score of each move in `st.moves[ply]`.

    The bands are search.py's: the table move first, then captures and promotions by MVV-LVA
    (take the most valuable victim with the least valuable attacker), then the two killers of
    this ply, then quiet moves by history score. Each band sits far above the next, so a history
    score can never overtake a killer nor a killer a capture. Quiescence uses the same function:
    its capture list has no quiet move to reach the killer and history bands, and its check
    evasions are ordered with them exactly as `search._order_moves` orders them.
    """
    moves = st.moves[ply]
    order = st.order[ply]
    board = pos.board
    side = pos.meta[M_SIDE]
    killer_first = st.killers[ply, 0]
    killer_second = st.killers[ply, 1]
    history = st.history[side]

    for i in range(count):
        move = moves[i]
        if move == tt_move:
            order[i] = _ORDER_TT
            continue
        frm = move & SQ_MASK
        to = (move >> SQ_BITS) & SQ_MASK
        promotion = (move >> PROMO_SHIFT) & PROMO_MASK
        victim = _victim(pos, move)
        if victim != 0 or promotion != 0:
            # The MVV-LVA rank of a piece is its piece type; only the order matters.
            attacker = board[frm] & PIECE_TYPE_MASK
            order[i] = _ORDER_CAPTURE + 10 * (victim + promotion) - attacker
        elif move == killer_first:
            order[i] = _ORDER_KILLER_FIRST
        elif move == killer_second:
            order[i] = _ORDER_KILLER_SECOND
        else:
            order[i] = history[frm * 128 + to]


@njit(cache=False)
def _pick_best(st: SearchState, ply: int, index: int, count: int) -> None:
    """Swap the best-scoring of the moves still to be tried into position `index`.

    Selecting on demand rather than sorting up front is what makes good ordering cheap: most
    interior nodes cut off on the first move or two, and the moves after them are never compared.
    """
    moves = st.moves[ply]
    order = st.order[ply]
    best = index
    for j in range(index + 1, count):
        if order[j] > order[best]:
            best = j
    if best != index:
        move = moves[index]
        moves[index] = moves[best]
        moves[best] = move
        score = order[index]
        order[index] = order[best]
        order[best] = score


@njit(cache=False)
def _reward_quiet_cutoff(pos: Position, st: SearchState, move: int, depth: int, ply: int) -> None:
    """A quiet move caused a beta cutoff: make it a killer and raise its history score."""
    if st.killers[ply, 0] != move:
        st.killers[ply, 1] = st.killers[ply, 0]
        st.killers[ply, 0] = move
    side = pos.meta[M_SIDE]
    index = (move & SQ_MASK) * 128 + ((move >> SQ_BITS) & SQ_MASK)
    # depth * depth: cutoffs near the root are rarer and worth more than cutoffs near leaves.
    value = st.history[side, index] + depth * depth
    st.history[side, index] = value if value < _HISTORY_MAX else _HISTORY_MAX


# ----------------------------------------------------------------------------- terminal scores


@njit(cache=False)
def _has_unpinned_move(pos: Position) -> int:
    """1 if the side to move certainly has a legal move; 0 if this test could not tell.

    The compiled half of `search.Engine._has_legal_move`, whose docstring is the readable
    argument: with no check on the board, a piece that is not shielding its king cannot expose it
    by moving, so any pseudo-legal move of such a piece is legal outright, and one pawn that can
    step forward or one piece with a square to go to settles the question. Finding it needs no
    make/unmake and no attack scan -- only reading that piece's destinations. One-way: a 0 means
    this test found nothing, never that the position is over, and the caller then asks properly.

    Two things differ from the Python version. It is only called when the side is not in check
    (the caller has that answer already and passes it in), and "not shielding the king" is the
    cruder test that the piece does not stand on a rank, file or diagonal *through* the king,
    rather than python-chess's exact slider-blocker set, because an 0x88 board has no bitboard to
    compute that from. The crude test is deliberately the generous one: a piece wrongly called
    "possibly pinned" costs the scan of one more piece, while a piece wrongly called free would
    be a stalemate scored as a stand-pat.

    A slider needs only the first square of each direction: every longer move down a direction
    passes over it, so if the slider can move at all it can move one step. En passant is skipped
    on purpose: it is the one move that can uncover a check from a piece the mover never stood in
    front of, so "cannot be pinned" does not settle it.
    """
    board = pos.board
    side = pos.meta[M_SIDE]
    king = pos.meta[M_KING + side]
    king_file = king & 7
    king_rank = king >> 4
    forward = 16 if side == WHITE else -16
    for slot in range(pos.meta[M_COUNT + side]):
        frm = pos.plist[side * PIECES_PER_SIDE + slot]
        kind = board[frm] & PIECE_TYPE_MASK
        if kind == KING:
            continue  # the king is never pinned, but its own moves need the attack scan
        file_gap = (frm & 7) - king_file
        rank_gap = (frm >> 4) - king_rank
        if file_gap == 0 or rank_gap == 0 or file_gap == rank_gap or file_gap == -rank_gap:
            continue
        if kind == PAWN:
            # A pawn never stands on the last rank, so the square in front of it is on the board.
            if board[frm + forward] == EMPTY:
                return 1
            for step in (-1, 1):
                to = frm + forward + step
                if (to & OFF_BOARD_MASK) == 0:
                    target = board[to]
                    if target != EMPTY and (target >> COLOUR_SHIFT) != side:
                        return 1
        elif kind == KNIGHT:
            for i in range(8):
                to = frm + _KNIGHT_DIRS[i]
                if (to & OFF_BOARD_MASK) == 0:
                    target = board[to]
                    if target == EMPTY or (target >> COLOUR_SHIFT) != side:
                        return 1
        else:
            for i in range(_SLIDER_N[kind]):
                to = frm + _SLIDER_DIRS[kind, i]
                if (to & OFF_BOARD_MASK) == 0:
                    target = board[to]
                    if target == EMPTY or (target >> COLOUR_SHIFT) != side:
                        return 1
    return 0


@njit(cache=False)
def _has_legal(pos: Position, st: SearchState, ply: int, in_chk: int) -> int:
    """1 if the side to move has any legal move.

    The cheap test comes first, because this sits on the hottest path in the whole tree: the
    quiescence stand-pat cutoff asks it at roughly a third of all nodes, and it exists only to
    stop a checkmate or a stalemate being scored as a stand-pat. `_has_unpinned_move` answers
    "yes" for nearly every position without generating a move -- measured over a depth-10 search,
    100 % of the calls from the standard start, 99.9 % in the Kiwipete middlegame and 86.6 % in a
    rook ending, where there is less material to find an unpinned piece among (DECISIONS.md) --
    and the full generation below runs for the rest.

    That generation uses this ply's buffer, which is free wherever this is called: the node has
    either not generated its moves yet or is about to return.
    """
    if in_chk == 0 and _has_unpinned_move(pos) != 0:
        return 1
    buffer = st.moves[ply]
    n = gen_pseudo(pos, buffer)
    for i in range(n):
        legal = make_move(pos, buffer[i])
        unmake_move(pos)
        if legal != 0:
            return 1
    return 0


@njit(cache=False)
def _game_over_score(pos: Position, st: SearchState, ply: int, in_chk: int) -> int:
    """Score where the referee would stop the game: checkmate wins, anything else draws."""
    if in_chk != 0 and _has_legal(pos, st, ply, in_chk) == 0:
        return -(MATE_SCORE - ply)
    return DRAW_SCORE


@njit(cache=False)
def _static_score(pos: Position, st: SearchState, ev: EvalTables, ply: int, in_chk: int) -> int:
    """Score for a node that may not recurse further (the MAX_PLY guard). Rare enough that
    generating moves here costs nothing, and it keeps the promise that a position with no legal
    move is never handed to the evaluation."""
    if _has_legal(pos, st, ply, in_chk) == 0:
        return -(MATE_SCORE - ply) if in_chk != 0 else DRAW_SCORE
    score: int = static_evaluate(pos, ev)
    return score


# ----------------------------------------------------------------------------- quiescence


@njit(cache=False)
def quiescence(
    pos: Position,
    st: SearchState,
    ev: EvalTables,
    alpha: int,
    beta: int,
    ply: int,
    in_chk: int,
    qs_ply: int,
) -> int:
    """Captures-only search that settles tactics before the static evaluation is trusted.

    In check, for the first QS_EVASION_PLIES quiescence plies, there is no standing pat, because
    doing nothing is not a legal option: every legal evasion is searched, and a position without
    one is checkmate. Otherwise the side to move may stand pat on the static evaluation or try
    captures and queen promotions, ordered by MVV-LVA. The stand-pat test comes before any move
    generation: it ends most quiescence nodes on its own.
    """
    ints = st.ints
    if ply > ints[I_SELDEPTH]:
        ints[I_SELDEPTH] = ply
    if ply >= MAX_PLY:
        return _static_score(pos, st, ev, ply, in_chk)

    key = int(pos.undo[pos.meta[M_PLY], U_KEY])  # carried forward by make_move; see fastboard
    evasions = in_chk != 0 and qs_ply < QS_EVASION_PLIES
    if evasions:
        count = gen_pseudo(pos, st.moves[ply])
        _score_moves(pos, st, ply, count, NO_MOVE)
        best_score = -_INFINITY
    else:
        best_score = _cached_eval(pos, st, ev, key)  # stand pat
        if best_score >= beta:
            # The cutoff is real only if the side to move has a move at all; without one the
            # position is over (a mate if in check, a stalemate otherwise).
            if _has_legal(pos, st, ply, in_chk) != 0:
                return best_score
            return -(MATE_SCORE - ply) if in_chk != 0 else DRAW_SCORE
        if best_score > alpha:
            alpha = best_score
        count = gen_captures(pos, st.moves[ply])
        _score_moves(pos, st, ply, count, NO_MOVE)

    # Delta pruning applies only where the side to move could stand pat: then a capture that
    # cannot lift the stand-pat score to alpha even in the best case is not worth searching.
    delta_floor = -_INFINITY
    if (
        DELTA_PRUNING
        and not evasions
        and alpha < MATE_THRESHOLD
        and alpha > best_score + DELTA_MARGIN
    ):
        delta_floor = alpha - best_score - DELTA_MARGIN
    values = ev.values_mg
    promotion_gain = values[QUEEN] - values[PAWN]

    legal_seen = 0
    for i in range(count):
        _pick_best(st, ply, i, count)
        move = st.moves[ply, i]
        if delta_floor > -_INFINITY:
            # values[0] is zero, so a promotion push (which captures nothing) starts from zero.
            gain = values[_victim(pos, move)]
            if ((move >> PROMO_SHIFT) & PROMO_MASK) != 0:
                gain += promotion_gain
            if gain < delta_floor:
                continue
        if make_move(pos, move) == 0:
            unmake_move(pos)
            continue
        legal_seen += 1
        nodes = ints[I_NODES] + 1
        ints[I_NODES] = nodes
        if nodes % NODE_CHECK_INTERVAL == 0:
            _check_limits(st)
        child_in_check = in_check(pos)
        score = -quiescence(pos, st, ev, -beta, -alpha, ply + 1, child_in_check, qs_ply + 1)
        unmake_move(pos)
        if ints[I_ABORT] != 0:
            return 0
        if score > best_score:
            best_score = score
            if score >= beta:
                return score
            if score > alpha:
                alpha = score

    # Quiet checks. A capture-only quiescence calls a position quiet whenever the move that
    # decides it happens to take nothing, and evaluates it statically; for the first
    # QS_CHECK_PLIES plies the quiet checking moves are searched too. They come after the
    # captures and only if no capture held beta, and they reuse this ply's buffer, which the
    # capture loop above has finished with. Not in the evasion branch: there every legal move is
    # searched already, checks among them.
    if not evasions and qs_ply < QS_CHECK_PLIES:
        count = gen_checks(pos, st.moves[ply])
        _score_moves(pos, st, ply, count, NO_MOVE)
        for i in range(count):
            _pick_best(st, ply, i, count)
            move = st.moves[ply, i]
            if make_move(pos, move) == 0:
                unmake_move(pos)
                continue
            legal_seen += 1
            nodes = ints[I_NODES] + 1
            ints[I_NODES] = nodes
            if nodes % NODE_CHECK_INTERVAL == 0:
                _check_limits(st)
            # `gen_checks` promises this is 1, and the board is asked anyway: one attack scan
            # against a whole child search is nothing, and it means a bug in the generator can
            # never reach the child as a false "in check" and come back as a false mate score.
            child_in_check = in_check(pos)
            score = -quiescence(pos, st, ev, -beta, -alpha, ply + 1, child_in_check, qs_ply + 1)
            unmake_move(pos)
            if ints[I_ABORT] != 0:
                return 0
            if score > best_score:
                best_score = score
                if score >= beta:
                    return score
                if score > alpha:
                    alpha = score

    if evasions:
        # No legal evasion is checkmate; there is no stand-pat score to fall back on.
        if legal_seen == 0:
            return -(MATE_SCORE - ply)
    elif legal_seen == 0 and _has_legal(pos, st, ply, in_chk) == 0:
        # Nothing was searched, and there is no legal move at all: the position is over and its
        # value is the mate or the stalemate, never the stand-pat evaluation.
        return -(MATE_SCORE - ply) if in_chk != 0 else DRAW_SCORE
    return best_score


# ----------------------------------------------------------------------------- main search


@njit(cache=False)
def negamax(
    pos: Position,
    st: SearchState,
    ev: EvalTables,
    depth: int,
    alpha: int,
    beta: int,
    ply: int,
    null_allowed: int,
) -> int:
    """Fail-soft negamax alpha-beta. Returns a score from the side to move's point of view.

    Fail-soft means the returned score may lie outside (alpha, beta): it is then a bound on the
    true value rather than the value itself, which is what the table records with the LOWER and
    UPPER flags. `null_allowed` is 0 directly after a null move, so two sides never pass in a row.
    The numbered comments match the ones in `search._negamax`.
    """
    ints = st.ints
    nodes = ints[I_NODES] + 1
    ints[I_NODES] = nodes
    if nodes % NODE_CHECK_INTERVAL == 0:
        _check_limits(st)
    if ints[I_ABORT] != 0:
        return 0
    if ply > ints[I_SELDEPTH]:
        ints[I_SELDEPTH] = ply

    in_chk = in_check(pos)

    # (1) The referee draws the game at the ply cap, unless the position is checkmate (it tests
    # for game-over conditions before the cap).
    if ints[I_ROOT_PLY] + ply >= GAME_PLY_CAP:
        return _game_over_score(pos, st, ply, in_chk)

    # (2) Repetition: a position already seen in the game, or earlier on the current line, is a
    # draw as far as the engine is concerned. Treating the first repetition as the draw keeps it
    # from drifting when ahead. A draw found on the current line only is flagged, because it is a
    # fact about the line and not about the position.
    key = int(pos.undo[pos.meta[M_PLY], U_KEY])  # carried forward by make_move; see fastboard
    if _in_history(st, key) != 0:
        return DRAW_SCORE
    halfmove = pos.meta[M_HALF]
    # Only positions since the last irreversible move can repeat, and only every second ancestor
    # has this side to move, so the scan is short even deep in the tree.
    ancestor = ply - 2
    while ancestor >= 0 and (ply - ancestor) <= halfmove:
        if st.path[ancestor] == key:
            ints[I_PATH_DRAW] = 1
            return DRAW_SCORE
        ancestor -= 2

    # (3) Fifty-move rule, again with checkmate taking precedence.
    if halfmove >= 100:
        return _game_over_score(pos, st, ply, in_chk)

    # (4) Mate-distance pruning. A node `ply` plies from the root cannot be worth less than
    # being mated here, -(MATE_SCORE - ply), nor more than mating on this very move,
    # MATE_SCORE - ply - 1, whatever the position is. Clamping the window to that costs two
    # comparisons and ends the search of a line as soon as a shorter mate is already known
    # somewhere above it, which is what stops a mate search from wandering off looking for a
    # longer one. The clamp is safe because it only removes values the node could never return,
    # so `alpha` is a true bound on the value in both directions when the window closes.
    mated_here = -(MATE_SCORE - ply)
    mate_next = MATE_SCORE - ply - 1
    if alpha < mated_here:
        alpha = mated_here
    if beta > mate_next:
        beta = mate_next
    if alpha >= beta:
        return alpha

    # (5) Check extension: a side in check has few sensible replies and the position is
    # tactically hot, so it is searched one ply deeper. It comes before the table probe so probe
    # and store agree on the depth of this node.
    if in_chk != 0:
        depth += 1

    # (6) Transposition table probe. Stored mate scores are distances from the stored node;
    # convert them to distances from the root before comparing with this node's window.
    tt_move = NO_MOVE
    index = _tt_probe(st, key)
    if index >= 0:
        entry_depth = st.tt_data[index, 0]
        entry_score: int = st.tt_data[index, 1]
        entry_flag = st.tt_data[index, 2]
        tt_move = st.tt_data[index, 3]
        if entry_depth >= depth:
            if entry_score >= MATE_THRESHOLD:
                entry_score -= ply
            elif entry_score <= -MATE_THRESHOLD:
                entry_score += ply
            if entry_flag == EXACT:
                return entry_score
            if entry_flag == LOWER:
                if entry_score >= beta:
                    return entry_score
            elif entry_score <= alpha:
                return entry_score

    # Safety net: never recurse past MAX_PLY, whatever the extensions did.
    if ply >= MAX_PLY:
        return _static_score(pos, st, ev, ply, in_chk)

    # (7) Horizon: resolve captures before evaluating.
    if depth <= 0:
        return quiescence(pos, st, ev, alpha, beta, ply, in_chk, 0)

    # (8) Interior node. Register the position on the current line for repetition checks, and
    # start a fresh path-draw flag for the subtree (the caller's is restored on the way out).
    st.path[ply] = key
    outer_path_draw = ints[I_PATH_DRAW]
    ints[I_PATH_DRAW] = 0

    alpha_original = alpha
    child_depth = depth - 1
    child_ply = ply + 1
    # Pruning decisions are never made where a mate bound is in the window: there quiet moves and
    # "doing nothing" are exactly what decides the position.
    mate_bounds = alpha <= -MATE_THRESHOLD or beta >= MATE_THRESHOLD

    # (9) Null-move pruning: if passing already holds beta, a real move surely does too.
    if (
        NULL_MOVE_PRUNING
        and null_allowed != 0
        and in_chk == 0
        and depth >= NULL_MOVE_MIN_DEPTH
        and not mate_bounds
        and _has_non_pawn_material(pos, pos.meta[M_SIDE]) != 0
        and _cached_eval(pos, st, ev, key) >= beta
    ):
        reduction = NULL_MOVE_BASE_REDUCTION + depth // NULL_MOVE_DEPTH_DIVISOR
        ints[I_NULL_MOVES] += 1
        saved_ep, saved_half, saved_key = _make_null(pos)
        null_score = -negamax(pos, st, ev, depth - 1 - reduction, -beta, -beta + 1, child_ply, 0)
        _unmake_null(pos, saved_ep, saved_half, saved_key)
        if ints[I_ABORT] != 0:
            return 0
        if null_score >= beta and abs(null_score) < MATE_THRESHOLD:
            tainted = ints[I_PATH_DRAW]
            ints[I_PATH_DRAW] = 1 if (outer_path_draw != 0 or tainted != 0) else 0
            _store(st, key, depth, beta, LOWER, tt_move, ply, tainted)
            return beta

    # (10) Futility: decided once for the node, applied to its quiet moves in the loop.
    futility_bound = -_INFINITY
    if FUTILITY_PRUNING and depth < _FUTILITY_DEPTHS and in_chk == 0 and not mate_bounds:
        bound = _cached_eval(pos, st, ev, key) + _FUTILITY[depth]
        if bound <= alpha:
            futility_bound = bound
    pruned_any = 0

    reduce_late = LATE_MOVE_REDUCTIONS and depth >= LMR_MIN_DEPTH and in_chk == 0
    killer_first = st.killers[ply, 0]
    killer_second = st.killers[ply, 1]

    count = gen_pseudo(pos, st.moves[ply])
    _score_moves(pos, st, ply, count, tt_move)
    best_score = -_INFINITY
    best_move = NO_MOVE
    searched = 0
    legal_seen = 0
    aborted = 0

    for i in range(count):
        _pick_best(st, ply, i, count)
        move = st.moves[ply, i]
        quiet = _victim(pos, move) == 0 and ((move >> PROMO_SHIFT) & PROMO_MASK) == 0
        # A quiet move from a position this far below alpha: its value is at most the futility
        # bound, which is at most alpha, so it cannot improve on what we have.
        futile = quiet and move != tt_move and futility_bound > -_INFINITY
        if futile and legal_seen != 0:
            # Nothing is made: the node has already found a legal move, so it is neither
            # checkmate nor stalemate whatever the rest of the list does, and the only reason the
            # move was ever made before being thrown away was to keep that test honest. This is
            # the common case -- futility applies at depths 1 and 2, which are most of the
            # interior nodes, and by the time the quiet moves come up a capture or the table move
            # has nearly always been searched already.
            pruned_any = 1
            continue
        if make_move(pos, move) == 0:
            unmake_move(pos)
            continue
        legal_seen = 1
        if futile:
            # The first legal move of the node is still made and then thrown away, because
            # "no legal move below" has to keep meaning mate or stalemate.
            unmake_move(pos)
            pruned_any = 1
            continue
        late = (
            reduce_late
            and quiet
            and move != tt_move
            and move != killer_first
            and move != killer_second
            and searched >= LMR_FULL_DEPTH_MOVES
        )
        if searched == 0:
            # (11) The first move searched is the principal variation candidate: the ordering
            # believes in it, so it gets the full window and its score is the one every later
            # move is measured against. It is never reduced.
            score = -negamax(pos, st, ev, child_depth, -beta, -alpha, child_ply, 1)
        else:
            # (12) Principal variation search. Every later move is expected to be worse than the
            # first, and proving "worse than alpha" is far cheaper than measuring how much
            # better a move is: a null window (alpha, alpha+1) cuts off at the first refutation
            # in every subtree. Only a move that beats alpha has to be measured properly, and
            # then it is searched again with the real window.
            #
            # (13) Late-move reduction rides on the same scan, and the two re-searches compose
            # in a fixed order: reduced null window, then full-depth null window, then full
            # window. Skipping the middle step would pay full depth *and* the full window for a
            # move that the shallow search only hinted at, which is where the classic bug is.
            reduction = 0
            if late:
                # The table is `search.LMR_TABLE`, generated there from the formula that defines
                # it; both indices are clamped to its edges, which is where a very deep node or a
                # position with more than sixty-four moves lands.
                row = depth if depth < LMR_TABLE_DEPTHS else LMR_TABLE_DEPTHS - 1
                column = searched if searched < LMR_TABLE_MOVES else LMR_TABLE_MOVES - 1
                reduction = _LMR[row, column]
            score = -negamax(pos, st, ev, child_depth - reduction, -alpha - 1, -alpha, child_ply, 1)
            if reduction != 0 and score > alpha and ints[I_ABORT] == 0:
                # The reduced search surprised us; repeat it at full depth, still null window.
                score = -negamax(pos, st, ev, child_depth, -alpha - 1, -alpha, child_ply, 1)
            if alpha < score < beta and ints[I_ABORT] == 0:
                # The null window only proved the move beats alpha, never by how much, and the
                # score is inside the real window so the node needs the exact value. When the
                # caller already gave a null window (beta == alpha + 1) no integer can sit
                # strictly between the two, so this re-search never happens twice over.
                score = -negamax(pos, st, ev, child_depth, -beta, -alpha, child_ply, 1)
        unmake_move(pos)
        if ints[I_ABORT] != 0:
            aborted = 1
            break
        searched += 1
        if score > best_score:
            best_score = score
            best_move = move
            if score >= beta:
                # Beta cutoff. Remember quiet moves that do this: they tend to refute other
                # moves in sibling positions.
                if quiet:
                    _reward_quiet_cutoff(pos, st, move, depth, ply)
                break
            if score > alpha:
                alpha = score

    tainted = ints[I_PATH_DRAW]
    ints[I_PATH_DRAW] = 1 if (outer_path_draw != 0 or tainted != 0) else 0
    if aborted != 0:
        return 0

    if pruned_any != 0:
        # The pruned moves are worth at most the futility bound; the node's value is at most the
        # larger of that and the best searched move (still a correct fail-soft bound).
        if futility_bound > best_score:
            best_score = futility_bound
    elif best_move == NO_MOVE:
        # No legal move at all. In check that is checkmate; otherwise stalemate.
        return -(MATE_SCORE - ply) if in_chk != 0 else DRAW_SCORE

    if best_score >= beta:
        flag = LOWER
    elif best_score <= alpha_original:
        flag = UPPER
    else:
        flag = EXACT
    _store(st, key, depth, best_score, flag, best_move, ply, tainted)
    return best_score


# ----------------------------------------------------------------------------- root
#
# The root -- iterative deepening, the aspiration window, and the loop over the legal moves of
# the position we were actually asked about -- is Python, not compiled code, and that is a
# deliberate choice with a measurement behind it.
#
# Compiling it costs about fourteen seconds of the platform's start-up budget. numba links a
# called function's whole compiled module into its caller and optimises the result again, so
# every layer stacked on top of `negamax` (which already contains the evaluation, the generator
# and make/unmake) pays for the whole engine to be optimised once more. Running the root in
# Python costs one boundary crossing per root move per iteration, measured at four microseconds:
# with forty root moves and fifteen iterations that is under three milliseconds a move, against
# the seconds it buys back at start-up. Everything that runs millions of times a move is still
# compiled; only the part that runs a few hundred times is not.
#
# It is also the part that is easiest to read as Python, and it now mirrors `search.Engine`
# almost statement for statement, which is what makes the port checkable by eye.


@njit(cache=False)
def _break_draw_tie(pos: Position, st: SearchState, ev: EvalTables, count: int, best: int) -> int:
    """Choose among root moves that all score a draw when the position is clearly won.

    When the fifty-move rule or the 600-ply cap falls inside the horizon, every line ends in the
    rule draw, every root move scores exactly DRAW_SCORE and the search would pick one
    arbitrarily, move after move, until the draw arrives. If the static evaluation says we are
    well ahead, the tied moves are told apart by the static evaluation of the position each one
    reaches, which keeps the mop-up progressing towards a mate the shallow search cannot yet see.
    A move that stalemates the opponent is never chosen this way.
    """
    tied = 0
    for i in range(count):
        if st.root_scores[i] == DRAW_SCORE:
            tied += 1
    if tied < 2 or static_evaluate(pos, ev) < DRAW_TIEBREAK_MARGIN:
        return best
    best_static = -_INFINITY
    for i in range(count):
        if st.root_scores[i] != DRAW_SCORE:
            continue
        move = st.moves[0, i]
        if make_move(pos, move) == 0:
            unmake_move(pos)
            continue
        # The evaluation is from the opponent's view after the move; negate it. A position with
        # no legal move is never evaluated (it is stalemate here: a mate would not score 0).
        static = (
            -static_evaluate(pos, ev) if _has_legal(pos, st, 1, in_check(pos)) != 0 else -_INFINITY
        )
        unmake_move(pos)
        if static > best_static:
            best = move
            best_static = static
    return best


# ----------------------------------------------------------------------------- python edge


class FastEngine:
    """The compiled search behind the same interface as ``search.Engine``.

    One instance lives for the whole game: the transposition table, the killers and the history
    heuristic persist from move to move, and ``new_game`` resets them. Everything the search
    touches is allocated here, once, so no move ever waits for memory.
    """

    def __init__(self, tt_bits: int = TT_BITS, eval_bits: int = EVAL_BITS) -> None:
        self.state = new_state(tt_bits, eval_bits)
        self.position = new_position()
        # Nodes per second, kept as a running estimate so the node cap that backs up the clock is
        # a measurement rather than a guess. Replaced by the warm-up search at import, unless the
        # import ran out of budget before reaching it (mikhail_letal/warmup.py), in which case
        # this constant stands until the first real search measures a rate.
        self.node_rate = DEFAULT_NODE_RATE
        # Progress of the root iteration in flight, used to salvage a move after an abort.
        self._partial_move = NO_MOVE
        self._partial_score = 0
        self._first_root_move = NO_MOVE

    def new_game(self) -> None:
        """Forget everything learned in the previous game."""
        st = self.state
        st.tt_key[:] = 0
        st.tt_data[:] = 0
        st.eval_key[:] = 0
        st.eval_value[:] = 0
        st.killers[:] = NO_MOVE
        st.history[:] = 0
        st.ints[I_GENERATION] = 0

    # ------------------------------------------------------------------ public entry point

    def search(
        self,
        board: chess.Board,
        history: Sequence[int],
        soft_deadline: float,
        hard_deadline: float,
        max_depth: int = 64,
        node_limit: int | None = None,
        params: TimeParams = DEFAULT_PARAMS,
    ) -> SearchResult:
        """Search ``board`` and return the best move found within the limits.

        ``history`` holds the position keys (``fastboard.position_key``) of every earlier position
        of the game, the root included; any of them reached inside the tree is scored as a draw.
        ``soft_deadline`` is the target: after each completed iteration the next one is started
        only if it is predicted to finish inside it, from the time the completed iterations took
        (``timing.should_start_next_depth``, which also stretches the target for an unsettled root
        move and cuts it for a settled one). ``hard_deadline`` aborts the search wherever it is,
        and bounds everything that rule does. ``node_limit`` overrides the cap derived from the
        measured node rate.
        """
        start = time.perf_counter()
        st = self.state
        pos = self.position
        set_from_board(pos, board)
        self._load_history(history)

        ints = st.ints
        ints[I_NODES] = 0
        ints[I_SELDEPTH] = 0
        ints[I_NULL_MOVES] = 0
        ints[I_ABORT] = 0
        ints[I_PATH_DRAW] = 0
        ints[I_ROOT_PLY] = board.ply()
        ints[I_GENERATION] += 1  # every entry written below belongs to this move (see _tt_store)
        st.flt[F_HARD] = hard_deadline
        if node_limit is None:
            # Twice what the measured rate says the hard budget can buy: the clock is the real
            # limit, and the cap only has to catch a clock read that has stopped working.
            ahead = max(hard_deadline - start, 0.0)
            node_limit = int(self.node_rate * ahead * 2.0) + 100_000
        ints[I_NODE_LIMIT] = node_limit

        count = int(gen_legal(pos, st.moves[0]))
        if count == 0:
            score = -MATE_SCORE if int(in_check(pos)) else DRAW_SCORE
            return SearchResult(None, score, 0, 0, 0, time.perf_counter() - start, False)

        st.path[0] = pos.undo[pos.meta[M_PLY], U_KEY]
        # Halve every history score so what was learned last move fades rather than saturates.
        # In place on the array itself: `st` is a NamedTuple, so its fields cannot be rebound.
        np.right_shift(st.history, 1, out=st.history)

        best_move = NO_MOVE
        best_score = DRAW_SCORE
        completed_depth = 0
        aborted = False
        # A forced move needs no deep search; one iteration gives it a score and banks the time.
        limit = 1 if count == 1 else max(1, min(max_depth, MAX_PLY - 1))

        # What the next iteration is expected to cost is read off these: how long each completed
        # depth took, and how settled the root move is (see timing.should_start_next_depth).
        iteration_times: list[float] = []
        iteration_start = start
        stable_depths = 0

        for depth in range(1, limit + 1):
            score, move = self._search_root_aspirated(
                count, depth, best_move, best_score, completed_depth
            )
            if ints[I_ABORT]:
                aborted = True
                if self._partial_move != NO_MOVE and (
                    completed_depth == 0 or self._partial_move != best_move
                ):
                    # The previous best was searched first at this depth and a later move beat it
                    # (or there was no previous iteration at all): the new move is trusted.
                    best_move, best_score = self._partial_move, self._partial_score
                elif best_move == NO_MOVE:
                    # Aborted inside the very first root move of depth 1: any legal move beats
                    # none, and the ordering has put the most promising one first.
                    best_move = self._first_root_move
                break
            # How settled the root is: iterations in a row that kept the same best move, and how
            # far the score fell at this one (negative when it rose).
            stable_depths = stable_depths + 1 if completed_depth and move == best_move else 0
            score_drop = best_score - score if completed_depth else 0
            best_move, best_score, completed_depth = move, score, depth
            now = time.perf_counter()
            iteration_times.append(now - iteration_start)
            iteration_start = now
            if not should_start_next_depth(
                now - start,
                iteration_times,
                soft_deadline - start,
                hard_deadline - start,
                stable_depths,
                score_drop,
                params,
            ):
                break
            # A mate in n plies found at depth >= n cannot be shortened by searching deeper.
            if abs(score) >= MATE_THRESHOLD and MATE_SCORE - abs(score) <= depth:
                break

        elapsed = time.perf_counter() - start
        nodes = int(ints[I_NODES])
        if elapsed > 0.05 and nodes > 20_000:
            # Only from a search long enough to measure: a rate taken from a two-millisecond move
            # would be mostly start-up cost. A slow average rides out one noisy move.
            self.node_rate += 0.25 * (nodes / elapsed - self.node_rate)
        return SearchResult(
            move=move_to_chess(best_move) if best_move != NO_MOVE else None,
            score=best_score,
            depth=completed_depth,
            seldepth=int(ints[I_SELDEPTH]),
            nodes=nodes,
            elapsed=elapsed,
            aborted=aborted,
        )

    # ------------------------------------------------------------------ the root iteration

    def _search_root_aspirated(
        self,
        count: int,
        depth: int,
        previous_best: int,
        previous_score: int,
        completed_depth: int,
    ) -> tuple[int, int]:
        """One root iteration, with an aspiration window when the feature is on.

        The window starts ``ASPIRATION_WINDOW`` either side of the previous iteration's score. A
        result on or outside an edge is only a bound, so the failing edge is moved out by the
        widening factor (from the bound, not the old guess) and the iteration searched again;
        after ``ASPIRATION_MAX_FAILS`` failures the full window is used. A move that failed high
        is searched first in the repeat. Mate scores are not aspirated: their exact value is what
        the iteration is for.
        """
        if (
            not ASPIRATION_WINDOWS
            or depth < ASPIRATION_MIN_DEPTH
            or completed_depth == 0
            or abs(previous_score) >= MATE_THRESHOLD
        ):
            return self._search_root(count, depth, previous_best, -_INFINITY, _INFINITY)

        window = ASPIRATION_WINDOW
        alpha = previous_score - window
        beta = previous_score + window
        fails = 0
        while True:
            score, move = self._search_root(count, depth, previous_best, alpha, beta)
            if self.state.ints[I_ABORT] or alpha < score < beta:
                return score, move
            fails += 1
            if fails >= ASPIRATION_MAX_FAILS:
                alpha, beta = -_INFINITY, _INFINITY
            elif score <= alpha:
                window *= ASPIRATION_WIDEN
                alpha = score - window
            else:
                window *= ASPIRATION_WIDEN
                beta = score + window
                previous_best = move

    def _search_root(
        self, count: int, depth: int, previous_best: int, alpha: int, beta: int
    ) -> tuple[int, int]:
        """One iteration over every legal root move, best guess first, inside (alpha, beta).

        With the full window the returned score is exact; with a narrower one it may be a bound,
        which the caller detects and searches again.
        """
        st = self.state
        pos = self.position
        ev = EVAL_TABLES
        ints = st.ints
        self._partial_move = NO_MOVE
        key = int(pos.undo[pos.meta[M_PLY], U_KEY])
        if previous_best == NO_MOVE:
            # First iteration: the table persists through the game, so it may remember this
            # position from the previous move's search. Trying that move first is the ordinary
            # "table move first" rule applied at the root.
            index = int(_tt_probe(st, key))
            if index >= 0 and int(st.tt_data[index, 3]) != NO_MOVE:
                previous_best = int(st.tt_data[index, 3])

        _score_moves(pos, st, 0, count, previous_best)
        self._order_root(count)
        self._first_root_move = int(st.moves[0, 0])

        alpha_original = alpha
        best_score = -_INFINITY
        best_move = int(st.moves[0, 0])
        ints[I_PATH_DRAW] = 0
        for i in range(count):
            move = int(st.moves[0, i])
            make_move(pos, move)  # produced by gen_legal, so it cannot be illegal
            score = -int(negamax(pos, st, ev, depth - 1, -beta, -alpha, 1, 1))
            unmake_move(pos)
            if ints[I_ABORT]:
                return 0, best_move
            st.root_scores[i] = score
            if score > best_score:
                best_score = score
                best_move = move
                if score > alpha:
                    # Above alpha the score is exact or a lower bound (the fail-soft argument in
                    # negamax), so this move really is better than everything before it and can
                    # be trusted if the search is aborted before the iteration ends. A move that
                    # merely tops earlier fail-low bounds cannot.
                    self._partial_move, self._partial_score = move, score
                    alpha = score
                    if score >= beta:
                        break  # fail high: the caller widens the window and searches again

        # An exact score means no move failed high, so every root move was searched and every
        # entry of `root_scores` was written by this iteration, which is what the tie-break reads.
        if alpha_original < best_score < beta and best_score == DRAW_SCORE:
            best_move = int(_break_draw_tie(pos, st, ev, count, best_move))
        if best_score >= beta:
            flag = LOWER
        elif best_score <= alpha_original:
            flag = UPPER
            # Nothing raised alpha, so no move stands out; keep the old first move as the hint.
            if previous_best != NO_MOVE:
                best_move = previous_best
        else:
            flag = EXACT
        _store(st, key, depth, best_score, flag, best_move, 0, int(ints[I_PATH_DRAW]))
        return best_score, best_move

    def _order_root(self, count: int) -> None:
        """Sort the root moves by the scores ``_score_moves`` just wrote, best first.

        ``kind="stable"`` keeps the generator's order among equal scores, so the iteration is
        deterministic and matches what ``search._order_moves`` (a stable Python sort) produces.
        """
        st = self.state
        moves = st.moves[0]
        order = np.argsort(-st.order[0, :count], kind="stable")
        moves[:count] = moves[:count][order]

        # If the first root move is an under-promotion, put the queen promotion of the same pawn
        # to the same square before it. The root keeps the first move that reaches the best
        # score, so whichever promotion is searched first wins an exact tie; normally MVV-LVA
        # puts the queen first, but the table move overrides the ordering, and once an
        # under-promotion has been chosen it would keep being chosen.
        first = int(moves[0])
        promotion = (first >> PROMO_SHIFT) & PROMO_MASK
        if promotion in (0, QUEEN):
            return
        squares = first & (SQ_MASK | (SQ_MASK << SQ_BITS))
        for i in range(1, count):
            move = int(moves[i])
            if (move & (SQ_MASK | (SQ_MASK << SQ_BITS))) == squares and (
                move >> PROMO_SHIFT
            ) & PROMO_MASK == QUEEN:
                shifted = moves[:i].copy()
                moves[1 : i + 1] = shifted
                moves[0] = move
                return

    def _load_history(self, history: Sequence[int]) -> None:
        """Fill the open-addressed set of positions the game has already visited."""
        st = self.state
        st.history_keys[:] = 0
        mask = int(st.ints[I_HISTORY_MASK])
        for key in history:
            value = int(key)
            if value == 0:  # the "empty slot" marker; one position in 2**64 loses its repetition
                continue
            index = value & mask
            for _ in range(mask + 1):  # bounded: a full table must not spin here
                stored = int(st.history_keys[index])
                if stored == 0 or stored == value:
                    st.history_keys[index] = value
                    break
                index = (index + 1) & mask


# ----------------------------------------------------------------------------- warm-up

WARM_UP_SECONDS: float = 0.0
"""How long `warm_up()` spent compiling, filled in by the call below."""

_WARM_UP_FENS: Final = (
    chess.STARTING_FEN,
    # A middlegame with captures, checks and castling still available.
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    # A rook ending: few pieces, deep searches, the mop-up branch of the evaluation.
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    # A mate in two, so the mate-score paths and the early exit are compiled.
    "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1",
    # Promotions and en passant, for the ordering and the quiescence generator.
    "r3k2r/1P6/8/1Pp5/8/3p4/4P3/R3K2R w KQkq c6 0 1",
    # A pawn ending with the side to move in check, for the evasion branch of quiescence.
    "8/8/8/3k4/8/8/4P3/4K2r w - - 0 1",
)

# Every jitted function of this module, in the order the warm-up compiles them. The test suite
# asserts that each has a signature after import and gains none during a game: a function first
# compiled on the clock costs a move, and numba would do it silently.
JITTED: Final = (
    "_clock",
    "_check_limits",
    "_tt_probe",
    "_tt_store",
    "_store",
    "_in_history",
    "_cached_eval",
    "_make_null",
    "_unmake_null",
    "_has_non_pawn_material",
    "gen_captures",
    "_diagonal",
    "_first_occupied",
    "_direct_check",
    "_discovered_slider",
    "_discovery_survives",
    "_check_is_safe",
    "gen_checks",
    "_victim",
    "_score_moves",
    "_pick_best",
    "_reward_quiet_cutoff",
    "_has_unpinned_move",
    "_has_legal",
    "_game_over_score",
    "_static_score",
    "quiescence",
    "negamax",
    "_break_draw_tie",
)


def warm_up(engine: FastEngine, deadline: float | None = None) -> float:
    """Compile every jitted entry point with the exact argument types a game will pass.

    Each function is called directly first, so that none is left to be compiled on the clock by a
    branch the sample searches happen not to take; then real searches compile what only a search
    reaches -- the aspiration re-search, the null move, the reductions and the abort path.

    The work is cut into six phases in the order the search needs them: the helper functions and
    `quiescence` and `negamax`, without which no search runs at all; the root tie-break, which
    only a drawn root reaches; the sample searches, which cost almost nothing now that `negamax`
    is compiled and are pure insurance; and last the search that measures this machine's node
    rate. Each phase is skipped if the shared `warmup` budget says it would not finish by
    `deadline` (`None`, the default, means no limit outside `agent.py`); the sample and node-rate
    phases are skipped outright if `negamax` was, since running them would compile it anyway.
    Reference seconds are development-machine measurements, recorded in docs/PROVENANCE.md.
    """
    started = time.perf_counter()
    limit = warmup.budget()
    if deadline is not None:
        limit.deadline = deadline

    st = engine.state
    ev = EVAL_TABLES
    pos = engine.position
    set_from_board(pos, chess.Board(_WARM_UP_FENS[1]))
    st.flt[F_HARD] = time.perf_counter() + 3600.0
    st.ints[I_NODE_LIMIT] = 0

    def helpers() -> None:
        _clock()
        _check_limits(st)
        _tt_store(st, 1, 1, 0, EXACT, NO_MOVE)
        _tt_probe(st, 1)
        _store(st, 1, 1, 0, EXACT, NO_MOVE, 1, 0)
        _store(st, 1, 1, 0, EXACT, NO_MOVE, 1, 1)
        _in_history(st, 1)
        key = int(hash_position(pos, st.zobrist))
        _cached_eval(pos, st, ev, key)
        _unmake_null(pos, *_make_null(pos))
        _has_non_pawn_material(pos, WHITE)
        count = int(gen_pseudo(pos, st.moves[1]))
        gen_captures(pos, st.moves[1])
        _victim(pos, st.moves[1, 0])
        _score_moves(pos, st, 1, count, NO_MOVE)
        _pick_best(st, 1, 0, count)
        _reward_quiet_cutoff(pos, st, st.moves[1, 0], 1, 1)
        _has_unpinned_move(pos)
        _has_legal(pos, st, 1, 0)
        _has_legal(pos, st, 1, 1)
        _game_over_score(pos, st, 1, 0)
        _static_score(pos, st, ev, 1, 0)
        gen_checks(pos, st.moves[1])

    def compile_quiescence() -> None:
        quiescence(pos, st, ev, -_INFINITY, _INFINITY, 1, 0, 0)

    def compile_negamax() -> None:
        negamax(pos, st, ev, 2, -_INFINITY, _INFINITY, 1, 1)

    def tie_break() -> None:
        st.root_scores[:] = DRAW_SCORE
        _break_draw_tie(pos, st, ev, 1, int(st.moves[0, 0]))

    def samples() -> None:
        now = time.perf_counter()
        for fen in _WARM_UP_FENS:
            board = chess.Board(fen)
            engine.search(board, [position_key(board)], now + 3600.0, now + 3600.0, max_depth=4)
        # The abort path, with a node cap small enough to fire in the middle of an iteration.
        board = chess.Board(_WARM_UP_FENS[1])
        engine.search(board, [position_key(board)], now + 3600.0, now + 3600.0, node_limit=5_000)

    def measure_node_rate() -> None:
        # Seed the node-rate estimate that backs up the clock, from a real search of a fixed
        # size. Skipped, `engine.node_rate` keeps DEFAULT_NODE_RATE, which is deliberately high:
        # the node cap only has to catch a clock that has stopped working, and a cap that never
        # binds is safe where one that binds early would cut a search short.
        board = chess.Board(_WARM_UP_FENS[1])
        now = time.perf_counter()
        result = engine.search(
            board, [position_key(board)], now + 3600.0, now + 3600.0, node_limit=400_000
        )
        if result.elapsed > 0:
            engine.node_rate = result.nodes / result.elapsed

    limit.run("fastsearch.helpers", 5.3, helpers)
    limit.run("fastsearch.quiescence", 2.1, compile_quiescence)
    searchable = limit.run("fastsearch.negamax", 12.5, compile_negamax)
    limit.run("fastsearch.tie_break", 1.6, tie_break)
    engine.new_game()
    limit.run("fastsearch.samples", 0.1, samples, ready=searchable)
    engine.new_game()
    limit.run("fastsearch.node_rate", 0.9, measure_node_rate, ready=searchable)
    engine.new_game()

    global WARM_UP_SECONDS
    WARM_UP_SECONDS = time.perf_counter() - started
    return WARM_UP_SECONDS
