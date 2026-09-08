"""Tests for the search-only board (``mikhail_letal.searchboard``) and for the two other exact
speedups v0.3 added to the search: the bitboard capture generator and the cheap "has a legal
move" test.

The theme of every test here is the same: a faster path is only allowed to exist if it is
*identical* to the slow one it replaces. So each test names a reference — a from-scratch
recompute, the previous implementation kept in the module, or python-chess itself — and asserts
equality rather than closeness.
"""

import random

import chess
import pytest

from mikhail_letal.evaluation import evaluate, material_pst
from mikhail_letal.search import Engine
from mikhail_letal.searchboard import SearchBoard
from tests.conftest import ROOT

# Positions that exercise the awkward cases of an incremental update all at once: pawns one push
# from promoting for both sides, both castlings available, and an en passant square.
PROMOTION_RACE = "n1n1k2r/PPPp1ppp/8/8/8/8/4KPPP/1N4N1 w k - 0 1"
CASTLING_BOTH = "r3k2r/pppppppp/8/8/8/8/PPPPPPPP/R3K2R w KQkq - 0 1"
EN_PASSANT = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2"
BUSY_MIDDLEGAME = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"


def openings() -> list[str]:
    """Every position in ``data/openings.txt`` (name and FEN, tab separated)."""
    path = ROOT / "data" / "openings.txt"
    with path.open(encoding="utf-8") as handle:
        return [line.split("\t")[1].strip() for line in handle if line.strip()]


def assert_running_totals_are_exact(board: SearchBoard, where: str) -> None:
    """The three running numbers, and the evaluation built on them, equal a full recompute."""
    assert (board.mg, board.eg, board.phase) == material_pst(board.board), where
    assert board.evaluate() == evaluate(board.board), where


def test_running_totals_survive_random_walks_from_every_opening() -> None:
    """The gate for the incremental evaluation: from all 219 openings plus positions built to be
    full of promotions, castlings and en passant, walk 40 random plies and check the totals after
    every move, then unwind and check after every unmake."""
    rng = random.Random(2026_09_08)
    starts = [
        *openings(),
        chess.STARTING_FEN,
        PROMOTION_RACE,
        CASTLING_BOTH,
        EN_PASSANT,
        BUSY_MIDDLEGAME,
    ]
    assert len(starts) >= 200
    checks = 0
    for fen in starts:
        board = chess.Board(fen)
        search_board = SearchBoard(board)
        assert_running_totals_are_exact(search_board, fen)
        made = 0
        for _ in range(40):
            moves = list(board.generate_legal_moves())
            if not moves:
                break
            search_board.push(rng.choice(moves))
            made += 1
            assert_running_totals_are_exact(search_board, f"{fen} after push {made}")
            checks += 1
            if not board.is_check() and rng.random() < 0.1:
                # A null move changes the side to move and nothing else, so the totals hold.
                search_board.push_null()
                assert_running_totals_are_exact(search_board, f"{fen} after null {made}")
                search_board.pop_null()
                assert_running_totals_are_exact(search_board, f"{fen} after null unmake {made}")
        while made:
            search_board.pop()
            made -= 1
            assert_running_totals_are_exact(search_board, f"{fen} after pop {made}")
            checks += 1
    assert checks > 10_000


@pytest.mark.parametrize("colour", [chess.WHITE, chess.BLACK])
def test_en_passant_updates_the_totals_on_every_file(colour: chess.Color) -> None:
    """En passant is the one capture whose victim is not on the move's target square.

    ``colour`` is the side that double-pushes; the other side takes en passant. Both directions
    and all fourteen file pairs are set up from an empty board.
    """
    for file_index in range(8):
        for adjacent in (file_index - 1, file_index + 1):
            if not 0 <= adjacent <= 7:
                continue
            board = chess.Board(None)
            board.set_piece_at(chess.E1, chess.Piece(chess.KING, chess.WHITE))
            board.set_piece_at(chess.E8, chess.Piece(chess.KING, chess.BLACK))
            home, ahead, beside = (1, 3, 3) if colour else (6, 4, 4)
            board.set_piece_at(chess.square(file_index, home), chess.Piece(chess.PAWN, colour))
            board.set_piece_at(chess.square(adjacent, beside), chess.Piece(chess.PAWN, not colour))
            board.turn = colour
            if not board.is_valid():
                continue
            search_board = SearchBoard(board)
            search_board.push(
                chess.Move(chess.square(file_index, home), chess.square(file_index, ahead))
            )
            capture = chess.Move(
                chess.square(adjacent, beside), chess.square(file_index, 2 if colour else 5)
            )
            assert board.is_en_passant(capture)
            search_board.push(capture)
            assert_running_totals_are_exact(search_board, f"en passant {capture}")
            search_board.pop()
            assert_running_totals_are_exact(search_board, "after unmaking en passant")


def test_promotions_and_castling_update_the_totals() -> None:
    """A promoted piece replaces the pawn in both sums and in the phase; castling moves the rook
    as well as the king."""
    board = chess.Board(PROMOTION_RACE)
    search_board = SearchBoard(board)
    promotions = 0
    for move in list(board.generate_legal_moves()):
        if move.promotion is None:
            continue
        before = search_board.phase
        search_board.push(move)
        assert_running_totals_are_exact(search_board, f"promotion {move}")
        # A promotion adds a piece to the phase (a knight, bishop, rook or queen), less whatever
        # it captured on the way.
        assert search_board.phase != before or board.is_capture(move)
        search_board.pop()
        promotions += 1
    assert promotions >= 8  # queen, rook, bishop and knight, plain and capturing

    board = chess.Board(CASTLING_BOTH)
    search_board = SearchBoard(board)
    for uci in ("e1g1", "e1c1"):
        move = chess.Move.from_uci(uci)
        assert board.is_castling(move)
        search_board.push(move)
        assert_running_totals_are_exact(search_board, f"castling {uci}")
        search_board.pop()
        assert_running_totals_are_exact(search_board, f"after unmaking {uci}")
    board.turn = chess.BLACK
    search_board = SearchBoard(board)
    for uci in ("e8g8", "e8c8"):
        move = chess.Move.from_uci(uci)
        assert board.is_castling(move)
        search_board.push(move)
        assert_running_totals_are_exact(search_board, f"castling {uci}")
        search_board.pop()


def test_chess960_is_refused() -> None:
    """The castling update assumes the standard king-two-files move, so a Chess960 board is
    rejected rather than silently mis-evaluated."""
    with pytest.raises(ValueError, match="Chess960"):
        SearchBoard(chess.Board(chess960=True))


def test_capture_generator_matches_python_chess_move_for_move() -> None:
    """The bitboard capture generator returns the identical list, in the identical order, as the
    masked python-chess generation it replaces (kept as ``_capture_moves_in_check``)."""
    engine = Engine()
    rng = random.Random(1234)
    compared = 0
    in_check = 0
    with_ep = 0
    with_pins = 0
    for fen in [*openings(), PROMOTION_RACE, CASTLING_BOTH, EN_PASSANT, BUSY_MIDDLEGAME]:
        board = chess.Board(fen)
        for _ in range(30):
            checked = board.is_check()
            in_check += checked
            with_ep += board.ep_square is not None
            king = board.king(board.turn)
            with_pins += king is not None and bool(board._slider_blockers(king))
            for quiescence in (False, True):
                assert engine._capture_moves(board, quiescence, checked) == (
                    engine._capture_moves_in_check(board, quiescence)
                ), f"{fen} quiescence={quiescence}"
                compared += 1
            moves = list(board.generate_legal_moves())
            if not moves:
                break
            board.push(rng.choice(moves))
    assert compared > 5_000
    assert in_check > 50 and with_ep > 50 and with_pins > 500  # the cases are actually reached


def test_has_legal_move_agrees_with_python_chess() -> None:
    """The cheap "is there a legal move" test never disagrees with generating one."""
    engine = Engine()
    positions = [
        "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",  # stalemate
        "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",  # checkmate
        "8/8/8/8/8/7k/7p/7K w - - 0 1",  # stalemate with a pawn on the board
        "K7/P7/8/8/8/8/8/k6r w - - 0 1",  # only the pinned-piece path can answer
        BUSY_MIDDLEGAME,
    ]
    checked = 0
    without = 0

    def sweep(board: chess.Board, depth: int) -> None:
        nonlocal checked, without
        in_check = board.is_check()
        expected = any(board.generate_legal_moves())
        assert engine._has_legal_move(board, in_check) is expected, board.fen()
        checked += 1
        without += not expected
        if depth:
            for move in list(board.generate_legal_moves()):
                board.push(move)
                sweep(board, depth - 1)
                board.pop()

    for fen in positions:
        sweep(chess.Board(fen), 2)
    assert checked > 1_000
    assert without > 0  # positions with no legal move are actually reached
