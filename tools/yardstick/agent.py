"""Yardstick: a harness-compatible agent that plays a UCI engine's moves (Stockfish, locally).

This is a measuring instrument, never a submission (brief, sections 2.2 and 8.2). The engine
binary lives outside the repository and is found through ``YARDSTICK_ENGINE``; this wrapper only
drives it over UCI so that ``harness.referee`` can play our agent against a known strength. It
must never be zipped, never influence a move of our engine, and nobody reads the engine's source.

Contract with the harness: ``get_move(fen, time_left_ms) -> uci``. The engine is opened once at
import so that its start-up lands in the 90 s init budget rather than on the clock, and the
harness suspends and kills the whole process group, so the engine child is frozen and reaped
together with this process.

Environment (all optional except that some engine must be found):

    YARDSTICK_ENGINE       path to the UCI binary; else ~/.local/opt/stockfish/stockfish, else
                           whatever ``stockfish`` resolves to on PATH
    YARDSTICK_ELO          UCI_LimitStrength + UCI_Elo (Stockfish accepts 1320..3190); unset means
                           full strength
    YARDSTICK_MOVETIME_MS  fixed time per move; unset means play on the clock the harness hands us
    YARDSTICK_INC_MS       the increment told to the engine when playing on the clock (default 500)
"""

from __future__ import annotations

import atexit
import contextlib
import os
import shutil
import sys
import threading
import time
from pathlib import Path

import chess
import chess.engine

DEFAULT_ENGINE_RELATIVE = Path(".local") / "opt" / "stockfish" / "stockfish"
DEFAULT_INC_MS = 500
ELO_RANGE = (1320, 3190)
# Fixed engine settings, brief 8.2: one thread like the platform, a small table, and a move
# overhead that absorbs the pipe round trip so the yardstick itself never flags.
OPTIONS: dict[str, int] = {"Threads": 1, "Hash": 16, "Move Overhead": 100}


def log(message: str) -> None:
    # The harness runner points file descriptor 1 at stderr before importing us, so print is
    # safe; stderr is the explicit choice anyway in case the module is imported elsewhere.
    print(message, file=sys.stderr, flush=True)


def home_directories() -> list[Path]:
    """``$HOME`` and the account's real home. The harness (like the platform) points ``HOME`` at
    a scratch directory for every agent, so the conventional install path has to be looked up
    through the password database as well, or the yardstick would never find it under a match."""
    homes = [Path.home()]
    try:
        import pwd  # POSIX only; imported here so the module still loads elsewhere

        homes.append(Path(pwd.getpwuid(os.getuid()).pw_dir))
    except (ImportError, KeyError, OSError):
        pass
    return homes


def default_engines() -> list[Path]:
    return [home / DEFAULT_ENGINE_RELATIVE for home in home_directories()]


def resolve_engine() -> Path | None:
    """The binary: ``YARDSTICK_ENGINE``, then the conventional install path, then PATH."""
    candidates: list[Path] = []
    configured = os.environ.get("YARDSTICK_ENGINE", "").strip()
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend(default_engines())
    found = shutil.which("stockfish")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _int_env(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        log(f"yardstick: {name}={raw!r} is not an integer; ignored")
        return None


def _elo() -> int | None:
    elo = _int_env("YARDSTICK_ELO")
    if elo is None:
        return None
    low, high = ELO_RANGE
    clamped = min(max(elo, low), high)
    if clamped != elo:
        log(f"yardstick: YARDSTICK_ELO={elo} is outside {low}..{high}; using {clamped}")
    return clamped


ELO = _elo()
MOVETIME_MS = _int_env("YARDSTICK_MOVETIME_MS")
INC_MS = _int_env("YARDSTICK_INC_MS") or DEFAULT_INC_MS
LEVEL = "full" if ELO is None else str(ELO)


def _open() -> chess.engine.SimpleEngine | None:
    path = resolve_engine()
    if path is None:
        log(
            "yardstick: no UCI engine found; set YARDSTICK_ENGINE or install Stockfish at "
            f"{default_engines()[-1]}. Every move will be the first legal move."
        )
        return None
    try:
        engine = chess.engine.SimpleEngine.popen_uci(str(path))
    except Exception as exc:  # a broken binary must degrade to fallback moves, never crash
        log(f"yardstick: could not start {path}: {type(exc).__name__}: {exc}")
        return None
    options: dict[str, int | bool] = dict(OPTIONS)
    if ELO is not None:
        options.update({"UCI_LimitStrength": True, "UCI_Elo": ELO})
    try:
        engine.configure(options)
    except Exception as exc:  # e.g. an engine without UCI_Elo: play it as it is, but say so
        log(f"yardstick: could not set {options}: {type(exc).__name__}: {exc}")
    name = engine.id.get("name", path.name)
    log(f"yardstick: {name} at {path}, level {LEVEL}, options {options}")
    return engine


def _quit() -> None:
    if ENGINE is None:
        return
    with contextlib.suppress(Exception):  # already gone (the harness killed the group)
        ENGINE.quit()
    with contextlib.suppress(Exception):
        ENGINE.close()


ENGINE = _open()
# python-chess drives the engine from a non-daemon thread, and the interpreter joins those threads
# *before* it runs atexit callbacks, so quitting from atexit alone deadlocks a normal exit (the
# harness SIGKILLs agents, so only a direct run would notice). threading's own pre-join hook,
# which concurrent.futures uses for the same reason, runs early enough; atexit is the fallback.
_register_early: object = getattr(threading, "_register_atexit", None)
if callable(_register_early):
    _register_early(_quit)
else:
    atexit.register(_quit)


def _limit(time_left_ms: int) -> chess.engine.Limit:
    """Fixed movetime when configured, else the clock we know: our own, told for both sides."""
    if MOVETIME_MS is not None:
        return chess.engine.Limit(time=max(MOVETIME_MS, 1) / 1000.0)
    seconds = max(time_left_ms, 0) / 1000.0
    increment = INC_MS / 1000.0
    # Only our own clock is in the request; the engine's time manager needs a number for the
    # opponent too, and giving it ours is neutral.
    return chess.engine.Limit(
        white_clock=seconds, black_clock=seconds, white_inc=increment, black_inc=increment
    )


def get_move(fen: str, time_left_ms: int) -> str:
    started = time.perf_counter()
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        log(f"yardstick: bad FEN {fen!r}: {exc}")
        return "0000"
    legal = sorted(board.legal_moves, key=lambda candidate: candidate.uci())
    if not legal:
        return "0000"
    move = legal[0]  # the fallback: any legal move keeps the game (and the measurement) alive
    if ENGINE is not None:
        try:
            played = ENGINE.play(board, _limit(time_left_ms)).move
        except Exception as exc:  # engine died or timed out: never raise, play the fallback
            log(f"yardstick: engine failed: {type(exc).__name__}: {exc}; playing {move.uci()}")
        else:
            if played is not None and played in board.legal_moves:
                move = played
            else:
                log(f"yardstick: engine returned {played}; playing {move.uci()}")
    spent_ms = (time.perf_counter() - started) * 1000.0
    log(f"yardstick {LEVEL} {move.uci()} {spent_ms:.0f}")
    return move.uci()
