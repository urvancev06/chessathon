"""Tests for the per-game position history (mikhail_letal/gamestate.py)."""

import chess

from mikhail_letal.gamestate import GameState


def _key(board: chess.Board) -> object:
    return board._transposition_key()


def _after(board: chess.Board, *sans: str) -> chess.Board:
    """A fresh board with the given SAN moves played from ``board``."""
    result = board.copy()
    for san in sans:
        result.push_san(san)
    return result


def test_first_observe_starts_history_at_the_root() -> None:
    state = GameState()
    board = chess.Board()
    assert state.observe(board) is True
    assert state.history == {_key(board): 1}
    assert state.own_moves == 0
    assert state.desyncs == 0


def test_scripted_game_records_both_sides_moves() -> None:
    state = GameState()
    root = chess.Board()
    state.observe(root)

    ours = _after(root, "e4")
    state.record_own_move(ours)
    assert state.own_moves == 1
    assert state.history[_key(ours)] == 1

    theirs = _after(ours, "e5")
    assert state.observe(theirs) is True
    assert state.history[_key(theirs)] == 1
    assert state.desyncs == 0

    ours2 = _after(theirs, "Nf3")
    state.record_own_move(ours2)
    theirs2 = _after(ours2, "Nc6")
    assert state.observe(theirs2) is True
    assert state.own_moves == 2
    # Four plies plus the root: five distinct positions, each seen once.
    assert len(state.history) == 5
    assert all(count == 1 for count in state.history.values())


def test_desync_resets_history_to_the_received_position() -> None:
    state = GameState()
    root = chess.Board()
    state.observe(root)
    state.record_own_move(_after(root, "e4"))
    # A position that is not one Black move away from 1.e4: a different opening, White to move.
    stray = chess.Board("rnbqkbnr/pp1ppppp/8/2p5/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 2")
    assert state.observe(stray) is False
    assert state.desyncs == 1
    assert state.history == {_key(stray): 1}
    # Bookkeeping about our own moves is not history and survives the reset.
    assert state.own_moves == 1
    # Play continues normally from the new root.
    ours = _after(stray, "d5")
    state.record_own_move(ours)
    assert state.observe(_after(ours, "e6")) is True
    assert state.desyncs == 1


def test_skipped_plies_are_a_desync() -> None:
    # If we are handed a position two of the opponent's moves later than expected (something
    # went wrong in between), the history cannot be trusted and is restarted.
    state = GameState()
    root = chess.Board()
    state.observe(root)
    state.record_own_move(_after(root, "e4"))
    assert state.observe(_after(root, "e4", "e5", "Nf3", "Nc6")) is False
    assert state.desyncs == 1


def test_repetition_counts_reach_two_and_three() -> None:
    state = GameState()
    root = chess.Board()
    state.observe(root)
    board = root.copy()
    shuffle = ["Nf3", "Nf6", "Ng1", "Ng8"]
    for lap in (2, 3):
        for i, san in enumerate(shuffle):
            board.push_san(san)
            if i % 2 == 0:
                state.record_own_move(board)
            else:
                assert state.observe(board) is True
        # After the knights return, the start position has occurred again: same pieces, same
        # side to move, same castling rights, so the same key despite a different move number.
        assert state.history[_key(root)] == lap
    assert state.own_moves == 4
    assert state.desyncs == 0
    assert state.history[_key(_after(root, "Nf3"))] == 2


def test_opponent_promotion_piece_is_distinguished() -> None:
    # After our move Black can promote; under-promotion to a knight must be recognised as the
    # move actually played, not confused with a queen promotion.
    state = GameState()
    root = chess.Board("4k3/8/8/8/8/8/1p6/4K2R w K - 0 1")
    state.observe(root)
    ours = _after(root, "Rh2")
    state.record_own_move(ours)
    knight = _after(ours, "b1=N")
    assert state.observe(knight) is True
    assert state.history[_key(knight)] == 1
    assert _key(_after(ours, "b1=Q")) not in state.history


def test_opponent_castling_and_en_passant_are_recognised() -> None:
    state = GameState()
    root = chess.Board("r3k2r/pppppppp/8/8/3P4/8/PPP1PPPP/R3K2R w KQkq - 0 1")
    state.observe(root)
    ours = _after(root, "d5")
    state.record_own_move(ours)
    castled = _after(ours, "O-O-O")
    assert state.observe(castled) is True
    ours2 = _after(castled, "Kf1")
    state.record_own_move(ours2)
    theirs = _after(ours2, "c5")
    assert state.observe(theirs) is True
    ours3 = _after(theirs, "dxc6")  # en passant, our move
    state.record_own_move(ours3)
    assert state.observe(_after(ours3, "bxc6")) is True
    assert state.desyncs == 0


def test_caller_may_keep_mutating_its_board() -> None:
    # The state must copy what it is given: the agent pushes our move onto its working board and
    # that board is not owned by the state.
    state = GameState()
    board = chess.Board()
    state.observe(board)
    board.push_san("d4")
    state.record_own_move(board)
    board.push_san("d5")  # the agent's board wanders on after the record ...
    board.push_san("c4")
    expected = _after(chess.Board(), "d4", "Nf6")  # ... but the real opponent played Nf6
    assert state.observe(expected) is True
    assert state.desyncs == 0


def test_history_always_contains_the_current_root() -> None:
    state = GameState()
    board = chess.Board()
    state.observe(board)
    for san in ["e4", "c5", "Nf3", "d6", "d4", "cxd4"]:
        board.push_san(san)
        if board.turn == chess.BLACK:
            state.record_own_move(board)
        else:
            assert state.observe(board) is True
            assert _key(board) in state.history
