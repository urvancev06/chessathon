"""Stockfish analysis for the web app: a job queue, one worker, cached JSON reports.

Stockfish is a local-only instrument (brief, section 2.2): the binary lives outside the repository
(``YARDSTICK_ENGINE``, else ``~/.local/opt/stockfish/stockfish``, else PATH), it never enters the
repository or the zip and it never influences a move our engine plays. Here it only grades games
that were already played. Without it every endpoint answers with a clear reason.

Analyses run one at a time on a worker thread so the machine stays predictable while games are
being played; each job opens its own engine (``Threads=1``, ``Hash=64``) and quits it at the end.
Every position of the game is analysed once at the requested depth with ``multipv`` lines; the
evaluation after a move is the evaluation of the next position, so the report costs one search
per position, not two. The final position is analysed too, unless the game is over on the board,
in which case the outcome decides: checkmate is reported as ``cp`` ±1000 (the value the formulas
below use for any mate score; "mate 0" cannot carry a sign through JSON) and a drawn position as 0.

Formulas are lichess's published ones, used because they are the de-facto standard for this kind
of report; the one deviation is that a side's accuracy is the plain mean of its per-move
accuracies (lichess uses a windowed harmonic mean). Evaluations are always from White's point of
view; win percentages, centipawn loss and judgements are from the mover's.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import math
import os
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import chess
import chess.engine
import chess.pgn

from harness.referee import RESULT_HEADERS
from tools.webapp.games import GameError, Registry, stockfish_path, stockfish_status

Status = Literal["queued", "running", "done", "failed", "cancelled"]
Judgement = Literal["best", "good", "inaccuracy", "mistake", "blunder"]
Colour = Literal["white", "black"]
JsonObject = dict[str, object]

DEPTH_RANGE = (8, 30)
DEFAULT_DEPTH = 18
MULTIPV_RANGE = (1, 5)
DEFAULT_MULTIPV = 3
HASH_MB = 64
LINE_LENGTH = 8  # SAN moves of the best line kept per position
MATE_CP = 1000  # a mate score counts as this many centipawns in win% and cp loss
MAX_CP_LOSS = 1000
# lichess: win% = 50 + 50 * (2 / (1 + exp(-0.00368208 * cp)) - 1)
WIN_SCALE = 0.00368208
# lichess: accuracy% = 103.1668 * exp(-0.04354 * (win% before - win% after)) - 3.1669
ACCURACY_A, ACCURACY_B, ACCURACY_C = 103.1668, 0.04354, 3.1669
JUDGEMENT_DROPS: tuple[tuple[float, Judgement], ...] = (
    (30.0, "blunder"),
    (20.0, "mistake"),
    (10.0, "inaccuracy"),
)
CANCEL_POLL_S = 0.05
MAX_JOBS_KEPT = 50  # finished jobs remembered in memory (results also sit in the cache)
MAX_FILES = 500
MAX_PGN_BYTES = 1_000_000
PGN_DIRS = ("data/webapp_games", "data/pgn")
HEADER_KEYS = ("White", "Black", "Result", "Date", "Termination", "Event")


class Cancelled(Exception):
    """Raised inside the worker when the job's cancel flag is seen."""


# --------------------------------------------------------------------------------------------
# Pure functions: evaluations, win%, judgements


@dataclass(frozen=True)
class Eval:
    """An engine score from White's point of view; exactly one of ``cp``/``mate`` is set."""

    cp: int | None
    mate: int | None

    def to_dict(self) -> JsonObject:
        return {"cp": self.cp, "mate": self.mate, "pov": "white"}

    def as_cp(self) -> int:
        """Centipawns with mates folded to ±MATE_CP; ``mate 0`` (being mated) counts as -MATE_CP."""
        if self.mate is not None:
            return MATE_CP if self.mate > 0 else -MATE_CP
        return self.cp if self.cp is not None else 0

    def for_mover(self, mover: chess.Color) -> int:
        cp = self.as_cp()
        return cp if mover == chess.WHITE else -cp


def eval_from_score(score: chess.engine.Score) -> Eval:
    """From a White-POV ``Score``; mate distances keep their sign (positive: White mates).

    "Mate 0" (the side to move is mated, or has just mated) has no sign of its own, so it is
    folded into the ±MATE_CP centipawn value the formulas use for every mate anyway.
    """
    mate = score.mate()
    if mate is not None and mate != 0:
        return Eval(None, mate)
    return Eval(score.score(mate_score=MATE_CP), None)


def terminal_eval(board: chess.Board) -> Eval | None:
    """The evaluation the outcome dictates for a finished position, else None.

    Threefold repetition and the fifty-move rule count (``claim_draw``) because the referee ends
    a game on them; the analysis only ever sees the full move stack, so both can be detected.
    """
    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        return None
    if outcome.winner is None:
        return Eval(0, None)
    return Eval(MATE_CP if outcome.winner == chess.WHITE else -MATE_CP, None)


def win_percent(cp: int) -> float:
    """lichess's win% for a centipawn score seen by the side it is measured for."""
    return 50.0 + 50.0 * (2.0 / (1.0 + math.exp(-WIN_SCALE * cp)) - 1.0)


def cp_loss(best_cp: int, played_cp: int) -> int:
    """Centipawns the mover gave away, both scores from the mover's side, capped and never < 0."""
    return max(0, min(MAX_CP_LOSS, best_cp - played_cp))


def accuracy(drop: float) -> float:
    """lichess's per-move accuracy for a win% drop, clamped to 0..100."""
    value = ACCURACY_A * math.exp(-ACCURACY_B * drop) - ACCURACY_C
    return max(0.0, min(100.0, value))


def judge(drop: float, rank: int | None) -> Judgement:
    """Blunder / mistake / inaccuracy by win% drop; best when the engine's first choice was
    played or nothing was lost; good otherwise."""
    for threshold, verdict in JUDGEMENT_DROPS:
        if drop >= threshold:
            return verdict
    if rank == 1 or drop <= 0.0:
        return "best"
    return "good"


# --------------------------------------------------------------------------------------------
# The report


@dataclass(frozen=True)
class Candidate:
    uci: str
    san: str
    eval: Eval
    line_san: tuple[str, ...] = ()

    def to_dict(self, with_line: bool) -> JsonObject:
        payload: JsonObject = {"uci": self.uci, "san": self.san, "eval": self.eval.to_dict()}
        if with_line:
            payload["line_san"] = list(self.line_san)
        return payload


@dataclass(frozen=True)
class PlyReport:
    ply: int
    move_number: int
    mover: Colour
    san: str
    uci: str
    fen_before: str
    fen_after: str
    eval_before: Eval
    eval_after: Eval
    best: Candidate
    top: tuple[Candidate, ...]
    rank: int | None
    cp_loss: int
    win_before: float
    win_after: float
    accuracy: float
    judgement: Judgement
    clock_after: float | None

    def to_dict(self) -> JsonObject:
        return {
            "ply": self.ply,
            "move_number": self.move_number,
            "mover": self.mover,
            "san": self.san,
            "uci": self.uci,
            "fen_before": self.fen_before,
            "fen_after": self.fen_after,
            "eval_before": self.eval_before.to_dict(),
            "eval_after": self.eval_after.to_dict(),
            "best": self.best.to_dict(with_line=True),
            "top": [candidate.to_dict(with_line=False) for candidate in self.top],
            "rank": self.rank,
            "cp_loss": self.cp_loss,
            "win_before": round(self.win_before, 2),
            "win_after": round(self.win_after, 2),
            "accuracy": round(self.accuracy, 2),
            "judgement": self.judgement,
            "clock_after": self.clock_after,
        }


def ply_report(
    board: chess.Board,
    move: chess.Move,
    ply: int,
    candidates: tuple[Candidate, ...],
    eval_after: Eval,
    fen_after: str,
    clock_after: float | None,
) -> PlyReport:
    """Grade one move given the analysis of the position it was played in (``candidates``, best
    first) and the evaluation of the position it led to."""
    mover = board.turn
    best = candidates[0]
    eval_before = best.eval
    uci = move.uci()
    rank = next((index for index, c in enumerate(candidates, start=1) if c.uci == uci), None)
    win_before = win_percent(eval_before.for_mover(mover))
    win_after = win_percent(eval_after.for_mover(mover))
    drop = win_before - win_after
    return PlyReport(
        ply=ply,
        move_number=board.fullmove_number,
        mover="white" if mover == chess.WHITE else "black",
        san=board.san(move),
        uci=uci,
        fen_before=board.fen(),
        fen_after=fen_after,
        eval_before=eval_before,
        eval_after=eval_after,
        best=best,
        top=candidates,
        rank=rank,
        cp_loss=cp_loss(eval_before.for_mover(mover), eval_after.for_mover(mover)),
        win_before=win_before,
        win_after=win_after,
        accuracy=accuracy(drop),
        judgement=judge(drop, rank),
        clock_after=clock_after,
    )


def summarise(plies: list[PlyReport], side: Colour, name: str) -> JsonObject:
    """One side's totals; means are plain means (said so in the UI), zero when it never moved."""
    own = [ply for ply in plies if ply.mover == side]
    moves = len(own)
    best_moves = sum(1 for ply in own if ply.rank == 1)
    top3_moves = sum(1 for ply in own if ply.rank is not None and ply.rank <= 3)

    def mean(values: list[float]) -> float:
        return round(sum(values) / len(values), 2) if values else 0.0

    def share(count: int) -> float:
        return round(100.0 * count / moves, 2) if moves else 0.0

    return {
        "name": name,
        "moves": moves,
        "best_moves": best_moves,
        "best_move_pct": share(best_moves),
        "top3_moves": top3_moves,
        "top3_pct": share(top3_moves),
        "acpl": mean([float(ply.cp_loss) for ply in own]),
        "accuracy": mean([ply.accuracy for ply in own]),
        "inaccuracies": sum(1 for ply in own if ply.judgement == "inaccuracy"),
        "mistakes": sum(1 for ply in own if ply.judgement == "mistake"),
        "blunders": sum(1 for ply in own if ply.judgement == "blunder"),
    }


# --------------------------------------------------------------------------------------------
# Driving the engine


def _line_san(board: chess.Board, moves: list[chess.Move]) -> tuple[str, ...]:
    scratch = board.copy(stack=False)
    line: list[str] = []
    for move in moves[:LINE_LENGTH]:
        if move not in scratch.legal_moves:  # a truncated or odd pv: keep what was sound
            break
        line.append(scratch.san(move))
        scratch.push(move)
    return tuple(line)


def analyse_position(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    depth: int,
    multipv: int,
    cancel: threading.Event,
) -> tuple[Candidate, ...]:
    """The engine's top lines for ``board``, best first. Polls ``cancel`` while the engine
    thinks, so a deep job can be stopped within a fraction of a second, not a position later."""
    with engine.analysis(board, chess.engine.Limit(depth=depth), multipv=multipv) as analysis:
        while True:
            if cancel.is_set():
                analysis.stop()
                raise Cancelled
            if analysis.would_block():
                time.sleep(CANCEL_POLL_S)
                continue
            if analysis.next() is None:
                break
        infos = analysis.multipv
    candidates: list[Candidate] = []
    for info in sorted(infos, key=lambda entry: entry.get("multipv", 1)):
        score = info.get("score")
        pv = info.get("pv")
        if score is None or not pv or pv[0] not in board.legal_moves:
            continue  # an info line without a line (a "string" note, a bound) grades nothing
        move = pv[0]
        candidates.append(
            Candidate(
                move.uci(), board.san(move), eval_from_score(score.white()), _line_san(board, pv)
            )
        )
    if not candidates:
        raise RuntimeError(f"the engine returned no line for {board.fen()}")
    return tuple(candidates)


def analyse_game(
    engine: chess.engine.SimpleEngine,
    game: chess.pgn.Game,
    depth: int,
    multipv: int,
    cancel: threading.Event | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> JsonObject:
    """The full RESULT for ``game`` (see the module docstring for what is computed)."""
    cancel = cancel if cancel is not None else threading.Event()
    nodes = list(game.mainline())
    total = len(nodes) + 1
    board = game.board()
    start_fen = board.fen()
    analyses: list[tuple[Candidate, ...]] = []
    for index, node in enumerate(nodes):
        analyses.append(analyse_position(engine, board, depth, multipv, cancel))
        if progress is not None:
            progress(index + 1, total)
        board.push(node.move)
    final = terminal_eval(board)
    if final is None:
        final = analyse_position(engine, board, depth, multipv, cancel)[0].eval
    if progress is not None:
        progress(total, total)

    board = game.board()
    plies: list[PlyReport] = []
    for index, node in enumerate(nodes):
        eval_after = analyses[index + 1][0].eval if index + 1 < len(nodes) else final
        after = board.copy(stack=False)
        after.push(node.move)
        plies.append(
            ply_report(
                board, node.move, index + 1, analyses[index], eval_after, after.fen(), node.clock()
            )
        )
        board.push(node.move)

    headers = {key: game.headers.get(key, "") for key in HEADER_KEYS}
    return {
        "engine": {"name": engine.id.get("name", "unknown"), "depth": depth, "multipv": multipv},
        "headers": headers,
        "start_fen": start_fen,
        "plies": [ply.to_dict() for ply in plies],
        "summary": {
            "white": summarise(plies, "white", headers["White"] or "White"),
            "black": summarise(plies, "black", headers["Black"] or "Black"),
        },
    }


# --------------------------------------------------------------------------------------------
# Sources


def parse_pgn(text: str) -> chess.pgn.Game:
    """The first game in ``text``, or a 400 explaining what is wrong with it."""
    if len(text.encode("utf-8", "replace")) > MAX_PGN_BYTES:
        raise GameError(400, "the PGN is too large")
    game = chess.pgn.read_game(io.StringIO(text))
    if game is None:
        raise GameError(400, "no game found in the PGN")
    if game.errors:
        raise GameError(400, f"the PGN could not be read: {game.errors[0]}")
    try:
        board = game.board()
    except ValueError as exc:
        raise GameError(400, f"the PGN's FEN header is invalid: {exc}") from None
    if board.status() != chess.STATUS_VALID:
        raise GameError(400, "the PGN starts from an illegal position")
    if game.next() is None:  # the reader is lenient: plain text parses as a moveless game
        raise GameError(400, "the PGN has no moves to analyse")
    return game


def cache_key(canonical_pgn: str, depth: int, multipv: int) -> str:
    digest = hashlib.sha1(f"{canonical_pgn}\ndepth={depth}\nmultipv={multipv}".encode())
    return digest.hexdigest()


def resolve_pgn_file(root: Path, spec: str, pgn_dirs: Iterable[Path] = ()) -> Path:
    """A ``.pgn`` file: relative paths resolve under the repository root; an absolute path is
    accepted only inside one of the listed PGN directories (the server's own archive when it is
    kept outside the repository). Nothing else on the disk can be read through this endpoint."""
    if not spec.strip() or "\x00" in spec:
        raise GameError(400, "file is required")
    repo = root.resolve()
    given = Path(spec.strip())
    if given.is_absolute():
        candidate = given.resolve()
        allowed = [directory.resolve() for directory in pgn_dirs]
        if not any(directory in candidate.parents for directory in allowed):
            raise GameError(400, f"{spec!r} is outside the PGN directories")
    else:
        candidate = (repo / given).resolve()
        if repo not in candidate.parents:
            raise GameError(400, f"{spec!r} is outside the repository")
    if candidate.suffix.lower() != ".pgn":
        raise GameError(400, "only .pgn files can be analysed")
    if not candidate.is_file():
        raise GameError(404, f"no such file: {spec}")
    return candidate


def _game_pgn(registry: Registry, game_id: str) -> tuple[str, str]:
    game = registry.get(game_id)
    if not game.moves:
        raise GameError(400, "the game has no moves yet")
    return game.pgn(), f"game {game_id}"


def load_source(
    registry: Registry, source: object, pgn_dirs: Iterable[Path] = ()
) -> tuple[chess.pgn.Game, str]:
    """``(game, description)`` for the request's ``source`` object."""
    if not isinstance(source, dict):
        raise GameError(400, "source must be an object with game_id, file or pgn")
    keys = [key for key in ("game_id", "file", "pgn") if source.get(key) is not None]
    if len(keys) != 1:
        raise GameError(400, "source must have exactly one of game_id, file or pgn")
    key = keys[0]
    value = source[key]
    if not isinstance(value, str):
        raise GameError(400, f"source.{key} must be a string")
    if key == "game_id":
        text, description = _game_pgn(registry, value)
    elif key == "file":
        path = resolve_pgn_file(registry.root, value, pgn_dirs)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise GameError(500, f"could not read {value}: {exc}") from None
        description = value
    else:
        text, description = value, "pasted PGN"
    return parse_pgn(text), description


def _file_entry(root: Path, path: Path) -> JsonObject | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            game = chess.pgn.read_game(handle)
    except (OSError, ValueError):
        return None
    if game is None:
        return None
    plies = sum(1 for _ in game.mainline_moves())
    white = game.headers.get("White", "?")
    black = game.headers.get("Black", "?")
    result = game.headers.get("Result", "*")
    resolved = path.resolve()
    inside = root.resolve() in resolved.parents
    return {
        "path": resolved.relative_to(root.resolve()).as_posix() if inside else str(resolved),
        "label": f"{white} vs {black} ({result}, {plies} plies)",
        "white": white,
        "black": black,
        "result": result,
        "date": game.headers.get("Date", ""),
        "plies": plies,
    }


# --------------------------------------------------------------------------------------------
# Jobs and the service


@dataclass
class Job:
    id: str
    key: str
    label: str
    depth: int
    multipv: int
    game: chess.pgn.Game
    source: str = ""  # "game <id>", the file, or "pasted PGN": where the moves came from
    created_at: float = field(default_factory=time.time)
    status: Status = "queued"
    done: int = 0
    total: int = 0
    error: str | None = None
    result: JsonObject | None = None
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_dict(self, with_result: bool) -> JsonObject:
        payload: JsonObject = {
            "job_id": self.id,
            "status": self.status,
            "progress": {"done": self.done, "total": self.total},
            "label": self.label,
            "source": self.source,
            "depth": self.depth,
            "multipv": self.multipv,
            "error": self.error,
            "created_at": int(self.created_at * 1000),
        }
        if with_result:
            payload["result"] = self.result
        return payload


class AnalysisService:
    """The analysis API behind ``/api/analysis``: sources, one worker, the job table, the cache."""

    def __init__(
        self,
        registry: Registry,
        cache_dir: Path | None = None,
        pgn_dirs: Iterable[Path] | None = None,
    ) -> None:
        self.registry = registry
        self.root = registry.root
        self.cache_dir = (
            cache_dir if cache_dir is not None else self.root / "data" / "webapp_analysis"
        )
        # The archives offered as sources: the two conventional directories plus wherever this
        # registry saves its games (the same directory unless the server was told otherwise).
        listed = (
            list(pgn_dirs)
            if pgn_dirs is not None
            else [self.root / relative for relative in PGN_DIRS] + [registry.games_dir]
        )
        self.pgn_dirs: list[Path] = []
        for directory in listed:
            if directory not in self.pgn_dirs:
                self.pgn_dirs.append(directory)
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._queue: queue.SimpleQueue[Job] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        self._closing = threading.Event()
        self._files_cache: dict[str, tuple[float, int, JsonObject | None]] = {}

    # -- read-only views ---------------------------------------------------------------------

    def engine_status(self) -> JsonObject:
        status = stockfish_status(self.root)
        # A missing tools/yardstick only matters for seats; the analysis needs just the binary.
        return {
            "available": status["available"],
            "path": status["path"],
            "name": status["name"],
            "reason": None if status["available"] else status["reason"],
        }

    def sources(self) -> JsonObject:
        games: list[JsonObject] = []
        for summary in self.registry.summaries():
            plies = summary["moves"]
            if not isinstance(plies, int) or plies == 0:
                continue  # nothing to grade yet
            result = summary["result"]
            result_text = RESULT_HEADERS[result] if isinstance(result, str) else "*"
            finished = summary["status"] == "finished"
            white, black = summary["white"], summary["black"]
            games.append(
                {
                    "id": summary["id"],
                    "label": f"{white} vs {black} ({result_text}, {plies} plies)",
                    "white": summary["white"],
                    "black": summary["black"],
                    "result": result_text,
                    "plies": plies,
                    "finished": finished,
                }
            )
        games.sort(key=lambda entry: not entry["finished"])  # stable: finished first
        return {"games": games, "files": self._files()}

    def _files(self) -> list[JsonObject]:
        paths: list[tuple[float, Path]] = []
        for directory in self.pgn_dirs:
            if not directory.is_dir():
                continue
            for path in directory.rglob("*.pgn"):
                try:
                    if path.is_file():
                        paths.append((path.stat().st_mtime, path))
                except OSError:
                    continue
        paths.sort(key=lambda item: item[0], reverse=True)
        entries: list[JsonObject] = []
        for mtime, path in paths[:MAX_FILES]:
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            cached = self._files_cache.get(key)
            if cached is None or cached[0] != mtime or cached[1] != size:
                cached = (mtime, size, _file_entry(self.root, path))
                self._files_cache[key] = cached
            if cached[2] is not None:
                entries.append(cached[2])
        return entries

    def jobs(self) -> JsonObject:
        with self._lock:
            jobs = [self._jobs[job_id] for job_id in self._order]
        return {"jobs": [job.to_dict(with_result=False) for job in jobs]}

    def get(self, job_id: str) -> Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise GameError(404, f"no analysis job {job_id!r}")
        return job

    # -- requests ----------------------------------------------------------------------------

    def submit(self, body: JsonObject) -> tuple[Job, bool]:
        """Queue an analysis, or hand back the finished one for the same game and settings."""
        depth = _int_field(body, "depth", DEFAULT_DEPTH, *DEPTH_RANGE)
        multipv = _int_field(body, "multipv", DEFAULT_MULTIPV, *MULTIPV_RANGE)
        game, description = load_source(self.registry, body.get("source"), self.pgn_dirs)
        status = self.engine_status()
        if not status["available"]:
            raise GameError(503, f"analysis needs Stockfish: {status['reason']}")
        if self._closing.is_set():
            raise GameError(503, "the server is shutting down")
        key = cache_key(str(game), depth, multipv)
        white = game.headers.get("White", "White")
        black = game.headers.get("Black", "Black")
        label = f"{white} vs {black} · depth {depth} · {multipv} lines"
        with self._lock:
            for job_id in reversed(self._order):
                existing = self._jobs[job_id]
                if existing.key == key and existing.status in ("queued", "running", "done"):
                    return existing, existing.status == "done"
            job = Job(uuid.uuid4().hex[:12], key, label, depth, multipv, game, description)
            job.total = sum(1 for _ in game.mainline()) + 1  # every position, the final one too
            cached = self._read_cache(key)
            if cached is not None:
                job.status, job.result, job.done = "done", cached, job.total
            self._remember(job)
        if job.status == "done":
            return job, True
        self._ensure_worker()
        self._queue.put(job)
        return job, False

    def cancel(self, job_id: str) -> None:
        job = self.get(job_id)
        with self._lock:
            job.cancel.set()
            if job.status == "queued":
                job.status = "cancelled"

    def shutdown(self) -> None:
        self._closing.set()
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel.set()

    # -- internals ---------------------------------------------------------------------------

    def _remember(self, job: Job) -> None:
        """Under the lock: keep the newest MAX_JOBS_KEPT finished jobs plus everything pending."""
        self._jobs[job.id] = job
        self._order.append(job.id)
        finished = [
            job_id
            for job_id in self._order
            if self._jobs[job_id].status in ("done", "failed", "cancelled")
        ]
        for job_id in finished[: max(0, len(finished) - MAX_JOBS_KEPT)]:
            self._order.remove(job_id)
            del self._jobs[job_id]

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(target=self._work, name="webapp-analysis", daemon=True)
            self._worker.start()

    def _work(self) -> None:
        while not self._closing.is_set():
            try:
                job = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if job.status != "queued":  # cancelled while waiting
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        job.status = "running"
        path = stockfish_path()
        if path is None:
            job.status, job.error = "failed", "the Stockfish binary disappeared"
            return

        def progress(done: int, total: int) -> None:
            job.done, job.total = done, total

        engine: chess.engine.SimpleEngine | None = None
        try:
            engine = chess.engine.SimpleEngine.popen_uci(str(path), timeout=15.0)
            engine.configure({"Threads": 1, "Hash": HASH_MB})
            result = analyse_game(engine, job.game, job.depth, job.multipv, job.cancel, progress)
        except Cancelled:
            job.status = "cancelled"
            return
        except Exception as exc:  # the engine died, an odd PGN...: the job fails, the server lives
            job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
            return
        finally:
            if engine is not None:
                with contextlib.suppress(Exception):  # already gone
                    engine.quit()
        job.result = result
        job.status = "done"
        self._write_cache(job.key, result)

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> JsonObject | None:
        path = self._cache_path(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) and "plies" in payload else None

    def _write_cache(self, key: str, result: JsonObject) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            target = self._cache_path(key)
            temporary = target.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)  # atomic: a reader never sees half a file
        except OSError:
            return  # a read-only data directory costs the cache, not the result


def _int_field(body: JsonObject, key: str, default: int, low: int, high: int) -> int:
    value = body.get(key, default)
    if value is None:
        value = default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise GameError(400, f"{key} must be a number")
    number = int(value)
    if not low <= number <= high:
        raise GameError(400, f"{key} must be between {low} and {high}")
    return number
