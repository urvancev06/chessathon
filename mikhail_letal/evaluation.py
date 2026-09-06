"""Placeholder evaluation: material only, until tools/gen_pst.py and the tapered PST land.

This file exists so the search can be developed against the final public API (constants and
``evaluate``). It is replaced by the full Stage 0 evaluation described in docs/DESIGN.md.
"""

import chess

MATE_SCORE = 100_000
MATE_THRESHOLD = MATE_SCORE - 1_000
DRAW_SCORE = 0
PHASE_TOTAL = 24

_MATERIAL = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}


def is_mate_score(score: int) -> bool:
    return abs(score) >= MATE_THRESHOLD


def evaluate(board: chess.Board) -> int:
    """Material balance from the side to move's point of view."""
    if board.is_insufficient_material():
        return DRAW_SCORE
    total = 0
    for piece_type, value in _MATERIAL.items():
        white = chess.popcount(board.pieces_mask(piece_type, chess.WHITE))
        black = chess.popcount(board.pieces_mask(piece_type, chess.BLACK))
        total += value * (white - black)
    return total if board.turn == chess.WHITE else -total
