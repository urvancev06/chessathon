"""Per-game position history, for repetition detection that agrees with the referee.

The platform tells us nothing but a FEN and a clock, once per move. A FEN carries no history, and
the referee claims threefold repetition automatically, so to know which positions have already
occurred we must remember them ourselves: the first position we receive (the curated opening the
game starts from), the position after each move we play, and each position we are handed after
the opponent replies.

Positions are identified by ``board._transposition_key()``, python-chess's own repetition key
(piece bitboards, side to move, castling rights, en passant square). It is what
``Board.is_repetition`` uses, so what we count as a repetition is exactly what the referee counts.
FEN strings are not compared, because the halfmove clock and move number in a FEN are not part of
repetition identity.
"""

from collections.abc import Hashable, Mapping

import chess

# A position key as produced by ``chess.Board._transposition_key()``.
type Key = Hashable


class GameState:
    """Counts of every position seen this game, plus a little bookkeeping for the agent."""

    def __init__(self) -> None:
        # How many times each position has occurred in the game so far.
        self._counts: dict[Key, int] = {}
        # The last position we know about: the one after our own last move, normally. The next
        # position we receive must be one legal move away from it, or the game has desynced.
        self._last: chess.Board | None = None
        self._own_moves = 0
        self._desyncs = 0

    def observe(self, board: chess.Board) -> bool:
        """Record the position we were just handed. Returns False if it was not expected.

        First call of the game: start the history here. Later calls: the position should be one
        legal opponent move away from the position after our last move; if it is, add it to the
        history. If it is not (a desync: the platform and we disagree about the game), forget the
        old history, start again from this position and return False. The current position is in
        the history either way, so the searcher can treat a return to it as a repetition.
        """
        key = board._transposition_key()
        if self._last is None:
            self._restart(board, key)
            return True

        # Reconstruct the opponent's move: the received position must be reachable by exactly one
        # legal move from where we left the board. Trying every legal move is cheap (tens of
        # moves) and needs no move information from the platform. The piece a pawn promoted to
        # matters here: promoting to a knight and to a queen give different keys.
        probe = self._last
        for move in probe.legal_moves:
            probe.push(move)
            reached = probe._transposition_key() == key
            probe.pop()
            if reached:
                self._counts[key] = self._counts.get(key, 0) + 1
                self._last = board.copy(stack=False)
                return True

        self._desyncs += 1
        self._restart(board, key)
        return False

    def record_own_move(self, board_after: chess.Board) -> None:
        """Record the position after the move we chose was pushed onto the board."""
        key = board_after._transposition_key()
        self._counts[key] = self._counts.get(key, 0) + 1
        # Copy without the move stack: the caller may keep mutating its board, and legal-move
        # generation needs only the current position (castling rights and the en passant square
        # are part of it), not how it was reached.
        self._last = board_after.copy(stack=False)
        self._own_moves += 1

    @property
    def history(self) -> Mapping[Key, int]:
        """Occurrence count of every position seen so far, including the current one.

        The searcher probes this on every node, so the dict itself is returned rather than a
        proxy; the ``Mapping`` type is the promise that callers only read it.
        """
        return self._counts

    @property
    def own_moves(self) -> int:
        """How many moves we have played this game (drives the time budget)."""
        return self._own_moves

    @property
    def desyncs(self) -> int:
        """How many times the received position was not where we expected the game to be."""
        return self._desyncs

    def _restart(self, board: chess.Board, key: Key) -> None:
        """Forget every earlier position and begin the history at ``board``."""
        self._counts = {key: 1}
        self._last = board.copy(stack=False)
