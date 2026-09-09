"""The always-legal fallback move: what the agent plays when the engine cannot be trusted.

It is used when the clock is nearly out, when the search raised, or when the search handed back
something that is not a legal move. Its only promises are that it is legal, deterministic and
fast (a few milliseconds). It looks one ply ahead: mate in one if there is one, otherwise the
move that leaves us the most material, preferring big captures and queen promotions, with the
UCI string as the last tie-break so the same position always gives the same move.
"""

from collections.abc import Sequence

import chess

# Textbook piece values in centipawns; the king has no exchange value.
_VALUE: dict[chess.PieceType, int] = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}


def fallback_move(board: chess.Board, legal: Sequence[chess.Move]) -> chess.Move:
    """Return the best move by a one-ply material rule. ``board`` is left untouched.

    Raises ``ValueError`` if ``legal`` is empty: the referee ends a game with no legal moves
    before ever asking us, so the agent treats that as an impossible state.
    """
    if not legal:
        raise ValueError("fallback_move needs at least one legal move")

    us = board.turn
    # Work on a copy without the move stack so the caller's board is never changed, even if
    # something unexpected interrupts the loop half way through a push/pop pair.
    probe = board.copy(stack=False)

    best_move = legal[0]
    best_rank: tuple[int, int, int, int, str] | None = None
    for move in legal:
        probe.push(move)
        mate = 1 if probe.is_checkmate() else 0
        material = _material(probe, us)
        probe.pop()
        # Higher is better in every numeric field. The UCI string is negated in effect by the
        # comparison below (smaller string wins), so ties are broken alphabetically.
        rank = (mate, material, _victim_value(board, move), _is_queen_promotion(move), move.uci())
        if best_rank is None or _better(rank, best_rank):
            best_rank = rank
            best_move = move
    return best_move


def _better(a: tuple[int, int, int, int, str], b: tuple[int, int, int, int, str]) -> bool:
    """True if ``a`` ranks above ``b``: larger numbers first, then the smaller UCI string."""
    if a[:4] != b[:4]:
        return a[:4] > b[:4]
    return a[4] < b[4]


def _material(board: chess.Board, us: chess.Color) -> int:
    """Our material minus theirs, in centipawns, from bitboard population counts."""
    total = 0
    for piece_type, value in _VALUE.items():
        ours = chess.popcount(board.pieces_mask(piece_type, us))
        theirs = chess.popcount(board.pieces_mask(piece_type, not us))
        total += value * (ours - theirs)
    return total


def _victim_value(board: chess.Board, move: chess.Move) -> int:
    """Value of the piece ``move`` captures, or 0 for a quiet move."""
    victim = board.piece_type_at(move.to_square)
    if victim is None:
        # The captured pawn is not on the destination square in an en passant capture.
        return _VALUE[chess.PAWN] if board.is_en_passant(move) else 0
    return _VALUE[victim]


def _is_queen_promotion(move: chess.Move) -> int:
    return 1 if move.promotion == chess.QUEEN else 0
