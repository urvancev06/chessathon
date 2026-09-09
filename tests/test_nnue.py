"""Gates for the trained evaluation: the port, the perspectives, and the quantisation.

``mikhail_letal.nnue`` is the specification and ``fasteval.nnue_evaluate`` is the compiled port, so
the first gate is the same one the hand-crafted evaluation has: they must return the same integer
on every position, with no rounding to excuse a difference. Both compute the same integer
arithmetic on the same weights.

The second gate is about perspectives, which is where this design goes wrong. Each side's
accumulator is built from its own point of view -- squares mirrored for Black, features saying
"friendly knight" rather than "white knight" -- and the output reads the side to move first. Get
any part of that backwards and the network still returns plausible numbers; it just evaluates the
wrong side. A position and its colour-swapped mirror are the *same position* from the side to
move's chair, so they must score exactly equal, and that equality is what catches it.
"""

from __future__ import annotations

import os
from pathlib import Path

import chess
import pytest

from mikhail_letal import fasteval as fe
from mikhail_letal import nnue
from mikhail_letal.fastboard import Position, from_board, new_position, set_from_board
from tests.test_fastboard import TRICKY_POSITIONS, playout_boards, sample_starts

FULL_GATES = os.environ.get("LETAL_FULL_GATES") == "1"
NET_PATH = Path(__file__).resolve().parent.parent / "weights" / "net.npz"
HAS_NET = NET_PATH.exists()

needs_net = pytest.mark.skipif(not HAS_NET, reason="no trained network in weights/")


@pytest.fixture(scope="module")
def net() -> nnue.Network:
    return nnue.Network.load(NET_PATH)


def _compare(net: nnue.Network, board: chess.Board, pos: Position) -> None:
    set_from_board(pos, board)
    compiled = int(fe.nnue_evaluate(pos, fe.TABLES.net))
    expected = nnue.evaluate(net, board)
    assert compiled == expected, f"{board.fen()}: compiled {compiled}, python {expected}"


@needs_net
def test_the_loaded_tables_are_the_weights_file(net: nnue.Network) -> None:
    """The compiled tables and the specification must be reading the same network, or every
    comparison below is between two different nets and proves nothing."""
    assert int(fe.TABLES.net.scalars[fe.N_WIDTH]) == net.width
    assert (fe.TABLES.net.feature_weights == net.feature_weights).all()
    assert (fe.TABLES.net.output_weights == net.output_weights).all()


@needs_net
def test_compiled_network_matches_the_specification_on_the_curated_openings(
    net: nnue.Network,
) -> None:
    from tests.test_fastboard import load_openings

    pos = new_position()
    for fen in load_openings():
        _compare(net, chess.Board(fen), pos)


@needs_net
@pytest.mark.parametrize("fen", TRICKY_POSITIONS)
def test_compiled_network_matches_the_specification_on_the_rule_breakers(
    net: nnue.Network, fen: str
) -> None:
    _compare(net, chess.Board(fen), new_position())


@needs_net
def test_compiled_network_matches_the_specification_on_playout_positions(
    net: nnue.Network,
) -> None:
    """The gate: every position compared on its own, integer for integer."""
    count = 20_000 if FULL_GATES else 2_000
    pos = new_position()
    compared = 0
    for board in playout_boards(count, seed=20260909, starts=sample_starts()):
        _compare(net, board, pos)
        compared += 1
    assert compared == count


@needs_net
def test_a_position_and_its_mirror_score_equal(net: nnue.Network) -> None:
    """From the side to move's chair a colour-swapped mirror is the same position.

    This is the test that catches a perspective mistake. Swap which accumulator is read first, or
    forget to mirror Black's squares, and the network still returns plausible centipawns for every
    position -- it is simply evaluating from the wrong side, which no amount of eyeballing scores
    would reveal.
    """
    for board in playout_boards(400, seed=31337, starts=sample_starts()):
        mirrored = board.mirror()
        assert nnue.evaluate(net, board) == nnue.evaluate(net, mirrored), board.fen()


@needs_net
def test_the_incremental_accumulator_equals_a_refresh(net: nnue.Network) -> None:
    """`apply_changes` is the foundation of the incremental accumulator the search will use once
    the network has earned its place. It is not on the hot path yet, and it is gated now rather
    than when it is load-bearing: an accumulator that drifts from the position is the
    characteristic bug of this design, and it shows as a slightly worse move, never as an error.
    """
    board = chess.Board()
    acc = nnue.refresh(net, board)
    for move in ("e2e4", "e7e5", "g1f3", "b8c6", "f1b5", "a7a6"):
        played = chess.Move.from_uci(move)
        piece = board.piece_at(played.from_square)
        assert piece is not None
        captured = board.piece_at(played.to_square)
        removed = [(piece.color, piece.piece_type, played.from_square)]
        added = [(piece.color, piece.piece_type, played.to_square)]
        if captured is not None:
            removed.append((captured.color, captured.piece_type, played.to_square))
        nnue.apply_changes(net, acc, removed, added)
        board.push(played)
        assert (acc == nnue.refresh(net, board)).all(), f"drifted after {move}"


@needs_net
def test_the_switch_keeps_the_insufficient_material_draw(net: nnue.Network) -> None:
    """A rule, not a judgement. The network is trained on evaluations and would happily score a
    dead draw as an advantage, so the draw survives the switch."""
    for fen in (
        "8/8/4k3/8/8/8/4B3/4K3 w - - 0 1",  # KB vs K
        "8/8/4k3/8/8/8/4N3/4K3 w - - 0 1",  # KN vs K
        "8/8/4k3/8/8/8/8/4K3 w - - 0 1",  # bare kings
    ):
        pos = from_board(chess.Board(fen))
        assert fe._insufficient(pos), fen
    # And a position with a pawn is never insufficient, whatever else is on the board.
    assert not fe._insufficient(from_board(chess.Board("8/8/4k3/8/8/8/4P3/4K3 w - - 0 1")))


@needs_net
def test_the_network_is_compiled_by_the_import(net: nnue.Network) -> None:
    """It must arrive compiled even while the switch is off, or turning the switch on would cost
    a compilation on the game clock -- which numba reports as a slow move, not as an error."""
    assert fe.nnue_evaluate.signatures, "nnue_evaluate was not compiled by warm_up()"
    assert fe._insufficient.signatures, "_insufficient was not compiled by warm_up()"


@needs_net
def test_the_weights_fit_the_integer_types_they_ship_in(net: nnue.Network) -> None:
    """Quantisation is only sound while nothing overflows, and the bound depends on the width."""
    assert net.feature_weights.dtype == "int16"
    assert net.output_weights.dtype == "int16"
    worst = 2 * net.width * nnue.CLIP_MAX * int(abs(net.output_weights).max())
    assert worst + abs(net.output_bias) < 2**31 - 1, f"output sum could overflow int32: {worst}"
