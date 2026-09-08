"""Tests for the Stage 0 searcher (``mikhail_letal.search``).

Every position used here is small enough to be checked by hand, and the mate-in-two is also
re-verified with python-chess inside the test so the expected answer does not rest on the
engine under test.
"""

import time
from collections.abc import Mapping

import chess
import pytest

import mikhail_letal.search as search_module
from mikhail_letal.evaluation import DRAW_SCORE, MATE_SCORE, evaluate, is_mate_score
from mikhail_letal.search import NODE_CHECK_INTERVAL, Engine, SearchResult
from mikhail_letal.searchboard import SearchBoard

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
    engine: Engine | None = None,
) -> SearchResult:
    """Search ``fen`` with no time pressure; the root key is in the history unless given."""
    board = chess.Board(fen)
    if history is None:
        history = {board._transposition_key(): 1}
    engine = engine if engine is not None else Engine()
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
    result = Engine().search(board, {board._transposition_key(): 1}, past, past)
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
    engine = Engine()
    fresh = run_search(HANGING_QUEEN, node_limit=5_000, engine=engine)
    warm = run_search(HANGING_QUEEN, node_limit=5_000, engine=engine)
    engine.new_game()
    reset = run_search(HANGING_QUEEN, node_limit=5_000, engine=engine)
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
    Engine().search(board, {board._transposition_key(): 1}, far_future(), far_future(), 3)
    assert board.fen() == before
    assert not board.move_stack


def test_result_fields_are_consistent() -> None:
    result = run_search(HANGING_QUEEN, max_depth=3)
    assert result.depth == 3
    assert result.seldepth >= result.depth
    assert result.nodes > 0
    assert result.elapsed >= 0.0
    assert not result.aborted


# ----------------------------------------------------------------------------- review fixes
# One test per item of the Stage 0 review (docs/DECISIONS.md, 2026-09-07). Letters match there.


def test_clock_is_read_every_128_nodes() -> None:
    # (A) 1024 nodes let the search overshoot the hard deadline by 25 ms on average and 65 ms at
    # worst on the dev box; a clock read costs ~60 ns, so 128 is free and bounds the overshoot.
    assert NODE_CHECK_INTERVAL == 128


def test_table_entries_are_int_only_and_the_move_is_rebuilt() -> None:
    # (B) chess.Move objects in the table made gen-2 garbage collections stall a node for 100+ ms.
    engine = Engine()
    result = run_search(HANGING_QUEEN, max_depth=3, engine=engine)
    assert engine._tt, "the search stored nothing"
    for entry in engine._tt.values():
        assert len(entry) == 4
        assert all(type(field) is int for field in entry)
    # The root's stored move code decodes back to the move the search chose.
    root_entry = engine._tt[chess.Board(HANGING_QUEEN)._transposition_key()]
    rebuilt = search_module._code_to_move(root_entry[3])
    assert rebuilt == result.move
    # A promotion survives the round trip too.
    promotion = chess.Move.from_uci("b7b8n")
    assert search_module._code_to_move(search_module._move_code(promotion)) == promotion


def test_table_is_emptied_between_moves_above_sixty_percent() -> None:
    # (B) A table well on its way to the cap is cleared at the start of a search, so the cap-hit
    # clear inside the search (kept as the backstop) almost never lands mid-iteration.
    engine = Engine(tt_max_entries=1000)
    assert Engine().tt_max_entries == 250_000
    for filler in range(601):
        engine._tt[("filler", filler)] = (1, 0, 0, -1)
    run_search(HANGING_QUEEN, max_depth=2, engine=engine)
    assert ("filler", 0) not in engine._tt
    engine._tt.clear()
    for filler in range(600):
        engine._tt[("filler", filler)] = (1, 0, 0, -1)
    run_search(HANGING_QUEEN, max_depth=2, engine=engine)
    assert ("filler", 0) in engine._tt  # exactly 60 % is kept


def test_rule_draw_inside_the_horizon_prefers_the_best_static_child() -> None:
    # (D) Queen against a bare king with the fifty-move draw four plies away: every root move
    # scores exactly 0 at depth 4, and the engine must not pick one arbitrarily (it did, and
    # shuffled won positions into the draw). It picks the move whose child evaluates best.
    fen = "8/8/8/8/3k4/8/8/4KQ2 w - - 96 60"
    result = run_search(fen, max_depth=4)
    assert result.score == DRAW_SCORE and result.depth == 4
    board = chess.Board(fen)
    assert evaluate(board) >= search_module.DRAW_TIEBREAK_MARGIN

    def child_static(move: chess.Move) -> int:
        board.push(move)
        value = -evaluate(board) if any(board.generate_legal_moves()) else -MATE_SCORE
        board.pop()
        return value

    assert result.move is not None
    assert child_static(result.move) == max(child_static(m) for m in board.legal_moves)
    # Without the material edge (a drawn rook ending) the tie-break stays out of the way.
    assert evaluate(chess.Board("8/8/8/8/3k4/8/8/4KR2 w - - 96 60")) < 1000


def test_path_repetition_draws_are_not_stored_as_position_values() -> None:
    # (E) With an empty game history the root is only on the search path, so the black position
    # reached by 1.Ke2 Ke4 2.Ke1 Ke5 (back to the root) is a draw *along that line only*. The
    # table used to record it as "black is at least level" (depth 4+, LOWER 0) although a fresh
    # search of the position gives about -628 for black.
    root = chess.Board("8/8/8/4k3/8/8/8/R3K3 w - - 0 1")
    engine = Engine()
    engine.search(root, {}, far_future(), far_future(), max_depth=7)
    key = chess.Board("8/8/8/8/4k3/8/8/R3K3 b - - 0 1")._transposition_key()
    entry = engine._tt.get(key)
    # Absent, an ordering hint without a score, or a genuine (clearly losing) score: anything but
    # the path-only draw. Which of the three depends on the evaluation tables in use.
    assert entry is None or entry[0] < 0 or entry[1] < -100, entry
    fresh = run_search("8/8/8/8/4k3/8/8/R3K3 b - - 0 1", max_depth=4)
    assert fresh.score < -300
    # A repetition seen inside the tree with the root in the history taints the same way: the
    # position after 1.Ke2 Kd4 2.Ke1 Ke4 3.Ke2 can only claim a draw for black by 3...Kd4
    # repeating the line, and its stored value must not say so.
    engine = Engine()
    engine.search(root, {root._transposition_key(): 1}, far_future(), far_future(), max_depth=7)
    inside = engine._tt.get(chess.Board("8/8/8/8/4k3/8/4K3/R7 b - - 0 1")._transposition_key())
    assert inside is None or inside[0] < 0 or inside[1] < 0


def test_queen_promotion_wins_an_exact_tie_over_an_under_promotion() -> None:
    # (H) b8=Q and b8=R both mate in one. If the table remembers b8=R as the move to try first
    # (as it did once an under-promotion was chosen), the queen must still be preferred.
    fen = "6k1/1P3ppp/8/8/8/8/8/6K1 w - - 0 1"
    board = chess.Board(fen)
    engine = Engine()
    rook_first = search_module._move_code(chess.Move.from_uci("b7b8r"))
    engine._tt[board._transposition_key()] = (1, MATE_SCORE - 1, search_module.EXACT, rook_first)
    result = run_search(fen, max_depth=2, engine=engine)
    assert result.move == chess.Move.from_uci("b7b8q")
    assert result.score == MATE_SCORE - 1


def test_stand_pat_cutoff_never_trusts_a_position_without_moves() -> None:
    # (K) Stand pat is tested before captures are generated (most quiescence nodes end there).
    # A stalemated or mated side may evaluate above beta; the position is still over.
    engine = Engine()
    engine.search(chess.Board(), {}, far_future(), far_future(), max_depth=1)  # primes state
    stalemate = chess.Board(STALEMATE_ROOT)
    assert stalemate.is_stalemate()
    low_beta = -50_000  # far below any static evaluation: the stand pat would cut off
    assert engine._quiescence(SearchBoard(stalemate), -MATE_SCORE, low_beta, 1, False, 0) == (
        DRAW_SCORE
    )
    mate = chess.Board(CHECKMATE_ROOT)
    assert mate.is_checkmate()
    # (M) Beyond QS_EVASION_PLIES a check is handled like any other node: still a mate here.
    deep = search_module.QS_EVASION_PLIES
    quiet_mate = SearchBoard(mate)
    assert engine._quiescence(quiet_mate, -MATE_SCORE, low_beta, 1, True, deep) == -(MATE_SCORE - 1)
    assert engine._quiescence(quiet_mate, -MATE_SCORE, MATE_SCORE, 1, True, 0) == -(MATE_SCORE - 1)


def test_check_extension_is_applied_before_the_table_probe() -> None:
    # (L) The probe used the unextended depth while the store recorded the extended one, so an
    # in-check node accepted an entry one ply too shallow. Now both use the extended depth.
    board = chess.Board("rnb1kbnr/pppp1ppp/8/4p3/4P3/8/PPPPqPPP/RNBQKBNR w KQkq - 0 3")
    assert board.is_check()
    engine = Engine()
    engine.search(board, {}, far_future(), far_future(), max_depth=1)  # primes deadlines etc.
    engine._path = {}
    engine._tt.clear()
    key = board._transposition_key()
    engine._negamax(SearchBoard(board.copy(stack=False)), 3, -MATE_SCORE, MATE_SCORE, 1)
    assert engine._tt[key][0] == 4  # stored at the extended depth
    before = engine._nodes
    engine._negamax(SearchBoard(board.copy(stack=False)), 4, -MATE_SCORE, MATE_SCORE, 1)
    assert engine._nodes - before > 1  # not a table hit: this node is depth 5 once extended
    assert engine._tt[key][0] == 5


def test_dense_position_keeps_the_first_iteration_small() -> None:
    # (M) Eight queens a side: with every check searched in full, a depth-1 iteration cost
    # hundreds of thousands of nodes. Evasions are searched in full for four quiescence plies
    # only; deeper checks stand pat like any other node.
    board = chess.Board("7k/8/qqqqqqqq/8/8/QQQQQQQQ/8/K7 w - - 0 1")
    assert board.is_valid()
    result = run_search(board.fen(), max_depth=1)
    assert result.depth == 1 and result.move is not None
    assert result.nodes < 100_000


# ----------------------------------------------------------------------------- v0.2 features
# One group per feature. Node counts are compared with the feature on and off on the same
# position; every search here is deterministic (no clock), so the comparisons are exact.

OPENING_MIDDLEGAME = "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R2Q1RK1 w - - 4 10"
ROOK_ENDGAME = "8/5pk1/6p1/1p2P2p/1P1r1P1P/6P1/3R2K1/8 w - - 0 1"
PAWN_ENDGAME = "8/8/4k3/2p2p2/2P2P2/4K3/8/8 w - - 0 1"  # zugzwang territory: no pieces at all


class NullMoveWatch(chess.Board):
    """A board that records the state every null move is played from (copy() keeps the class,
    so the engine's private copy records as well)."""

    null_moves_in_check = 0
    null_moves_without_a_piece = 0
    null_moves = 0

    def push(self, move: chess.Move) -> None:
        if not move:
            NullMoveWatch.null_moves += 1
            if self.is_check():
                NullMoveWatch.null_moves_in_check += 1
            if not self.occupied_co[self.turn] & ~(self.pawns | self.kings):
                NullMoveWatch.null_moves_without_a_piece += 1
        super().push(move)


def nodes_with(flag: str, value: bool, fen: str, depth: int) -> int:
    saved = getattr(search_module, flag)
    setattr(search_module, flag, value)
    try:
        return run_search(fen, max_depth=depth).nodes
    finally:
        setattr(search_module, flag, saved)


def test_null_move_is_never_played_in_check_or_without_a_piece() -> None:
    NullMoveWatch.null_moves = 0
    NullMoveWatch.null_moves_in_check = 0
    NullMoveWatch.null_moves_without_a_piece = 0
    for fen, depth in ((OPENING_MIDDLEGAME, 6), (ROOK_ENDGAME, 7), (MATE_IN_TWO, 5)):
        board = NullMoveWatch(fen)
        Engine().search(board, {board._transposition_key(): 1}, far_future(), far_future(), depth)
    assert NullMoveWatch.null_moves > 0  # the feature is on and used
    assert NullMoveWatch.null_moves_in_check == 0
    assert NullMoveWatch.null_moves_without_a_piece == 0
    # A pawn ending never sees a null move at all: zugzwang is the rule there, not the exception.
    NullMoveWatch.null_moves = 0
    board = NullMoveWatch(PAWN_ENDGAME)
    engine = Engine()
    engine.search(board, {board._transposition_key(): 1}, far_future(), far_future(), 8)
    assert NullMoveWatch.null_moves == 0 and engine._null_moves == 0


def test_null_move_pruning_saves_nodes_and_can_be_switched_off() -> None:
    on = nodes_with("NULL_MOVE_PRUNING", True, OPENING_MIDDLEGAME, 6)
    off = nodes_with("NULL_MOVE_PRUNING", False, OPENING_MIDDLEGAME, 6)
    assert on < off
    assert run_search(PAWN_ENDGAME, max_depth=8).nodes == nodes_with(
        "NULL_MOVE_PRUNING", False, PAWN_ENDGAME, 8
    )  # without pieces the feature never engages, so the tree is identical


def test_late_move_reductions_save_nodes() -> None:
    assert nodes_with("LATE_MOVE_REDUCTIONS", True, ROOK_ENDGAME, 7) < nodes_with(
        "LATE_MOVE_REDUCTIONS", False, ROOK_ENDGAME, 7
    )
    # Below LMR_MIN_DEPTH nothing is reduced: a depth-2 search is the same tree either way.
    assert search_module.LMR_MIN_DEPTH == 3
    assert nodes_with("LATE_MOVE_REDUCTIONS", True, ROOK_ENDGAME, 2) == nodes_with(
        "LATE_MOVE_REDUCTIONS", False, ROOK_ENDGAME, 2
    )


def test_aspiration_windows_start_at_depth_four_and_keep_the_answer() -> None:
    # Depths 1-3 are always searched with the full window, so the trees are identical.
    assert nodes_with("ASPIRATION_WINDOWS", True, OPENING_MIDDLEGAME, 3) == nodes_with(
        "ASPIRATION_WINDOWS", False, OPENING_MIDDLEGAME, 3
    )
    # From depth 4 the window narrows the tree, and the move is still the same: a fail-high or
    # fail-low is re-searched, so the answer matches the full-window search.
    saved = search_module.ASPIRATION_WINDOWS
    try:
        search_module.ASPIRATION_WINDOWS = True
        aspirated = run_search(OPENING_MIDDLEGAME, max_depth=6)
        search_module.ASPIRATION_WINDOWS = False
        full = run_search(OPENING_MIDDLEGAME, max_depth=6)
    finally:
        search_module.ASPIRATION_WINDOWS = saved
    assert aspirated.nodes < full.nodes
    assert aspirated.move == full.move


def test_aspiration_windows_keep_the_score_exact_without_the_window_heuristics() -> None:
    """The score, unlike the move, is only window-independent once the heuristics that read
    alpha are switched off.

    Delta pruning's floor, the futility bound, the null-move threshold and the late-move
    re-search test are all comparisons against alpha, so a narrower window prunes a different
    tree and the fail-soft score it returns can differ by a few centipawns from the full-window
    one. Principal variation search searches most moves with a null window, which makes those
    heuristics see much narrower alphas and turned a difference that used to be invisible in
    this position into a visible one (DECISIONS.md, PVS). Nothing there is unsound -- every
    bound is still a bound -- so the invariant worth pinning is this: with the window-dependent
    heuristics off, aspiration and the full window agree exactly, which is what says the
    aspiration re-searches themselves lose nothing.
    """
    flags = ("LATE_MOVE_REDUCTIONS", "NULL_MOVE_PRUNING", "FUTILITY_PRUNING", "DELTA_PRUNING")
    saved = {name: getattr(search_module, name) for name in flags}
    saved_windows = search_module.ASPIRATION_WINDOWS
    try:
        for name in flags:
            setattr(search_module, name, False)
        search_module.ASPIRATION_WINDOWS = True
        aspirated = run_search(OPENING_MIDDLEGAME, max_depth=5)
        search_module.ASPIRATION_WINDOWS = False
        full = run_search(OPENING_MIDDLEGAME, max_depth=5)
    finally:
        search_module.ASPIRATION_WINDOWS = saved_windows
        for name, value in saved.items():
            setattr(search_module, name, value)
    assert (aspirated.move, aspirated.score) == (full.move, full.score)


def test_aspiration_re_search_after_a_failure() -> None:
    # Force the first window to fail by making it absurdly narrow, and check the search still
    # returns the same exact result (widened, then full-window) rather than a bound.
    saved = search_module.ASPIRATION_WINDOW
    try:
        search_module.ASPIRATION_WINDOW = 1
        narrow = run_search(ROOK_ENDGAME, max_depth=7)
        search_module.ASPIRATION_WINDOW = 10_000
        wide = run_search(ROOK_ENDGAME, max_depth=7)
    finally:
        search_module.ASPIRATION_WINDOW = saved
    assert (narrow.move, narrow.score) == (wide.move, wide.score)


def test_futility_pruning_saves_nodes_but_not_in_mating_positions() -> None:
    assert nodes_with("FUTILITY_PRUNING", True, OPENING_MIDDLEGAME, 6) < nodes_with(
        "FUTILITY_PRUNING", False, OPENING_MIDDLEGAME, 6
    )
    # The mates are still found with every feature on (the default), at the same depths.
    mate_one = run_search(MATE_IN_ONE_WHITE, max_depth=2)
    mate_two = run_search(MATE_IN_TWO, max_depth=4)
    assert mate_one.move is not None and mate_one.move.uci() == "a1a8"
    assert mate_one.score == MATE_SCORE - 1
    assert mate_two.move is not None and mate_two.move.uci() == "h4h7"
    assert mate_two.score == MATE_SCORE - 3


def test_delta_pruning_saves_quiescence_nodes_and_keeps_the_hanging_queen() -> None:
    assert nodes_with("DELTA_PRUNING", True, BUSY_MIDDLEGAME, 4) < nodes_with(
        "DELTA_PRUNING", False, BUSY_MIDDLEGAME, 4
    )
    result = run_search(HANGING_QUEEN, max_depth=3)
    assert result.move is not None and result.move.uci() == "f3h4"
