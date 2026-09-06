"""Iterative-deepening alpha-beta search for Mikhail LeTal (Stage 0).

How the search works, in one page
---------------------------------
The engine answers "which move is best here?" with a *negamax* tree search. Every score is
measured from the side to move's point of view, so the value of a position is the negation of the
best value the opponent can reach after any reply: ``value(p) = max(-value(child))``. Alpha-beta
pruning keeps a window ``(alpha, beta)`` of scores that can still matter to the ancestors; a child
whose value falls outside the window is abandoned early because a better alternative is already
known higher up the tree.

The search is run to depth 1, then depth 2, then 3, ... (*iterative deepening*). This looks
wasteful but is not: each iteration is several times cheaper than the next, the earlier ones fill
the transposition table with good first-try moves that make the deeper ones prune far better, and
the engine always has a fully-searched answer ready when the clock runs out.

At the leaves of the tree (``depth <= 0``) the position is not simply evaluated, because a static
evaluation in the middle of a capture sequence is meaningless. A *quiescence* search continues
with captures (and queen promotions) only, until the position is quiet, and the side to move may
always choose to "stand pat" and accept the static evaluation instead of capturing.

Move ordering is the heart of alpha-beta efficiency: the sooner the best move is tried, the more
of the remaining moves can be pruned. Moves are tried in this order: the move the transposition
table remembers as best for this position, then captures by *MVV-LVA* (take the Most Valuable
Victim with the Least Valuable Attacker), then two *killer* moves (quiet moves that recently
caused cutoffs at the same distance from the root), then the remaining quiet moves ranked by the
*history heuristic* (how often each from-to move caused a cutoff anywhere in the tree).

Repetition and the fifty-move rule are handled inside the tree so the engine neither drifts into
a draw when it is winning nor avoids one when it is losing. The referee's 600-ply cap is applied
the same way.

Everything is deterministic: identical inputs and limits produce identical output. The only
clock-dependent behaviour is the abort at the hard deadline.
"""

from __future__ import annotations

import time
from collections.abc import Hashable, Iterator, Mapping
from dataclasses import dataclass

import chess

from mikhail_letal.evaluation import (
    DRAW_SCORE,
    MATE_SCORE,
    MATE_THRESHOLD,
    evaluate,
    is_mate_score,
)

Key = Hashable

# How often (in nodes) the search reads the clock and checks the node limit. Reading the clock
# costs about as much as a node, so it is done in batches.
NODE_CHECK_INTERVAL = 1024

# Deepest ply the tree may reach, including quiescence and check extensions. Python's default
# recursion limit is 1000; each search ply uses a couple of frames, so 128 leaves ample room.
MAX_PLY = 128

# The platform declares any game that reaches this many plies a draw (the opening position counts).
GAME_PLY_CAP = 600

# Transposition-table entry flags: what the stored score means.
EXACT = 0  # the score is the exact minimax value at the stored depth
LOWER = 1  # the true value is at least the stored score (a beta cutoff happened)
UPPER = 2  # the true value is at most the stored score (every move failed low)

# (depth, ply-independent score, flag, best move). The move is the one to try first next time.
TTEntry = tuple[int, int, int, chess.Move | None]

# One more than the largest possible score, so it is beyond every real value including mates.
_INFINITY = MATE_SCORE + 1

# Move-ordering bands. Each band is far above the next so that a history score can never
# overtake a killer, nor a killer a capture. Higher sorts first.
_ORDER_TT = 3_000_000
_ORDER_CAPTURE = 2_000_000
_ORDER_KILLER_FIRST = 1_000_001
_ORDER_KILLER_SECOND = 1_000_000
_HISTORY_MAX = _ORDER_KILLER_SECOND - 1

# Rank of each piece type for MVV-LVA, indexed by python-chess piece type (PAWN=1 .. KING=6).
# Only the order matters, not the magnitudes, so the plain ranks 1..6 are used. Index 0 is for
# "no piece" and contributes nothing.
_MVV_LVA_RANK = (0, 1, 2, 3, 4, 5, 6)

# Sentinel for "no move" in the integer move codes used by the ordering (see _move_code).
_NO_MOVE_CODE = -1

# Squares a pawn must stand on to promote with its next push, per colour.
_PROMOTION_RANK = {chess.WHITE: chess.BB_RANK_7, chess.BLACK: chess.BB_RANK_2}

_now = time.perf_counter


class SearchAborted(Exception):
    """Raised inside the tree when the hard deadline or the node limit is reached."""


@dataclass
class SearchResult:
    """What one call to ``Searcher.search`` produced."""

    move: chess.Move | None  # None only when the root position has no legal moves
    score: int  # side-to-move perspective, from the iteration that chose ``move``
    depth: int  # last completed iteration depth
    seldepth: int  # deepest ply reached, quiescence included
    nodes: int
    elapsed: float  # seconds, measured inside search()
    aborted: bool  # the hard deadline or the node limit stopped an iteration


def _move_code(move: chess.Move) -> int:
    """Pack a move into one small int so ordering can compare moves with integer equality.

    Comparing ``chess.Move`` objects goes through a Python-level ``__eq__``; comparing ints is
    several times cheaper, and the ordering does this for every move at every node.
    """
    return move.from_square | move.to_square << 6 | (move.promotion or 0) << 12


class Searcher:
    """Iterative-deepening negamax alpha-beta searcher with a transposition table.

    One instance lives for the whole game: its transposition table, killer moves and history
    heuristic persist from move to move (``new_game`` resets them). The per-search state (node
    counts, deadlines, the repetition path) is reset by every call to ``search``.
    """

    def __init__(self, tt_max_entries: int = 400_000) -> None:
        self.tt_max_entries = tt_max_entries
        self._tt: dict[Key, TTEntry] = {}
        # Two killer move codes per ply. Index MAX_PLY itself is reachable by the ply guard.
        self._killers: list[list[int]] = [
            [_NO_MOVE_CODE, _NO_MOVE_CODE] for _ in range(MAX_PLY + 1)
        ]
        # history[colour][from * 64 + to]: cutoff credit for quiet moves, flat for fast indexing.
        self._history_heuristic: list[list[int]] = [[0] * 4096, [0] * 4096]

        # Per-search state, (re)initialised by search().
        self._game_history: Mapping[Key, int] = {}
        self._path: dict[Key, int] = {}
        self._nodes = 0
        self._seldepth = 0
        self._hard_deadline = 0.0
        self._node_limit: int | None = None
        self._root_game_ply = 0
        # Progress of the root iteration in flight, used to salvage a move after an abort.
        self._partial: tuple[chess.Move, int] | None = None
        self._first_root_move: chess.Move | None = None

    def new_game(self) -> None:
        """Forget everything learned in the previous game."""
        self._tt.clear()
        for pair in self._killers:
            pair[0] = _NO_MOVE_CODE
            pair[1] = _NO_MOVE_CODE
        for table in self._history_heuristic:
            table[:] = [0] * 4096

    # ------------------------------------------------------------------ public entry point

    def search(
        self,
        board: chess.Board,
        history: Mapping[Key, int],
        soft_deadline: float,
        hard_deadline: float,
        max_depth: int = 64,
        node_limit: int | None = None,
    ) -> SearchResult:
        """Search ``board`` and return the best move found within the limits.

        ``history`` holds the transposition keys of every earlier position of the game (the root
        included); any of them reached inside the tree is scored as a draw. ``soft_deadline`` is
        the ``perf_counter()`` time after which no new iteration starts; ``hard_deadline`` aborts
        the search wherever it is. ``node_limit`` is a deterministic stand-in for the clock.
        """
        start = _now()
        # Work on a private copy: the caller's board is never touched, even if the search is
        # aborted in the middle of a line. ``stack=False`` drops the move history, which the
        # search does not need (repetitions come from ``history``, the ply from the counters).
        board = board.copy(stack=False)
        root_moves = list(board.generate_legal_moves())
        self._nodes = 0
        self._seldepth = 0

        if not root_moves:
            score = -MATE_SCORE if board.is_check() else DRAW_SCORE
            return SearchResult(None, score, 0, 0, 0, _now() - start, False)

        self._game_history = history
        self._path = {board._transposition_key(): 1}
        self._hard_deadline = hard_deadline
        self._node_limit = node_limit
        self._root_game_ply = board.ply()
        self._age_history()

        best_move: chess.Move | None = None
        best_score = DRAW_SCORE
        completed_depth = 0
        aborted = False
        # A forced move needs no deep search; one iteration gives it a score and banks the time.
        depth_limit = 1 if len(root_moves) == 1 else max(1, min(max_depth, MAX_PLY - 1))

        for depth in range(1, depth_limit + 1):
            try:
                score, move = self._search_root(board, root_moves, depth, best_move)
            except SearchAborted:
                aborted = True
                partial = self._partial
                if partial is not None and (completed_depth == 0 or partial[0] != best_move):
                    # The previous best was searched first at this depth and a later move beat
                    # it (or there was no previous iteration at all): the new move is trusted.
                    best_move, best_score = partial
                elif best_move is None:
                    # Aborted inside the very first root move of depth 1: any legal move beats
                    # none, and the ordering has put the most promising one first.
                    best_move = self._first_root_move
                break
            best_move, best_score, completed_depth = move, score, depth
            if _now() >= soft_deadline:
                break
            # A mate in n plies found at depth >= n cannot be shortened by searching deeper.
            if is_mate_score(score) and MATE_SCORE - abs(score) <= depth:
                break

        return SearchResult(
            best_move,
            best_score,
            completed_depth,
            self._seldepth,
            self._nodes,
            _now() - start,
            aborted,
        )

    # ------------------------------------------------------------------ root

    def _search_root(
        self,
        board: chess.Board,
        root_moves: list[chess.Move],
        depth: int,
        previous_best: chess.Move | None,
    ) -> tuple[int, chess.Move]:
        """One iteration at the root: every legal move with a full window, best first."""
        self._partial = None
        root_key = board._transposition_key()
        if previous_best is None:
            # First iteration: the table persists through the game, so it may remember this
            # position from the previous move's search. Trying that move first is the ordinary
            # "TT move first" rule applied at the root.
            entry = self._tt.get(root_key)
            if entry is not None:
                previous_best = entry[3]
        first_code = _move_code(previous_best) if previous_best is not None else _NO_MOVE_CODE
        ordered = self._order_moves(board, root_moves, first_code, 0)
        self._first_root_move = ordered[0]

        negamax = self._negamax
        alpha = -_INFINITY
        beta = _INFINITY
        best_score = -_INFINITY
        best_move = ordered[0]
        for move in ordered:
            board.push(move)
            score = -negamax(board, depth - 1, -beta, -alpha, 1)
            board.pop()
            # With alpha raised to the best score so far, any later move that returns a higher
            # score has an exact value (see the fail-soft argument in _negamax), so the root's
            # best score is always exact.
            if score > best_score:
                best_score = score
                best_move = move
                self._partial = (move, score)
                alpha = score

        self._store(root_key, depth, best_score, EXACT, best_move, 0)
        return best_score, best_move

    # ------------------------------------------------------------------ main search

    def _negamax(self, board: chess.Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        """Fail-soft negamax alpha-beta. Returns a score from the side to move's view.

        Fail-soft means the returned score may lie outside ``(alpha, beta)``: it is then a bound
        on the true value rather than the value itself, which is what the transposition table
        records with the LOWER/UPPER flags.
        """
        nodes = self._nodes + 1
        self._nodes = nodes
        if nodes % NODE_CHECK_INTERVAL == 0:
            self._check_limits()
        if ply > self._seldepth:
            self._seldepth = ply

        # (1) The referee draws the game at the ply cap, unless the position is checkmate (the
        # referee tests for game-over conditions before the cap).
        if self._root_game_ply + ply >= GAME_PLY_CAP:
            return self._game_over_score(board, ply)

        # (2) Repetition: a position already seen in the game, or earlier on the current line,
        # is a draw by the threefold rule as far as the engine is concerned. Treating the first
        # repetition as the draw keeps the engine from drifting when it is ahead.
        key = board._transposition_key()
        if key in self._game_history or key in self._path:
            return DRAW_SCORE

        # (3) Fifty-move rule, again with checkmate taking precedence.
        if board.halfmove_clock >= 100:
            return self._game_over_score(board, ply)

        # (4) Transposition table probe. Stored mate scores are distances from the stored node;
        # convert them to distances from the root before comparing with this node's window.
        tt = self._tt
        entry = tt.get(key)
        tt_move: chess.Move | None = None
        if entry is not None:
            entry_depth, entry_score, entry_flag, tt_move = entry
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

        # (5) Check extension: a side in check has few sensible replies and the position is
        # tactically hot, so it is searched one ply deeper rather than handed to quiescence.
        in_check = board.is_check()
        if in_check:
            depth += 1

        # Safety net: never recurse past MAX_PLY, whatever the extensions did.
        if ply >= MAX_PLY:
            return self._static_score(board, ply, in_check)

        # (6) Horizon: resolve captures before evaluating.
        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply, in_check)

        # (7) Interior node. Register the position on the current line for repetition checks.
        path = self._path
        path[key] = 1

        alpha_original = alpha
        best_score = -_INFINITY
        best_move: chess.Move | None = None
        child_depth = depth - 1
        child_ply = ply + 1
        negamax = self._negamax

        for move in self._staged_moves(board, tt_move, ply):
            board.push(move)
            score = -negamax(board, child_depth, -beta, -alpha, child_ply)
            board.pop()
            if score > best_score:
                best_score = score
                best_move = move
                if score >= beta:
                    # Beta cutoff: the opponent would never allow this position. Remember quiet
                    # moves that do this, they tend to refute other moves in sibling positions.
                    if move.promotion is None and not board.is_capture(move):
                        self._reward_quiet_cutoff(board, move, depth, ply)
                    break
                if score > alpha:
                    alpha = score

        del path[key]

        if best_move is None:
            # No legal move at all. In check that is checkmate; otherwise stalemate.
            return -(MATE_SCORE - ply) if in_check else DRAW_SCORE

        if best_score >= beta:
            flag = LOWER
        elif best_score <= alpha_original:
            flag = UPPER
        else:
            flag = EXACT
        self._store(key, depth, best_score, flag, best_move, ply)
        return best_score

    def _staged_moves(
        self, board: chess.Board, tt_move: chess.Move | None, ply: int
    ) -> Iterator[chess.Move]:
        """Yield the moves of the node in search order, generating lazily.

        The transposition-table move is handed out before the legal moves are generated at all:
        it is legal by construction (the key identifies the position exactly, and the move was
        legal there when it was stored) and it produces a cutoff often enough that skipping the
        generation and sorting of the other moves is a large saving. If the search asks for
        more, the full list is generated and sorted; the TT move sorts first and is skipped.
        """
        if tt_move is not None:
            yield tt_move
            tt_code = _move_code(tt_move)
        else:
            tt_code = _NO_MOVE_CODE
        moves = list(board.generate_legal_moves())
        ordered = self._order_moves(board, moves, tt_code, ply)
        yield from ordered[1:] if tt_move is not None else ordered

    # ------------------------------------------------------------------ quiescence

    def _quiescence(
        self, board: chess.Board, alpha: int, beta: int, ply: int, in_check: bool
    ) -> int:
        """Captures-only search that settles tactics before the static evaluation is trusted.

        The caller has already counted this node and computed ``in_check`` (the main search does
        this at the horizon; the capture loop below does it for each capture it makes).

        In check there is no standing pat, because doing nothing is not a legal option: every
        legal evasion is searched, and a position without one is checkmate. Otherwise the side to
        move may stand pat on the static evaluation or try captures and queen promotions, ordered
        by MVV-LVA. A position with no legal move at all is stalemate and never evaluated.
        """
        if ply > self._seldepth:
            self._seldepth = ply
        if ply >= MAX_PLY:
            return self._static_score(board, ply, in_check)

        if in_check:
            moves = list(board.generate_legal_moves())
            if not moves:
                return -(MATE_SCORE - ply)
            best_score = -_INFINITY
        else:
            moves = list(board.generate_legal_captures())
            if not moves and not any(board.generate_legal_moves()):
                return DRAW_SCORE
            best_score = evaluate(board)  # stand pat
            if best_score >= beta:
                return best_score
            if best_score > alpha:
                alpha = best_score
            turn = board.turn
            promoting = board.pawns & board.occupied_co[turn] & _PROMOTION_RANK[turn]
            if promoting:
                for move in board.generate_legal_moves(promoting, ~board.occupied & chess.BB_ALL):
                    if move.promotion == chess.QUEEN:
                        moves.append(move)
            if not moves:
                return best_score

        if len(moves) > 1:
            self._order_moves(board, moves, _NO_MOVE_CODE, ply)

        quiescence = self._quiescence
        child_ply = ply + 1
        for move in moves:
            promotion = move.promotion
            if promotion is not None and promotion != chess.QUEEN:
                continue  # under-promotions are almost never the point of a capture sequence
            board.push(move)
            nodes = self._nodes + 1
            self._nodes = nodes
            if nodes % NODE_CHECK_INTERVAL == 0:
                self._check_limits()
            child_in_check = board.is_check()
            score = -quiescence(board, -beta, -alpha, child_ply, child_in_check)
            board.pop()
            if score > best_score:
                best_score = score
                if score >= beta:
                    return score
                if score > alpha:
                    alpha = score
        return best_score

    # ------------------------------------------------------------------ move ordering

    def _order_moves(
        self, board: chess.Board, moves: list[chess.Move], tt_code: int, ply: int
    ) -> list[chess.Move]:
        """Sort ``moves`` in place, best guess first, and return the list.

        Order: TT move, captures/promotions by MVV-LVA (victim rank x 10 - attacker rank, a
        promotion counting the promoted piece as the victim), the two killers of this ply, then
        quiet moves by history score. Python's sort is stable, so ties keep the generator's
        order and the result is deterministic.
        """
        piece_type_at = board.piece_type_at
        ep_square = board.ep_square
        killer_first, killer_second = self._killers[ply]
        history = self._history_heuristic[board.turn]
        rank = _MVV_LVA_RANK
        pawn = chess.PAWN

        def order_key(move: chess.Move) -> int:
            from_square = move.from_square
            to_square = move.to_square
            promotion = move.promotion
            code = from_square | to_square << 6 | (promotion or 0) << 12
            if code == tt_code:
                return _ORDER_TT
            victim = piece_type_at(to_square)
            # A pawn landing on the en passant square captures a pawn that is not on that square.
            if victim is None and to_square == ep_square and piece_type_at(from_square) == pawn:
                victim = pawn
            if victim is not None or promotion is not None:
                gain = rank[victim or 0] + rank[promotion or 0]
                return _ORDER_CAPTURE + 10 * gain - rank[piece_type_at(from_square) or 0]
            if code == killer_first:
                return _ORDER_KILLER_FIRST
            if code == killer_second:
                return _ORDER_KILLER_SECOND
            return history[from_square << 6 | to_square]

        moves.sort(key=order_key, reverse=True)
        return moves

    def _reward_quiet_cutoff(
        self, board: chess.Board, move: chess.Move, depth: int, ply: int
    ) -> None:
        """A quiet move caused a beta cutoff: make it a killer and raise its history score."""
        killers = self._killers[ply]
        code = _move_code(move)
        if killers[0] != code:
            killers[1] = killers[0]
            killers[0] = code
        history = self._history_heuristic[board.turn]
        index = move.from_square << 6 | move.to_square
        # depth * depth: cutoffs near the root are rarer and worth more than cutoffs near leaves.
        history[index] = min(history[index] + depth * depth, _HISTORY_MAX)

    def _age_history(self) -> None:
        """Halve every history score so what was learned last move fades rather than saturates."""
        for table in self._history_heuristic:
            table[:] = [value >> 1 for value in table]

    # ------------------------------------------------------------------ helpers

    def _store(
        self, key: Key, depth: int, score: int, flag: int, move: chess.Move | None, ply: int
    ) -> None:
        """Write a TT entry with the score made independent of the node's distance from the root."""
        if score >= MATE_THRESHOLD:
            score += ply
        elif score <= -MATE_THRESHOLD:
            score -= ply
        tt = self._tt
        if len(tt) >= self.tt_max_entries:
            tt.clear()  # simplest possible bound on memory; Stage 1 replaces this with ageing
        tt[key] = (depth, score, flag, move)

    def _check_limits(self) -> None:
        """Every NODE_CHECK_INTERVAL nodes: abort past the node limit or the hard deadline."""
        limit = self._node_limit
        if limit is not None and self._nodes >= limit:
            raise SearchAborted
        if _now() >= self._hard_deadline:
            raise SearchAborted

    @staticmethod
    def _game_over_score(board: chess.Board, ply: int) -> int:
        """Score where the referee would stop the game: checkmate wins, anything else draws."""
        return -(MATE_SCORE - ply) if board.is_checkmate() else DRAW_SCORE

    @staticmethod
    def _static_score(board: chess.Board, ply: int, in_check: bool) -> int:
        """Score for a node that may not recurse further (the MAX_PLY guard).

        Rare enough that generating moves here costs nothing overall, and it keeps the promise
        that a position without legal moves is never handed to ``evaluate``.
        """
        if not any(board.generate_legal_moves()):
            return -(MATE_SCORE - ply) if in_check else DRAW_SCORE
        return evaluate(board)
