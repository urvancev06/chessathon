"""Tests for the compiled searcher (``mikhail_letal.fastsearch``).

The compiled search is a port of ``mikhail_letal.search``, so this file asks the same behavioural
questions ``tests/test_search.py`` asks of the original: does it find the mate, take the hanging
queen, avoid a repetition when ahead and seek one when behind, stop at its limits, and answer with
a legal move whatever happens. The two searchers are *not* required to agree move for move --
the compiled one replaces its transposition table's entries where the Python one accumulates them
in a dict, so their pruning differs -- and that is why the comparison here is against chess, not
against the other engine.

Two gates are specific to the compiled build and matter more than any of the rest:

* every jitted function is compiled at import and gains no specialisation during a game, because
  a function first compiled on the clock costs a move on the platform;
* the search never hands back an illegal move, on any position, at any limit.
"""

from __future__ import annotations

import os
import random
import time

import chess
import numpy as np
import numpy.typing as npt
import pytest

from mikhail_letal.evaluation import DRAW_SCORE, MATE_SCORE, MATE_THRESHOLD
from mikhail_letal.fastboard import (
    EMPTY,
    FLAG_CASTLE,
    FLAG_EN_PASSANT,
    FLAG_MASK,
    FLAG_SHIFT,
    M_KING,
    M_SIDE,
    MAX_MOVES,
    NO_SQ,
    PIECE_TYPE_MASK,
    PROMO_MASK,
    PROMO_SHIFT,
    SQ_BITS,
    SQ_MASK,
    Position,
    from_board,
    gen_pseudo,
    move_to_chess,
    new_position,
    position_key,
    set_from_board,
)
from mikhail_letal.fasteval import TABLES as EVAL_TABLES
from mikhail_letal.fasteval import evaluate as compiled_evaluate
from mikhail_letal.fastsearch import (
    _DIR_TABLE,
    DEFAULT_NODE_RATE,
    F_HARD,
    I_EVAL_MASK,
    I_HISTORY_MASK,
    I_NODE_LIMIT,
    I_TT_MASK,
    JITTED,
    FastEngine,
    _cached_eval,
    _check_is_safe,
    _direct_check,
    _discovered_slider,
    _discovery_survives,
    _has_legal,
    _has_unpinned_move,
    _make_null,
    _unmake_null,
    gen_captures,
    gen_checks,
    negamax,
    new_state,
    quiescence,
    warm_up,
)
from mikhail_letal.search import QS_CHECK_PLIES, Engine, SearchResult
from mikhail_letal.warmup import arm, budget
from tests.test_fastboard import playout_boards, sample_starts

FULL_GATES = os.environ.get("LETAL_FULL_GATES") == "1"

MATE_IN_ONE_WHITE = "6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1"
MATE_IN_ONE_BLACK = "r3k3/8/8/8/8/8/5PPP/6K1 b - - 0 1"
# Mate in two (Anastasia's pattern): 1. Qxh7+ Kxh7 (forced) 2. Rh1#.
MATE_IN_TWO = "5r1k/4Nppp/8/8/7Q/8/6K1/3R4 w - - 0 1"
HANGING_QUEEN = "rnb1kbnr/pppp1ppp/8/4p3/7q/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 3"
QUEEN_VS_ROOK_WHITE_TO_MOVE = "5rk1/8/8/8/3Q4/8/8/6K1 w - - 0 1"
QUEEN_VS_ROOK_BLACK_TO_MOVE = "5rk1/8/8/8/3Q4/8/8/6K1 b - - 0 1"
STALEMATE_ROOT = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
# Stalemates with the side to move holding progressively more material, so the cheap legality
# probe has to answer "cannot tell" for a bare king, for blocked pawns and for a boxed-in piece.
STALEMATES = (
    STALEMATE_ROOT,  # bare king, boxed by a queen
    "k7/8/1Q6/8/8/8/8/7K b - - 0 1",  # bare king in the corner
    "8/8/8/8/8/1q6/2k5/K7 w - - 0 1",  # the same the other way round
    "8/8/8/8/8/8/p7/k1K5 b - - 0 1",  # a king and one blocked pawn
    "8/8/8/8/8/4k3/4p3/4K3 w - - 0 1",  # a king with a pawn in front of it
    "5bnr/4p1pq/4Qpkr/7p/2P4P/8/PP1PPPP1/RNB1KBNR b KQ - 0 1",  # a full army, none of it mobile
)
CHECKMATE_ROOT = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
BUSY_MIDDLEGAME = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
# Eight queens a side: the position that used to make one depth-1 iteration cost hundreds of
# thousands of quiescence nodes before the check-evasion cap.
DENSE = "QQQQ1QQk/8/8/8/8/8/8/qqqq1qqK w - - 0 1"

# One engine for the whole file: the compile is the expensive part and the tests that care about
# a fresh table call new_game() themselves.
ENGINE = FastEngine()
warm_up(ENGINE)


def far_future() -> float:
    return time.perf_counter() + 3600.0


def run_search(
    fen: str,
    *,
    history: list[int] | None = None,
    max_depth: int = 64,
    node_limit: int | None = None,
    engine: FastEngine | None = None,
    deadline: float | None = None,
) -> SearchResult:
    """Search ``fen`` with no time pressure; the root key is in the history unless given."""
    board = chess.Board(fen)
    if history is None:
        history = [position_key(board)]
    engine = engine if engine is not None else ENGINE
    if engine is ENGINE:
        engine.new_game()
    when = far_future() if deadline is None else deadline
    return engine.search(board, history, when, when, max_depth=max_depth, node_limit=node_limit)


def key_after(fen: str, uci: str) -> int:
    board = chess.Board(fen)
    board.push_uci(uci)
    return position_key(board)


# --------------------------------------------------------------- (a) compiled at import, once


def test_every_jitted_function_is_compiled_at_import() -> None:
    import mikhail_letal.fastsearch as module

    for name in JITTED:
        assert getattr(module, name).signatures, f"{name} was not compiled by warm_up()"


def test_nothing_compiles_during_a_game() -> None:
    """The gate that matters on the platform: numba silently compiles a second specialisation
    when a caller hands over a different argument type, and that would land on the clock."""
    import mikhail_letal.fastsearch as module

    before = {name: list(getattr(module, name).signatures) for name in JITTED}
    engine = FastEngine()
    # Ask for an unbounded warm-up explicitly. `agent` arms the shared budget with a 70-second
    # deadline when pytest imports `tests/test_properties.py` during collection, and by the time
    # this test runs that deadline can already have passed; the phases would then be *skipped*,
    # which leaves their names in the shared budget and breaks the two tests below that read it.
    arm(None)
    warm_up(engine)
    after_warm = {name: list(getattr(module, name).signatures) for name in JITTED}

    board = chess.Board()
    keys = [position_key(board)]
    engine.new_game()
    rng = random.Random(20260908)
    for _ in range(30):
        if board.is_game_over() or board.ply() > 60:
            break
        result = engine.search(board, keys, far_future(), far_future(), max_depth=4)
        assert result.move is not None
        board.push(result.move)
        keys.append(position_key(board))
        moves = list(board.legal_moves)
        if not moves:
            break
        board.push(rng.choice(moves))
        keys.append(position_key(board))
    after = {name: list(getattr(module, name).signatures) for name in JITTED}
    assert after == after_warm == before


def test_an_expired_deadline_skips_every_phase_and_still_returns() -> None:
    """The safety property behind `mikhail_letal/warmup.py`: a warm-up that has run out of wall
    clock stops instead of overrunning the platform's 90-second import budget. Nothing raises,
    the phases are recorded by name for the log line, and the node rate that backs up the clock
    keeps its conservative default rather than being left at zero."""
    engine = FastEngine()
    assert engine.node_rate == DEFAULT_NODE_RATE
    arm(None)  # the budget is shared and `warm_up` only sets its deadline: start its log empty
    try:
        # `budget()` is one shared record whose `skipped` list accumulates across calls, so the
        # test arms it itself rather than reading whatever earlier tests (or the agent import)
        # happened to leave in it. `arm` resets the accounting; `warm_up` only sets the deadline.
        arm(time.perf_counter() - 1.0)
        spent = warm_up(engine)
        skipped = set(budget().skipped)
    finally:
        arm(None)  # the budget is shared, so put it back before the next test
    assert spent < 1.0  # nothing ran, so nothing was compiled
    assert engine.node_rate == DEFAULT_NODE_RATE
    # Every phase of this module has to be in there. Membership, not an exact list: the order and
    # any phases other modules record are not what this test is about.
    assert {
        "fastsearch.helpers",
        "fastsearch.quiescence",
        "fastsearch.negamax",
        "fastsearch.tie_break",
        "fastsearch.samples",
        "fastsearch.node_rate",
    } <= skipped


def test_a_partial_deadline_runs_the_phases_that_fit() -> None:
    """Phases are judged one at a time against what they cost on the development machine, so a
    budget that fits some of them runs those; and the two that need a compiled `negamax` are
    skipped once it is, because running them would compile it anyway."""
    engine = FastEngine()
    arm(None)  # see the note in the test above
    try:
        # Three seconds fits `quiescence` (2.1 reference seconds) and `tie_break` (1.6) but not
        # `helpers` (5.3) or `negamax` (12.5).
        warm_up(engine, deadline=time.perf_counter() + 3.0)
        skipped = list(budget().skipped)
    finally:
        arm(None)
    assert skipped == [
        "fastsearch.helpers",
        "fastsearch.negamax",
        "fastsearch.samples",
        "fastsearch.node_rate",
    ]
    assert engine.node_rate == DEFAULT_NODE_RATE  # its seeding search was one of the four


def test_a_generous_deadline_runs_the_whole_warm_up() -> None:
    engine = FastEngine()
    arm(None)  # see the note two tests above
    try:
        warm_up(engine, deadline=time.perf_counter() + 3600.0)
        skipped = list(budget().skipped)
    finally:
        arm(None)
    assert skipped == []
    assert engine.node_rate > 0.0


# ----------------------------------------------------------------------------- (b) tactics


@pytest.mark.parametrize(
    ("fen", "expected"), [(MATE_IN_ONE_WHITE, "a1a8"), (MATE_IN_ONE_BLACK, "a8a1")]
)
def test_mate_in_one_found_at_depth_one(fen: str, expected: str) -> None:
    result = run_search(fen, max_depth=1)
    assert result.move is not None
    assert result.move.uci() == expected
    assert result.score == MATE_SCORE - 1


def test_mate_in_two_is_a_forced_mate() -> None:
    """The expected line is re-verified with python-chess, so the answer does not rest on the
    engine under test."""
    board = chess.Board(MATE_IN_TWO)
    board.push_uci("h4h7")
    assert board.is_check()
    assert [m.uci() for m in board.legal_moves] == ["h8h7"]
    board.push_uci("h8h7")
    board.push_uci("d1h1")
    assert board.is_checkmate()

    result = run_search(MATE_IN_TWO, max_depth=4)
    assert result.move is not None
    assert result.move.uci() == "h4h7"
    assert result.score == MATE_SCORE - 3  # mate delivered three plies from the root


def test_captures_hanging_queen() -> None:
    result = run_search(HANGING_QUEEN, max_depth=4)
    assert result.move is not None
    assert result.move.uci() == "f3h4"
    assert result.score > 500


def test_mate_in_one_beats_the_fifty_move_rule() -> None:
    """A checkmate on the hundredth halfmove is a win, not a draw: the referee tests for mate
    before it tests for the fifty-move rule."""
    result = run_search("6k1/5ppp/8/8/8/8/8/R3K3 w - - 99 80", max_depth=2)
    assert result.move is not None
    assert result.move.uci() == "a1a8"
    assert result.score == MATE_SCORE - 1


# ----------------------------------------------------------------------------- (c) draws


def test_side_ahead_avoids_repetition() -> None:
    fen = QUEEN_VS_ROOK_WHITE_TO_MOVE
    repeating = "d4d1"
    result = run_search(
        fen, history=[position_key(chess.Board(fen)), key_after(fen, repeating)], max_depth=4
    )
    assert result.move is not None
    assert result.move.uci() != repeating
    assert result.score > 300


def test_side_behind_seeks_repetition() -> None:
    fen = QUEEN_VS_ROOK_BLACK_TO_MOVE
    repeating = "f8e8"
    result = run_search(
        fen, history=[position_key(chess.Board(fen)), key_after(fen, repeating)], max_depth=4
    )
    assert result.move is not None
    assert result.move.uci() == repeating
    assert result.score == DRAW_SCORE
    plain = run_search(fen, max_depth=4)
    assert plain.score < -300


def test_fifty_move_rule_draws_a_won_position() -> None:
    """Queen against a bare king with the halfmove clock at 99: every legal move is the hundredth
    halfmove without a capture or a pawn move, so the position is drawn whatever is played."""
    result = run_search("Q7/8/8/8/4k3/8/8/7K w - - 99 80", max_depth=3)
    assert result.move is not None
    assert result.score == DRAW_SCORE


@pytest.mark.parametrize(
    "fen",
    [
        "Q7/8/8/8/4k3/8/8/7K w - - 0 300",  # ply 598: two plies left before the cap
        "Q7/8/8/8/4k3/8/8/7K w - - 0 400",  # already past it
    ],
)
def test_ply_cap_scores_draw(fen: str) -> None:
    result = run_search(fen, max_depth=4)
    assert result.move is not None
    assert result.score == DRAW_SCORE


def test_rule_draw_inside_the_horizon_prefers_the_best_static_child() -> None:
    """With every move scoring the same rule draw, the tie-break keeps the mop-up going instead
    of shuffling until the draw arrives. Never onto a stalemate."""
    result = run_search("8/8/8/4k3/8/8/8/Q6K w - - 99 80", max_depth=3)
    assert result.move is not None
    assert result.score == DRAW_SCORE
    board = chess.Board("8/8/8/4k3/8/8/8/Q6K w - - 99 80")
    board.push(result.move)
    assert not board.is_stalemate()


def test_stalemate_root_has_no_move_and_draw_score() -> None:
    result = run_search(STALEMATE_ROOT, max_depth=3)
    assert result.move is None
    assert result.score == DRAW_SCORE
    assert result.nodes == 0


def test_checkmate_root_has_no_move_and_mated_score() -> None:
    result = run_search(CHECKMATE_ROOT, max_depth=3)
    assert result.move is None
    assert result.score == -MATE_SCORE


def test_stand_pat_cutoff_never_trusts_a_position_without_moves() -> None:
    """The compiled twin of the same question in `tests/test_search.py`. A mated or stalemated
    side can evaluate far above beta; the quiescence stand-pat must still score the position as
    the mate or the draw, whichever it is, and never as the evaluation."""
    from mikhail_letal.fastboard import from_board, in_check
    from mikhail_letal.fastsearch import quiescence
    from mikhail_letal.search import QS_EVASION_PLIES

    engine = FastEngine()
    st = engine.state
    low_beta = -50_000  # far below any static evaluation, so a stand pat would cut off

    stalemate = chess.Board(STALEMATE_ROOT)
    assert stalemate.is_stalemate()
    pos = from_board(stalemate)
    assert int(quiescence(pos, st, EVAL_TABLES, -MATE_SCORE, low_beta, 1, 0, 0)) == DRAW_SCORE

    mate = chess.Board(CHECKMATE_ROOT)
    assert mate.is_checkmate()
    pos = from_board(mate)
    checked = int(in_check(pos))
    # Beyond QS_EVASION_PLIES a check is handled like any other node: still a mate here.
    deep = QS_EVASION_PLIES
    assert int(quiescence(pos, st, EVAL_TABLES, -MATE_SCORE, low_beta, 1, checked, deep)) == -(
        MATE_SCORE - 1
    )
    assert int(quiescence(pos, st, EVAL_TABLES, -MATE_SCORE, MATE_SCORE, 1, checked, 0)) == -(
        MATE_SCORE - 1
    )


def test_the_cheap_legality_probe_is_one_way_and_never_misses_a_mate() -> None:
    """`_has_unpinned_move` is a *sufficient* reason to believe the side to move has a move, and
    `_has_legal` has to stay exact whatever it answers. Both are checked against python-chess on
    a playout sample: the probe may say "cannot tell", but a "yes" must be true, and a position
    with no legal move must never get one."""
    from mikhail_letal.fastboard import from_board

    engine = FastEngine()
    st = engine.state
    asked = 0
    answered = 0
    terminal = 0

    def audit(board: chess.Board) -> None:
        nonlocal asked, answered, terminal
        pos = from_board(board)
        before = pos.board.tolist()
        in_chk = int(board.is_check())
        want = 1 if any(board.legal_moves) else 0
        assert int(_has_legal(pos, st, 1, in_chk)) == want, board.fen()
        assert pos.board.tolist() == before, board.fen()  # the probe leaves the board alone
        if in_chk:
            return
        asked += 1
        probe = int(_has_unpinned_move(pos))
        answered += probe
        assert probe == 0 or want == 1, board.fen()  # one-way: a yes is never wrong
        if want == 0:
            terminal += 1
            assert probe == 0, board.fen()  # a stalemate is never called free

    # Random playouts almost never end in stalemate, so the positions the test exists for are
    # named rather than sampled.
    for fen in STALEMATES:
        board = chess.Board(fen)
        assert board.is_stalemate(), fen
        audit(board)
    for board in playout_boards(4_000, 20260908, sample_starts()):
        audit(board)
    assert terminal == len(STALEMATES)  # every one of them reached the "no legal move" branch
    assert answered > asked * 0.9  # and the probe settles the great majority without generating


# ----------------------------------------------------------------------------- (d) limits


def test_hard_deadline_in_the_past_returns_a_legal_move_quickly() -> None:
    board = chess.Board()
    past = time.perf_counter() - 1.0
    started = time.perf_counter()
    ENGINE.new_game()
    result = ENGINE.search(board, [position_key(board)], past, past)
    assert time.perf_counter() - started < 0.5
    assert result.move is not None
    assert result.move in board.legal_moves


def test_node_limit_stops_the_search_close_to_the_limit() -> None:
    """The cap that backs up the clock: it must actually bite, and within one check interval of
    where it was asked to."""
    result = run_search(BUSY_MIDDLEGAME, node_limit=20_000)
    assert result.aborted
    assert 20_000 <= result.nodes < 20_000 + 4_096
    assert result.move is not None


def test_abort_inside_the_first_iteration_still_returns_a_legal_move() -> None:
    board = chess.Board(BUSY_MIDDLEGAME)
    ENGINE.new_game()
    result = ENGINE.search(board, [position_key(board)], far_future(), far_future(), node_limit=1)
    assert result.move is not None
    assert result.move in board.legal_moves


def test_the_hard_deadline_is_respected() -> None:
    """The clock, not the node cap, is what has to stop the search: with the cap far away, a
    quarter-second budget must not overrun by more than a few milliseconds."""
    board = chess.Board(BUSY_MIDDLEGAME)
    ENGINE.new_game()
    started = time.perf_counter()
    deadline = started + 0.25
    result = ENGINE.search(board, [position_key(board)], deadline, deadline, node_limit=10**9)
    overshoot = time.perf_counter() - deadline
    assert overshoot < 0.05, f"overran the hard deadline by {overshoot * 1000:.0f} ms"
    assert result.move is not None
    assert result.move in board.legal_moves


def test_the_soft_target_stops_the_deepening() -> None:
    """A soft target already in the past ends the search after one completed iteration, and one
    sized for a couple of iterations stops well inside the hard window."""
    board = chess.Board(BUSY_MIDDLEGAME)
    ENGINE.new_game()
    started = time.perf_counter()
    shallow = ENGINE.search(board, [position_key(board)], started, started + 5.0)
    assert shallow.depth == 1
    assert not shallow.aborted

    ENGINE.new_game()
    started = time.perf_counter()
    result = ENGINE.search(board, [position_key(board)], started + 0.30, started + 2.0)
    elapsed = time.perf_counter() - started
    # The prediction is what stops it: it neither runs to the hard deadline nor stops at the
    # 0.45 share of the target that the fixed rule used to stop at.
    assert result.depth >= 1
    assert elapsed < 2.0, f"took {elapsed:.2f} s of a 2.0 s hard budget"


def test_the_engines_agree_on_when_to_stop_deepening() -> None:
    """The reference searcher runs the same rule, so both stop at the same soft target."""
    board = chess.Board(BUSY_MIDDLEGAME)
    started = time.perf_counter()
    reference = Engine().search(board, {}, started, started + 5.0)
    assert reference.depth == 1
    assert not reference.aborted


def test_dense_position_keeps_the_first_iteration_small() -> None:
    """Eight queens a side, where an uncapped check-evasion search explodes."""
    result = run_search(DENSE, max_depth=1)
    assert result.move is not None
    assert result.nodes < 50_000, result.nodes


# ----------------------------------------------------------------------------- (e) invariants


def test_identical_searches_give_identical_results() -> None:
    first = run_search(BUSY_MIDDLEGAME, max_depth=5, engine=FastEngine())
    second = run_search(BUSY_MIDDLEGAME, max_depth=5, engine=FastEngine())
    assert first.move == second.move
    assert (first.score, first.depth, first.nodes) == (second.score, second.depth, second.nodes)


def test_new_game_restores_a_fresh_searcher() -> None:
    engine = FastEngine()
    fresh = engine.search(
        chess.Board(BUSY_MIDDLEGAME),
        [position_key(chess.Board(BUSY_MIDDLEGAME))],
        far_future(),
        far_future(),
        max_depth=5,
    )
    engine.search(
        chess.Board(HANGING_QUEEN),
        [position_key(chess.Board(HANGING_QUEEN))],
        far_future(),
        far_future(),
        max_depth=5,
    )
    engine.new_game()
    again = engine.search(
        chess.Board(BUSY_MIDDLEGAME),
        [position_key(chess.Board(BUSY_MIDDLEGAME))],
        far_future(),
        far_future(),
        max_depth=5,
    )
    assert (again.move, again.score, again.nodes) == (fresh.move, fresh.score, fresh.nodes)


def test_search_does_not_mutate_the_callers_board() -> None:
    board = chess.Board(BUSY_MIDDLEGAME)
    before = board.fen()
    ENGINE.new_game()
    ENGINE.search(board, [position_key(board)], far_future(), far_future(), max_depth=5)
    assert board.fen() == before


def test_result_fields_are_consistent() -> None:
    result = run_search(BUSY_MIDDLEGAME, max_depth=6)
    assert result.move is not None
    assert result.depth == 6
    assert result.seldepth >= result.depth
    assert result.nodes > 0
    assert result.elapsed > 0
    assert not result.aborted


def test_the_evaluation_cache_returns_what_the_evaluation_would() -> None:
    """A cache hit must be indistinguishable from a fresh evaluation: the key is the whole
    position, so there is no approximation to allow for."""
    from mikhail_letal.fastboard import ZOBRIST, hash_position, new_position, set_from_board

    state = new_state()
    state.ints[I_EVAL_MASK] = state.eval_key.shape[0] - 1
    pos = new_position()
    checked = 0
    for board in playout_boards(400, seed=27182818, starts=sample_starts()):
        set_from_board(pos, board)
        key = int(hash_position(pos, ZOBRIST))
        expected = int(compiled_evaluate(pos, EVAL_TABLES))
        assert int(_cached_eval(pos, state, EVAL_TABLES, key)) == expected  # miss, then store
        assert int(_cached_eval(pos, state, EVAL_TABLES, key)) == expected  # hit
        checked += 1
    assert checked == 400


def test_negamax_leaves_the_position_exactly_as_it_found_it() -> None:
    """Including when the abort fires in the middle of a line: the search returns through every
    ``unmake_move`` on the way out, so the board is never left half-played."""
    from mikhail_letal.fastboard import new_position, running_key, set_from_board

    state = new_state()
    pos = new_position()
    board = chess.Board(BUSY_MIDDLEGAME)
    set_from_board(pos, board)
    for limit in (1, 37, 500, 5_000, 0):
        state.ints[:] = 0
        state.ints[I_TT_MASK] = state.tt_key.shape[0] - 1
        state.ints[I_EVAL_MASK] = state.eval_key.shape[0] - 1
        state.ints[I_HISTORY_MASK] = state.history_keys.shape[0] - 1
        state.ints[I_NODE_LIMIT] = limit
        state.flt[F_HARD] = time.perf_counter() + 3600.0
        snapshot = (
            pos.board.copy(),
            pos.plist.copy(),
            pos.pidx.copy(),
            pos.meta.copy(),
        )
        # The running Zobrist key is part of the position now, and every `unmake_move` on the way
        # out has to put it back; an abort in mid-line must not leave it drifted.
        key_before = running_key(pos)
        negamax(pos, state, EVAL_TABLES, 6, -MATE_SCORE - 1, MATE_SCORE + 1, 1, 1)
        for expected, actual in zip(
            snapshot, (pos.board, pos.plist, pos.pidx, pos.meta), strict=True
        ):
            assert (expected == actual).all(), f"position changed with node limit {limit}"
        assert running_key(pos) == key_before, f"key changed with node limit {limit}"


# ----------------------------------------------------------------------------- (f) legality


def test_every_move_returned_is_legal_on_sampled_positions() -> None:
    """The gate the whole build rests on. One illegal move loses a game outright, so this runs
    over positions from playouts of the curated openings, at three different limits."""
    count = 3_000 if FULL_GATES else 400
    engine = FastEngine()
    checked = 0
    for index, board in enumerate(playout_boards(count, seed=16180339, starts=sample_starts())):
        if not any(board.legal_moves):
            continue
        limits = (1, 250, 3_000)
        result = engine.search(
            board,
            [position_key(board)],
            far_future(),
            far_future(),
            node_limit=limits[index % 3],
        )
        assert result.move is not None, board.fen()
        assert result.move in board.legal_moves, (board.fen(), result.move)
        checked += 1
    assert checked > count // 2


def test_score_is_never_beyond_a_mate() -> None:
    engine = FastEngine()
    for board in playout_boards(200, seed=12345677, starts=sample_starts()):
        result = engine.search(
            board, [position_key(board)], far_future(), far_future(), max_depth=3
        )
        assert -MATE_SCORE <= result.score <= MATE_SCORE
        if abs(result.score) >= MATE_THRESHOLD:
            assert result.move is not None or not any(board.legal_moves)


def test_a_forced_move_is_returned_without_a_deep_search() -> None:
    """One legal reply: the search spends a single iteration on it and banks the rest."""
    fen = "7k/8/8/8/8/8/1q6/K7 w - - 0 1"  # in check; only Kxb2 is legal
    board = chess.Board(fen)
    assert board.legal_moves.count() == 1
    result = run_search(fen)
    assert result.move is not None
    assert result.move in board.legal_moves
    assert result.depth == 1


def test_the_null_move_keeps_the_position_key_exact() -> None:
    """`_make_null` maintains the running key that `make_move` maintains everywhere else.

    Passing touches no piece, so only two terms of the key can change: the side-to-move term,
    which always flips, and the en passant term, which the pass clears -- and which counts only
    when a pawn of the side to move was standing ready to take. That last condition is why this
    is checked against `hash_position` rather than argued: it is evaluated on the position before
    the pass and has to be removed from the key of the position after it.
    """
    from mikhail_letal.fastboard import (
        ZOBRIST,
        hash_position,
        new_position,
        running_key,
        set_from_board,
    )

    # Positions with an en passant square that can be taken, one that cannot, and none at all,
    # ahead of a broad sample from random playouts.
    fens = [
        "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3",
        "rnbqkbnr/pppp1ppp/8/8/3pP3/8/PPP2PPP/RNBQKBNR b KQkq e3 0 3",
        "8/8/8/8/1pPp4/8/8/K5k1 b - c3 0 1",
        "8/8/8/8/7p/2P5/8/K5k1 b - c3 0 1",
        BUSY_MIDDLEGAME,
    ]
    boards = [chess.Board(fen) for fen in fens]
    pos = new_position()
    checked = 0
    for board in [*boards, *playout_boards(600, seed=31415926, starts=sample_starts())]:
        set_from_board(pos, board)
        before = running_key(pos)
        saved = _make_null(pos)
        assert running_key(pos) == int(hash_position(pos, ZOBRIST)), board.fen()
        _unmake_null(pos, *saved)
        assert running_key(pos) == before, board.fen()
        checked += 1
    assert checked == len(fens) + 600


# ----------------------------------------------------------------------- quiescence checks
#
# `gen_checks` is the one place in the engine that decides, without making the move, whether a
# move gives check. Everything downstream trusts it: quiescence hands the child an `in_check`
# flag, and a child wrongly told it is in check searches evasions and can answer with a mate that
# is not on the board. So it is checked against python-chess move by move, not by spot positions.


def _gives_check_by_hand(pos: Position, move: int) -> bool:
    """The three geometry primitives composed independently of `gen_checks`.

    `gen_checks` hoists the discovered-check test out of its move loop, because whether *leaving*
    a square uncovers a slider depends only on the square left. This restates the rule without
    that optimisation, so a bug in the hoisting shows up as a disagreement here rather than being
    reproduced identically on both sides of the comparison.
    """
    board = pos.board
    side = int(pos.meta[M_SIDE])
    king = int(pos.meta[M_KING + 1 - side])
    frm = move & SQ_MASK
    to = (move >> SQ_BITS) & SQ_MASK
    if _direct_check(board, int(board[frm]) & PIECE_TYPE_MASK, side, frm, to, king):
        return True
    slider = int(_discovered_slider(board, side, frm, king))
    if slider == NO_SQ:
        return False
    return bool(_discovery_survives(to, king, slider, int(_DIR_TABLE[frm - king + 128])))


def _quiet_candidates(pos: Position, scratch: npt.NDArray[np.int32]) -> list[int]:
    """The pseudo-legal moves `gen_checks` is allowed to consider: quiet, not a promotion, and
    neither en passant (which lands on an empty square but is a capture) nor castling (which
    moves two pieces, so a from-to test would not see the rook that delivers the check)."""
    out = []
    for i in range(int(gen_pseudo(pos, scratch))):
        move = int(scratch[i])
        if pos.board[(move >> SQ_BITS) & SQ_MASK] != EMPTY:
            continue
        if ((move >> PROMO_SHIFT) & PROMO_MASK) != 0:
            continue
        if ((move >> FLAG_SHIFT) & FLAG_MASK) in (FLAG_EN_PASSANT, FLAG_CASTLE):
            continue
        out.append(move)
    return out


def test_gen_checks_agrees_with_python_chess_on_every_legal_quiet_move() -> None:
    """The gate for the whole feature: the geometry is exact, in both directions.

    A move emitted that gives no check would tell the child it is in check and could come back as
    a mate that is not there. A check missed is only lost tactics, but a systematically missed
    *kind* of check -- a discovery, say -- would make the feature look useless when it is merely
    broken, so both directions are asserted, and the sample is required to contain both kinds.

    Pseudo-legal king steps next to the enemy king are the one deliberate disagreement with
    python-chess: they "give check" only because python-chess counts a king as an attacker, they
    are illegal, and `make_move` rejects them. Asking only about legal moves excludes them, and
    legal moves are the only kind quiescence ever searches.
    """
    pos = new_position()
    scratch = np.zeros(MAX_MOVES, dtype=np.int32)
    direct = discovered = 0

    for board in playout_boards(3_000 if FULL_GATES else 500, 20260909, sample_starts()):
        if board.is_game_over():
            continue
        set_from_board(pos, board)
        legal = {move.uci() for move in board.legal_moves}
        side = int(pos.meta[M_SIDE])
        king = int(pos.meta[M_KING + 1 - side])
        for move in _quiet_candidates(pos, scratch):
            chess_move = move_to_chess(move)
            if chess_move.uci() not in legal:
                continue
            board.push(chess_move)
            attacked_king = board.king(board.turn)
            assert attacked_king is not None, "a playout position lost a king"
            truth = bool(board.is_attacked_by(not board.turn, attacked_king))
            board.pop()
            assert _gives_check_by_hand(pos, move) is truth, (
                f"{board.fen()} {chess_move.uci()}: engine and python-chess disagree"
            )
            if truth:
                if _direct_check(
                    pos.board,
                    int(pos.board[move & SQ_MASK]) & PIECE_TYPE_MASK,
                    side,
                    move & SQ_MASK,
                    (move >> SQ_BITS) & SQ_MASK,
                    king,
                ):
                    direct += 1
                else:
                    discovered += 1

    assert direct > 0, "no direct check in the sample: the comparison proved only half the code"
    assert discovered > 0, "no discovered check in the sample"


def test_gen_checks_emits_checks_only_and_drops_only_what_the_filter_drops() -> None:
    """`gen_checks` is the geometry plus `_check_is_safe`, and nothing else.

    Everything it emits must be a check, or quiescence mis-scores a child. Everything it drops
    must be explained by the safety filter rather than by a gap in the generator, which is what
    keeps the filter the single place the policy lives: swapping it for a static exchange
    evaluation stays a one-function change.
    """
    pos = new_position()
    buffer = np.zeros(MAX_MOVES, dtype=np.int32)
    scratch = np.zeros(MAX_MOVES, dtype=np.int32)

    for board in playout_boards(500 if FULL_GATES else 200, 4242, sample_starts()):
        if board.is_game_over():
            continue
        set_from_board(pos, board)
        emitted = {int(buffer[i]) for i in range(int(gen_checks(pos, buffer)))}
        for move in emitted:
            assert _gives_check_by_hand(pos, move), (
                f"{board.fen()}: emitted a move that is no check"
            )
        for move in _quiet_candidates(pos, scratch):
            if not _gives_check_by_hand(pos, move) or move in emitted:
                continue
            assert int(_check_is_safe(pos, move)) == 0, (
                f"{board.fen()}: dropped a check the filter would have kept"
            )


def test_the_two_quiescence_move_lists_never_overlap() -> None:
    """Quiescence searches captures and then checks, so a move in both lists would be searched
    twice and would quietly double what the feature costs."""
    pos = new_position()
    checks = np.zeros(MAX_MOVES, dtype=np.int32)
    captures = np.zeros(MAX_MOVES, dtype=np.int32)

    for board in playout_boards(300, 77, sample_starts()):
        if board.is_game_over():
            continue
        set_from_board(pos, board)
        quiet = {int(checks[i]) for i in range(int(gen_checks(pos, checks)))}
        set_from_board(pos, board)
        loud = {int(captures[i]) for i in range(int(gen_captures(pos, captures)))}
        assert not (quiet & loud), f"{board.fen()}: a move is in both quiescence move lists"


def test_quiescence_sees_a_mate_that_begins_with_a_quiet_check() -> None:
    """What the feature is for, shown against itself rather than against another engine.

    Ra1-a8 is mate and takes nothing, so a capture-only quiescence never generates it and answers
    with the static evaluation of a position it believes is quiet. The only difference between the
    two calls is `qs_ply`: at 0 the checks are searched and the mate is found; at QS_CHECK_PLIES
    they are past the cap and the same position scores as material.
    """
    back_rank = chess.Board("6k1/5ppp/8/8/8/8/8/R6K w - - 0 1")
    assert back_rank.is_valid()
    engine = FastEngine()

    pos = from_board(back_rank)
    found = int(quiescence(pos, engine.state, EVAL_TABLES, -MATE_SCORE, MATE_SCORE, 0, 0, 0))
    assert found == MATE_SCORE - 1, "quiescence did not find the quiet mating check"

    pos = from_board(back_rank)
    capped = int(
        quiescence(pos, engine.state, EVAL_TABLES, -MATE_SCORE, MATE_SCORE, 0, 0, QS_CHECK_PLIES)
    )
    assert capped < MATE_THRESHOLD, "a check was searched past the QS_CHECK_PLIES cap"
