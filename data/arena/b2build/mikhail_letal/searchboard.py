"""A search-only board: python-chess for the rules, running totals for the evaluation.

``SearchBoard`` owns a ``chess.Board`` and does nothing to it that python-chess would not do —
every move is made and unmade by ``chess.Board.push``/``pop``, and move generation and legality
still come from python-chess. What it adds is three integers kept up to date beside the board:

* ``mg`` and ``eg``: the middlegame and endgame sums of the combined material-plus-square tables
  over every piece, from **White's** point of view (White's pieces added, Black's subtracted);
* ``phase``: the raw phase weight of the pieces on the board (24 with a full board, 0 in a
  king-and-pawn ending; promotions can push it above 24 and the blend clamps it).

A move touches at most three squares, so updating the three totals costs a handful of table
lookups, where recomputing them from scratch walks all 32 pieces. ``evaluate()`` is then the
non-per-piece part of the evaluation only: the structural terms, the phase blend and the mop-up.

The result is *exactly* what ``evaluation.evaluate`` would return — both paths end in the same
``evaluation.evaluate_running`` on the same three numbers, and ``tests/test_searchboard.py``
asserts the running totals equal ``evaluation.material_pst`` after every make and every unmake
along random walks from every opening in ``data/openings.txt``.

Special cases the update has to get right, all handled explicitly below: a capture (the victim
leaves both sums and the phase), en passant (the captured pawn is not on the move's target
square), a promotion (the promoted piece replaces the pawn in both sums and *adds* to the phase),
and castling (the rook moves too). Unmake restores the previous three numbers from a stack, so it
cannot drift even if a make were wrong.
"""

from __future__ import annotations

import chess

from mikhail_letal.evaluation import TABLES, evaluate_running, material_pst

# Signed piece-square rows, indexed ``[colour][piece_type] -> (mg row, eg row)``. The Black rows
# are negated so that adding a piece is always ``+= row[square]`` whatever its colour, and the
# Black tables are already square-mirrored by ``evaluation.load_tables``. Index 0 of the piece
# dimension is never used (python-chess piece types start at 1); it holds zeros so a stray index
# would be loud in a test rather than silently wrong.
_ZERO = [0] * 64
_ROWS: tuple[tuple[tuple[list[int], list[int]], ...], ...] = tuple(
    tuple(
        (_ZERO, _ZERO)
        if piece_type == 0
        else (
            [value if colour else -value for value in TABLES.mg[colour][piece_type]],
            [value if colour else -value for value in TABLES.eg[colour][piece_type]],
        )
        for piece_type in range(7)
    )
    for colour in (0, 1)
)

# Phase weight per piece type; zero for pawns and kings (see evaluation.load_tables).
_PHASE: list[int] = TABLES.phase_weights

_BB = chess.BB_SQUARES
_NULL_MOVE = chess.Move.null()


class SearchBoard:
    """A ``chess.Board`` plus the three running evaluation totals for the position on it."""

    __slots__ = ("_stack", "board", "eg", "mg", "phase")

    def __init__(self, board: chess.Board) -> None:
        if board.chess960:
            # The castling update below assumes the standard king-two-files move; Chess960 would
            # need the rook's real square. The engine only ever sees standard positions.
            raise ValueError("SearchBoard does not support Chess960")
        self.board = board
        self._stack: list[tuple[int, int, int]] = []
        self.mg, self.eg, self.phase = material_pst(board)

    def evaluate(self) -> int:
        """The static evaluation of the current position, in centipawns from the mover's view."""
        return evaluate_running(self.board, self.mg, self.eg, self.phase)

    def push(self, move: chess.Move) -> None:
        """Make ``move`` on the board and fold it into the three running totals."""
        board = self.board
        mg = self.mg
        eg = self.eg
        phase = self.phase
        self._stack.append((mg, eg, phase))

        from_square = move.from_square
        to_square = move.to_square
        mover = board.turn
        rows = _ROWS[mover]

        # The moving piece leaves its square. Testing the bitboards in place is the same work as
        # ``board.piece_type_at`` without the call.
        from_bb = _BB[from_square]
        if board.pawns & from_bb:
            piece_type = chess.PAWN
        elif board.knights & from_bb:
            piece_type = chess.KNIGHT
        elif board.bishops & from_bb:
            piece_type = chess.BISHOP
        elif board.rooks & from_bb:
            piece_type = chess.ROOK
        elif board.queens & from_bb:
            piece_type = chess.QUEEN
        else:
            piece_type = chess.KING
        mg_row, eg_row = rows[piece_type]
        mg -= mg_row[from_square]
        eg -= eg_row[from_square]

        to_bb = _BB[to_square]
        if board.occupied & to_bb:
            # An ordinary capture: the victim stands on the target square.
            if board.pawns & to_bb:
                victim = chess.PAWN
            elif board.knights & to_bb:
                victim = chess.KNIGHT
            elif board.bishops & to_bb:
                victim = chess.BISHOP
            elif board.rooks & to_bb:
                victim = chess.ROOK
            elif board.queens & to_bb:
                victim = chess.QUEEN
            else:  # unreachable in a legal game: a king is never captured
                victim = chess.KING
            victim_mg, victim_eg = _ROWS[not mover][victim]
            mg -= victim_mg[to_square]
            eg -= victim_eg[to_square]
            phase -= _PHASE[victim]
        elif (
            piece_type == chess.PAWN
            and to_square == board.ep_square
            and from_square & 7 != to_square & 7
        ):
            # En passant: a pawn changing file onto the empty en passant square takes the pawn
            # that stands beside it, one rank back from the target.
            captured = to_square - 8 if mover else to_square + 8
            victim_mg, victim_eg = _ROWS[not mover][chess.PAWN]
            mg -= victim_mg[captured]
            eg -= victim_eg[captured]

        promotion = move.promotion
        if promotion:
            # The pawn never arrives; the promoted piece does, and it counts toward the phase.
            piece_type = promotion
            phase += _PHASE[promotion]
            mg_row, eg_row = rows[promotion]
        mg += mg_row[to_square]
        eg += eg_row[to_square]

        if piece_type == chess.KING and to_square - from_square in (2, -2):
            # Castling is generated as a king move of two files (python-chess converts its own
            # king-takes-rook encoding back to that), and no other king move covers two files.
            if to_square > from_square:
                rook_from = from_square + 3
                rook_to = from_square + 1
            else:
                rook_from = from_square - 4
                rook_to = from_square - 1
            rook_mg, rook_eg = rows[chess.ROOK]
            mg += rook_mg[rook_to] - rook_mg[rook_from]
            eg += rook_eg[rook_to] - rook_eg[rook_from]

        self.mg = mg
        self.eg = eg
        self.phase = phase
        board.push(move)

    def pop(self) -> None:
        """Unmake the last move and restore the totals saved when it was made."""
        self.board.pop()
        self.mg, self.eg, self.phase = self._stack.pop()

    def push_null(self) -> None:
        """Pass the move to the opponent. No piece moves, so the totals do not change."""
        self.board.push(_NULL_MOVE)

    def pop_null(self) -> None:
        """Undo ``push_null``."""
        self.board.pop()
