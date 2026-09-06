"""Tests for the always-legal fallback move (mikhail_letal/fallback.py)."""

import random
import time

import chess
import pytest

from mikhail_letal.fallback import fallback_move


def _pick(fen: str) -> chess.Move:
    board = chess.Board(fen)
    return fallback_move(board, list(board.legal_moves))


def test_mate_in_one_is_chosen() -> None:
    # Back-rank mate: Ra8# beats every capture-free alternative and even a free queen.
    assert _pick("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1") == chess.Move.from_uci("a1a8")
    # Mate outranks material: gxh3 wins a whole queen, but Qxf7 is Scholar's mate.
    board = chess.Board("r1bqkbnr/1ppp1ppp/2n5/4p2Q/2B1P3/7q/PPPP1PPP/RNB1K1NR w KQkq - 4 4")
    assert board.is_valid()
    legal = list(board.legal_moves)
    assert chess.Move.from_uci("g2h3") in legal  # the queen is there for the taking
    assert fallback_move(board, legal) == chess.Move.from_uci("h5f7")


def test_best_capture_is_chosen() -> None:
    # The rook may take a pawn on b1 or a queen on a8; the queen is worth more.
    assert _pick("q3k3/8/8/8/8/8/8/Rp2K3 w - - 0 1") == chess.Move.from_uci("a1a8")
    # Two free pieces: the rook (500) over the bishop (330).
    assert _pick("4k3/8/8/1b1r4/8/4N3/8/4K3 w - - 0 1") == chess.Move.from_uci("e3d5")


def test_promotion_to_queen_is_chosen() -> None:
    move = _pick("8/P7/8/8/8/8/8/k6K w - - 0 1")
    assert move == chess.Move.from_uci("a7a8q")


def test_en_passant_is_seen_as_a_capture() -> None:
    board = chess.Board("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2")
    move = fallback_move(board, list(board.legal_moves))
    assert move == chess.Move.from_uci("e5d6")


def test_ties_break_by_uci_string_and_order_does_not_matter() -> None:
    # Bare kings: no move changes material, so the alphabetically first UCI must win.
    board = chess.Board("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
    legal = list(board.legal_moves)
    expected = min(legal, key=lambda m: m.uci())
    assert fallback_move(board, legal) == expected
    assert fallback_move(board, list(reversed(legal))) == expected
    shuffled = legal[:]
    random.Random(7).shuffle(shuffled)
    assert fallback_move(board, shuffled) == expected


def _random_positions(count: int, seed: int) -> list[chess.Board]:
    rng = random.Random(seed)
    positions: list[chess.Board] = []
    while len(positions) < count:
        board = chess.Board()
        for _ in range(rng.randint(0, 80)):
            moves = list(board.legal_moves)
            if not moves or board.is_game_over():
                break
            board.push(rng.choice(moves))
        if list(board.legal_moves):
            positions.append(board)
    return positions


def test_legal_in_random_positions_and_board_untouched() -> None:
    positions = _random_positions(200, seed=2026)
    for board in positions:
        before = board.fen()
        legal = list(board.legal_moves)
        move = fallback_move(board, legal)
        assert move in legal
        assert board.fen() == before
        # Deterministic: asking again gives the same answer.
        assert fallback_move(board, legal) == move


def test_returns_within_a_few_milliseconds() -> None:
    positions = _random_positions(200, seed=99)
    worst = 0.0
    total = 0.0
    for board in positions:
        legal = list(board.legal_moves)
        started = time.perf_counter()
        fallback_move(board, legal)
        elapsed = time.perf_counter() - started
        worst = max(worst, elapsed)
        total += elapsed
    # Generous bounds so a loaded CI machine does not flake; typical values are far lower.
    assert total / len(positions) < 0.010
    assert worst < 0.050


def test_empty_legal_list_raises() -> None:
    board = chess.Board()
    with pytest.raises(ValueError, match="legal move"):
        fallback_move(board, [])
