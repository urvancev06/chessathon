"""Mikhail LeTal: the submission entrypoint. The platform imports this file and calls get_move.

This file is deliberately small. It is a safety wrapper around the engine in ``mikhail_letal``:
whatever happens inside the search (a bug, a slow move, a bad result), ``get_move`` never raises
and never returns an illegal move, because either of those loses the game on the spot. The engine
itself (search, evaluation, time management, position history) lives in the package; here we only
build the board, decide how much time to spend, call the engine, and check its answer.

The engine underneath is compiled: ``mikhail_letal.fastsearch`` searches its own 0x88 board
(``fastboard``) with numba, about fourteen times as many nodes a second as the searcher in
``search.py``, which stays in the repository as the specification the compiled port is checked
against. That changes nothing here. python-chess is still the legality oracle -- the board is
built with it, the move that comes back is looked up in its ``legal_moves``, and anything that
fails that test is replaced by the fallback -- so the safety guarantees do not depend on the
compiled code being right.
"""

import contextlib
import os
from time import perf_counter

_IMPORT_STARTED = perf_counter()
# One core, one thread: numeric libraries that spawn worker threads lose time here. Setting these
# before any other import (numba arrives in Stage 1) is the only way to make them stick.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("NUMBA_NUM_THREADS", "1")

# These imports follow the timer and the environment settings on purpose, so the load time we
# print includes them; hence the E402 waivers.
import chess  # noqa: E402

from mikhail_letal import (  # noqa: E402
    ENGINE_NAME,
    __version__,
    fastboard,
    fasteval,
    fastsearch,
)
from mikhail_letal.fallback import fallback_move  # noqa: E402
from mikhail_letal.fastsearch import FastEngine  # noqa: E402
from mikhail_letal.gamestate import GameState  # noqa: E402
from mikhail_letal.search import GAME_PLY_CAP  # noqa: E402
from mikhail_letal.timing import DEFAULT_PARAMS, budget  # noqa: E402

# Module state lives for one game: the platform starts a fresh process per game and keeps it alive
# (suspended while the opponent thinks) between our moves.
STATE = GameState()  # every position seen this game, so the search knows about repetitions
ENGINE = FastEngine()  # compiled iterative-deepening alpha-beta; its table persists all game
PARAMS = DEFAULT_PARAMS  # every time-management constant, in one place (mikhail_letal/timing.py)


def _say(text: str) -> None:
    """Print one short log line. The log keeps only its first and last 4 KB, and a print that
    fails must never cost a game, so lines are capped at 120 bytes and errors are swallowed.

    ``flush=True`` matters: the runner points our stdout at a pipe, which Python block-buffers,
    and the process is killed when the game ends. Without the flush, a game's worth of lines
    would sit in the buffer and never reach the log (observed in the local harness).
    """
    with contextlib.suppress(Exception):
        print(text[:120], flush=True)


def get_move(fen: str, time_left_ms: int) -> str:
    """Return a legal move in UCI notation (``e2e4``, or ``e7e8q`` for a promotion).

    ``fen`` is the position to move in; our colour is the side to move. ``time_left_ms`` is our
    clock before this move; the 500 ms increment lands after it. Elapsed time is measured from
    this line, so board construction and bookkeeping count against the budget, as they do on the
    platform's clock.
    """
    t0 = perf_counter()
    move: chess.Move | None = None
    depth = seldepth = nodes = nps = 0
    soft_ms = hard_ms = 0.0
    try:
        board = chess.Board(fen)
        if not STATE.observe(board):
            _say("desync: position not reachable from our last move; history restarted")
            ENGINE.new_game()  # its stored draws may rest on the history just discarded
        legal = list(board.legal_moves)
        if len(legal) == 1:
            move = legal[0]  # forced: nothing to think about (still validated below)
        elif time_left_ms < PARAMS.panic_ms:
            move = fallback_move(board, legal)  # almost out of time: a legal move, instantly
        elif legal:  # an empty list is impossible (the referee ends the game first)
            plan = budget(
                time_left_ms,
                STATE.own_moves,
                PARAMS,
                # A win must be forced before the referee's draws land: fewer moves to share
                # the clock over when either deadline is close (mikhail_letal/timing.py).
                plies_to_cap=GAME_PLY_CAP - board.ply(),
                fifty_move_room=_fifty_move_room(board),
            )
            soft_ms, hard_ms = plan.soft_ms, plan.hard_ms
            result = ENGINE.search(
                board,
                STATE.fast_history,
                # Do not start another depth once this share of the soft budget has elapsed:
                # the next iteration costs several times the previous one.
                soft_deadline=t0 + PARAMS.next_iteration_fraction * soft_ms / 1000.0,
                # Abort mid-iteration here, whatever the state of the search.
                hard_deadline=t0 + hard_ms / 1000.0,
            )
            depth, seldepth, nodes = result.depth, result.seldepth, result.nodes
            # Node rate over the search's own clock: the number calibration compares.
            nps = int(nodes / result.elapsed) if result.elapsed > 0 else 0
            if result.move in legal:
                move = result.move
            else:
                _say(f"search returned {result.move}, not legal here; using fallback")
                move = fallback_move(board, legal)
    except Exception as exc:  # anything at all: the fallback plays instead
        _say(f"error in get_move: {type(exc).__name__}: {exc}")
        move = None

    uci = _validated(fen, move)
    _check_signatures()  # a jitted function compiled on the clock would cost a move; say so
    elapsed_ms = (perf_counter() - t0) * 1000.0
    _say(
        f"m {uci} d {depth}/{seldepth} n {nodes} nps {nps} t {elapsed_ms:.0f}"
        f" s {soft_ms:.0f} h {hard_ms:.0f} c {time_left_ms}"
    )
    return uci


def _fifty_move_room(board: chess.Board) -> int | None:
    """Plies left before the fifty-move draw, but only in a mop-up (no pawns, one side a bare
    king), where nothing but the mate itself can reset the halfmove clock. Elsewhere ``None``:
    a capture or a pawn move resets the clock in the normal course of play."""
    if board.pawns:
        return None
    kings = board.kings
    if board.occupied_co[chess.WHITE] & ~kings and board.occupied_co[chess.BLACK] & ~kings:
        return None
    return 100 - board.halfmove_clock


def _validated(fen: str, move: chess.Move | None) -> str:
    """The last line of defence: check the move against a fresh board built from the FEN.

    The UCI string is parsed back and looked up in the fresh board's legal moves, exactly as the
    referee will do it. Anything that fails that test is replaced by the fallback move. The
    chosen move is then recorded in the game history so the next call knows where we left off.
    """
    uci = "0000"  # only if the position has no legal moves, which the referee never sends
    try:
        fresh = chess.Board(fen)
        legal = list(fresh.legal_moves)
        if legal:
            if move is None or chess.Move.from_uci(move.uci()) not in legal:
                if move is not None:
                    _say(f"guard rejected {move.uci()}; using fallback")
                move = fallback_move(fresh, legal)
            uci = move.uci()
            fresh.push(move)
            STATE.record_own_move(fresh)
    except Exception as exc:  # a bookkeeping failure must not lose the game
        _say(f"error in final guard: {type(exc).__name__}: {exc}")
    return uci


# Every compiled function of the engine, by module. numba compiles a function the first time it
# is called with a given set of argument types; on the platform that first call has to happen
# here, inside the 90-second import budget, and never on the clock, where it would cost a move.
_JITTED = (
    (fastboard, fastboard.JITTED),
    (fasteval, fasteval.JITTED),
    (fastsearch, fastsearch.JITTED),
)


def _signatures() -> dict[str, int]:
    """How many compiled specialisations each jitted function has right now."""
    return {
        f"{module.__name__}.{name}": len(getattr(module, name).signatures)
        for module, names in _JITTED
        for name in names
    }


def _warm_up() -> dict[str, int]:
    """Compile the whole engine and run a real search, so that nothing compiles on the clock.

    Wrapped, because a failure here must not break the import: an engine that has not warmed up
    is slow, an agent that fails to import loses every game. The table is cleared afterwards, so
    the real game begins from a fresh searcher.
    """
    try:
        fastsearch.warm_up(ENGINE)
        ENGINE.new_game()
        missing = [name for name, count in _signatures().items() if count == 0]
        if missing:  # a function left to compile on the clock: say so in the log
            _say(f"warm-up missed {len(missing)}: {missing[0]}")
    except Exception as exc:  # see the docstring
        _say(f"warm-up failed: {type(exc).__name__}: {exc}")
    return _signatures()


# The gate this pins: after the warm-up every jitted function has exactly the specialisations it
# will ever have. ``get_move`` re-checks the counts once a move (a few dozen attribute reads, tens
# of microseconds) and says so in the log if one has changed, which is how a missed warm-up shows
# up in a real game rather than as a mysteriously slow move.
_WARM_SIGNATURES = _warm_up()


def _check_signatures() -> None:
    """Compare the compiled specialisations against the warm-up's, and log any that appeared."""
    with contextlib.suppress(Exception):
        for name, count in _signatures().items():
            if count != _WARM_SIGNATURES.get(name):
                _say(f"jit: {name} now has {count} signatures, not {_WARM_SIGNATURES[name]}")


_say(
    f"init {(perf_counter() - _IMPORT_STARTED) * 1000:.0f} ms {ENGINE_NAME} {__version__}"
    f" jit {fastboard.WARM_UP_SECONDS + fasteval.WARM_UP_SECONDS + fastsearch.WARM_UP_SECONDS:.1f}s"
    f" nps {ENGINE.node_rate:.0f}"
)
