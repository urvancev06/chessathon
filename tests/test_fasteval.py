"""The gate for the compiled evaluation: it must equal the Python one, integer for integer.

``mikhail_letal.evaluation`` is the specification. ``mikhail_letal.fasteval`` is a port of it onto
the 0x88 board, written so the search can run entirely inside compiled code. Both compute the same
integer arithmetic on the same weights, so *any* difference is a bug -- there is no rounding to
excuse one, and a single centipawn of drift would change which move the search picks.

The gate below is twenty thousand positions drawn from random playouts of the 219 curated
openings (which is where rated games start) and of the rule-breaking positions in
``test_fastboard.py``, plus a hand-built list of the positions each term is *about*: passed,
doubled and isolated pawns, the bishop pair, rooks on open and semi-open files, king shields,
every insufficient-material combination, and pawnless mop-ups from both sides.
"""

from __future__ import annotations

import os

import chess
import pytest

from mikhail_letal import fasteval as fe
from mikhail_letal.evaluation import evaluate as python_evaluate
from mikhail_letal.evaluation import game_phase
from mikhail_letal.fastboard import Position, new_position, set_from_board
from tests.test_fastboard import TRICKY_POSITIONS, playout_boards, sample_starts

FULL_GATES = os.environ.get("LETAL_FULL_GATES") == "1"

# One position per structural term, so a term that is simply never exercised by the playouts
# cannot slip through. The comment on each says what it is there to catch.
TERM_POSITIONS = [
    # A passed pawn for each side, on different ranks, so the per-rank weighting is compared.
    "8/1p6/8/8/8/6P1/8/K6k w - - 0 1",
    "8/8/8/1P6/8/8/6p1/K6k b - - 0 1",
    # A passer blocked by an enemy pawn on the file, and one blocked from an adjacent file.
    "8/1p6/8/1P6/8/8/8/K6k w - - 0 1",
    "8/2p5/8/1P6/8/8/8/K6k w - - 0 1",
    # Doubled and tripled pawns.
    "8/8/8/8/P7/P7/P7/K6k w - - 0 1",
    "8/p7/p7/8/8/8/8/K6k b - - 0 1",
    # Isolated pawns, and the a- and h-file edge cases of "no neighbouring file".
    "8/8/8/8/P1P5/8/8/K6k w - - 0 1",
    "8/8/8/8/7P/8/8/K6k w - - 0 1",
    "8/8/8/8/P7/8/8/K6k w - - 0 1",
    # The bishop pair, for each side and for both at once.
    "8/8/8/8/2BB4/8/8/K6k w - - 0 1",
    "8/2bb4/8/8/8/8/8/K6k b - - 0 1",
    "8/2bb4/8/8/2BB4/8/8/K6k w - - 0 1",
    # Rooks on an open file, a semi-open file and a closed one.
    "8/8/8/8/8/8/1P6/KR5k w - - 0 1",
    "8/1p6/8/8/8/8/8/KR5k w - - 0 1",
    "8/1p6/8/8/8/8/1P6/KR5k w - - 0 1",
    # King shield and king danger live in MIDDLEGAME_TERM_POSITIONS below: both are middlegame-only
    # terms, so a position without pieces to carry the phase compares them as zero on both sides.
    # Every insufficient-material combination python-chess recognises, and the near misses.
    "8/8/4k3/8/8/8/8/4K3 w - - 0 1",  # bare kings
    "8/8/4k3/8/8/8/4N3/4K3 w - - 0 1",  # KN vs K
    "8/8/4k3/8/8/8/4B3/4K3 w - - 0 1",  # KB vs K
    "8/8/2b1k3/8/8/8/4B3/4K3 w - - 0 1",  # bishops on the same colour: still a draw
    "8/8/3b4/4k3/8/8/4B3/4K3 w - - 0 1",  # opposite colours: not a draw
    "8/8/2n1k3/8/8/8/4N3/4K3 w - - 0 1",  # knight each: not insufficient
    "8/8/4k3/8/8/8/3NN3/4K3 w - - 0 1",  # two knights: not insufficient
    "8/8/4k1n1/8/8/8/4B3/4K3 w - - 0 1",  # bishop against knight
    "8/8/4k3/8/8/8/4P3/4K3 w - - 0 1",  # a pawn is always sufficient material
    # Mop-ups from both sides, above and below the material gate, and with the kings adjacent.
    "8/8/4k3/8/8/8/4Q3/4K3 w - - 0 1",
    "4K3/4q3/8/8/8/4k3/8/8 b - - 0 1",
    "8/8/4k3/8/8/8/4R3/4K3 b - - 0 1",
    "8/8/4k3/8/8/8/3BB3/4K3 w - - 0 1",  # two bishops: 660 >= 500, the mop-up applies
    "8/8/4k3/8/8/8/4N3/4K3 b - - 0 1",  # one knight: below the gate, no mop-up
    "7k/8/6K1/8/8/8/8/6Q1 w - - 0 1",  # kings adjacent, weak king in the corner
    # Pawnless but with pieces on both sides: the mop-up must not fire.
    "8/8/4k3/6r1/8/8/4Q3/4K3 w - - 0 1",
    # Promotion-heavy positions, where the phase clamps at PHASE_TOTAL.
    "QQQQkQQQ/8/8/8/8/8/8/QQQQKQQQ w - - 0 1",
    "8/8/8/8/8/8/8/QQQQKQQk w - - 0 1",
]


def _compare(board: chess.Board, pos: Position, message: str) -> None:
    set_from_board(pos, board)
    compiled = int(fe.evaluate(pos, fe.TABLES))
    expected = python_evaluate(board)
    assert compiled == expected, f"{message}: compiled {compiled}, python {expected}"


def test_warm_up_compiled_at_import() -> None:
    """The evaluation is compiled before the clock starts, as it will be on the platform."""
    assert fe.WARM_UP_SECONDS > 0.0
    assert fe.evaluate.signatures, "evaluate was not compiled by warm_up()"


def test_nothing_compiles_after_import() -> None:
    """No new specialisation appears under load: a second signature would be compiled on the
    clock, which on the platform costs a move rather than raising an error."""
    before = list(fe.evaluate.signatures)
    pos = new_position()
    for board in playout_boards(500, seed=31415926, starts=sample_starts()):
        set_from_board(pos, board)
        fe.evaluate(pos, fe.TABLES)
    assert list(fe.evaluate.signatures) == before


# Positions for the terms that exist only in the middlegame half of the score: the king pawn
# shield and king danger. Both are added to ``mg`` alone, and the phase blend is
# ``(mg * phase + eg * (24 - phase)) / 24`` -- so at phase 0 the term's whole contribution is
# multiplied away and the comparison below would pass even if one implementation omitted it.
# Every entry therefore needs real pieces on the board, which
# ``test_middlegame_positions_carry_phase`` enforces. The four king-shield positions that used to
# live in TERM_POSITIONS were kings and pawns only, and proved nothing for exactly this reason.
MIDDLEGAME_TERM_POSITIONS = [
    # King shields: full for both sides, partial where the shield pawns have advanced, and on the
    # edge file where the king's zone runs off the board.
    "r2q1rk1/pp3ppp/2n1b3/8/8/2N1B3/PP3PPP/R2Q1RK1 w - - 0 1",
    "r2q1rk1/pp3p1p/2n1b1p1/8/8/2N1B1P1/PP3P1P/R2Q1RK1 w - - 0 1",
    "2rq1r1k/pp4pp/2n1b3/8/8/2N1B3/PP4PP/2RQ1R1K w - - 0 1",
    # King danger. The first is round 70 immediately after 8...O-O-O -- the position this term
    # exists because of (handoff/FINDING-king-safety.md); it scores 90 against the black king.
    "2kr1b1r/pp1qpppp/2n2n2/3p4/3P1Bb1/1QPB4/PP1N1PPP/R3K1NR w KQ - 7 9",
    # The penalty against White instead of Black, so the sign is compared in both directions.
    "1nb3nr/1p1p1k2/8/1pp1p2P/1PP2ppq/r4P1P/PB1KP3/2Q2BNR w - - 0 20",
    # A small penalty at full phase, and one driven by pieces that reach the zone by a long ray.
    "rnbq1b2/ppppkp1r/4pn1p/6p1/P3Q3/1PP1P3/3P1PPP/RNB1KBNR w KQ - 1 7",
    "3r1b2/Ppk3p1/2p1p1Pr/4p3/3Q3p/B2P3P/b4PBR/RN3K2 w - - 0 36",
    # Queen, two rooks, two bishops and a knight on one bare king: 17 attack units, so the
    # quadratic overshoots KING_DANGER_CAP and the clamp is what is compared.
    "8/2N5/7R/4k3/7R/B7/8/KB1Q4 b - - 0 1",
]

TERM_POSITIONS += MIDDLEGAME_TERM_POSITIONS


@pytest.mark.parametrize("fen", MIDDLEGAME_TERM_POSITIONS)
def test_middlegame_positions_carry_phase(fen: str) -> None:
    """A middlegame-only term is compared as zero at phase 0, so its positions must have pieces.

    This is the guard on the guard: without it, a position added here in the shape of a pawn
    ending would make the parity comparison above pass whatever the compiled port computed.
    """
    board = chess.Board(fen)
    assert board.is_valid(), fen
    assert game_phase(board) > 0, fen


@pytest.mark.parametrize("fen", TERM_POSITIONS)
def test_matches_python_on_each_term(fen: str) -> None:
    """One position per evaluation term, so no term escapes the comparison by never occurring."""
    _compare(chess.Board(fen), new_position(), fen)


@pytest.mark.parametrize("fen", TRICKY_POSITIONS)
def test_matches_python_on_the_rule_breakers(fen: str) -> None:
    _compare(chess.Board(fen), new_position(), fen)


def test_matches_python_on_the_curated_openings() -> None:
    """Every rated game starts from one of these, so they are compared exactly, not sampled."""
    from tests.test_fastboard import load_openings

    fens = load_openings()
    assert len(fens) == 219
    pos = new_position()
    for fen in fens:
        _compare(chess.Board(fen), pos, fen)


def test_matches_python_on_twenty_thousand_playout_positions() -> None:
    """The gate: 20,000 positions from playouts of the curated openings, integer for integer.

    Reduced to 2,000 unless ``LETAL_FULL_GATES=1``, so the ordinary test run stays quick; the
    full count is what is run before anything is promoted.
    """
    count = 20_000 if FULL_GATES else 2_000
    pos = new_position()
    compared = 0
    for board in playout_boards(count, seed=20260908, starts=sample_starts()):
        _compare(board, pos, board.fen())
        compared += 1
    assert compared == count


def test_matches_python_on_mirrored_positions() -> None:
    """A position and its colour-swapped mirror must agree between the two evaluations too.

    The mirror is where an indexing mistake in the Black piece-square tables shows up, and where
    the truncate-toward-zero phase blend matters: floor division would make the two differ by one.
    """
    pos = new_position()
    compared = 0
    for board in playout_boards(2_000, seed=16180339, starts=sample_starts()):
        mirrored = board.mirror()
        _compare(board, pos, board.fen())
        _compare(mirrored, pos, mirrored.fen())
        compared += 1
    assert compared == 2_000
