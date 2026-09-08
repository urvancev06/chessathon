"""Arena over the collected openings: harness referee as a library, parallel workers, same numbers.

Why this exists. ``harness/arena.py`` cycles only the eight openings in ``harness/rules.py`` and
``harness/`` must not be edited (CLAUDE.md). Games from eight openings are far from independent, so
this tool plays the same kind of match but draws openings from ``data/openings.txt`` (the curated
positions collected by ``tools/collect_openings.py``), runs several games at once when cores are
spare, and prints the same score / margin / Elo numbers with the same formulas, plus what the brief
(section 7.3) asks for on top: draw rate, termination counts, machine load, the lowest clock the
agent reached (the flag-risk indicator), and a Markdown results row plus a JSON record.

Usage, from the repo root::

    .venv/bin/python -m tools.arena_openings --opponent baselines/greedy --games 64 --workers 4 \\
        --label v0.1 --results docs/RESULTS.md --json data/arena/v0.1-greedy.json

Only the harness's public surface is used (``play_match``, ``local``, ``FAILED_TERMINATIONS`` and
the rule constants). The statistics are re-implemented below rather than imported from private
names, and ``tests/test_arena_openings.py`` checks they print exactly what the harness prints.

Numbers measured with more than one worker describe a shared machine: use them for strength, never
for time management (brief section 7.4).
"""

import argparse
import io
import json
import math
import os
import random
import re
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import chess
import chess.engine
import chess.pgn

from harness.referee import FAILED_TERMINATIONS, play_match
from harness.rules import BASE_MS, INCREMENT_MS, OPENINGS, PLY_CAP
from harness.sandbox import local

# These mirror harness/arena.py so the numbers printed here compare directly with `make arena`.
CONFIDENCE = 1.96
FAST_BASE_MS = 10_000
FAST_INCREMENT_MS = 100

DEFAULT_GAMES = 32
DEFAULT_OPENINGS = Path("data/openings.txt")
HARNESS_OPENINGS = "harness"
# The opening order is shuffled once with a constant seed: the same file always gives the same
# schedule, so a run is reproducible from its command line, while consecutive game pairs still
# vary the opening instead of walking the file in whatever order it was collected.
SHUFFLE_SEED = 20260906

RESULTS_COLUMNS = (
    "label",
    "agent",
    "opponent",
    "time control",
    "games",
    "+W =D -L",
    "score",
    "95% interval",
    "Elo (95%)",
    "draw rate",
    "terminations",
    "workers",
    "load start / end",
    "openings",
)

LoadAverage = tuple[float, float, float]


@dataclass(frozen=True)
class Opening:
    name: str
    fen: str


@dataclass(frozen=True)
class Settings:
    """Everything a run needs; ``parse_args`` builds it from the command line."""

    agent: Path
    opponent: Path
    games: int
    base_ms: int
    increment_ms: int
    ply_cap: int
    pgn_dir: Path | None
    openings: str
    workers: int
    seed_offset: int
    label: str
    results: Path | None
    json_path: Path | None
    # ``--env KEY=VALUE`` pairs, applied to this process before any agent starts. The sandbox
    # copies the process environment into every agent, which is how a yardstick seat
    # (tools/yardstick, driven by YARDSTICK_ELO and friends) is configured from the command line.
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GameRecord:
    index: int  # 0-based position of the game in this run
    seed: int  # index + seed_offset: picks the opening and colour, and seeds the baselines
    opening: str
    fen: str
    colour: str  # the agent's colour, "white" or "black"
    result: str  # "white", "black", "draw" or "void", exactly as the referee reports it
    termination: str
    plies: int
    agent_low_clock_ms: float | None  # lowest clock the agent had right after one of its moves
    elapsed_s: float

    @property
    def won(self) -> bool:
        return self.result == self.colour

    @property
    def lost(self) -> bool:
        return self.result in ("white", "black") and self.result != self.colour


@dataclass(frozen=True)
class Statistics:
    wins: int
    draws: int
    losses: int
    played: int
    score: float
    margin: float | None  # None with fewer than two scored games (no spread to estimate)
    elo: float | None  # None unless the whole interval lies strictly inside (0, 1)
    elo_low: float | None
    elo_high: float | None
    draw_rate: float


@dataclass
class RunRecord:
    label: str
    agent: str
    opponent: str
    base_ms: int
    increment_ms: int
    ply_cap: int
    games: int
    workers: int
    seed_offset: int
    openings_source: str
    openings_count: int
    started_at: str
    finished_at: str
    load_start: LoadAverage | None
    load_end: LoadAverage | None
    results: list[GameRecord]
    terminations: dict[str, int]
    failed: dict[str, int]  # the subset of terminations in FAILED_TERMINATIONS
    statistics: Statistics | None
    low_clock_ms: float | None
    low_clock_game: int | None  # 1-based game number, as printed in the per-game lines
    env: dict[str, str] = field(default_factory=dict)  # the --env pairs the agents ran with


# --- statistics: the same formulas as harness/arena.py ---


def elo_from_score(score: float) -> float:
    """Elo difference implied by an expected score, the usual logistic inversion."""
    return 400.0 * math.log10(score / (1.0 - score))


def statistics(wins: int, draws: int, losses: int) -> Statistics:
    """Score, 95% margin and Elo interval, computed exactly as harness/arena.py does.

    The margin is 1.96 standard errors of the mean game score (each game scores 1, 1/2 or 0),
    using the sample variance with the n - 1 correction. The Elo interval is the image of the score
    interval under ``elo_from_score``; it is undefined when the interval touches 0% or 100%, and
    when every game had the same result (zero spread), which is when the harness prints nothing.
    """
    played = wins + draws + losses
    score = (wins + draws / 2) / played
    margin: float | None = None
    if played >= 2:
        spread = wins * (1 - score) ** 2 + draws * (0.5 - score) ** 2 + losses * score**2
        margin = CONFIDENCE * math.sqrt(spread / (played - 1) / played)
    elo = elo_low = elo_high = None
    if margin is not None and margin > 0.0 and score - margin > 0.0 and score + margin < 1.0:
        elo = elo_from_score(score)
        elo_low = elo_from_score(score - margin)
        elo_high = elo_from_score(score + margin)
    return Statistics(
        wins=wins,
        draws=draws,
        losses=losses,
        played=played,
        score=score,
        margin=margin,
        elo=elo,
        elo_low=elo_low,
        elo_high=elo_high,
        draw_rate=draws / played,
    )


def format_statistics(stats: Statistics) -> list[str]:
    """The lines harness/arena.py prints for the same W/D/L, character for character."""
    head = f"+{stats.wins} ={stats.draws} -{stats.losses}, score {stats.score:.1%}"
    if stats.margin is None:
        return [head]
    if stats.margin == 0.0:
        return [f"{head}, every game had the same result"]
    lines = [f"{head} +- {stats.margin:.1%}"]
    if stats.elo is not None and stats.elo_low is not None and stats.elo_high is not None:
        lines.append(
            f"Elo {stats.elo:+.0f}, 95% interval {stats.elo_low:+.0f} to {stats.elo_high:+.0f}"
        )
    return lines


# --- openings and the game schedule ---


def harness_openings() -> list[Opening]:
    return [Opening(name, fen) for name, fen in OPENINGS]


def read_openings_file(path: Path) -> list[Opening]:
    """Parse ``name<TAB>fen`` lines; blank lines and ``#`` comments are skipped, duplicates dropped.

    A bad line is an error rather than a warning: a measuring instrument should refuse to run on
    data it does not understand instead of quietly measuring something else.
    """
    openings: list[Opening] = []
    seen: set[str] = set()
    for number, raw in enumerate(path.read_text().splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, tab, fen = line.partition("\t")
        if not tab:
            raise ValueError(f"{path}:{number}: expected 'name<TAB>fen'")
        fen = fen.strip()
        try:
            board = chess.Board(fen)
        except ValueError as error:
            raise ValueError(f"{path}:{number}: invalid FEN: {error}") from None
        if not board.is_valid():
            raise ValueError(f"{path}:{number}: position is not legal: {board.status()!r}")
        if fen in seen:
            continue
        seen.add(fen)
        openings.append(Opening(name.strip(), fen))
    if not openings:
        raise ValueError(f"{path}: no openings found")
    return openings


def load_openings(spec: str) -> tuple[list[Opening], str]:
    """Return the openings in their fixed shuffled order and a label saying where they came from.

    ``spec`` is a path, or the word ``harness`` for ``harness.rules.OPENINGS``. A missing file also
    falls back to the harness set, loudly, so a typo in the path cannot silently change the run.
    """
    if spec == HARNESS_OPENINGS:
        openings, source = harness_openings(), "harness.rules.OPENINGS"
    else:
        path = Path(spec)
        if path.is_file():
            openings, source = read_openings_file(path), str(path)
        else:
            print(
                f"Openings file {path} not found; using harness.rules.OPENINGS instead", flush=True
            )
            openings, source = harness_openings(), f"harness.rules.OPENINGS ({path} missing)"
    random.Random(SHUFFLE_SEED).shuffle(openings)
    return openings, source


def schedule(
    index: int, seed_offset: int, openings: Sequence[Opening]
) -> tuple[int, Opening, bool]:
    """Seed, opening and colour for one game: games 2k and 2k+1 share an opening, colours swapped.

    The offset shifts the whole schedule (and the seed the baselines read for their tie-breaks),
    so runs with different offsets cover different openings and can be pooled.
    """
    seed = index + seed_offset
    opening = openings[(seed // 2) % len(openings)]
    plays_white = seed % 2 == 0
    return seed, opening, plays_white


# --- one game ---


def agent_clocks_ms(pgn: str, plays_white: bool, increment_ms: int) -> tuple[int, list[float]]:
    """Plies played, and the agent's clock after each of its moves before the increment landed.

    The referee stores ``[%clk]`` after adding the increment. Subtracting it recovers the low point
    the clock actually reached, which is the number a flag would have been judged on.
    """
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        return 0, []
    board = game.board()
    agent_colour = chess.WHITE if plays_white else chess.BLACK
    clocks: list[float] = []
    plies = 0
    for node in game.mainline():
        remaining = node.clock()
        if board.turn == agent_colour and remaining is not None:
            clocks.append(remaining * 1000.0 - increment_ms)
        board.push(node.move)
        plies += 1
    return plies, clocks


# One agent log line per move, as `agent.py` writes it: `m e2e4 d 12/30 n 805926 t 805 ... e +45`.
# Tokens are read by name, so a field appearing or disappearing does not break the parse.
AGENT_LINE_RE = re.compile(r"^m (?P<uci>[a-h][1-8][a-h][1-8][qrbn]?) (?P<rest>.*)$")


def agent_move_reports(stderr_log: str) -> list[dict[str, str]]:
    """The engine's own per-move report lines, in order, as token dictionaries."""
    reports: list[dict[str, str]] = []
    for line in stderr_log.splitlines():
        match = AGENT_LINE_RE.match(line.strip())
        if match is None:
            continue
        tokens = match.group("rest").split()
        fields = dict(zip(tokens[::2], tokens[1::2], strict=False))
        fields["m"] = match.group("uci")
        reports.append(fields)
    return reports


def stamp_agent_evaluations(pgn: str, reports: Sequence[dict[str, str]], plays_white: bool) -> str:
    """Write the engine's own score and depth into the PGN, beside the clocks the referee wrote.

    `[%eval]` is python-chess's native comment, so every PGN viewer and our own analysis tool read
    it without a parser. Having the engine's score and Stockfish's score on the same move turns
    finding a blunder into a subtraction instead of a manual reproduction.
    """
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None or not reports:
        return pgn
    ours = 0
    for index, node in enumerate(game.mainline()):
        if (index % 2 == 0) != plays_white:  # not our move
            continue
        if ours >= len(reports):
            break
        report = reports[ours]
        ours += 1
        raw = report.get("e")
        if raw is None:  # the engine does not report a score yet
            continue
        try:
            centipawns = int(raw)
            depth = int(report.get("d", "0").split("/")[0])
        except ValueError:
            continue
        # Scores are from the side to move; PovScore records whose point of view it is.
        node.set_eval(chess.engine.PovScore(chess.engine.Cp(centipawns), node.parent.turn()), depth)
    return str(game)


def play_game(
    index: int, settings: Settings, openings: Sequence[Opening]
) -> tuple[GameRecord, str]:
    """Play one game through the harness referee and return its record and PGN."""
    seed, opening, plays_white = schedule(index, settings.seed_offset, openings)
    agent = settings.agent.resolve()
    opponent = settings.opponent.resolve()
    white, black = (agent, opponent) if plays_white else (opponent, agent)
    started = time.perf_counter()
    # Bound to names so the agent's own log can be read back after the game; `play_match` stops
    # both agents, which is what fills `stderr_log`.
    white_agent, black_agent = local(white, seed), local(black, seed)
    ours = white_agent if plays_white else black_agent
    outcome = play_match(
        white_agent,
        black_agent,
        settings.base_ms,
        settings.increment_ms,
        ply_cap=settings.ply_cap,
        start_fen=opening.fen,
    )
    elapsed = time.perf_counter() - started
    plies, clocks = agent_clocks_ms(outcome.pgn, plays_white, settings.increment_ms)
    record = GameRecord(
        index=index,
        seed=seed,
        opening=opening.name,
        fen=opening.fen,
        colour="white" if plays_white else "black",
        result=outcome.result,
        termination=outcome.termination,
        plies=plies,
        agent_low_clock_ms=min(clocks) if clocks else None,
        elapsed_s=elapsed,
    )
    stamped = stamp_agent_evaluations(outcome.pgn, agent_move_reports(ours.stderr_log), plays_white)
    return record, stamped


def describe_game(record: GameRecord, played: int) -> str:
    low = "no move" if record.agent_low_clock_ms is None else f"{record.agent_low_clock_ms:.0f} ms"
    return (
        f"Game {record.index + 1}/{played} (seed {record.seed}), {record.opening} as "
        f"{record.colour}, {record.result} by {record.termination}, {record.plies} plies, "
        f"low clock {low}, {record.elapsed_s:.1f} s"
    )


# --- the run ---


def load_average() -> LoadAverage | None:
    try:
        one, five, fifteen = os.getloadavg()
    except (AttributeError, OSError):  # not every platform reports a load average
        return None
    return (one, five, fifteen)


def format_load(load: LoadAverage | None) -> str:
    return "n/a" if load is None else " ".join(f"{value:.2f}" for value in load)


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run(settings: Settings) -> RunRecord:
    """Play the whole match, print progress and the summary, write the outputs, return the record.

    Games run on a thread pool: every game already runs both agents as separate processes through
    the harness sandbox, so threads only wait on pipes and cost nothing. Results are printed in
    game order as they complete, whichever order the workers finish in.
    """
    openings, source = load_openings(settings.openings)
    played = max(2, settings.games - settings.games % 2)
    if played != settings.games:
        print(f"Playing {played} games so both colours get the same number", flush=True)
    if settings.pgn_dir is not None:
        settings.pgn_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(settings.env)  # before the first agent starts; the sandbox copies it

    started_at = now_iso()
    load_start = load_average()
    print(
        f"{settings.agent} vs {settings.opponent}: {played} games at "
        f"{settings.base_ms}+{settings.increment_ms} ms, ply cap {settings.ply_cap}, "
        f"{settings.workers} worker(s), openings from {source} ({len(openings)}), "
        f"seed offset {settings.seed_offset}, load {format_load(load_start)}"
        + (f", env {format_env(settings.env)}" if settings.env else ""),
        flush=True,
    )

    results: list[GameRecord] = []
    waiting: dict[int, tuple[GameRecord, str]] = {}
    next_to_print = 0
    with ThreadPoolExecutor(max_workers=settings.workers) as pool:
        futures = [pool.submit(play_game, index, settings, openings) for index in range(played)]
        for future in as_completed(futures):
            record, pgn = future.result()
            waiting[record.index] = (record, pgn)
            # Flush every finished game that is next in index order, so the log reads in order.
            while next_to_print in waiting:
                record, pgn = waiting.pop(next_to_print)
                print(describe_game(record, played), flush=True)
                if settings.pgn_dir is not None:
                    destination = settings.pgn_dir / f"game-{record.seed + 1:04d}.pgn"
                    destination.write_text(pgn + "\n")
                results.append(record)
                next_to_print += 1

    load_end = load_average()
    record_of_run = summarise(
        settings, played, source, len(openings), results, load_start, load_end
    )
    record_of_run.started_at = started_at
    print_summary(settings, record_of_run)
    if settings.results is not None:
        append_results_row(settings.results, record_of_run)
    if settings.json_path is not None:
        write_json(settings.json_path, record_of_run)
    return record_of_run


def summarise(
    settings: Settings,
    played: int,
    source: str,
    openings_count: int,
    results: Sequence[GameRecord],
    load_start: LoadAverage | None,
    load_end: LoadAverage | None,
) -> RunRecord:
    scored = [game for game in results if game.result != "void"]
    wins = sum(1 for game in scored if game.won)
    losses = sum(1 for game in scored if game.lost)
    draws = sum(1 for game in scored if game.result == "draw")
    terminations: dict[str, int] = {}
    for game in results:
        terminations[game.termination] = terminations.get(game.termination, 0) + 1
    failed = {name: count for name, count in terminations.items() if name in FAILED_TERMINATIONS}

    low_clock_ms: float | None = None
    low_clock_game: int | None = None
    for game in results:
        if game.agent_low_clock_ms is None:
            continue
        if low_clock_ms is None or game.agent_low_clock_ms < low_clock_ms:
            low_clock_ms, low_clock_game = game.agent_low_clock_ms, game.index + 1

    return RunRecord(
        label=settings.label,
        agent=str(settings.agent),
        opponent=str(settings.opponent),
        base_ms=settings.base_ms,
        increment_ms=settings.increment_ms,
        ply_cap=settings.ply_cap,
        games=played,
        workers=settings.workers,
        seed_offset=settings.seed_offset,
        openings_source=source,
        openings_count=openings_count,
        started_at="",
        finished_at=now_iso(),
        load_start=load_start,
        load_end=load_end,
        results=list(results),
        terminations=terminations,
        failed=failed,
        statistics=statistics(wins, draws, losses) if scored else None,
        low_clock_ms=low_clock_ms,
        low_clock_game=low_clock_game,
        env=dict(settings.env),
    )


def print_summary(settings: Settings, record: RunRecord) -> None:
    print(f"\n{settings.agent} vs {settings.opponent}")
    print(
        f"Time control {record.base_ms}+{record.increment_ms} ms, {record.games} games, "
        f"{record.workers} worker(s), openings from {record.openings_source} "
        f"({record.openings_count})"
    )
    print("Terminations " + ", ".join(f"{k} {v}" for k, v in record.terminations.items()))
    if record.statistics is not None:
        for line in format_statistics(record.statistics):
            print(line)
        print(f"Draw rate {record.statistics.draw_rate:.1%}")
    if record.low_clock_ms is not None:
        print(
            f"Lowest agent clock {record.low_clock_ms:.0f} ms after its move, before the "
            f"increment, in game {record.low_clock_game}"
        )
    print(
        f"Load average start {format_load(record.load_start)}, end {format_load(record.load_end)}"
    )
    if record.workers > 1:
        print("Note: games shared the machine, so clock figures measure load as well as the agent")
    print("", flush=True)


# --- outputs ---


def format_env(env: dict[str, str]) -> str:
    return " ".join(f"{key}={value}" for key, value in env.items())


def markdown_cell(text: str) -> str:
    return text.replace("|", "\\|") or "-"


def results_row(record: RunRecord) -> str:
    """One Markdown table row in the shape the brief's results tables use (section 7.3, 12)."""
    stats = record.statistics
    if stats is None:
        wdl = score = interval = elo = draw_rate = "-"
    else:
        wdl = f"+{stats.wins} ={stats.draws} -{stats.losses}"
        score = f"{stats.score:.1%}"
        interval = "-" if stats.margin is None else f"±{stats.margin:.1%}"
        elo = "-"
        if stats.elo is not None and stats.elo_low is not None and stats.elo_high is not None:
            elo = f"{stats.elo:+.0f} ({stats.elo_low:+.0f} to {stats.elo_high:+.0f})"
        draw_rate = f"{stats.draw_rate:.1%}"
    # The opponent cell carries the environment it ran with: "tools/yardstick" alone says
    # nothing about the level, and the row has to stand on its own in the results table.
    opponent = record.opponent
    if record.env:
        opponent = f"{opponent} ({format_env(record.env)})"
    cells = (
        record.label,
        record.agent,
        opponent,
        f"{record.base_ms / 1000:g}+{record.increment_ms / 1000:g} s",
        str(record.games),
        wdl,
        score,
        interval,
        elo,
        draw_rate,
        ", ".join(f"{k} {v}" for k, v in record.terminations.items()),
        str(record.workers),
        f"{format_load(record.load_start)} / {format_load(record.load_end)}",
        record.openings_source,
    )
    return "| " + " | ".join(markdown_cell(cell) for cell in cells) + " |"


def _ends_with_table_row(text: str) -> bool:
    """Does the file already end inside a Markdown table, so a row appended now renders as one?"""
    for line in reversed(text.split("\n")):
        if line.strip():
            return line.startswith("|")
    return False


def append_results_row(path: Path, record: RunRecord) -> None:
    """Append the row, writing a fresh table header above it whenever the file does not end in one.

    ``docs/RESULTS.md`` is append-only and chronological: each run is a dated section of prose with
    its rows beneath, and that ordering is the point -- a row means little apart from the paragraph
    saying what was run and why. So rows keep landing at the end of the file rather than being
    collected into one table elsewhere.

    What was wrong was only the rendering. A row appended straight after a paragraph has no table
    header above it, and Markdown shows it as a line of literal pipes: the measurement is in the
    file but invisible in the rendered document, which is how twenty-five rows accumulated
    unnoticed. Emitting the header whenever the file does not already end inside a table fixes that
    without moving a single measurement.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else ""
    with path.open("a") as handle:
        if not _ends_with_table_row(text):
            if text and not text.endswith("\n"):
                handle.write("\n")
            if text:
                handle.write("\n")
            handle.write("| " + " | ".join(RESULTS_COLUMNS) + " |\n")
            handle.write("|" + "---|" * len(RESULTS_COLUMNS) + "\n")
        handle.write(results_row(record) + "\n")


def write_json(path: Path, record: RunRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(record), indent=2) + "\n")


# --- command line ---


def positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {text}")
    return value


def non_negative_int(text: str) -> int:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"expected a non-negative integer, got {text}")
    return value


def env_pair(text: str) -> tuple[str, str]:
    key, separator, value = text.partition("=")
    if not separator or not key.strip():
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    return key.strip(), value


def even_non_negative_int(text: str) -> int:
    value = non_negative_int(text)
    if value % 2:
        raise argparse.ArgumentTypeError(
            f"expected an even number, got {text}: games 2k and 2k+1 play one opening with both "
            "colours, and an odd offset would split those pairs"
        )
    return value


def parse_args(argv: Sequence[str] | None = None) -> Settings:
    parser = argparse.ArgumentParser(
        description="Score an agent over many games drawn from the collected openings.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--agent", type=Path, default=Path("."), help="directory with agent.py")
    parser.add_argument("--opponent", type=Path, default=Path("baselines/greedy"))
    parser.add_argument(
        "--games",
        type=positive_int,
        default=DEFAULT_GAMES,
        help="games to play; rounded down to an even number so each colour is played equally",
    )
    parser.add_argument("--base-ms", type=positive_int, default=FAST_BASE_MS)
    parser.add_argument("--increment-ms", type=non_negative_int, default=FAST_INCREMENT_MS)
    parser.add_argument(
        "--real-clock",
        action="store_true",
        help=f"play at the event clock, {BASE_MS}+{INCREMENT_MS} ms, overriding the two above",
    )
    parser.add_argument("--ply-cap", type=positive_int, default=PLY_CAP)
    parser.add_argument("--pgn-dir", type=Path, help="write game-NNNN.pgn files here")
    parser.add_argument(
        "--openings",
        default=str(DEFAULT_OPENINGS),
        help="name<TAB>fen file, or 'harness' for harness.rules.OPENINGS (also the fallback "
        "when the file is missing)",
    )
    parser.add_argument(
        "--workers",
        type=positive_int,
        default=1,
        help="games to run at once; more than one makes clock figures meaningless",
    )
    parser.add_argument(
        "--seed-offset",
        type=even_non_negative_int,
        default=0,
        help="added to every game index before choosing the opening and the baseline seed",
    )
    parser.add_argument(
        "--env",
        type=env_pair,
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="set an environment variable for every agent (repeatable), e.g. YARDSTICK_ELO=1600 "
        "for --opponent tools/yardstick; recorded in the JSON record and the results row",
    )
    parser.add_argument("--label", default="", help="free text copied into the results row")
    parser.add_argument("--results", type=Path, help="append one Markdown table row to this file")
    parser.add_argument("--json", dest="json_path", type=Path, help="write the full run record")
    arguments = parser.parse_args(argv)
    base_ms, increment_ms = arguments.base_ms, arguments.increment_ms
    if arguments.real_clock:
        base_ms, increment_ms = BASE_MS, INCREMENT_MS
    return Settings(
        agent=arguments.agent,
        opponent=arguments.opponent,
        games=arguments.games,
        base_ms=base_ms,
        increment_ms=increment_ms,
        ply_cap=arguments.ply_cap,
        pgn_dir=arguments.pgn_dir,
        openings=arguments.openings,
        workers=arguments.workers,
        seed_offset=arguments.seed_offset,
        label=arguments.label,
        results=arguments.results,
        json_path=arguments.json_path,
        env=dict(arguments.env),
    )


def main(argv: Sequence[str] | None = None) -> None:
    record = run(parse_args(argv))
    if record.failed:
        # Same exit path as harness/arena.py: a game that did not finish cleanly fails the run.
        raise SystemExit(
            "A game did not finish cleanly: "
            + ", ".join(f"{name} {count}" for name, count in record.failed.items())
        )


if __name__ == "__main__":
    main()
