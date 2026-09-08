"""Compiled static evaluation: the same function as ``mikhail_letal.evaluation``, on ``fastboard``.

This is a *port*, not a redesign. Every term, every weight and every rounding decision is the one
in ``evaluation.py``, which stays in the repository as the specification and as the oracle the
gate compares against: ``tests/test_fasteval.py`` requires the two to return the same integer on
twenty thousand positions drawn from playouts of the curated openings. A difference of one
centipawn anywhere is a bug, because both sides compute the same integer arithmetic; nothing
here is a floating-point approximation of anything.

The one thing that genuinely changes is the *representation*. ``evaluation.py`` reads bitboards
and leans on Python's arbitrary-precision integers for the pawn-structure fills (``bb >> 8``,
``bb << 32`` and so on). Inside numba those would be 64-bit machine words, where a signed right
shift sign-extends and a left shift silently overflows -- the classic way to get an evaluation
that is right in Python and wrong when compiled. So the pawn structure is computed from *per-file
summaries* instead: for each colour and file, how many pawns stand there and the highest and
lowest rank they occupy. Every bitboard fill in ``evaluation.py`` is a statement about those
three numbers, and the docstrings below say which:

* a white pawn is passed when no black pawn on its own or an adjacent file stands on a *higher*
  rank -- that is, when the highest black pawn on each of those files is below it;
* a file with *k* pawns contributes *k - 1* doubled pawns, whichever direction the fill runs;
* a pawn is isolated when the two neighbouring files hold no pawn of its colour.

Reading the position costs two passes over the piece lists (at most 32 squares), which is why no
bitboards are built at all: the mailbox already knows where every piece is.

Scores are centipawns from the side to move's point of view, exactly as in ``evaluation.py``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final, NamedTuple

import chess
import numpy as np
import numpy.typing as npt
from numba import njit

from mikhail_letal import warmup
from mikhail_letal.evaluation import (
    DRAW_SCORE,
    PHASE_TOTAL,
    STRUCTURE_TERMS,
    STRUCTURE_WEIGHTS,
    load_tables,
)
from mikhail_letal.fastboard import (
    BISHOP,
    BLACK,
    KNIGHT,
    M_COUNT,
    M_KING,
    M_SIDE,
    PAWN,
    PIECE_TYPE_MASK,
    PIECES_PER_SIDE,
    QUEEN,
    ROOK,
    WHITE,
    Position,
    from_board,
    sq64,
)

# ----------------------------------------------------------------------------- table layout

# Index of each structural weight in the `weights` array. The names match STRUCTURE_WEIGHTS.
W_PASSED_MG: Final = 0
W_PASSED_EG: Final = 1
W_DOUBLED: Final = 2
W_ISOLATED: Final = 3
W_BISHOP_PAIR: Final = 4
W_ROOK_OPEN: Final = 5
W_ROOK_SEMI: Final = 6
W_KING_SHIELD: Final = 7
W_COUNT: Final = 8

_WEIGHT_KEYS: Final = (
    "passed_pawn_mg",
    "passed_pawn_eg",
    "doubled_pawn",
    "isolated_pawn",
    "bishop_pair",
    "rook_open_file",
    "rook_semi_open_file",
    "king_shield",
)

# Index of each scalar in the `misc` array.
E_MOPUP_EDGE: Final = 0
E_MOPUP_CLOSE: Final = 1
E_MOPUP_MIN_MATERIAL: Final = 2
E_STRUCTURE_ON: Final = 3  # mirrors evaluation.STRUCTURE_TERMS, so both switch together
E_COUNT: Final = 4

# Layout of the per-file pawn summary in `scratch`, as [group + colour * 8 + file].
S_COUNT: Final = 0  # pawns of that colour on that file
S_TOP: Final = 16  # highest rank index they occupy, -1 for none
S_BOTTOM: Final = 32  # lowest rank index they occupy, 8 for none
S_PIECES: Final = 48  # [S_PIECES + colour * 8 + piece type]: pieces of that type and colour
S_LEN: Final = 64


class EvalTables(NamedTuple):
    """Everything the compiled evaluation reads, as arrays numba can index without boxing.

    ``scratch`` is working memory rather than a table. The evaluation is never called from inside
    itself (nothing it does can recurse) and the engine is single-threaded by rule, so one buffer
    shared by every call is safe and saves an allocation per node.
    """

    pst_mg: npt.NDArray[np.int32]  # [colour, piece type, 0x88 square], material folded in
    pst_eg: npt.NDArray[np.int32]
    values_mg: npt.NDArray[np.int32]  # middlegame material value by piece type
    phase_weights: npt.NDArray[np.int32]  # by piece type; zero for pawns and kings
    weights: npt.NDArray[np.int32]  # the structural weights, indexed by W_*
    misc: npt.NDArray[np.int32]  # the scalars, indexed by E_*
    centre: npt.NDArray[np.int32]  # distance to the nearest centre square, by 0x88 square
    scratch: npt.NDArray[np.int32]  # S_LEN entries of per-file pawn summary


def load_eval_tables(path: Path | None = None) -> EvalTables:
    """Build the compiled evaluation's arrays from ``weights/pst.json``.

    ``evaluation.load_tables`` does the reading and the material folding, so there is exactly one
    parser for the weights file and the two evaluations cannot drift apart in how they read it.
    The only work here is re-indexing: ``evaluation`` indexes ``[colour][piece][0..63]`` with
    ``colour`` 1 = White (python-chess's ``WHITE is True``), while ``fastboard`` uses
    ``WHITE = 0`` and 0x88 squares.
    """
    tables = load_tables(path)

    pst_mg = np.zeros((2, 7, 128), dtype=np.int32)
    pst_eg = np.zeros((2, 7, 128), dtype=np.int32)
    for colour in (WHITE, BLACK):
        source = 1 - colour  # fastboard WHITE = 0 is python-chess colour index 1
        for piece_type in range(1, 7):
            for square in range(128):
                if square & 0x88:
                    continue
                pst_mg[colour, piece_type, square] = tables.mg[source][piece_type][sq64(square)]
                pst_eg[colour, piece_type, square] = tables.eg[source][piece_type][sq64(square)]

    weights = np.zeros(W_COUNT, dtype=np.int32)
    for index, key in enumerate(_WEIGHT_KEYS):
        weights[index] = STRUCTURE_WEIGHTS[key]

    misc = np.zeros(E_COUNT, dtype=np.int32)
    misc[E_MOPUP_EDGE] = tables.mopup_edge
    misc[E_MOPUP_CLOSE] = tables.mopup_close
    # "At least a rook's worth" of non-pawn material triggers the mop-up (evaluation.py).
    misc[E_MOPUP_MIN_MATERIAL] = tables.piece_values_mg[chess.ROOK]
    misc[E_STRUCTURE_ON] = 1 if STRUCTURE_TERMS else 0

    centre = np.zeros(128, dtype=np.int32)
    for square in range(128):
        if square & 0x88:
            continue
        file_index, rank_index = square & 7, square >> 4
        centre[square] = min(abs(file_index - 3), abs(file_index - 4)) + min(
            abs(rank_index - 3), abs(rank_index - 4)
        )

    return EvalTables(
        pst_mg=pst_mg,
        pst_eg=pst_eg,
        values_mg=np.array(tables.piece_values_mg, dtype=np.int32),
        phase_weights=np.array(tables.phase_weights, dtype=np.int32),
        weights=weights,
        misc=misc,
        centre=centre,
        scratch=np.zeros(S_LEN, dtype=np.int32),
    )


TABLES = load_eval_tables()


# ----------------------------------------------------------------------------- jitted core


@njit(cache=False)
def evaluate(pos: Position, ev: EvalTables) -> int:
    """Static evaluation in centipawns from the side to move's point of view.

    Line for line the same function as ``evaluation.evaluate``: the insufficient-material draw,
    the tapered material-and-square tables, the structural terms, the phase blend truncated
    toward zero, and the mop-up bonus for a pawnless ending against a bare king.
    """
    board = pos.board
    meta = pos.meta
    plist = pos.plist
    scratch = ev.scratch
    for i in range(16):
        scratch[S_COUNT + i] = 0
        scratch[S_TOP + i] = -1  # no pawn of this colour on this file
        scratch[S_BOTTOM + i] = 8
        scratch[S_PIECES + i] = 0  # [colour * 8 + piece type], index 7 of each half unused

    mg = 0
    eg = 0
    bishops_light = 0  # over both colours: what python-chess's `self.bishops` mask means
    bishops_dark = 0

    # First pass: the tables, the piece counts and the per-file pawn summary.
    for colour in range(2):
        base = colour * PIECES_PER_SIDE
        for slot in range(meta[M_COUNT + colour]):
            square = plist[base + slot]
            kind = board[square] & PIECE_TYPE_MASK
            scratch[S_PIECES + colour * 8 + kind] += 1
            if colour == WHITE:
                mg += ev.pst_mg[WHITE, kind, square]
                eg += ev.pst_eg[WHITE, kind, square]
            else:
                mg -= ev.pst_mg[BLACK, kind, square]
                eg -= ev.pst_eg[BLACK, kind, square]
            file_index = square & 7
            rank_index = square >> 4
            if kind == PAWN:
                cell = colour * 8 + file_index
                scratch[S_COUNT + cell] += 1
                if rank_index > scratch[S_TOP + cell]:
                    scratch[S_TOP + cell] = rank_index
                if rank_index < scratch[S_BOTTOM + cell]:
                    scratch[S_BOTTOM + cell] = rank_index
            elif kind == BISHOP:
                if ((file_index + rank_index) & 1) == 1:
                    bishops_light += 1
                else:
                    bishops_dark += 1

    white = S_PIECES + WHITE * 8
    black = S_PIECES + BLACK * 8
    pawns = scratch[white + PAWN] + scratch[black + PAWN]
    knights = scratch[white + KNIGHT] + scratch[black + KNIGHT]
    bishops = scratch[white + BISHOP] + scratch[black + BISHOP]
    rooks = scratch[white + ROOK] + scratch[black + ROOK]
    queens = scratch[white + QUEEN] + scratch[black + QUEEN]

    # Insufficient material. Only knights and bishops can ever be insufficient, so the check is
    # skipped whenever a pawn, rook or queen is on the board -- the same short-circuit, and the
    # same semantics, as evaluation.evaluate.
    if pawns == 0 and rooks == 0 and queens == 0:
        white_out = _has_insufficient_material(
            scratch[white + KNIGHT],
            scratch[white + BISHOP],
            scratch[black + KNIGHT],
            scratch[black + BISHOP],
            knights,
            bishops_light,
            bishops_dark,
        )
        if white_out:
            black_out = _has_insufficient_material(
                scratch[black + KNIGHT],
                scratch[black + BISHOP],
                scratch[white + KNIGHT],
                scratch[white + BISHOP],
                knights,
                bishops_light,
                bishops_dark,
            )
            if black_out:
                return DRAW_SCORE

    phase = (
        ev.phase_weights[KNIGHT] * knights
        + ev.phase_weights[BISHOP] * bishops
        + ev.phase_weights[ROOK] * rooks
        + ev.phase_weights[QUEEN] * queens
    )
    if phase > PHASE_TOTAL:
        phase = PHASE_TOTAL

    if ev.misc[E_STRUCTURE_ON] != 0:
        structure_mg, structure_eg = _structure(pos, ev)
        mg += structure_mg
        eg += structure_eg

    # Blend the two phases, truncating toward zero rather than flooring, so that a position and
    # its colour-swapped mirror get exactly opposite scores.
    total = mg * phase + eg * (PHASE_TOTAL - phase)
    score = total // PHASE_TOTAL if total >= 0 else -((-total) // PHASE_TOTAL)

    if pawns == 0:
        score += _mopup(pos, ev)

    signed: int = score if meta[M_SIDE] == WHITE else -score
    return signed


@njit(cache=False)
def _has_insufficient_material(
    own_knights: int,
    own_bishops: int,
    their_knights: int,
    their_bishops: int,
    all_knights: int,
    bishops_light: int,
    bishops_dark: int,
) -> bool:
    """python-chess's ``Board.has_insufficient_material`` for one colour, given that no pawn,
    rook or queen is on the board (the caller has checked that, exactly as ``evaluation.py`` does).

    With those gone, "this colour's pieces" is its king plus its knights and bishops, and "the
    other colour's pieces that are neither king nor queen" is their knights plus their bishops,
    which is what makes the popcount tests below plain sums.
    """
    if own_knights > 0:
        # A knight mates only with help: we may hold nothing else, and they nothing that could
        # be sacrificed into a self-mate.
        return (1 + own_knights + own_bishops) <= 2 and (their_knights + their_bishops) == 0
    if own_bishops > 0:
        # Bishops on one colour of square can never mate; a knight anywhere allows a self-mate.
        same_colour = bishops_dark == 0 or bishops_light == 0
        return same_colour and all_knights == 0
    return True


@njit(cache=False)
def _structure(pos: Position, ev: EvalTables) -> tuple[int, int]:
    """(middlegame, endgame) structural terms from White's point of view.

    Passed pawns by rank, doubled and isolated pawns, the bishop pair, rooks on open and
    semi-open files, and the middlegame king pawn shield -- the same six terms, with the same
    weights, as ``evaluation._structure`` and ``evaluation.pawn_structure``.
    """
    board = pos.board
    meta = pos.meta
    plist = pos.plist
    scratch = ev.scratch
    weights = ev.weights
    passed_mg = weights[W_PASSED_MG]
    passed_eg = weights[W_PASSED_EG]
    mg = 0
    eg = 0

    # Second pass: passed pawns and rook files, both of which need the file summary complete.
    for colour in range(2):
        base = colour * PIECES_PER_SIDE
        for slot in range(meta[M_COUNT + colour]):
            square = plist[base + slot]
            kind = board[square] & PIECE_TYPE_MASK
            if kind != PAWN and kind != ROOK:
                continue
            file_index = square & 7
            first = file_index - 1 if file_index > 0 else 0
            last = file_index + 1 if file_index < 7 else 7

            if kind == PAWN:
                rank_index = square >> 4
                blocked = False
                for neighbour in range(first, last + 1):
                    if colour == WHITE:
                        # A black pawn above this one on an adjacent file stops it.
                        if scratch[S_TOP + 8 + neighbour] > rank_index:
                            blocked = True
                            break
                    elif scratch[S_BOTTOM + neighbour] < rank_index:
                        blocked = True
                        break
                if not blocked:
                    # Ranks advanced from home: 1 on the second rank ... 6 on the seventh.
                    advance = rank_index if colour == WHITE else 7 - rank_index
                    if colour == WHITE:
                        mg += passed_mg * advance
                        eg += passed_eg * advance
                    else:
                        mg -= passed_mg * advance
                        eg -= passed_eg * advance
            else:
                own = scratch[S_COUNT + colour * 8 + file_index]
                total = scratch[S_COUNT + file_index] + scratch[S_COUNT + 8 + file_index]
                if total == 0:
                    bonus = weights[W_ROOK_OPEN]
                elif own == 0:
                    bonus = weights[W_ROOK_SEMI]
                else:
                    bonus = 0
                if bonus != 0:
                    if colour == WHITE:
                        mg += bonus
                        eg += bonus
                    else:
                        mg -= bonus
                        eg -= bonus

    # Doubled and isolated pawns. On a file holding k pawns exactly k - 1 of them have another
    # own pawn above; a pawn is isolated when neither neighbouring file holds one of its colour.
    doubled = 0
    isolated = 0
    for colour in range(2):
        sign = 1 if colour == WHITE else -1
        for file_index in range(8):
            here = scratch[S_COUNT + colour * 8 + file_index]
            if here == 0:
                continue
            doubled += sign * (here - 1)
            left = scratch[S_COUNT + colour * 8 + file_index - 1] if file_index > 0 else 0
            right = scratch[S_COUNT + colour * 8 + file_index + 1] if file_index < 7 else 0
            if left == 0 and right == 0:
                isolated += sign * here
    # Both penalties count against the side that has them, in both phases.
    penalty = weights[W_DOUBLED] * doubled + weights[W_ISOLATED] * isolated
    mg -= penalty
    eg -= penalty

    pair = weights[W_BISHOP_PAIR]
    if scratch[S_PIECES + WHITE * 8 + BISHOP] >= 2:
        mg += pair
        eg += pair
    if scratch[S_PIECES + BLACK * 8 + BISHOP] >= 2:
        mg -= pair
        eg -= pair

    # King shield, middlegame only: own pawns on the king's file or a neighbour, one or two
    # ranks towards the enemy.
    shield = 0
    for colour in range(2):
        king = meta[M_KING + colour]
        if king < 0:
            continue
        king_file = king & 7
        king_rank = king >> 4
        step = 1 if colour == WHITE else -1
        own_pawn = PAWN | (colour << 3)
        found = 0
        first = king_file - 1 if king_file > 0 else 0
        last = king_file + 1 if king_file < 7 else 7
        for ahead in range(1, 3):
            rank_index = king_rank + step * ahead
            if rank_index < 0 or rank_index > 7:
                continue
            for neighbour in range(first, last + 1):
                if board[rank_index * 16 + neighbour] == own_pawn:
                    found += 1
        shield += found if colour == WHITE else -found
    mg += weights[W_KING_SHIELD] * shield

    return mg, eg


@njit(cache=False)
def _mopup(pos: Position, ev: EvalTables) -> int:
    """Bonus (from White's view) for the side hunting a bare king in a pawnless ending, else 0.

    Two geometric ideas, as in ``evaluation._mopup``: the lone king can only be mated on the
    edge, so reward its distance from the centre; and the mating side's king must help, so
    reward closeness between the kings.
    """
    scratch = ev.scratch
    white = S_PIECES + WHITE * 8
    black = S_PIECES + BLACK * 8
    white_pieces = (
        scratch[white + KNIGHT]
        + scratch[white + BISHOP]
        + scratch[white + ROOK]
        + scratch[white + QUEEN]
    )
    black_pieces = (
        scratch[black + KNIGHT]
        + scratch[black + BISHOP]
        + scratch[black + ROOK]
        + scratch[black + QUEEN]
    )
    if white_pieces == 0 and scratch[white + PAWN] == 0:
        weak, strong, sign = WHITE, BLACK, -1
    elif black_pieces == 0 and scratch[black + PAWN] == 0:
        weak, strong, sign = BLACK, WHITE, 1
    else:
        return 0

    values = ev.values_mg
    base = S_PIECES + strong * 8
    material = (
        values[KNIGHT] * scratch[base + KNIGHT]
        + values[BISHOP] * scratch[base + BISHOP]
        + values[ROOK] * scratch[base + ROOK]
        + values[QUEEN] * scratch[base + QUEEN]
    )
    if material < ev.misc[E_MOPUP_MIN_MATERIAL]:
        return 0

    weak_king = pos.meta[M_KING + weak]
    strong_king = pos.meta[M_KING + strong]
    apart = abs((weak_king & 7) - (strong_king & 7)) + abs((weak_king >> 4) - (strong_king >> 4))
    edge = ev.misc[E_MOPUP_EDGE] * ev.centre[weak_king]
    # The annotation narrows numpy's element type back to `int` for mypy; numba ignores it.
    bonus: int = sign * (edge + ev.misc[E_MOPUP_CLOSE] * (14 - apart))
    return bonus


# ----------------------------------------------------------------------------- python edge


def evaluate_board(board: chess.Board) -> int:
    """The compiled evaluation of a ``chess.Board``. For tests and tools only: it rebuilds the
    whole position, which the search never does."""
    return int(evaluate(from_board(board), TABLES))


# ----------------------------------------------------------------------------- warm-up

WARM_UP_SECONDS: float = 0.0
"""How long `warm_up()` spent compiling, filled in by the call below."""

JITTED: Final = ("evaluate", "_has_insufficient_material", "_structure", "_mopup")
"""Every jitted function here; see `fastboard.JITTED`."""

_WARM_UP_FENS: Final = (
    chess.STARTING_FEN,
    # A middlegame with passers, doubled and isolated pawns, rooks on open and semi-open files.
    "r4rk1/1pp2ppp/p1np1q2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R2Q1RK1 w - - 0 1",
    # A pawnless mop-up: bare black king, so the mop-up term and its material gate both run.
    "8/8/4k3/8/8/8/4Q3/4K3 w - - 0 1",
    # Insufficient material: king and bishop against king.
    "8/8/4k3/8/8/8/4B3/4K3 w - - 0 1",
    # A king with a full shield, and a knight-only ending for the other branch of the draw test.
    "8/8/8/8/8/5N2/PPP5/2K4k b - - 0 1",
)


def warm_up(deadline: float | None = None) -> float:
    """Compile the evaluation with the exact argument types the search will pass it.

    One phase: the first FEN compiles `evaluate` and the three helpers, and the rest only widen
    the branches already inside them, so there is nothing here worth splitting. It is skipped
    whole if the shared `warmup` budget says it would not finish by `deadline` -- see
    `mikhail_letal/warmup.py`.
    """
    started = time.perf_counter()
    limit = warmup.budget()
    if deadline is not None:
        limit.deadline = deadline

    def evaluate_all() -> None:
        for fen in _WARM_UP_FENS:
            evaluate(from_board(chess.Board(fen)), TABLES)

    limit.run("fasteval.evaluate", 1.6, evaluate_all)  # 1.6 s on the development machine

    global WARM_UP_SECONDS
    WARM_UP_SECONDS = time.perf_counter() - started
    return WARM_UP_SECONDS


warm_up()
