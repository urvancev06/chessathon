"""Property tests for ``agent.get_move`` on the awkward positions of the brief's Stage 0 DoD.

Every case checks two invariants the platform enforces: the move is legal in the FEN it was asked
about, and the wall time from call to return stays under the hard budget the engine's own timing
formula gives for that clock (plus a fixed slack for the test process). Cases then add the
property they are named for. Each FEN is verified with python-chess inside the test, so a wrong
hand-built position fails loudly instead of testing nothing.

The engine modules are written in parallel with this file, so the whole module skips until
``mikhail_letal.search`` and ``mikhail_letal.timing`` import.

Game state. The platform starts one process per game, so module state never survives between
games. Here every case runs in one process, so an autouse fixture restores that condition before
each test through ``reset_agent``: a public ``agent.new_game()`` hook if the module offers one,
otherwise ``importlib.reload(agent)``, which re-runs the import and rebuilds the module state.
"""

import importlib
import time
from collections.abc import Iterator
from types import ModuleType

import chess
import pytest

pytest.importorskip("mikhail_letal.search")
timing = pytest.importorskip("mikhail_letal.timing")
import agent  # noqa: E402  (must follow the importorskip guards)

# Slack on top of the engine's hard budget: the test process, `chess.Board(fen)` and the assert
# itself all run inside the measured window.
BUDGET_SLACK_S = 0.2
FULL_CLOCK = 120_000  # the event clock
SHORT_CLOCK = 5_000  # a hard budget near 1.25 s: the tight, realistic check
PANIC_CLOCK = 1_400  # below the panic threshold: the fallback path, budget ~0 + slack
ENGINE_CLOCKS = (SHORT_CLOCK, PANIC_CLOCK)
ALL_CLOCKS = (FULL_CLOCK, SHORT_CLOCK, PANIC_CLOCK)

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
}

# Hand-built positions (each test re-checks the claimed property with python-chess).
FOUR_PROMOTIONS = "8/1P4k1/8/8/8/8/4K3/8 w - - 0 1"  # b8 is free: q, r, b and n all legal
QUEEN_WINS = "k7/6P1/8/p7/8/8/8/2K5 w - - 0 1"  # g8=Q+ wins material, no stalemate trick
CAPTURE_PROMOTION = "r3k3/1P6/8/8/8/8/8/4K3 w - - 0 1"  # bxa8 promotes with capture
KNIGHT_MATE = "7R/1Ppkn3/3b4/5P2/8/8/8/7K w - - 0 1"  # b8=N is the only mate in one
STALEMATE_TRAP = "7k/Q7/8/5K2/8/8/8/8 w - - 0 1"  # Qf7 stalemates; there is no mate in one
INSUFFICIENT = (
    "8/8/4k3/8/8/8/8/4KB2 w - - 0 1",  # K+B vs K
    "8/8/4k3/8/8/8/8/4KN2 b - - 0 1",  # K vs K+N, Black to move
    "4k3/8/8/8/8/8/8/4K3 w - - 0 1",  # bare kings
)
SINGLE_LEGAL = (
    "R5k1/6pp/8/8/8/8/8/6K1 b - - 0 1",  # Kf7 is the only way out of check
    "k7/8/8/8/8/8/1q6/K7 w - - 0 1",  # Kxb2 is the only legal move
)
MATE_IN_ONE = (
    "6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1",  # Ra8#
    "r5k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1",  # Ra1#
)
HALFMOVE_99 = "4k3/8/8/8/8/8/P7/3QK3 w - - 99 120"  # any quiet move lets the fifty-move claim in
SHUFFLE_START = (
    "6k1/5p1p/6p1/8/8/8/8/RN4K1 w - - 0 1"  # R+N vs three pawns: ahead, but no quick mate
)


def fen_after(moves: str) -> str:
    """FEN after a space-separated UCI line from the standard start; python-chess validates it."""
    board = chess.Board()
    for uci in moves.split():
        board.push_uci(uci)
    return board.fen()


def reset_agent() -> ModuleType:
    hook = getattr(agent, "new_game", None)
    if callable(hook):
        hook()
        return agent
    return importlib.reload(agent)


@pytest.fixture(autouse=True)
def fresh_game() -> Iterator[None]:
    reset_agent()
    yield


def own_moves_played() -> int:
    """How many moves the agent believes it has played this game; 0 when the module hides it."""
    state = getattr(agent, "STATE", None)
    return int(getattr(state, "own_moves", 0))


def hard_budget_s(time_left_ms: int) -> float:
    """The engine's own hard budget for this clock and game stage, plus the test slack."""
    return float(timing.budget(time_left_ms, own_moves_played()).hard_ms) / 1000.0 + BUDGET_SLACK_S


def ask(fen: str, time_left_ms: int) -> chess.Move:
    """Call get_move as the platform would and assert the two invariants every case shares."""
    board = chess.Board(fen)
    limit = hard_budget_s(time_left_ms)
    started = time.perf_counter()
    uci = agent.get_move(fen, time_left_ms)
    elapsed = time.perf_counter() - started
    assert isinstance(uci, str)
    move = chess.Move.from_uci(uci)
    assert move in board.legal_moves, f"{uci} is not legal in {fen}"
    assert elapsed <= limit, (
        f"{elapsed:.3f} s exceeds the hard budget {limit:.3f} s at time_left {time_left_ms} ms"
    )
    return move


def material_balance(board: chess.Board, colour: chess.Color) -> int:
    total = 0
    for piece_type, value in PIECE_VALUES.items():
        total += value * len(board.pieces(piece_type, colour))
        total -= value * len(board.pieces(piece_type, not colour))
    return total


def mating_moves(board: chess.Board) -> list[chess.Move]:
    found = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            found.append(move)
        board.pop()
    return found


def stalemating_moves(board: chess.Board) -> list[chess.Move]:
    found = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_stalemate():
            found.append(move)
        board.pop()
    return found


# --- promotions ---


@pytest.mark.parametrize("time_left_ms", ENGINE_CLOCKS)
def test_all_four_promotions_are_available(time_left_ms: int) -> None:
    board = chess.Board(FOUR_PROMOTIONS)
    promotions = {move.promotion for move in board.legal_moves if move.promotion}
    assert promotions == {chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT}
    ask(FOUR_PROMOTIONS, time_left_ms)


@pytest.mark.parametrize("time_left_ms", ALL_CLOCKS)
def test_promotes_to_a_queen_when_that_wins_material(time_left_ms: int) -> None:
    board = chess.Board(QUEEN_WINS)
    assert not board.is_insufficient_material()
    assert not mating_moves(board) and not stalemating_moves(board)
    assert chess.Move.from_uci("g7g8q") in board.legal_moves
    move = ask(QUEEN_WINS, time_left_ms)
    # Nothing else in the position gains material, and there is no stalemate to sidestep, so the
    # queen strictly dominates every other promotion piece.
    assert move.promotion == chess.QUEEN, f"expected a queen promotion, got {move.uci()}"


@pytest.mark.parametrize("time_left_ms", ENGINE_CLOCKS)
def test_capture_promotion(time_left_ms: int) -> None:
    board = chess.Board(CAPTURE_PROMOTION)
    capture = chess.Move.from_uci("b7a8q")
    assert capture in board.legal_moves and board.is_capture(capture)
    move = ask(CAPTURE_PROMOTION, time_left_ms)
    assert move.to_square == chess.A8 and move.promotion == chess.QUEEN, move.uci()


@pytest.mark.parametrize("time_left_ms", ALL_CLOCKS)
def test_underpromotion_to_a_knight_when_it_is_the_only_mate(time_left_ms: int) -> None:
    board = chess.Board(KNIGHT_MATE)
    assert mating_moves(board) == [chess.Move.from_uci("b7b8n")]
    move = ask(KNIGHT_MATE, time_left_ms)
    assert move == chess.Move.from_uci("b7b8n"), f"missed the knight-promotion mate: {move.uci()}"


# --- special moves ---


@pytest.mark.parametrize("time_left_ms", (FULL_CLOCK, PANIC_CLOCK))
def test_en_passant_available_for_white(time_left_ms: int) -> None:
    fen = fen_after("e2e4 c7c5 e4e5 d7d5")
    assert chess.Board(fen).has_legal_en_passant()
    ask(fen, time_left_ms)


@pytest.mark.parametrize("time_left_ms", ENGINE_CLOCKS)
def test_en_passant_available_for_black(time_left_ms: int) -> None:
    fen = fen_after("a2a3 d7d5 a3a4 d5d4 e2e4")
    assert chess.Board(fen).has_legal_en_passant()
    ask(fen, time_left_ms)


CASTLING_LINE = "g1f3 g8f6 e2e3 e7e6 d2d3 d7d6 f1e2 f8e7 b1c3 b8c6 d1d2 d8d7 b2b3 b7b6 c1b2 c8b7"


@pytest.mark.parametrize("time_left_ms", (FULL_CLOCK, PANIC_CLOCK))
def test_castling_both_ways_available_for_white(time_left_ms: int) -> None:
    fen = fen_after(CASTLING_LINE)
    board = chess.Board(fen)
    castles = {move.uci() for move in board.legal_moves if board.is_castling(move)}
    assert castles == {"e1g1", "e1c1"}
    ask(fen, time_left_ms)


@pytest.mark.parametrize("time_left_ms", ENGINE_CLOCKS)
def test_castling_both_ways_available_for_black(time_left_ms: int) -> None:
    fen = fen_after(CASTLING_LINE + " a2a3")
    board = chess.Board(fen)
    castles = {move.uci() for move in board.legal_moves if board.is_castling(move)}
    assert castles == {"e8g8", "e8c8"}
    ask(fen, time_left_ms)


# --- draws and dead positions ---


@pytest.mark.parametrize("time_left_ms", ALL_CLOCKS)
def test_stalemate_trap(time_left_ms: int) -> None:
    board = chess.Board(STALEMATE_TRAP)
    assert stalemating_moves(board) == [chess.Move.from_uci("a7f7")]
    assert not mating_moves(board)
    move = ask(STALEMATE_TRAP, time_left_ms)
    if time_left_ms != PANIC_CLOCK:
        # A queen up against a bare king, the engine must not throw the win away. The panic
        # fallback is a one-ply material rule and is only held to legality here.
        board.push(move)
        assert not board.is_stalemate(), f"{move.uci()} stalemates with a queen up"


@pytest.mark.parametrize("fen", INSUFFICIENT)
@pytest.mark.parametrize("time_left_ms", ENGINE_CLOCKS)
def test_insufficient_material_still_answers(fen: str, time_left_ms: int) -> None:
    # The referee ends such a game before asking, but the platform's validation may not: the agent
    # has to answer with a legal move rather than stall or crash on an evaluation of nothing.
    assert chess.Board(fen).is_insufficient_material()
    ask(fen, time_left_ms)


@pytest.mark.parametrize("fen", SINGLE_LEGAL)
@pytest.mark.parametrize("time_left_ms", ALL_CLOCKS)
def test_single_legal_move_is_returned(fen: str, time_left_ms: int) -> None:
    legal = list(chess.Board(fen).legal_moves)
    assert len(legal) == 1
    assert ask(fen, time_left_ms) == legal[0]


@pytest.mark.parametrize("fen", MATE_IN_ONE)
@pytest.mark.parametrize("time_left_ms", ALL_CLOCKS)
def test_mate_in_one_is_played(fen: str, time_left_ms: int) -> None:
    board = chess.Board(fen)
    mates = mating_moves(board)
    assert len(mates) == 1
    assert ask(fen, time_left_ms) == mates[0]


@pytest.mark.parametrize("time_left_ms", ALL_CLOCKS)
def test_halfmove_clock_99(time_left_ms: int) -> None:
    board = chess.Board(HALFMOVE_99)
    assert board.halfmove_clock == 99
    assert not mating_moves(board)
    quiet = chess.Move.from_uci("d1d2")
    board.push(quiet)
    assert board.is_fifty_moves(), "a quiet move must let the referee claim the fifty-move draw"
    board.pop()
    move = ask(HALFMOVE_99, time_left_ms)
    if time_left_ms != PANIC_CLOCK:
        # A queen up, the only way to keep the win is a move that resets the counter.
        assert board.is_zeroing(move), f"{move.uci()} walks into a fifty-move draw a queen up"


# --- game history: repetition and the fresh-game reset ---


class Referee:
    """The platform's side of the conversation: keeps the true board and feeds FENs to the agent."""

    def __init__(self, fen: str) -> None:
        self.board = chess.Board(fen)
        self.visits: dict[object, int] = {self.key(): 1}

    def key(self) -> object:
        return self.board._transposition_key()

    def push(self, move: chess.Move) -> None:
        self.board.push(move)
        self.visits[self.key()] = self.visits.get(self.key(), 0) + 1

    def engine_moves(self, time_left_ms: int) -> chess.Move:
        move = ask(self.board.fen(), time_left_ms)
        self.push(move)
        return move

    def opponent_shuffles(self) -> chess.Move:
        """A deterministic opponent that seeks repetition: reversible moves, most-visited first."""

        def preference(move: chess.Move) -> tuple[int, int, str]:
            self.board.push(move)
            visits = self.visits.get(self.key(), 0)
            self.board.pop()
            return (0 if self.board.is_zeroing(move) else 1, visits, move.uci())

        # Reversible before irreversible, then the position seen most often, then UCI order:
        # the sort is descending on the first two keys and ascending on the last.
        candidates = sorted(self.board.legal_moves, key=lambda move: move.uci())
        move = max(candidates, key=lambda move: preference(move)[:2])
        self.push(move)
        return move


def test_engine_does_not_repeat_when_clearly_ahead() -> None:
    """A scripted shuffle through the module's real state.

    The opponent keeps steering back into positions already seen. Positions the engine creates
    are its responsibility: none of them may be a third occurrence while it is clearly ahead, and
    the game must not end drawn by repetition. Mating within the run is a fine way to pass.
    """
    referee = Referee(SHUFFLE_START)
    engine = referee.board.turn
    assert material_balance(referee.board, engine) >= 300
    calls = 0
    for _ in range(10):
        if referee.board.is_game_over() or referee.board.is_repetition(3):
            break
        move = referee.engine_moves(SHORT_CLOCK)
        calls += 1
        assert not referee.board.is_repetition(3), (
            f"{move.uci()} created a third occurrence while ahead; line {referee.board.move_stack}"
        )
        if referee.board.is_game_over():
            break
        referee.opponent_shuffles()
    assert calls >= 1
    assert not referee.board.is_repetition(3)
    assert not referee.board.is_stalemate()
    assert material_balance(referee.board, engine) >= 300, "the engine lost material shuffling"

    # The module's history must have tracked the whole game from the first FEN: one entry per
    # observed position plus one per own move (docs/DESIGN.md, GameState). Checked only when the
    # module exposes the state, since the platform contract does not require it to.
    state = getattr(agent, "STATE", None)
    if state is not None:
        assert state.own_moves == calls
        history = getattr(state, "history", None)
        if history is not None:
            assert sum(history.values()) == 2 * calls


def test_fresh_game_state_is_not_confused_by_the_previous_game() -> None:
    # Game one: two engine moves from the standard start, with a scripted opponent in between.
    first = Referee(chess.STARTING_FEN)
    first.engine_moves(SHORT_CLOCK)
    first.opponent_shuffles()
    first.engine_moves(SHORT_CLOCK)
    # Craft game two's first FEN to be one legal move on from where game one stopped: exactly the
    # position a stale history would mistake for the opponent's reply in the old game.
    continuation = first.board.copy()
    continuation.push(next(iter(continuation.legal_moves)))
    reset_agent()
    assert own_moves_played() == 0
    second = Referee(continuation.fen())
    second.engine_moves(PANIC_CLOCK)
    second.opponent_shuffles()
    second.engine_moves(SHORT_CLOCK)
    state = getattr(agent, "STATE", None)
    if state is not None:
        assert own_moves_played() == 2, "module state leaked from the previous game"
        assert int(getattr(state, "desyncs", 0)) == 0
