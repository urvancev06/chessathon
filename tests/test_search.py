"""Tests for the Stage 0 searcher (``mikhail_letal.search``).

Every position used here is small enough to be checked by hand, and the mate-in-two is also
re-verified with python-chess inside the test so the expected answer does not rest on the
engine under test.
"""

import time
from collections.abc import Mapping

import chess
import pytest

from mikhail_letal.evaluation import DRAW_SCORE, MATE_SCORE, is_mate_score
from mikhail_letal.search import NODE_CHECK_INTERVAL, Searcher, SearchResult

# Mate in one: a rook to the back rank against a king boxed in by its own pawns.
MATE_IN_ONE_WHITE = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"
MATE_IN_ONE_BLACK = "r3k3/8/8/8/8/8/5PPP/6K1 b - - 0 1"
# Mate in two (Anastasia's pattern): 1. Qxh7+ Kxh7 (forced) 2. Rh1#. The black rook on f8
# stops the immediate Rd8#, so Qxh7+ is the unique forcing first move.
MATE_IN_TWO = "5r1k/4Nppp/8/8/7Q/8/6K1/3R4 w - - 0 1"
# Black's queen on h4 is undefended and attacked by the knight on f3.
HANGING_QUEEN = "rnb1kbnr/pppp1ppp/8/4p3/7q/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 3"
# Queen versus rook: the side with the queen is clearly ahead, the other clearly behind.
QUEEN_VS_ROOK_WHITE_TO_MOVE = "5rk1/8/8/8/3Q4/8/8/6K1 w - - 0 1"
QUEEN_VS_ROOK_BLACK_TO_MOVE = "5rk1/8/8/8/3Q4/8/8/6K1 b - - 0 1"
STALEMATE_ROOT = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
CHECKMATE_ROOT = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
# A busy middlegame with many captures, so even a depth-1 search takes well over 1024 nodes.
BUSY_MIDDLEGAME = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"


def far_future() -> float:
    return time.perf_counter() + 3600.0


def run_search(
    fen: str,
    *,
    history: Mapping[object, int] | None = None,
    max_depth: int = 64,
    node_limit: int | None = None,
    searcher: Searcher | None = None,
) -> SearchResult:
    """Search ``fen`` with no time pressure; the root key is in the history unless given."""
    board = chess.Board(fen)
    if history is None:
        history = {board._transposition_key(): 1}
    engine = searcher if searcher is not None else Searcher()
    deadline = far_future()
    return engine.search(
        board, history, deadline, deadline, max_depth=max_depth, node_limit=node_limit
    )


def key_after(fen: str, uci: str) -> object:
    board = chess.Board(fen)
    board.push_uci(uci)
    return board._transposition_key()


# ----------------------------------------------------------------------------- (a) mate in one


@pytest.mark.parametrize(
    ("fen", "expected"), [(MATE_IN_ONE_WHITE, "a1a8"), (MATE_IN_ONE_BLACK, "a8a1")]
)
def test_mate_in_one_found_at_shallow_depth(fen: str, expected: str) -> None:
    result = run_search(fen, max_depth=2)
    assert result.move is not None
    assert result.move.uci() == expected
    assert result.score == MATE_SCORE - 1
    assert is_mate_score(result.score)
    assert 1 <= result.depth <= 2
    assert not result.aborted


def test_mate_in_one_beats_the_fifty_move_rule() -> None:
    # The mating move is the 100th halfmove: the referee tests checkmate before the fifty-move
    # draw, so the search must still score it as mate rather than as a draw.
    result = run_search("6k1/5ppp/8/8/8/8/8/R3K3 w - - 99 70", max_depth=2)
    assert result.move is not None
    assert result.move.uci() == "a1a8"
    assert result.score == MATE_SCORE - 1


# ----------------------------------------------------------------------------- (b) mate in two


def test_mate_in_two_position_is_a_forced_mate() -> None:
    """Independent check with python-chess that the test position is what it claims to be."""
    board = chess.Board(MATE_IN_TWO)
    assert board.is_valid()

    def mates_in_one(b: chess.Board) -> bool:
        for move in b.legal_moves:
            b.push(move)
            mate = b.is_checkmate()
            b.pop()
            if mate:
                return True
        return False

    assert not mates_in_one(board)
    board.push_uci("h4h7")
    replies = list(board.legal_moves)
    assert [m.uci() for m in replies] == ["h8h7"]
    board.push(replies[0])
    assert mates_in_one(board)


def test_mate_in_two_found_by_depth_four() -> None:
    result = run_search(MATE_IN_TWO, max_depth=4)
    assert result.move is not None
    assert result.move.uci() == "h4h7"
    # Mate delivered on the third ply from the root, and no longer mate is reported instead.
    assert result.score == MATE_SCORE - 3
    assert result.depth <= 4


# ----------------------------------------------------------------------------- (c) material


def test_captures_hanging_queen() -> None:
    result = run_search(HANGING_QUEEN, max_depth=3)
    assert result.move is not None
    assert result.move.uci() == "f3h4"
    assert result.score > 500


# ----------------------------------------------------------------------------- (d) repetition


def test_side_ahead_avoids_repetition() -> None:
    fen = QUEEN_VS_ROOK_WHITE_TO_MOVE
    repeating = "d4d1"
    history = {chess.Board(fen)._transposition_key(): 1, key_after(fen, repeating): 1}
    result = run_search(fen, history=history, max_depth=4)
    assert result.move is not None
    assert result.move.uci() != repeating
    assert result.score > 300  # keeps the material advantage instead of drawing


def test_side_behind_seeks_repetition() -> None:
    fen = QUEEN_VS_ROOK_BLACK_TO_MOVE
    repeating = "f8e8"
    history = {chess.Board(fen)._transposition_key(): 1, key_after(fen, repeating): 1}
    result = run_search(fen, history=history, max_depth=4)
    assert result.move is not None
    assert result.move.uci() == repeating
    assert result.score == DRAW_SCORE
    # Without the history entry the same position is simply lost material.
    plain = run_search(fen, max_depth=4)
    assert plain.score < -300


def test_fifty_move_rule_draws_a_won_position() -> None:
    # Queen versus bare king with the halfmove clock at 99: every legal move is the 100th
    # halfmove without a capture or pawn move, so the position is a draw whatever is played.
    result = run_search("Q7/8/8/8/4k3/8/8/7K w - - 99 80", max_depth=3)
    assert result.move is not None
    assert result.score == DRAW_SCORE


# ----------------------------------------------------------------------------- (e) limits


def test_hard_deadline_in_the_past_returns_legal_move_quickly() -> None:
    board = chess.Board()
    past = time.perf_counter() - 1.0
    started = time.perf_counter()
    result = Searcher().search(board, {board._transposition_key(): 1}, past, past)
    assert time.perf_counter() - started < 0.5
    assert result.move is not None and result.move in board.legal_moves
    assert result.aborted or result.depth >= 1


def test_node_limit_stops_search_close_to_the_limit() -> None:
    node_limit = 3000
    result = run_search(chess.STARTING_FEN, node_limit=node_limit)
    assert result.aborted
    assert node_limit <= result.nodes <= node_limit + NODE_CHECK_INTERVAL
    assert result.move is not None and result.move in chess.Board().legal_moves
    assert result.depth >= 1


def test_abort_inside_first_iteration_still_returns_a_legal_move() -> None:
    board = chess.Board(BUSY_MIDDLEGAME)
    # Sanity: depth 1 alone needs more than one check interval here, so a limit of 1 node aborts
    # before any iteration completes.
    full = run_search(BUSY_MIDDLEGAME, max_depth=1)
    assert full.nodes > NODE_CHECK_INTERVAL
    result = run_search(BUSY_MIDDLEGAME, node_limit=1)
    assert result.aborted
    assert result.depth == 0
    assert result.move is not None and result.move in board.legal_moves


# ----------------------------------------------------------------------------- (f) terminal roots


def test_stalemate_root_has_no_move_and_draw_score() -> None:
    result = run_search(STALEMATE_ROOT)
    assert result.move is None
    assert result.score == DRAW_SCORE
    assert result.nodes == 0


def test_checkmate_root_has_no_move_and_mated_score() -> None:
    result = run_search(CHECKMATE_ROOT)
    assert result.move is None
    assert result.score == -MATE_SCORE
    assert is_mate_score(result.score)


# ----------------------------------------------------------------------------- (g) determinism


def test_identical_searches_give_identical_results() -> None:
    first = run_search(chess.STARTING_FEN, node_limit=20_000)
    second = run_search(chess.STARTING_FEN, node_limit=20_000)
    assert (first.move, first.nodes, first.score, first.depth, first.seldepth) == (
        second.move,
        second.nodes,
        second.score,
        second.depth,
        second.seldepth,
    )


def test_new_game_restores_a_fresh_searcher() -> None:
    engine = Searcher()
    fresh = run_search(HANGING_QUEEN, node_limit=5_000, searcher=engine)
    warm = run_search(HANGING_QUEEN, node_limit=5_000, searcher=engine)
    engine.new_game()
    reset = run_search(HANGING_QUEEN, node_limit=5_000, searcher=engine)
    # A warm table changes the node count; new_game() brings it back to the fresh figure.
    assert (reset.move, reset.nodes, reset.score) == (fresh.move, fresh.nodes, fresh.score)
    assert warm.move == fresh.move


# ----------------------------------------------------------------------------- (h) ply cap


@pytest.mark.parametrize(
    "fen",
    [
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 7 301",  # root itself at ply 600
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 b - - 7 300",  # every reply lands on ply 600
    ],
)
def test_ply_cap_scores_draw(fen: str) -> None:
    board = chess.Board(fen)
    assert board.ply() >= 599
    result = run_search(fen, max_depth=4)
    assert result.move is not None and result.move in board.legal_moves
    assert result.score == DRAW_SCORE


# ----------------------------------------------------------------------------- housekeeping


def test_search_does_not_mutate_the_callers_board() -> None:
    board = chess.Board(BUSY_MIDDLEGAME)
    before = board.fen()
    Searcher().search(board, {board._transposition_key(): 1}, far_future(), far_future(), 3)
    assert board.fen() == before
    assert not board.move_stack


def test_result_fields_are_consistent() -> None:
    result = run_search(HANGING_QUEEN, max_depth=3)
    assert result.depth == 3
    assert result.seldepth >= result.depth
    assert result.nodes > 0
    assert result.elapsed >= 0.0
    assert not result.aborted
