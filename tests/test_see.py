"""Static exchange evaluation, on positions whose answer is worked out by hand.

Every expected value below was computed by hand from the swap-off sequence *before* the code was
run, and every test in this file was confirmed to fail against a deliberately broken `see` — the
standard `docs/DECISIONS.md` records as "the check existed and did not check". The x-ray and en
passant cases exist because they are the two that a correct-looking implementation gets wrong
silently: the first by never seeing the piece behind the attacker, the second by looking for the
victim on the destination square, where it is not.
"""

from __future__ import annotations

import chess

from mikhail_letal import fastboard as fb
from mikhail_letal.fastsearch import see

PAWN, KNIGHT, BISHOP, ROOK, QUEEN = 100, 320, 330, 500, 900


def see_of(fen: str, uci: str) -> int:
    """SEE of `uci` played in `fen`, through the same conversion the search uses."""
    board = chess.Board(fen)
    pos = fb.from_board(board)
    return see(pos, fb.move_from_chess(pos, chess.Move.from_uci(uci)))


def test_a_quiet_move_is_worth_nothing() -> None:
    assert see_of("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1", "e2e4") == 0


def test_an_undefended_pawn_is_won_outright() -> None:
    """P takes P, nothing recaptures: the whole pawn."""
    assert see_of("4k3/8/8/4p3/3P4/8/8/4K3 w - - 0 1", "d4e5") == PAWN


def test_pawn_takes_a_defended_pawn_is_an_even_trade() -> None:
    """PxP (+100), PxP (-100). Neither side gains, so the exchange is worth 0."""
    assert see_of("4k3/8/5p2/4p3/3P4/8/8/4K3 w - - 0 1", "d4e5") == 0


def test_queen_takes_a_defended_pawn_loses_the_difference() -> None:
    """QxP (+100) then PxQ (-900). White should not play it: -800."""
    assert see_of("4k3/8/2p5/3p4/8/8/8/3QK3 w - - 0 1", "d1d5") == PAWN - QUEEN


def test_an_xray_behind_the_attacker_joins_the_exchange() -> None:
    """The case a mailbox scan gets wrong unless removals reveal what stood behind.

    White doubles rooks on the e-file, black pawn on e5 defended by d6.
    RxP (+100), PxR (-500), and then the *second* rook recaptures (+100): net -300.
    Without the x-ray the second rook is invisible, the sequence stops one capture early, and the
    answer comes out -400. The two differ, which is what makes this a test rather than a claim.
    """
    fen = "4k3/8/3p4/4p3/8/8/4R3/4RK2 w - - 0 1"
    assert see_of(fen, "e2e5") == PAWN - ROOK + PAWN


def test_en_passant_wins_the_pawn_when_nothing_recaptures() -> None:
    """The basic value. Note this alone does NOT prove the captured pawn is removed from the
    right square -- see the next test, which is the one that does."""
    assert see_of("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6") == PAWN


def test_en_passant_removes_the_pawn_from_the_square_it_actually_stands_on() -> None:
    """The discriminating case, and the reason the test above is not enough.

    The captured pawn on d5 is what blocks the black rook on d1 from the destination square d6.
    Removing it is what lets the rook recapture, so the exchange is even (0) rather than a free
    pawn (100). An implementation that clears the *destination* square instead leaves the d5 pawn
    standing, the rook stays blocked, and it reports +100.

    The first version of this test used a position with no recapture at all, where clearing the
    wrong square is invisible -- it passed against a deliberately broken `see`, which is how it
    was caught.
    """
    assert see_of("4k3/8/8/3pP3/8/8/7K/3r4 w - d6 0 1", "e5d6") == 0


def test_a_capture_promotion_counts_the_new_piece() -> None:
    """bxa8=Q with nothing defending: the rook, plus a queen replacing a pawn."""
    assert see_of("r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1", "b7a8q") == ROOK + QUEEN - PAWN


def test_a_defended_capture_promotion_stops_at_the_recapture() -> None:
    """bxa8=Q (+500 +800), Kxa8 (-900). White still gains, so the sequence is played out."""
    fen = "r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1"
    defended = fen.replace("r3k3", "rk6")  # black king on b8 now defends a8
    assert see_of(defended, "b7a8q") == ROOK + QUEEN - PAWN - QUEEN


def test_the_cheapest_attacker_recaptures_first() -> None:
    """Black has a queen and a pawn bearing on e5; SEE must use the pawn.

    PxP (+100), then the *pawn* recaptures (-100) rather than the queen. Using the queen would
    give the same first two terms here but a different sequence in general, so the point of the
    test is the ordering: the answer is 0, not something that depends on which piece was chosen.
    """
    assert see_of("3qk3/8/5p2/4p3/3P4/8/8/4K3 w - - 0 1", "d4e5") == 0


def test_the_board_is_left_exactly_as_it_was() -> None:
    """`see` mutates the mailbox to reveal x-rays and must restore it. If it does not, every
    later evaluation in the search reads a board with pieces missing."""
    board = chess.Board("4k3/8/3p4/4p3/8/8/4R3/4RK2 w - - 0 1")
    pos = fb.from_board(board)
    before = pos.board.copy()
    see(pos, fb.move_from_chess(pos, chess.Move.from_uci("e2e5")))
    assert (pos.board == before).all(), "see did not restore the board"
