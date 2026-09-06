"""Game and session logic for the local web app.

Standard library plus ``chess``. The harness is used strictly as a library (``harness.sandbox``
runs the agent process, ``harness.rules`` holds the event constants, ``harness.referee`` the result
vocabulary) and is never modified: the move loop here mirrors ``harness.referee._play`` step for
step so a game in the browser is refereed the way a rated game is.

Concurrency model. A :class:`Registry` owns every :class:`Game` behind one lock. Each game has a
state lock (board, clocks, move list, status) that is held only briefly, and each :class:`Seat`
(one agent process) has its own lock so no two threads ever speak to the same process at once.
Engine calls happen on background threads, never inside an HTTP request; requests only read
snapshots or set flags, so the server keeps answering while an engine thinks for two minutes.
"""

from __future__ import annotations

import ast
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import chess
import chess.pgn

from harness import sandbox
from harness.referee import FAILED_TERMINATIONS, RESULT_HEADERS
from harness.rules import (
    BASE_MS,
    INCREMENT_MS,
    INIT_BUDGET_S,
    OPENINGS,
    PLY_CAP,
    STDERR_HEAD,
    STDERR_TAIL,
    STDOUT_CAP,
    WATCHDOG_GRACE_MS,
)
from harness.sandbox import AgentFailure

ROOT = Path(__file__).resolve().parents[2]
ENGINE_NAME = "Mikhail LeTal"
TAGLINE = (
    "Chess engine for AI Chessathon 2026. Own search, evaluation and time management on "
    "python-chess. Named after Mikhail Tal."
)

Colour = Literal["white", "black"]
Result = Literal["white", "black", "draw", "void"]
Kind = Literal["play", "spectate"]
Status = Literal["starting", "running", "finished"]

BASELINES = ("random", "greedy", "minimax", "numba")
TIME_CONTROLS: tuple[tuple[str, int, int], ...] = (
    ("Platform 120 s + 0.5 s", BASE_MS, INCREMENT_MS),
    ("60 s + 0.5 s", 60_000, 500),
    ("30 s + 0.3 s", 30_000, 300),
    ("10 s + 0.1 s", 10_000, 100),
    ("3 s + 0.05 s", 3_000, 50),
)
MAX_BASE_MS = 3_600_000
MAX_INCREMENT_MS = 60_000
MAX_HUMAN_SPENT_MS = 7 * 24 * 3_600_000
LOG_GRACE_S = 0.1
LOG_POLL_S = 0.01
# Tokens the engine prints per move (docs/DESIGN.md, "Determinism and logging"). Anything else is
# still parsed as a key/value pair and shown raw.
KNOWN_LOG_KEYS: dict[str, str] = {
    "m": "move",
    "d": "depth",
    "n": "nodes",
    "nps": "nps",
    "t": "time_ms",
    "s": "soft_ms",
    "h": "hard_ms",
    "c": "clock_ms",
}
# Terminations the referee can produce plus the ones only a playground has.
TERMINATIONS: dict[str, str] = {
    "checkmate": "Checkmate",
    "stalemate": "Stalemate",
    "insufficient_material": "Draw by insufficient material",
    "seventyfive_moves": "Draw by the seventy-five move rule",
    "fivefold_repetition": "Draw by fivefold repetition",
    "threefold_repetition": "Draw by threefold repetition",
    "fifty_moves": "Draw by the fifty move rule",
    "ply_cap": "Draw at the ply cap",
    "flag": "Flag fall",
    "illegal": "Illegal move",
    "crash": "Agent crashed",
    "init": "Agent failed to start within the init budget",
    "both_failed": "Both agents failed to start",
    "resignation": "Resignation",
    "aborted": "Stopped",
    "abandoned": "Abandoned (idle timeout)",
    "error": "Internal error",
}


class GameError(Exception):
    """A request the game logic rejects; carries the HTTP status the server should answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# --------------------------------------------------------------------------------------------
# Engine directories


@dataclass(frozen=True)
class EngineInfo:
    path: str
    label: str
    short: str
    kind: Literal["engine", "version", "baseline"]

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "label": self.label, "short": self.short, "kind": self.kind}


def list_engines(root: Path) -> list[EngineInfo]:
    """The working tree, every frozen ``versions/*`` build, then the four baselines."""
    engines: list[EngineInfo] = []
    if (root / "agent.py").is_file():
        engines.append(EngineInfo(".", f"{ENGINE_NAME} (working tree)", "letal", "engine"))
    versions = root / "versions"
    if versions.is_dir():
        for directory in sorted(versions.iterdir()):
            if (directory / "agent.py").is_file():
                engines.append(
                    EngineInfo(
                        f"versions/{directory.name}",
                        f"{ENGINE_NAME} {directory.name}",
                        f"letal-{directory.name}",
                        "version",
                    )
                )
    for name in BASELINES:
        if (root / "baselines" / name / "agent.py").is_file():
            engines.append(EngineInfo(f"baselines/{name}", f"Baseline: {name}", name, "baseline"))
    return engines


def resolve_engine(root: Path, spec: str) -> Path:
    """The agent directory for ``spec``; it must sit inside the repo and contain ``agent.py``."""
    if not isinstance(spec, str) or not spec.strip() or "\x00" in spec:
        raise GameError(400, "engine directory is missing")
    spec = spec.strip()
    if Path(spec).is_absolute():
        raise GameError(400, "engine directory must be relative to the repository root")
    repo = root.resolve()
    candidate = (repo / spec).resolve()
    if candidate != repo and repo not in candidate.parents:
        raise GameError(400, f"engine directory {spec!r} is outside the repository")
    if not (candidate / "agent.py").is_file():
        raise GameError(400, f"{spec!r} has no agent.py")
    return candidate


def engine_label(root: Path, spec: str) -> EngineInfo:
    spec = spec.strip()
    for info in list_engines(root):
        if info.path == spec or Path(info.path) == Path(spec):
            return info
    resolved = resolve_engine(root, spec)
    return EngineInfo(spec, resolved.name, resolved.name, "engine")


# --------------------------------------------------------------------------------------------
# Engine log lines


@dataclass
class LogRecord:
    """What one engine printed to stderr while it produced one move."""

    ply: int
    spent_ms: float
    raw: list[str]
    fields: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "ply": self.ply,
            "spent_ms": round(self.spent_ms, 1),
            "raw": self.raw,
            "fields": self.fields,
            "known": {
                KNOWN_LOG_KEYS[key]: value
                for key, value in self.fields.items()
                if key in KNOWN_LOG_KEYS
            },
            "unknown": {
                key: value for key, value in self.fields.items() if key not in KNOWN_LOG_KEYS
            },
        }


def parse_log_line(line: str) -> dict[str, str]:
    """``m e2e4 d 5/9 n 31240 ...`` as key/value pairs; a dangling odd token lands in ``_tail``."""
    tokens = line.split()
    fields: dict[str, str] = {}
    index = 0
    while index + 1 < len(tokens):
        fields[tokens[index]] = tokens[index + 1]
        index += 2
    if index < len(tokens):
        fields["_tail"] = tokens[index]
    return fields


def new_output(before: str, after: str) -> str:
    """The text appended to an agent's kept output since ``before`` was read.

    The sandbox keeps the first 4 KB and the last 4 KB of stderr, so once the middle is being
    dropped ``after`` no longer starts with ``before``; then the end of ``before`` is used as an
    anchor inside the sliding tail.
    """
    if after.startswith(before):
        return after[len(before) :]
    anchor = before[-256:]
    if anchor:
        position = after.rfind(anchor)
        if position >= 0:
            return after[position + len(anchor) :]
    return after


def make_record(ply: int, spent_ms: float, text: str) -> LogRecord:
    lines = [line for line in text.splitlines() if line.strip()]
    fields: dict[str, str] = {}
    for line in reversed(lines):
        if line.split()[:1] == ["m"]:
            fields = parse_log_line(line)
            break
    return LogRecord(ply=ply, spent_ms=spent_ms, raw=lines, fields=fields)


def _kept_output(agent: sandbox.Agent) -> str:
    # Agent._output() is the sandbox's own view of the stderr it kept (first 4 KB + last 4 KB), the
    # same text harness.play prints after a game. Reading it from a development tool is the point
    # of keeping it; the referee's contract with the agent is untouched. Agent._drain() pulls the
    # chunks the reader threads have queued since the last protocol line was consumed, without
    # which a log line written just before the move reply would only show up after the next move.
    agent._drain()
    return agent._output()


def _await_output(agent: sandbox.Agent, before: str, grace_s: float = LOG_GRACE_S) -> str:
    """Poll briefly for the stderr line that accompanies a reply; stderr and stdout are separate
    pipes, so the log line may reach our reader thread a few milliseconds after the move did."""
    deadline = time.monotonic() + grace_s
    while True:
        text = new_output(before, _kept_output(agent))
        if "\n" in text or time.monotonic() >= deadline:
            return text
        time.sleep(LOG_POLL_S)


# --------------------------------------------------------------------------------------------
# One agent process


class Seat:
    """One engine process, driven exactly as harness.referee drives it."""

    def __init__(self, root: Path, spec: str, seed: int) -> None:
        self.path = resolve_engine(root, spec)
        self.info = engine_label(root, spec)
        self.agent = sandbox.local(self.path, seed)
        self.init_ms: float | None = None
        self.init_failure: str | None = None
        self.init_log = ""
        self.records: list[LogRecord] = []
        self._lock = threading.Lock()
        self._started = False
        self._stopped = False
        self._ever_logged = False

    @property
    def alive(self) -> bool:
        return self._started and not self._stopped

    def start(self) -> str | None:
        """Start and suspend the agent like ``referee._start``; return the failure reason if any."""
        with self._lock:
            self._started = True
            began = time.monotonic()
            try:
                self.agent.start(INIT_BUDGET_S)
            except AgentFailure as failure:
                self.init_ms = (time.monotonic() - began) * 1000.0
                self.init_failure = failure.reason
                return failure.reason
            self.init_ms = (time.monotonic() - began) * 1000.0
            self.agent.suspend()
            self.init_log = _await_output(self.agent, "").strip()
            self._ever_logged = bool(self.init_log)
            return None

    def think(self, fen: str, time_left_ms: int, ply: int) -> tuple[str | None, float, str | None]:
        """Resume, ask for a move, time it on wall time, suspend.

        Returns ``(uci, spent_ms, failure)`` where ``failure`` is the referee's reason or None.
        """
        with self._lock:
            before = _kept_output(self.agent)
            self.agent.resume()
            started_at = time.monotonic()
            uci: str | None = None
            failure: str | None = None
            try:
                uci = self.agent.move(fen, time_left_ms)
            except AgentFailure as caught:
                failure = caught.reason
            spent_ms = (time.monotonic() - started_at) * 1000.0
            self.agent.suspend()  # After the timer, so the freeze is never on the clock.
            # A silent agent (every baseline) gets the grace twice; after that there is nothing
            # to wait for and a long engine-vs-engine game should not pay 100 ms a move for it.
            grace = LOG_GRACE_S if self._ever_logged or len(self.records) < 2 else 0.0
            text = _await_output(self.agent, before, grace)
            self._ever_logged = self._ever_logged or bool(text.strip())
            self.records.append(make_record(ply, spent_ms, text))
            return uci, spent_ms, failure

    def kill(self) -> None:
        """Terminate the process now, from any thread, without touching the agent's queues.

        ``Agent.stop()`` drains the chunk queue, which races with a ``move()`` in flight on the game
        thread and can leave that call waiting for the whole clock. A bare SIGKILL makes the reader
        threads hit EOF, so ``move()`` raises ``AgentFailure`` at once and the game thread then runs
        ``stop()`` itself.
        """
        process = self.agent._process
        if process is None:
            return
        try:
            if sandbox.SUSPENDS:
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (ProcessLookupError, PermissionError):
            return

    def stop(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            try:
                self.agent.stop()
            except Exception:  # a dead process must never take the server down
                return

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": "engine",
            "path": self.info.path,
            "label": self.info.label,
            "short": self.info.short,
            "alive": self.alive,
            "init_ms": None if self.init_ms is None else round(self.init_ms, 1),
            "init_budget_ms": int(INIT_BUDGET_S * 1000),
            "init_ok": self.init_failure is None and self.init_ms is not None,
            "init_failure": self.init_failure,
            "init_log": self.init_log,
            "log": [record.to_dict() for record in self.records],
        }


# --------------------------------------------------------------------------------------------
# Games


@dataclass
class MoveRecord:
    ply: int
    san: str
    uci: str
    by: Colour
    spent_ms: float
    clock_ms: float
    white_ms: float
    black_ms: float
    fen: str
    log: LogRecord | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ply": self.ply,
            "san": self.san,
            "uci": self.uci,
            "by": self.by,
            "spent_ms": round(self.spent_ms, 1),
            "clock_ms": round(self.clock_ms, 1),
            "white_ms": round(self.white_ms, 1),
            "black_ms": round(self.black_ms, 1),
            "fen": self.fen,
            "log": None if self.log is None else self.log.to_dict(),
        }


@dataclass(frozen=True)
class GameSpec:
    kind: Kind
    white: str | None  # engine directory, or None for the human
    black: str | None
    base_ms: int
    increment_ms: int
    start_fen: str
    ply_cap: int
    opening: str | None

    @property
    def human(self) -> Colour | None:
        if self.kind != "play":
            return None
        return "white" if self.white is None else "black"


def _side(colour: chess.Color) -> Colour:
    return "white" if colour == chess.WHITE else "black"


def _decide(finish: chess.Outcome) -> Result:
    return "draw" if finish.winner is None else _side(finish.winner)


def _flagged(board: chess.Board, mover: chess.Color) -> Result:
    return "draw" if board.has_insufficient_material(not mover) else _side(not mover)


def _legal_move(board: chess.Board, uci: str) -> chess.Move | None:
    try:
        move = chess.Move.from_uci(uci)
    except chess.InvalidMoveError:
        return None
    return move if move in board.legal_moves else None


def validate_fen(fen: str, ply_cap: int = PLY_CAP) -> chess.Board:
    """A board for ``fen`` or a GameError explaining why the position cannot start a game."""
    try:
        board = chess.Board(fen.strip())
    except ValueError as exc:
        raise GameError(400, f"invalid FEN: {exc}") from None
    status = board.status()
    if status != chess.STATUS_VALID:
        problems = [
            str(flag.name).lower().replace("_", " ") for flag in chess.Status if flag & status
        ]
        raise GameError(400, "illegal position: " + ", ".join(problems))
    if board.is_game_over():
        raise GameError(400, "the position is already over")
    if board.ply() >= ply_cap:
        raise GameError(400, f"the position is already at ply {board.ply()}, past the cap")
    return board


def _slug(text: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return slug or "agent"


class Game:
    """One game, human vs engine or engine vs engine, refereed like ``harness.referee``."""

    def __init__(self, registry: Registry, spec: GameSpec) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.registry = registry
        self.spec = spec
        self.kind: Kind = spec.kind
        self.human: Colour | None = spec.human
        self.board = chess.Board(spec.start_fen)
        self.start_fen = self.board.fen()
        self.moves: list[MoveRecord] = []
        self.clock: dict[chess.Color, float] = {
            chess.WHITE: float(spec.base_ms),
            chess.BLACK: float(spec.base_ms),
        }
        self.status: Status = "starting"
        self.result: Result | None = None
        self.termination: str | None = None
        self.error: str | None = None
        self.thinking = False
        self.thinking_since: float | None = None
        self.pgn_path: Path | None = None
        self.created_at = time.time()
        self.updated_at = self.created_at
        self._lock = threading.RLock()
        self._stop_requested = False
        self._stop_reason = "aborted"
        self._stop_result: Result = "void"
        self._slots_released = False
        self._finishing = False
        seed = int.from_bytes(os.urandom(4), "big") % 1_000_000
        self.seats: dict[chess.Color, Seat] = {}
        if spec.white is not None:
            self.seats[chess.WHITE] = Seat(registry.root, spec.white, seed)
        if spec.black is not None:
            self.seats[chess.BLACK] = Seat(registry.root, spec.black, seed + 1)
        self.slots = len(self.seats)

    # -- lifecycle ---------------------------------------------------------------------------

    def launch(self) -> None:
        threading.Thread(target=self._bootstrap, name=f"game-{self.id}", daemon=True).start()

    def _bootstrap(self) -> None:
        try:
            failures: dict[chess.Color, str | None] = {}
            for colour in (chess.WHITE, chess.BLACK):  # the referee starts White first
                seat = self.seats.get(colour)
                if seat is not None and not self._stop_requested:
                    failures[colour] = seat.start()
            white_failure = failures.get(chess.WHITE)
            black_failure = failures.get(chess.BLACK)
            with self._lock:
                self._touch()
                if self._stop_requested:
                    self._finish(self._stop_result, self._stop_reason)
                    return
                if white_failure is not None and black_failure is not None:
                    self._finish("void", "both_failed")
                    return
                if white_failure is not None:
                    self._finish("black", white_failure)
                    return
                if black_failure is not None:
                    self._finish("white", black_failure)
                    return
                self.status = "running"
                if self._check_end():
                    return
            if self.kind == "spectate":
                while self._engine_turn():
                    pass
            else:
                self._engine_turn()
        except Exception as exc:  # an engine problem must never crash the server
            with self._lock:
                self.error = f"{type(exc).__name__}: {exc}"
                self._finish("void", "error")

    def _engine_turn(self) -> bool:
        """Let the engine to move play one move; True when the game is still running afterwards."""
        with self._lock:
            if self.status != "running":
                return False
            if self._stop_requested:
                self._finish(self._stop_result, self._stop_reason)
                return False
            mover = self.board.turn
            seat = self.seats.get(mover)
            if seat is None:
                return False
            fen = self.board.fen()
            time_left = int(self.clock[mover])
            ply = self.board.ply() + 1
            self.thinking = True
            self.thinking_since = time.time()
        uci, spent_ms, failure = seat.think(fen, time_left, ply)
        with self._lock:
            self.thinking = False
            self.thinking_since = None
            self._touch()
            if self.status != "running":
                return False
            if self._stop_requested:
                self._finish(self._stop_result, self._stop_reason)
                return False
            if failure is not None:
                self._finish(_side(not mover), failure)
                return False
            self.clock[mover] -= spent_ms
            if self.clock[mover] < 0:
                self._finish(_flagged(self.board, mover), "flag")
                return False
            move = _legal_move(self.board, uci or "")
            if move is None:
                self._finish(_side(not mover), "illegal")
                return False
            self._push(move, mover, spent_ms, seat.records[-1] if seat.records else None)
            return not self._check_end()

    def _push(
        self, move: chess.Move, mover: chess.Color, spent_ms: float, log: LogRecord | None
    ) -> None:
        san = self.board.san(move)
        self.board.push(move)
        self.clock[mover] += self.spec.increment_ms
        self.moves.append(
            MoveRecord(
                ply=self.board.ply(),
                san=san,
                uci=move.uci(),
                by=_side(mover),
                spent_ms=spent_ms,
                clock_ms=self.clock[mover],
                white_ms=self.clock[chess.WHITE],
                black_ms=self.clock[chess.BLACK],
                fen=self.board.fen(),
                log=log,
            )
        )
        self._touch()

    def _check_end(self) -> bool:
        """The referee's end-of-game checks, in the referee's order. True when the game ended."""
        finish = self.board.outcome()
        if finish is not None:
            self._finish(_decide(finish), finish.termination.name.lower())
            return True
        if self.board.is_repetition(3):
            self._finish("draw", "threefold_repetition")
            return True
        if self.board.is_fifty_moves():
            self._finish("draw", "fifty_moves")
            return True
        if self.board.ply() >= self.spec.ply_cap:
            self._finish("draw", "ply_cap")
            return True
        return False

    def _finish(self, result: Result, termination: str) -> None:
        """End the game: stop the agents, free their slots, archive the PGN, then flip the status.

        Always called under the state lock. The status changes last so that anyone who observes
        "finished" also sees the processes gone and the slots released.
        """
        if self.status == "finished" or self._finishing:
            return
        self._finishing = True
        self.result = result
        self.termination = termination
        self.thinking = False
        self.thinking_since = None
        self._touch()
        for seat in self.seats.values():
            seat.stop()
        if not self._slots_released:
            self._slots_released = True
            self.registry.release(self.slots)
        if self.moves:
            try:
                self.pgn_path = self.registry.save_pgn(self)
            except OSError as exc:
                self.error = f"could not save PGN: {exc}"
        self.status = "finished"

    def _touch(self) -> None:
        self.updated_at = time.time()

    # -- requests ----------------------------------------------------------------------------

    def human_move(self, uci: str, spent_ms: float) -> None:
        with self._lock:
            self._touch()
            if self.status == "starting":
                raise GameError(409, "the engine is still starting")
            if self.status != "running":
                raise GameError(409, "the game is over")
            if self.human is None:
                raise GameError(409, "this is an engine vs engine game")
            if self.thinking or _side(self.board.turn) != self.human:
                raise GameError(409, "it is not your turn")
            move = _legal_move(self.board, uci)
            if move is None:
                raise GameError(400, f"{uci!r} is not a legal move here")
            mover = self.board.turn
            spent = min(max(spent_ms, 0.0), float(MAX_HUMAN_SPENT_MS))
            # The human clock is displayed, never enforced: a playground does not flag its owner.
            self.clock[mover] = max(0.0, self.clock[mover] - spent)
            self._push(move, mover, spent, None)
            if self._check_end():
                return
            threading.Thread(
                target=self._engine_turn, name=f"game-{self.id}-move", daemon=True
            ).start()

    def takeback(self) -> None:
        """Undo the last full move pair so the human is to move again."""
        with self._lock:
            self._touch()
            if self.status != "running":
                raise GameError(409, "takeback is only possible while the game is running")
            if self.human is None:
                raise GameError(409, "takeback needs a human player")
            if self.thinking or _side(self.board.turn) != self.human:
                raise GameError(409, "wait for the engine to move first")
            if not self.moves:
                raise GameError(409, "nothing to take back")
            self._pop()
            if self.moves and _side(self.board.turn) != self.human:
                self._pop()
            if self._side_to_move() != self.human:
                # Only reachable when the engine opened the game and every move was undone.
                threading.Thread(
                    target=self._engine_turn, name=f"game-{self.id}-move", daemon=True
                ).start()

    def _pop(self) -> None:
        self.board.pop()
        self.moves.pop()
        if self.moves:
            last = self.moves[-1]
            self.clock[chess.WHITE] = last.white_ms
            self.clock[chess.BLACK] = last.black_ms
        else:
            self.clock[chess.WHITE] = float(self.spec.base_ms)
            self.clock[chess.BLACK] = float(self.spec.base_ms)

    def _side_to_move(self) -> Colour:
        return _side(self.board.turn)

    def resign(self) -> None:
        with self._lock:
            self._touch()
            if self.status == "finished":
                raise GameError(409, "the game is over")
            if self.human is None:
                raise GameError(409, "only a human can resign; use stop")
            winner: Result = "black" if self.human == "white" else "white"
            if self.thinking or self.status == "starting":
                # The engine thread owns the process; make its move() return now and let it
                # finish the game with the recorded result and reason.
                self._stop_requested = True
                self._stop_reason = "resignation"
                self._stop_result = winner
                for seat in self.seats.values():
                    seat.kill()
                return
            self._finish(winner, "resignation")

    def stop(self, reason: str = "aborted") -> None:
        with self._lock:
            self._touch()
            if self.status == "finished":
                return
            self._stop_requested = True
            self._stop_reason = reason
            self._stop_result = "void"
            if self.thinking or self.status == "starting":
                for seat in self.seats.values():
                    seat.kill()
                return
            self._finish("void", reason)

    # -- views -------------------------------------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            human_to_move = (
                self.status == "running"
                and not self.thinking
                and self.human is not None
                and self._side_to_move() == self.human
            )
            check_square = (
                chess.square_name(king)
                if self.board.is_check() and (king := self.board.king(self.board.turn)) is not None
                else None
            )
            result = self.result
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "stopping": self._stop_requested and self.status != "finished",
                "human": self.human,
                "white": self._player(chess.WHITE),
                "black": self._player(chess.BLACK),
                "turn": self._side_to_move(),
                "thinking": self.thinking,
                "thinking_since": (
                    None if self.thinking_since is None else int(self.thinking_since * 1000)
                ),
                "fen": self.board.fen(),
                "start_fen": self.start_fen,
                "opening": self.spec.opening,
                "ply": self.board.ply(),
                "ply_cap": self.spec.ply_cap,
                "moves": [record.to_dict() for record in self.moves],
                "clocks": {
                    "white": round(self.clock[chess.WHITE], 1),
                    "black": round(self.clock[chess.BLACK], 1),
                },
                "time_control": {
                    "base_ms": self.spec.base_ms,
                    "increment_ms": self.spec.increment_ms,
                },
                "legal_moves": (
                    [move.uci() for move in self.board.legal_moves] if human_to_move else []
                ),
                "check_square": check_square,
                "result": result,
                "result_text": None if result is None else RESULT_HEADERS[result],
                "termination": self.termination,
                "termination_text": (
                    None
                    if self.termination is None
                    else TERMINATIONS.get(self.termination, self.termination)
                ),
                "failed": self.termination in FAILED_TERMINATIONS,
                "error": self.error,
                "pgn_path": None if self.pgn_path is None else str(self.pgn_path),
                "created_at": int(self.created_at * 1000),
                "updated_at": int(self.updated_at * 1000),
                "server_time": int(time.time() * 1000),
            }

    def _player(self, colour: chess.Color) -> dict[str, object]:
        seat = self.seats.get(colour)
        if seat is None:
            return {"kind": "human", "label": "You", "short": "you", "path": None, "log": []}
        return seat.to_dict()

    def summary(self) -> dict[str, object]:
        with self._lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "status": self.status,
                "white": self._player_label(chess.WHITE),
                "black": self._player_label(chess.BLACK),
                "ply": self.board.ply(),
                "result": self.result,
                "termination": self.termination,
                "updated_at": int(self.updated_at * 1000),
            }

    def _player_label(self, colour: chess.Color) -> str:
        seat = self.seats.get(colour)
        return "You" if seat is None else seat.info.label

    def pgn(self) -> str:
        """The PGN the referee would write, plus the headers a PGN reader expects."""
        with self._lock:
            game = chess.pgn.Game.from_board(self.board)
            result = self.result or "void"
            game.headers["Event"] = f"{ENGINE_NAME} webapp ({self.kind})"
            game.headers["Site"] = "localhost"
            game.headers["Date"] = datetime.fromtimestamp(self.created_at, UTC).strftime("%Y.%m.%d")
            game.headers["Round"] = "-"
            game.headers["White"] = self._player_label(chess.WHITE)
            game.headers["Black"] = self._player_label(chess.BLACK)
            game.headers["Result"] = RESULT_HEADERS[result]
            game.headers["TimeControl"] = (
                f"{self.spec.base_ms // 1000}+{self.spec.increment_ms / 1000:g}"
            )
            if self.start_fen != chess.STARTING_FEN:
                game.headers["SetUp"] = "1"
                game.headers["FEN"] = self.start_fen
            if self.spec.opening:
                game.headers["Opening"] = self.spec.opening
            if self.termination is not None:
                game.headers["Termination"] = self.termination
            for node, record in zip(game.mainline(), self.moves, strict=True):
                node.set_clock(max(record.clock_ms, 0.0) / 1000.0)
            return str(game)

    def pgn_filename(self) -> str:
        stamp = datetime.fromtimestamp(self.created_at).strftime("%Y%m%d-%H%M%S")
        white = _slug(self._player_label(chess.WHITE))
        black = _slug(self._player_label(chess.BLACK))
        return f"{stamp}-{white}-vs-{black}.pgn"


# --------------------------------------------------------------------------------------------
# Registry


class Registry:
    """Every game the server knows about, the engine-process cap, and the PGN archive."""

    def __init__(
        self,
        root: Path = ROOT,
        games_dir: Path | None = None,
        max_engines: int = 4,
        idle_seconds: float = 30 * 60,
    ) -> None:
        self.root = root
        self.games_dir = games_dir if games_dir is not None else root / "data" / "webapp_games"
        self.max_engines = max_engines
        self.idle_seconds = idle_seconds
        self._games: dict[str, Game] = {}
        self._lock = threading.Lock()
        self._live = 0
        self._closing = threading.Event()
        self._reaper: threading.Thread | None = None

    # -- slots -------------------------------------------------------------------------------

    @property
    def live_engines(self) -> int:
        with self._lock:
            return self._live

    def _reserve(self, count: int) -> None:
        with self._lock:
            if self._live + count > self.max_engines:
                raise GameError(
                    429,
                    f"{self._live} of {self.max_engines} engine processes are already running; "
                    "stop a game first or start the server with --max-engines",
                )
            self._live += count

    def release(self, count: int) -> None:
        with self._lock:
            self._live = max(0, self._live - count)

    # -- games -------------------------------------------------------------------------------

    def create(self, body: dict[str, object]) -> Game:
        spec = parse_spec(self.root, body)
        if self._closing.is_set():
            raise GameError(503, "the server is shutting down")
        self._reserve(2 if spec.kind == "spectate" else 1)
        try:
            game = Game(self, spec)
        except Exception:
            self.release(2 if spec.kind == "spectate" else 1)
            raise
        with self._lock:
            self._games[game.id] = game
        game.launch()
        return game

    def get(self, game_id: str) -> Game:
        with self._lock:
            game = self._games.get(game_id)
        if game is None:
            raise GameError(404, f"no game {game_id!r}")
        return game

    def remove(self, game_id: str) -> None:
        game = self.get(game_id)
        game.stop("aborted")
        with self._lock:
            self._games.pop(game_id, None)

    def summaries(self) -> list[dict[str, object]]:
        with self._lock:
            games = list(self._games.values())
        return [game.summary() for game in sorted(games, key=lambda g: g.created_at, reverse=True)]

    def save_pgn(self, game: Game) -> Path:
        self.games_dir.mkdir(parents=True, exist_ok=True)
        path = self.games_dir / game.pgn_filename()
        if path.exists():
            path = path.with_name(f"{path.stem}-{game.id}.pgn")
        path.write_text(game.pgn() + "\n", encoding="utf-8")
        return path

    # -- housekeeping ------------------------------------------------------------------------

    def reap(self, now: float | None = None) -> list[str]:
        """Stop games nobody has touched for ``idle_seconds``; returns the ids stopped."""
        now = time.time() if now is None else now
        with self._lock:
            games = list(self._games.values())
        stopped: list[str] = []
        for game in games:
            if game.status != "finished" and now - game.updated_at > self.idle_seconds:
                game.stop("abandoned")
                stopped.append(game.id)
        return stopped

    def start_reaper(self, interval_s: float = 15.0) -> None:
        if self._reaper is not None:
            return

        def loop() -> None:
            while not self._closing.wait(interval_s):
                self.reap()

        self._reaper = threading.Thread(target=loop, name="webapp-reaper", daemon=True)
        self._reaper.start()

    def shutdown(self) -> None:
        """Stop every agent process; safe to call more than once (atexit and Ctrl-C both do)."""
        self._closing.set()
        with self._lock:
            games = list(self._games.values())
        for game in games:
            game.stop("aborted")
        # A game whose engine thread is mid-move finishes asynchronously; give it a moment so the
        # process is reaped before the interpreter goes away.
        deadline = time.monotonic() + 2.0
        for game in games:
            while game.status != "finished" and time.monotonic() < deadline:
                time.sleep(0.02)
            for seat in game.seats.values():
                seat.stop()


def _int_field(body: dict[str, object], key: str, default: int, low: int, high: int) -> int:
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GameError(400, f"{key} must be a number")
    number = int(value)
    if not low <= number <= high:
        raise GameError(400, f"{key} must be between {low} and {high}")
    return number


def _str_field(body: dict[str, object], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise GameError(400, f"{key} must be a string")
    return value


def parse_spec(root: Path, body: dict[str, object]) -> GameSpec:
    kind = body.get("kind", "play")
    if kind not in ("play", "spectate"):
        raise GameError(400, "kind must be 'play' or 'spectate'")
    base_ms = _int_field(body, "base_ms", BASE_MS, 100, MAX_BASE_MS)
    increment_ms = _int_field(body, "increment_ms", INCREMENT_MS, 0, MAX_INCREMENT_MS)
    ply_cap = _int_field(body, "ply_cap", PLY_CAP, 1, PLY_CAP)
    fen = _str_field(body, "fen") or chess.STARTING_FEN
    board = validate_fen(fen, ply_cap)
    opening = _str_field(body, "opening")
    if opening is not None:
        opening = opening.strip()[:120] or None
    if kind == "play":
        engine = _str_field(body, "engine")
        if engine is None:
            raise GameError(400, "engine is required")
        resolve_engine(root, engine)
        human = body.get("human", "white")
        if human not in ("white", "black"):
            raise GameError(400, "human must be 'white' or 'black'")
        white, black = (None, engine) if human == "white" else (engine, None)
    else:
        white = _str_field(body, "white")
        black = _str_field(body, "black")
        if white is None or black is None:
            raise GameError(400, "white and black engine directories are required")
        resolve_engine(root, white)
        resolve_engine(root, black)
    return GameSpec(
        kind=kind,
        white=white,
        black=black,
        base_ms=base_ms,
        increment_ms=increment_ms,
        start_fen=board.fen(),
        ply_cap=ply_cap,
        opening=opening,
    )


# --------------------------------------------------------------------------------------------
# Repository information for the info, docs, weights and openings pages

DOC_ORDER = ("DESIGN", "DECISIONS", "RESULTS", "CALIBRATION", "PROVENANCE", "INTEGRATION_NOTES")
_TABLE_SEPARATOR = re.compile(r":?-{2,}:?")


def engine_identity(root: Path) -> dict[str, object]:
    """Name and version read from ``mikhail_letal/__init__.py`` without importing it, so a broken
    engine build (it is being written concurrently) cannot take the web app down."""
    name, version = ENGINE_NAME, None
    path = root / "mikhail_letal" / "__init__.py"
    if path.is_file():
        try:
            module = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            module = None
        for node in module.body if module is not None else []:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "__version__" in targets and isinstance(node.value.value, str):
                    version = node.value.value
                if "ENGINE_NAME" in targets and isinstance(node.value.value, str):
                    name = node.value.value
    return {"name": name, "version": version, "tagline": TAGLINE, "package": "mikhail_letal"}


def _git(root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() if completed.returncode == 0 else None


def git_info(root: Path) -> dict[str, object]:
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    return {
        "commit": _git(root, "rev-parse", "HEAD"),
        "short": _git(root, "rev-parse", "--short", "HEAD"),
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "describe": _git(root, "describe", "--tags", "--always", "--dirty"),
        "dirty": None if status is None else bool(status.strip()),
    }


def markdown_tables(text: str) -> list[list[list[str]]]:
    """Every pipe table in ``text`` as rows of cells (separator rows removed)."""
    tables: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and len(stripped) > 1:
            cells = [cell.strip() for cell in stripped[1:-1].split("|")]
            if all(_TABLE_SEPARATOR.fullmatch(cell) for cell in cells):
                continue
            if current is None:
                current = []
                tables.append(current)
            current.append(cells)
        else:
            current = None
    return tables


def results_status(root: Path, rows: int = 5) -> dict[str, object]:
    """The last few data rows of the last populated table in docs/RESULTS.md."""
    path = root / "docs" / "RESULTS.md"
    if not path.is_file():
        return {"present": False, "columns": [], "rows": []}
    for table in reversed(markdown_tables(path.read_text(encoding="utf-8"))):
        header, *data = table
        if data:
            return {
                "present": True,
                "columns": header,
                "rows": [dict(zip(header, row, strict=False)) for row in data[-rows:]],
                "total_rows": len(data),
            }
    return {"present": True, "columns": [], "rows": []}


def contract() -> list[dict[str, object]]:
    """The competition contract, with every number that exists in harness/rules.py taken from it."""
    return [
        {
            "label": "Time control",
            "value": f"{BASE_MS // 1000} s + {INCREMENT_MS / 1000:g} s per move",
            "source": "harness/rules.py",
        },
        {
            "label": "Init budget",
            "value": f"{INIT_BUDGET_S:g} s before the clock starts",
            "source": "harness/rules.py",
        },
        {
            "label": "Ply cap",
            "value": f"{PLY_CAP} plies, counted from the start FEN",
            "source": "harness/rules.py",
        },
        {
            "label": "CPU",
            "value": "one core of an AMD EPYC 9V74 at 2.60 GHz",
            "source": "agent contract",
        },
        {"label": "Memory", "value": "2 GB, no GPU, no network", "source": "agent contract"},
        {
            "label": "Move reply",
            "value": f"one UCI string, at most {STDOUT_CAP} bytes",
            "source": "harness/rules.py",
        },
        {
            "label": "Kept output",
            "value": f"first {STDERR_HEAD} B and last {STDERR_TAIL} B of stderr",
            "source": "harness/rules.py",
        },
        {
            "label": "Watchdog grace",
            "value": f"{WATCHDOG_GRACE_MS} ms past the clock",
            "source": "harness/rules.py",
        },
        {
            "label": "Losses",
            "value": "illegal move, malformed reply, crash, out of memory, flag fall",
            "source": "agent contract",
        },
        {
            "label": "Draws",
            "value": "FIDE rules; flag against insufficient material; ply cap",
            "source": "agent contract",
        },
        {
            "label": "Zip",
            "value": "agent.py at the root, under 50 MB unzipped, source only",
            "source": "agent contract",
        },
    ]


def docs_list(root: Path) -> list[dict[str, object]]:
    directory = root / "docs"
    if not directory.is_dir():
        return []
    files = {path.stem: path for path in directory.glob("*.md") if path.is_file()}
    ordered = [files.pop(name) for name in DOC_ORDER if name in files]
    ordered.extend(files[name] for name in sorted(files))
    documents: list[dict[str, object]] = []
    for path in ordered:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            content = f"(could not read {path.name}: {exc})"
        documents.append({"name": path.stem, "file": f"docs/{path.name}", "content": content})
    return documents


def _read_json(path: Path) -> tuple[object, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name}: {exc}"


def weights(root: Path) -> dict[str, object]:
    pst_path = root / "weights" / "pst.json"
    provenance_path = root / "weights" / "PROVENANCE.json"
    payload: dict[str, object] = {
        "present": pst_path.is_file(),
        "path": "weights/pst.json",
        "pst": None,
        "provenance_present": provenance_path.is_file(),
        "provenance": None,
        "errors": [],
    }
    errors: list[str] = []
    if pst_path.is_file():
        data, error = _read_json(pst_path)
        if error is not None:
            errors.append(error)
        elif isinstance(data, dict):
            payload["pst"] = data
        else:
            errors.append("pst.json: expected an object at the top level")
    if provenance_path.is_file():
        data, error = _read_json(provenance_path)
        if error is not None:
            errors.append(error)
        else:
            payload["provenance"] = data
    payload["errors"] = errors
    return payload


def openings(root: Path) -> dict[str, object]:
    path = root / "data" / "openings.txt"
    rows: list[dict[str, object]] = []
    invalid = 0
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, _, fen = line.partition("\t")
            if not fen:
                name, fen = "", line.strip()
            fen = fen.strip()
            try:
                board = chess.Board(fen)
                valid = board.status() == chess.STATUS_VALID
            except ValueError:
                valid = False
            invalid += 0 if valid else 1
            rows.append({"index": len(rows), "name": name.strip(), "fen": fen, "valid": valid})
    return {
        "present": path.is_file(),
        "path": "data/openings.txt",
        "count": len(rows),
        "names": len({row["name"] for row in rows}),
        "invalid": invalid,
        "openings": rows,
        "harness": [{"name": name, "fen": fen} for name, fen in OPENINGS],
    }
