"""Compiled board, move generation and make/unmake for Mikhail LeTal (Stage 1, phase 1).

This module is the foundation of the numba engine described in ``docs/PLAN.md``. It owns a
chess position and produces its legal moves without creating a single Python object in the hot
path, so that the search and evaluation added in a later phase can run entirely inside compiled
code. `python-chess` remains the oracle: it builds the position (`from_board`), reads it back
(`to_fen`), and the tests check every generated move against it.

Why 0x88 mailbox with piece lists
---------------------------------
Correctness first, speed second, so the representation is chosen for how quickly it can be made
provably right rather than for peak throughput.

A 0x88 board is a 128-entry array laid out as sixteen files per rank, of which the left eight are
the real board and the right eight are a permanent guard region. Its whole value is one line:
``(square & 0x88) == 0`` is true exactly for the 64 real squares, so every knight hop, king step
and slider ray tests for "fell off the edge" with a single AND, with no wrapping bug possible.
The classic bug of a mailbox generator -- a rook on h4 sliding east onto a5 -- cannot be written
here. Rank and file are ``sq >> 4`` and ``sq & 7``, both exact.

Bitboards would generate moves several times faster, but they need magic multipliers or
kindergarten tables, careful 64-bit unsigned arithmetic (where Python's arbitrary-precision ints
leak into numba as int64 and silently overflow into negatives), and a separate correct-by-
construction pinned-piece analysis. That is the right representation to move to once the whole
engine is measured and green; it is the wrong one to debug first.

Piece lists (up to sixteen squares per colour, with a square->slot index for O(1) removal) avoid
scanning all 64 squares at every node. They cost one extra invariant, which `check_invariants`
verifies in the tests after every make and unmake.

Legality is by "make, then ask whether the mover's king is attacked", not by pin analysis. It is
the slower of the two standard schemes and by far the harder one to get wrong: en passant
discovered check, a king walking along the ray of the checking slider, and castling out of or
through check all fall out of it for free, with no special case to forget.

Conventions
-----------
- Every array is ``int32``. One dtype everywhere means one numba specialisation per function,
  no implicit casts, and no chance of an int8 piece code wrapping when it is multiplied.
- Colours are ``WHITE = 0`` and ``BLACK = 1`` (note that `python-chess` uses ``True``/``False``;
  `from_board` and `to_fen` are the only places the two meet).
- Piece types match `python-chess`: ``PAWN = 1 .. KING = 6``, so a promotion code can be handed
  to `chess.Move` unchanged. A piece code is ``piece_type | colour << 3``.
- Squares inside this module are 0x88; ``a1 = 0x00``, ``h1 = 0x07``, ``a8 = 0x70``. The rest of
  the engine and `python-chess` use 0..63 with ``a1 = 0``; `sq64` and `sq88` convert.
- A move is one int32: ``from | to << 7 | promotion << 14 | flag << 17``. Seven bits per square
  because 0x88 squares run to 119. ``promotion`` is 0 or a piece type; ``flag`` distinguishes a
  double pawn push, an en passant capture and a castling move, which make/unmake cannot infer
  from the squares alone.
"""

from __future__ import annotations

import time
from typing import Final, NamedTuple

import chess
import numpy as np
import numpy.typing as npt
from numba import njit

from mikhail_letal import warmup

# ----------------------------------------------------------------------------- piece encoding

EMPTY: Final = 0
PAWN: Final = 1
KNIGHT: Final = 2
BISHOP: Final = 3
ROOK: Final = 4
QUEEN: Final = 5
KING: Final = 6

WHITE: Final = 0
BLACK: Final = 1

COLOUR_SHIFT: Final = 3  # piece code = piece_type | colour << 3, so white 1..6, black 9..14
PIECE_TYPE_MASK: Final = 7

# ----------------------------------------------------------------------------- squares

NO_SQ: Final = -1
A1: Final = 0x00
B1: Final = 0x01
C1: Final = 0x02
D1: Final = 0x03
E1: Final = 0x04
F1: Final = 0x05
G1: Final = 0x06
H1: Final = 0x07
A8: Final = 0x70
B8: Final = 0x71
C8: Final = 0x72
D8: Final = 0x73
E8: Final = 0x74
F8: Final = 0x75
G8: Final = 0x76
H8: Final = 0x77

OFF_BOARD_MASK: Final = 0x88

# ----------------------------------------------------------------------------- castling rights

CASTLE_WK: Final = 1
CASTLE_WQ: Final = 2
CASTLE_BK: Final = 4
CASTLE_BQ: Final = 8

# Rights lost when a piece leaves *or* arrives on a square: the king's square kills both of its
# side's rights, a rook's home square kills that side's right on that wing. Applied to both the
# origin and the destination of every move, which covers a rook captured on its home square.
_CASTLE_MASK = np.full(128, CASTLE_WK | CASTLE_WQ | CASTLE_BK | CASTLE_BQ, dtype=np.int32)
_CASTLE_MASK[E1] = CASTLE_BK | CASTLE_BQ
_CASTLE_MASK[H1] = CASTLE_WQ | CASTLE_BK | CASTLE_BQ
_CASTLE_MASK[A1] = CASTLE_WK | CASTLE_BK | CASTLE_BQ
_CASTLE_MASK[E8] = CASTLE_WK | CASTLE_WQ
_CASTLE_MASK[H8] = CASTLE_WK | CASTLE_WQ | CASTLE_BQ
_CASTLE_MASK[A8] = CASTLE_WK | CASTLE_WQ | CASTLE_BK

# ----------------------------------------------------------------------------- move encoding

FLAG_NORMAL: Final = 0
FLAG_DOUBLE_PUSH: Final = 1
FLAG_EN_PASSANT: Final = 2
FLAG_CASTLE: Final = 3

SQ_BITS: Final = 7
SQ_MASK: Final = 0x7F
PROMO_SHIFT: Final = 14
PROMO_MASK: Final = 7
FLAG_SHIFT: Final = 17
FLAG_MASK: Final = 7

NO_MOVE: Final = 0  # a1a1 is not a legal move, so zero is a safe "no move" sentinel

# ----------------------------------------------------------------------------- position layout

# `meta` holds every scalar of the position, so that the whole state is arrays and a position can
# be copied with three `np.copyto` calls.
M_SIDE: Final = 0  # 0 white to move, 1 black
M_CASTLE: Final = 1  # CASTLE_* bit set
M_EP: Final = 2  # en passant target square (0x88) or NO_SQ
M_HALF: Final = 3  # halfmove clock (plies since the last capture or pawn move)
M_FULL: Final = 4  # fullmove number, incremented after Black moves
M_PLY: Final = 5  # depth of the undo stack
M_KING: Final = 6  # M_KING + colour: that king's square
M_COUNT: Final = 8  # M_COUNT + colour: number of pieces in that colour's list
META_N: Final = 10

# One undo record per ply. Everything here is either not derivable from the move (the captured
# piece, the previous clocks and rights) or expensive to recompute (the piece-list slot the
# captured piece occupied, which the swap-with-last removal would otherwise lose).
U_MOVE: Final = 0
U_CAPTURED: Final = 1  # piece code, 0 for a quiet move
U_CAPTURE_SQ: Final = 2  # differs from the move's destination for en passant
U_CAPTURE_SLOT: Final = 3
U_CASTLE: Final = 4
U_EP: Final = 5
U_HALF: Final = 6
UNDO_N: Final = 7

MAX_UNDO: Final = 512  # plies of make/unmake nesting; the referee caps a game at 600 plies
MAX_MOVES: Final = 256  # the most pseudo-legal moves a position can have is well under 256
PIECES_PER_SIDE: Final = 16

# The most moves one piece can contribute to `gen_pseudo`: a queen on an empty board reaches 27
# squares, and no other piece reaches more (a pawn tops out at twelve -- four quiet promotions
# and four each way as capture-promotions). `gen_pseudo` reserves this much room before it starts
# on a piece, which turns a buffer overflow from a silent write past the end of the array into a
# raised exception. Numbered rather than derived so the guard is one integer comparison.
MOVES_PER_PIECE_MAX: Final = 27
CASTLING_MOVES_MAX: Final = 2  # the two castling moves, written after the piece loop

# ----------------------------------------------------------------------------- direction tables

# 0x88 offsets. Adding one to a square moves one file east; adding sixteen moves one rank north.
_KNIGHT_DIRS = np.array([33, 31, 18, 14, -14, -18, -31, -33], dtype=np.int32)
_KING_DIRS = np.array([17, 16, 15, 1, -1, -15, -16, -17], dtype=np.int32)

# Sliding directions indexed by piece type, so the generator branches once on the type rather
# than three times. Row `pt` holds `_SLIDER_N[pt]` valid offsets.
_SLIDER_DIRS = np.zeros((7, 8), dtype=np.int32)
_SLIDER_N = np.zeros(7, dtype=np.int32)
_SLIDER_DIRS[BISHOP, :4] = (17, 15, -15, -17)
_SLIDER_N[BISHOP] = 4
_SLIDER_DIRS[ROOK, :4] = (16, 1, -1, -16)
_SLIDER_N[ROOK] = 4
_SLIDER_DIRS[QUEEN, :8] = (17, 16, 15, 1, -1, -15, -16, -17)
_SLIDER_N[QUEEN] = 8

_PROMOTION_PIECES = np.array([QUEEN, ROOK, BISHOP, KNIGHT], dtype=np.int32)


class Position(NamedTuple):
    """The whole position. numba types this as a namedtuple of arrays, so the arrays are shared
    with the caller and mutated in place; nothing is boxed on a call."""

    board: npt.NDArray[np.int32]  # 128 entries, 0x88 indexed; piece code or EMPTY
    plist: npt.NDArray[np.int32]  # 32 entries: colour * 16 + slot -> square
    pidx: npt.NDArray[np.int32]  # 128 entries: square -> slot in its colour's list, else -1
    meta: npt.NDArray[np.int32]  # META_N scalars
    undo: npt.NDArray[np.int32]  # MAX_UNDO x UNDO_N


def new_position() -> Position:
    """Allocate an empty position. Every array is preallocated once and never grows."""
    return Position(
        board=np.zeros(128, dtype=np.int32),
        plist=np.zeros(2 * PIECES_PER_SIDE, dtype=np.int32),
        pidx=np.full(128, -1, dtype=np.int32),
        meta=np.zeros(META_N, dtype=np.int32),
        undo=np.zeros((MAX_UNDO, UNDO_N), dtype=np.int32),
    )


def new_move_buffer() -> npt.NDArray[np.int32]:
    """A buffer for one call to `gen_pseudo` or `gen_legal`."""
    return np.zeros(MAX_MOVES, dtype=np.int32)


def new_move_stack(max_ply: int = 64) -> npt.NDArray[np.int32]:
    """One move buffer per recursion level, for `perft` (and later, the search)."""
    return np.zeros((max_ply, MAX_MOVES), dtype=np.int32)


# ----------------------------------------------------------------------------- square helpers


def sq88(square: int) -> int:
    """0..63 (a1 = 0, python-chess) -> 0x88."""
    return (square >> 3) * 16 + (square & 7)


def sq64(square: int) -> int:
    """0x88 -> 0..63 (a1 = 0, python-chess)."""
    return (square >> 4) * 8 + (square & 7)


# ----------------------------------------------------------------------------- move helpers


def pack_move(frm: int, to: int, promotion: int = 0, flag: int = FLAG_NORMAL) -> int:
    """Build the packed int32 move. Squares are 0x88."""
    return frm | (to << SQ_BITS) | (promotion << PROMO_SHIFT) | (flag << FLAG_SHIFT)


def move_from(move: int) -> int:
    return int(move) & SQ_MASK


def move_to(move: int) -> int:
    return (int(move) >> SQ_BITS) & SQ_MASK


def move_promotion(move: int) -> int:
    return (int(move) >> PROMO_SHIFT) & PROMO_MASK


def move_flag(move: int) -> int:
    return (int(move) >> FLAG_SHIFT) & FLAG_MASK


# ----------------------------------------------------------------------------- jitted core
#
# Every function below is compiled. `warm_up()` calls each of them once with the exact argument
# types they see at runtime, so the compilation lands in the platform's import budget.
#
# `cache=False` is deliberate: the platform wipes `/tmp` between games and every cache path
# points there, so an on-disk cache would never hit and would only add a write to the start-up
# budget. numba ships type stubs, so mypy checks these bodies and their call sites normally; the
# one place it cannot help is the return type of a call into another dispatcher, which it widens
# to `Any` (see `in_check`).


@njit(cache=False)
def attacked(board: npt.NDArray[np.int32], square: int, by_colour: int) -> int:
    """Is `square` (0x88) attacked by any piece of `by_colour`? Returns 1 or 0.

    The scan runs outward from the square rather than over the attacker's pieces, so it costs the
    same whatever the material is. `square` itself may be empty or occupied by either colour.
    """
    them = by_colour << COLOUR_SHIFT

    # Pawns. A white pawn attacking `square` stands one rank below it, a black pawn one above.
    pawn = PAWN | them
    if by_colour == WHITE:
        left, right = square - 17, square - 15
    else:
        left, right = square + 15, square + 17
    if (left & OFF_BOARD_MASK) == 0 and board[left] == pawn:
        return 1
    if (right & OFF_BOARD_MASK) == 0 and board[right] == pawn:
        return 1

    # Knights.
    for i in range(8):
        frm = square + _KNIGHT_DIRS[i]
        if (frm & OFF_BOARD_MASK) == 0 and board[frm] == (KNIGHT | them):
            return 1

    # Kings.
    for i in range(8):
        frm = square + _KING_DIRS[i]
        if (frm & OFF_BOARD_MASK) == 0 and board[frm] == (KING | them):
            return 1

    # Sliders. `_KING_DIRS` is ordered so that indices 0, 2, 5 and 7 are the diagonals; a
    # direction is diagonal exactly when its offset is not a multiple of 16 and not +-1.
    for i in range(8):
        direction = _KING_DIRS[i]
        diagonal = direction != 16 and direction != -16 and direction != 1 and direction != -1
        frm = square + direction
        while (frm & OFF_BOARD_MASK) == 0:
            piece = board[frm]
            if piece != EMPTY:
                if (piece >> COLOUR_SHIFT) == by_colour:
                    kind = piece & PIECE_TYPE_MASK
                    if kind == QUEEN or kind == (BISHOP if diagonal else ROOK):
                        return 1
                break
            frm += direction

    return 0


@njit(cache=False)
def in_check(pos: Position) -> int:
    """Is the side to move in check? Returns 1 or 0."""
    side = pos.meta[M_SIDE]
    # The annotation is what narrows the dispatcher's `Any` return back to `int` for mypy.
    hit: int = attacked(pos.board, pos.meta[M_KING + side], 1 - side)
    return hit


@njit(cache=False)
def _remove_piece(pos: Position, colour: int, square: int) -> int:
    """Take the piece on `square` out of `colour`'s piece list, returning the slot it held.

    The removal is swap-with-last, so the slot must be recorded for `_restore_piece` to undo it.
    The board array is *not* touched here; the caller owns that.
    """
    # The annotation narrows the array element back to `int` for mypy; numba ignores it.
    slot: int = pos.pidx[square]
    last = pos.meta[M_COUNT + colour] - 1
    moved = pos.plist[colour * PIECES_PER_SIDE + last]
    pos.plist[colour * PIECES_PER_SIDE + slot] = moved
    pos.pidx[moved] = slot
    pos.meta[M_COUNT + colour] = last
    pos.pidx[square] = -1
    return slot


@njit(cache=False)
def _restore_piece(pos: Position, colour: int, square: int, slot: int) -> None:
    """Exact inverse of `_remove_piece`: put the piece back in the slot it held."""
    last = pos.meta[M_COUNT + colour]
    moved = pos.plist[colour * PIECES_PER_SIDE + slot]
    pos.plist[colour * PIECES_PER_SIDE + last] = moved
    pos.pidx[moved] = last
    pos.plist[colour * PIECES_PER_SIDE + slot] = square
    pos.pidx[square] = slot
    pos.meta[M_COUNT + colour] = last + 1


@njit(cache=False)
def gen_pseudo(pos: Position, out: npt.NDArray[np.int32]) -> int:
    """Write every pseudo-legal move into `out` and return how many there are.

    "Pseudo-legal" means every rule is obeyed except that the mover may be left in check. The
    exception is castling, whose "not out of, through or into check" conditions are checked here
    because they are conditions on squares the king does not end on, which the make-and-test
    legality filter would not see.
    """
    board = pos.board
    side = pos.meta[M_SIDE]
    them = 1 - side
    ep = pos.meta[M_EP]
    n = 0
    # Read from the array rather than from MAX_MOVES so the guard is about the buffer actually
    # handed in, and so a caller with a shorter buffer is caught too.
    room = out.shape[0]

    for slot in range(pos.meta[M_COUNT + side]):
        # The overflow guard. One comparison per piece, before anything is written for it: the
        # writes below add at most MOVES_PER_PIECE_MAX for this piece, so if that much room is
        # left no write can pass the end. Nothing here is derived from a compile-time constant,
        # so the compiler cannot prove it away. A raise (rather than a truncated move list) is
        # deliberate: silently dropping legal moves would make the engine play a wrong move,
        # while the exception is caught in agent.py and answered with the fallback.
        if n + MOVES_PER_PIECE_MAX > room:
            raise IndexError("gen_pseudo: move buffer too small")
        frm = pos.plist[side * PIECES_PER_SIDE + slot]
        kind = board[frm] & PIECE_TYPE_MASK

        if kind == PAWN:
            if side == WHITE:
                forward = 16
                start_rank = 1
                promo_rank = 7
            else:
                forward = -16
                start_rank = 6
                promo_rank = 0

            to = frm + forward
            if (to & OFF_BOARD_MASK) == 0 and board[to] == EMPTY:
                if (to >> 4) == promo_rank:
                    for i in range(4):
                        out[n] = frm | (to << SQ_BITS) | (_PROMOTION_PIECES[i] << PROMO_SHIFT)
                        n += 1
                else:
                    out[n] = frm | (to << SQ_BITS)
                    n += 1
                    if (frm >> 4) == start_rank:
                        two = frm + 2 * forward
                        if board[two] == EMPTY:
                            out[n] = frm | (two << SQ_BITS) | (FLAG_DOUBLE_PUSH << FLAG_SHIFT)
                            n += 1

            for side_step in range(2):
                to = frm + forward + (1 if side_step == 0 else -1)
                if (to & OFF_BOARD_MASK) != 0:
                    continue
                target = board[to]
                if target != EMPTY:
                    if (target >> COLOUR_SHIFT) == them:
                        if (to >> 4) == promo_rank:
                            for i in range(4):
                                out[n] = (
                                    frm | (to << SQ_BITS) | (_PROMOTION_PIECES[i] << PROMO_SHIFT)
                                )
                                n += 1
                        else:
                            out[n] = frm | (to << SQ_BITS)
                            n += 1
                elif to == ep:
                    out[n] = frm | (to << SQ_BITS) | (FLAG_EN_PASSANT << FLAG_SHIFT)
                    n += 1

        elif kind in (KNIGHT, KING):
            dirs = _KNIGHT_DIRS if kind == KNIGHT else _KING_DIRS
            for i in range(8):
                to = frm + dirs[i]
                if (to & OFF_BOARD_MASK) != 0:
                    continue
                target = board[to]
                if target == EMPTY or (target >> COLOUR_SHIFT) == them:
                    out[n] = frm | (to << SQ_BITS)
                    n += 1

        else:
            for i in range(_SLIDER_N[kind]):
                direction = _SLIDER_DIRS[kind, i]
                to = frm + direction
                while (to & OFF_BOARD_MASK) == 0:
                    target = board[to]
                    if target == EMPTY:
                        out[n] = frm | (to << SQ_BITS)
                        n += 1
                    else:
                        if (target >> COLOUR_SHIFT) == them:
                            out[n] = frm | (to << SQ_BITS)
                            n += 1
                        break
                    to += direction

    # Castling. The king must be on its home square with the right still standing (guaranteed by
    # the rights bits, which are cleared the moment either piece moves), the squares between king
    # and rook must be empty, and the king must not stand on, cross, or land on an attacked
    # square. The rook may be attacked and may cross an attacked square; only the king may not.
    rights = pos.meta[M_CASTLE]
    if rights != 0:
        if n + CASTLING_MOVES_MAX > room:  # the same guard for the two moves written below
            raise IndexError("gen_pseudo: move buffer too small")
        if side == WHITE:
            king_side, queen_side, home = CASTLE_WK, CASTLE_WQ, E1
        else:
            king_side, queen_side, home = CASTLE_BK, CASTLE_BQ, E8
        if (rights & (king_side | queen_side)) != 0 and attacked(board, home, them) == 0:
            if (
                (rights & king_side) != 0
                and board[home + 1] == EMPTY
                and board[home + 2] == EMPTY
                and attacked(board, home + 1, them) == 0
                and attacked(board, home + 2, them) == 0
            ):
                out[n] = home | ((home + 2) << SQ_BITS) | (FLAG_CASTLE << FLAG_SHIFT)
                n += 1
            if (
                (rights & queen_side) != 0
                and board[home - 1] == EMPTY
                and board[home - 2] == EMPTY
                and board[home - 3] == EMPTY
                and attacked(board, home - 1, them) == 0
                and attacked(board, home - 2, them) == 0
            ):
                out[n] = home | ((home - 2) << SQ_BITS) | (FLAG_CASTLE << FLAG_SHIFT)
                n += 1

    return n


@njit(cache=False)
def make_move(pos: Position, move: int) -> int:
    """Play `move`, pushing an undo record. Returns 1 if the move was legal, 0 if it left the
    mover in check.

    The move is always played and the undo record is always pushed, so the caller must call
    `unmake_move` exactly once whatever the answer is. This is what makes the legality test free
    in a search: the move it wants to keep is already on the board.
    """
    board = pos.board
    meta = pos.meta
    side = meta[M_SIDE]
    them = 1 - side

    frm = move & SQ_MASK
    to = (move >> SQ_BITS) & SQ_MASK
    promotion = (move >> PROMO_SHIFT) & PROMO_MASK
    flag = (move >> FLAG_SHIFT) & FLAG_MASK

    ply = meta[M_PLY]
    undo = pos.undo
    # The undo-stack guard, one comparison per move made. Overflowing it would write past the end
    # of `undo` and corrupt whatever numpy put after it, which on the platform would show up as
    # anything at all; the exception reaches agent.py, which answers with the fallback.
    if ply >= undo.shape[0]:
        raise IndexError("make_move: undo stack full")
    undo[ply, U_MOVE] = move
    undo[ply, U_CASTLE] = meta[M_CASTLE]
    undo[ply, U_EP] = meta[M_EP]
    undo[ply, U_HALF] = meta[M_HALF]

    piece = board[frm]
    kind = piece & PIECE_TYPE_MASK

    # The captured piece. En passant is the one case where it does not stand on the destination:
    # it is the pawn that just double-pushed, one rank behind the destination.
    if flag == FLAG_EN_PASSANT:
        capture_sq = to - 16 if side == WHITE else to + 16
        captured = board[capture_sq]
    else:
        capture_sq = to
        captured = board[to]
    if captured == EMPTY:
        capture_sq = NO_SQ
        capture_slot = -1
    else:
        capture_slot = _remove_piece(pos, them, capture_sq)
        board[capture_sq] = EMPTY
    undo[ply, U_CAPTURED] = captured
    undo[ply, U_CAPTURE_SQ] = capture_sq
    undo[ply, U_CAPTURE_SLOT] = capture_slot

    # Move the piece, promoting it if asked.
    slot = pos.pidx[frm]
    board[frm] = EMPTY
    pos.pidx[frm] = -1
    board[to] = piece if promotion == 0 else (promotion | (side << COLOUR_SHIFT))
    pos.pidx[to] = slot
    pos.plist[side * PIECES_PER_SIDE + slot] = to
    if kind == KING:
        meta[M_KING + side] = to

    # The rook's half of a castling move. The king has already moved two files; the rook jumps
    # over it to the square the king crossed.
    if flag == FLAG_CASTLE:
        if to > frm:
            rook_from, rook_to = frm + 3, frm + 1
        else:
            rook_from, rook_to = frm - 4, frm - 1
        rook_slot = pos.pidx[rook_from]
        board[rook_to] = board[rook_from]
        board[rook_from] = EMPTY
        pos.pidx[rook_from] = -1
        pos.pidx[rook_to] = rook_slot
        pos.plist[side * PIECES_PER_SIDE + rook_slot] = rook_to

    meta[M_CASTLE] = meta[M_CASTLE] & _CASTLE_MASK[frm] & _CASTLE_MASK[to]
    # The en passant target is the square the pawn skipped, set after any double push whether or
    # not a capture is actually available -- that is what `chess.Board.ep_square` holds too.
    meta[M_EP] = (frm + to) // 2 if flag == FLAG_DOUBLE_PUSH else NO_SQ
    meta[M_HALF] = 0 if (kind == PAWN or captured != EMPTY) else meta[M_HALF] + 1
    if side == BLACK:
        meta[M_FULL] += 1
    meta[M_SIDE] = them
    meta[M_PLY] = ply + 1

    return 0 if attacked(board, meta[M_KING + side], them) != 0 else 1


@njit(cache=False)
def unmake_move(pos: Position) -> None:
    """Undo the last `make_move`, restoring board, piece lists, rights, en passant and clocks."""
    board = pos.board
    meta = pos.meta

    ply = meta[M_PLY] - 1
    meta[M_PLY] = ply
    undo = pos.undo
    move = undo[ply, U_MOVE]
    meta[M_CASTLE] = undo[ply, U_CASTLE]
    meta[M_EP] = undo[ply, U_EP]
    meta[M_HALF] = undo[ply, U_HALF]

    frm = move & SQ_MASK
    to = (move >> SQ_BITS) & SQ_MASK
    promotion = (move >> PROMO_SHIFT) & PROMO_MASK
    flag = (move >> FLAG_SHIFT) & FLAG_MASK

    side = 1 - meta[M_SIDE]
    meta[M_SIDE] = side
    if side == BLACK:
        meta[M_FULL] -= 1

    slot = pos.pidx[to]
    piece = board[to] if promotion == 0 else (PAWN | (side << COLOUR_SHIFT))
    board[to] = EMPTY
    pos.pidx[to] = -1
    board[frm] = piece
    pos.pidx[frm] = slot
    pos.plist[side * PIECES_PER_SIDE + slot] = frm
    if (piece & PIECE_TYPE_MASK) == KING:
        meta[M_KING + side] = frm

    if flag == FLAG_CASTLE:
        if to > frm:
            rook_from, rook_to = frm + 3, frm + 1
        else:
            rook_from, rook_to = frm - 4, frm - 1
        rook_slot = pos.pidx[rook_to]
        board[rook_from] = board[rook_to]
        board[rook_to] = EMPTY
        pos.pidx[rook_to] = -1
        pos.pidx[rook_from] = rook_slot
        pos.plist[side * PIECES_PER_SIDE + rook_slot] = rook_from

    # Restoring the captured piece last matters: for an ordinary capture its square is the
    # destination, which the block above had to clear first.
    captured = undo[ply, U_CAPTURED]
    if captured != EMPTY:
        capture_sq = undo[ply, U_CAPTURE_SQ]
        board[capture_sq] = captured
        _restore_piece(pos, 1 - side, capture_sq, undo[ply, U_CAPTURE_SLOT])


@njit(cache=False)
def gen_legal(pos: Position, out: npt.NDArray[np.int32]) -> int:
    """Write every legal move into `out` and return how many there are.

    Filtering happens in place: the write index never overtakes the read index, so no second
    buffer is needed.
    """
    n = gen_pseudo(pos, out)
    kept = 0
    for i in range(n):
        move = out[i]
        legal = make_move(pos, move)
        unmake_move(pos)
        if legal != 0:
            out[kept] = move
            kept += 1
    return kept


@njit(cache=False)
def perft(pos: Position, stack: npt.NDArray[np.int32], depth: int, ply: int) -> int:
    """Count the leaves of the legal move tree at `depth`. `stack` is one move buffer per ply."""
    if depth <= 0:
        return 1
    total = 0
    buffer = stack[ply]
    n = gen_pseudo(pos, buffer)
    for i in range(n):
        if make_move(pos, buffer[i]) != 0:
            if depth == 1:
                total += 1
            else:
                total += perft(pos, stack, depth - 1, ply + 1)
        unmake_move(pos)
    return total


@njit(cache=False)
def has_legal_move(pos: Position, out: npt.NDArray[np.int32]) -> int:
    """1 if the side to move has any legal move, else 0 (checkmate or stalemate)."""
    n = gen_pseudo(pos, out)
    for i in range(n):
        legal = make_move(pos, out[i])
        unmake_move(pos)
        if legal != 0:
            return 1
    return 0


# ----------------------------------------------------------------------------- position key
#
# A Zobrist key: one random 64-bit number per (piece, square), one for "Black to move", one per
# castling-rights combination and one per en passant file, exclusive-ORed together. Two positions
# with the same key are the same position up to a collision of about one in 2**64.
#
# The key is what the search uses for its transposition table and for repetition detection, so
# what it includes has to match what "the same position" means to the referee: piece placement,
# side to move, castling rights, and the en passant square *only when a capture onto it is
# actually available*. python-chess's own repetition key (`Board._transposition_key`) applies the
# stricter test of a fully legal en passant capture; here it is a pawn of the side to move
# standing on one of the two squares that could take, which differs only when that pawn is
# pinned. Both sides of the engine call this one function, so the search and the game history it
# is handed can never disagree about which positions are equal.
#
# The numbers are generated here from numpy's PCG64 with a fixed seed, so they are reproducible
# and provably not copied from anywhere (docs/PROVENANCE.md).

ZOBRIST_SEED: Final = 20260908

Z_PIECES: Final = 2 * 7 * 128  # [(colour * 7 + piece type) * 128 + square]
Z_SIDE: Final = Z_PIECES  # exclusive-ORed in when Black is to move
Z_CASTLE: Final = Z_SIDE + 1  # + the four castling-rights bits, so sixteen entries
Z_EP: Final = Z_CASTLE + 16  # + the file of the en passant square, eight entries
Z_LEN: Final = Z_EP + 8


def zobrist_keys(seed: int = ZOBRIST_SEED) -> npt.NDArray[np.int64]:
    """The random numbers behind the position key, drawn once at import."""
    rng = np.random.default_rng(seed)
    info = np.iinfo(np.int64)
    keys = rng.integers(info.min, info.max, size=Z_LEN, dtype=np.int64, endpoint=True)
    # A key of exactly zero would collide with the "empty slot" marker in the search's tables.
    keys[keys == 0] = 1
    return keys


ZOBRIST: Final = zobrist_keys()


@njit(cache=False)
def hash_position(pos: Position, zob: npt.NDArray[np.int64]) -> int:
    """The Zobrist key of `pos`. See the note above for what it includes and why."""
    board = pos.board
    meta = pos.meta
    key = np.int64(0)
    for colour in range(2):
        base = colour * PIECES_PER_SIDE
        for slot in range(meta[M_COUNT + colour]):
            square = pos.plist[base + slot]
            kind = board[square] & PIECE_TYPE_MASK
            key ^= zob[(colour * 7 + kind) * 128 + square]
    if meta[M_SIDE] == BLACK:
        key ^= zob[Z_SIDE]
    key ^= zob[Z_CASTLE + meta[M_CASTLE]]

    ep = meta[M_EP]
    if ep != NO_SQ:
        side = meta[M_SIDE]
        pawn = PAWN | (side << COLOUR_SHIFT)
        if side == WHITE:
            left, right = ep - 17, ep - 15
        else:
            left, right = ep + 15, ep + 17
        taker = ((left & OFF_BOARD_MASK) == 0 and board[left] == pawn) or (
            (right & OFF_BOARD_MASK) == 0 and board[right] == pawn
        )
        if taker:
            key ^= zob[Z_EP + (ep & 7)]
    # The annotation narrows numba's dispatcher return from `Any` back to `int` for mypy.
    result: int = key
    return result


def position_key(board: chess.Board) -> int:
    """`hash_position` for a `chess.Board`. The boundary helper the game history uses."""
    return int(hash_position(from_board(board), ZOBRIST))


# ----------------------------------------------------------------------------- python-chess edge

_PIECE_FROM_CHESS: Final = {
    chess.PAWN: PAWN,
    chess.KNIGHT: KNIGHT,
    chess.BISHOP: BISHOP,
    chess.ROOK: ROOK,
    chess.QUEEN: QUEEN,
    chess.KING: KING,
}
_FEN_LETTER: Final = " PNBRQK"


def set_from_board(pos: Position, board: chess.Board) -> None:
    """Overwrite `pos` with `board`'s position. The undo stack is reset."""
    pos.board[:] = EMPTY
    pos.pidx[:] = -1
    pos.plist[:] = 0
    pos.meta[:] = 0
    pos.meta[M_KING + WHITE] = NO_SQ
    pos.meta[M_KING + BLACK] = NO_SQ

    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece is None:
            continue
        colour = WHITE if piece.color == chess.WHITE else BLACK
        kind = _PIECE_FROM_CHESS[piece.piece_type]
        target = sq88(square)
        pos.board[target] = kind | (colour << COLOUR_SHIFT)
        slot = int(pos.meta[M_COUNT + colour])
        if slot >= PIECES_PER_SIDE:
            # `chess.Board` happily holds positions that cannot arise in a game; the piece lists
            # are fixed-size, so refuse loudly rather than write past the end of one.
            raise ValueError(f"more than {PIECES_PER_SIDE} pieces of one colour in {board.fen()}")
        pos.plist[colour * PIECES_PER_SIDE + slot] = target
        pos.pidx[target] = slot
        pos.meta[M_COUNT + colour] = slot + 1
        if kind == KING:
            pos.meta[M_KING + colour] = target

    pos.meta[M_SIDE] = WHITE if board.turn == chess.WHITE else BLACK
    rights = 0
    if board.has_kingside_castling_rights(chess.WHITE):
        rights |= CASTLE_WK
    if board.has_queenside_castling_rights(chess.WHITE):
        rights |= CASTLE_WQ
    if board.has_kingside_castling_rights(chess.BLACK):
        rights |= CASTLE_BK
    if board.has_queenside_castling_rights(chess.BLACK):
        rights |= CASTLE_BQ
    pos.meta[M_CASTLE] = rights
    pos.meta[M_EP] = NO_SQ if board.ep_square is None else sq88(board.ep_square)
    pos.meta[M_HALF] = board.halfmove_clock
    pos.meta[M_FULL] = board.fullmove_number
    pos.meta[M_PLY] = 0


def from_board(board: chess.Board) -> Position:
    """A fresh `Position` holding `board`'s position."""
    pos = new_position()
    set_from_board(pos, board)
    return pos


def from_fen(fen: str) -> Position:
    """A fresh `Position` for a FEN. `python-chess` does the parsing, so the two agree by
    construction and a malformed FEN raises where the rest of the engine already expects it to."""
    return from_board(chess.Board(fen))


def legal_moves(pos: Position) -> list[int]:
    """The legal moves as packed integers. A boundary helper; the hot path uses `gen_legal`."""
    buffer = new_move_buffer()
    n = gen_legal(pos, buffer)
    return [int(buffer[i]) for i in range(n)]


def to_fen(pos: Position) -> str:
    """The FEN, matching `chess.Board.fen()` byte for byte.

    That includes `python-chess`'s default en passant rule: the target square is printed only
    when a legal en passant capture actually exists, so a double push that nobody can answer
    prints a dash.
    """
    rows = []
    for rank in range(7, -1, -1):
        row = ""
        empty = 0
        for file in range(8):
            piece = int(pos.board[rank * 16 + file])
            if piece == EMPTY:
                empty += 1
                continue
            if empty:
                row += str(empty)
                empty = 0
            letter = _FEN_LETTER[piece & PIECE_TYPE_MASK]
            row += letter if (piece >> COLOUR_SHIFT) == WHITE else letter.lower()
        if empty:
            row += str(empty)
        rows.append(row)

    rights = int(pos.meta[M_CASTLE])
    castling = ""
    if rights & CASTLE_WK:
        castling += "K"
    if rights & CASTLE_WQ:
        castling += "Q"
    if rights & CASTLE_BK:
        castling += "k"
    if rights & CASTLE_BQ:
        castling += "q"

    ep = int(pos.meta[M_EP])
    ep_field = "-"
    if ep != NO_SQ and any(move_flag(m) == FLAG_EN_PASSANT for m in legal_moves(pos)):
        ep_field = chess.SQUARE_NAMES[sq64(ep)]

    return "{} {} {} {} {} {}".format(
        "/".join(rows),
        "w" if int(pos.meta[M_SIDE]) == WHITE else "b",
        castling or "-",
        ep_field,
        int(pos.meta[M_HALF]),
        int(pos.meta[M_FULL]),
    )


def move_to_uci(move: int) -> str:
    """UCI for a packed move, castling included (`e1g1`, as `python-chess` reports it)."""
    text = chess.SQUARE_NAMES[sq64(move_from(move))] + chess.SQUARE_NAMES[sq64(move_to(move))]
    promotion = move_promotion(move)
    if promotion:
        text += _FEN_LETTER[promotion].lower()
    return text


def move_to_chess(move: int) -> chess.Move:
    """The `chess.Move` for a packed move."""
    promotion = move_promotion(move)
    return chess.Move(
        sq64(move_from(move)),
        sq64(move_to(move)),
        promotion=promotion if promotion else None,
    )


def move_from_chess(pos: Position, move: chess.Move) -> int:
    """The packed move for a `chess.Move` in `pos`.

    The flags a packed move carries -- double push, en passant, castling -- are properties of the
    position rather than of the move, so this needs the position to recover them. Castling is
    recognised as the king moving two files, which is how `python-chess` reports it outside
    Chess960.
    """
    frm = sq88(move.from_square)
    to = sq88(move.to_square)
    promotion = _PIECE_FROM_CHESS[move.promotion] if move.promotion else 0
    piece = int(pos.board[frm])
    kind = piece & PIECE_TYPE_MASK

    flag = FLAG_NORMAL
    if kind == KING and abs((to & 7) - (frm & 7)) == 2:
        flag = FLAG_CASTLE
    elif kind == PAWN:
        if abs((to >> 4) - (frm >> 4)) == 2:
            flag = FLAG_DOUBLE_PUSH
        elif (to & 7) != (frm & 7) and pos.board[to] == EMPTY:
            flag = FLAG_EN_PASSANT
    return pack_move(frm, to, promotion, flag)


def check_invariants(pos: Position) -> None:
    """Raise if the piece lists, the index map and the board disagree.

    Not used at runtime. The tests call it after every make and unmake in a slow perft, which is
    what turns the piece-list bookkeeping from a thing to worry about into a thing that is
    checked on millions of positions.
    """
    for colour in (WHITE, BLACK):
        count = int(pos.meta[M_COUNT + colour])
        if not 0 <= count <= PIECES_PER_SIDE:
            raise AssertionError(f"piece count {count} out of range for colour {colour}")
        seen = set()
        for slot in range(count):
            square = int(pos.plist[colour * PIECES_PER_SIDE + slot])
            piece = int(pos.board[square])
            if piece == EMPTY:
                raise AssertionError(f"piece list points at empty square {square:#x}")
            if (piece >> COLOUR_SHIFT) != colour:
                raise AssertionError(f"piece list of {colour} holds a {piece} at {square:#x}")
            if int(pos.pidx[square]) != slot:
                raise AssertionError(f"pidx[{square:#x}] != {slot}")
            seen.add(square)
        king = int(pos.meta[M_KING + colour])
        if king != NO_SQ and int(pos.board[king]) != (KING | (colour << COLOUR_SHIFT)):
            raise AssertionError(f"king square {king:#x} of {colour} holds no king")

    occupied = 0
    for square in range(128):
        if square & OFF_BOARD_MASK:
            if int(pos.board[square]) != EMPTY:
                raise AssertionError(f"off-board square {square:#x} is not empty")
            continue
        piece = int(pos.board[square])
        if piece == EMPTY:
            if int(pos.pidx[square]) != -1:
                raise AssertionError(f"pidx[{square:#x}] set for an empty square")
            continue
        occupied += 1
        colour = piece >> COLOUR_SHIFT
        slot = int(pos.pidx[square])
        if not 0 <= slot < int(pos.meta[M_COUNT + colour]):
            raise AssertionError(f"square {square:#x} has slot {slot} outside its list")
        if int(pos.plist[colour * PIECES_PER_SIDE + slot]) != square:
            raise AssertionError(f"plist round trip failed for {square:#x}")
    if occupied != int(pos.meta[M_COUNT + WHITE]) + int(pos.meta[M_COUNT + BLACK]):
        raise AssertionError("piece counts do not match the board")


# ----------------------------------------------------------------------------- warm-up

WARM_UP_SECONDS: float = 0.0
"""How long `warm_up()` spent compiling, filled in by the call below."""

JITTED: Final = (
    "attacked",
    "in_check",
    "_remove_piece",
    "_restore_piece",
    "gen_pseudo",
    "gen_legal",
    "make_move",
    "unmake_move",
    "perft",
    "has_legal_move",
    "hash_position",
)
"""Every jitted function here, so `agent.py` and the tests can check that all of them were
compiled by `warm_up()` and that none gains a second specialisation during a game."""

WARM_UP_FEN: Final = "r3k2r/1P6/8/1Pp5/8/3p4/4P3/R3K2R w KQkq c6 0 1"
"""White to move with every irregular move available at once: O-O, O-O-O, b5xc6 en passant,
b7xa8 and b7b8 promotions, e2e4, and e2xd3."""


def warm_up(deadline: float | None = None) -> float:
    """Compile every jitted entry point with the exact argument types it sees at runtime.

    Called at import so that the cost lands in the platform's 90-second start-up budget. `/tmp`
    is wiped between games on the platform, so `cache=True` would never hit and is not used.
    Returns the seconds spent.

    The work is cut into four phases, most important first, and each is skipped if the shared
    `warmup` budget says it would not finish by `deadline` (`None`, the default, means the
    budget's own deadline, which is unset outside `agent.py` and so imposes no limit). Anything
    skipped compiles on the first move instead; see `mikhail_letal/warmup.py` for why that trade
    is the right way round. `perft` is last because the game never calls it -- only the tests do.
    """
    started = time.perf_counter()
    limit = warmup.budget()
    if deadline is not None:
        limit.deadline = deadline

    pos = from_board(chess.Board())
    buffer = new_move_buffer()
    stack = new_move_stack(8)
    drill = from_fen(WARM_UP_FEN)

    def generate() -> None:
        attacked(pos.board, E1, BLACK)
        in_check(pos)
        gen_pseudo(pos, buffer)
        gen_legal(pos, buffer)
        has_legal_move(pos, buffer)

    def make_unmake() -> None:
        # A position built to exercise every make/unmake branch at least once: castling both
        # ways, an en passant capture, a capture-promotion, a quiet promotion, a double push, an
        # ordinary capture, and a rook move that gives up a castling right.
        for uci in ("e1g1", "e1c1", "b5c6", "b7a8q", "b7b8n", "e2e4", "e2d3", "a1b1"):
            move = move_from_chess(drill, chess.Move.from_uci(uci))
            make_move(drill, move)
            unmake_move(drill)
        # One nested make/unmake so that the Black branches (the fullmove counter, the other pawn
        # direction) are compiled too.
        make_move(drill, move_from_chess(drill, chess.Move.from_uci("e2e4")))
        make_move(drill, move_from_chess(drill, chess.Move.from_uci("d3e2")))
        unmake_move(drill)
        unmake_move(drill)
        slot = _remove_piece(drill, WHITE, E1)
        _restore_piece(drill, WHITE, E1, slot)

    def hashing() -> None:
        hash_position(pos, ZOBRIST)
        hash_position(drill, ZOBRIST)  # a position with an en passant square, the other branch

    def counting() -> None:
        perft(pos, stack, 2, 0)

    # The reference seconds are what each phase costs on the development machine, measured
    # 2026-09-08 and recorded in docs/PROVENANCE.md; the budget scales them by this machine's
    # observed slowdown to decide whether the next phase still fits.
    limit.run("fastboard.generate", 2.6, generate)
    limit.run("fastboard.make_unmake", 0.4, make_unmake)
    limit.run("fastboard.hash", 0.2, hashing)
    limit.run("fastboard.perft", 0.5, counting)

    global WARM_UP_SECONDS
    WARM_UP_SECONDS = time.perf_counter() - started
    return WARM_UP_SECONDS


warm_up()
