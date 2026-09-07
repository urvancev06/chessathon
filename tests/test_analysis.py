"""Tests for tools/webapp/analysis.py.

The formulas (win%, centipawn loss, judgements, accuracy, side summaries) are checked without an
engine. The end-to-end tests drive the HTTP API against a real Stockfish and are skipped when no
binary resolves (``YARDSTICK_ENGINE``, ``~/.local/opt/stockfish/stockfish``, or PATH): the engine
is a local instrument, never something the repository provides.
"""

from __future__ import annotations

import io
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn
import pytest

from tools.webapp import analysis
from tools.webapp.analysis import AnalysisService, Candidate, Eval, PlyReport
from tools.webapp.games import GameError, Registry, stockfish_path
from tools.webapp.server import run_in_thread, serve

ROOT = Path(__file__).resolve().parent.parent
JsonDict = dict[str, Any]
STOCKFISH = stockfish_path()
needs_stockfish = pytest.mark.skipif(STOCKFISH is None, reason="no local Stockfish binary")

# Eight plies with the referee's %clk comments, so clock_after has something to read.
SHORT_PGN = """[Event "Test"]
[White "Alice"]
[Black "Bob"]
[Result "*"]

1. e4 { [%clk 0:01:59] } e5 { [%clk 0:01:58] } 2. Nf3 { [%clk 0:01:57] } Nc6 { [%clk 0:01:56] }
3. Bb5 { [%clk 0:01:55] } a6 { [%clk 0:01:54] } 4. Ba4 { [%clk 0:01:53] } Nf6 { [%clk 0:01:52] } *
"""
FOOLS_MATE = "1. f3 e5 2. g4 Qh4# 0-1"
# White plays the engine's first choices, Black two moves no engine lists (the second a blunder).
LOPSIDED_PGN = '[White "Good"]\n[Black "Bad"]\n\n1. e4 f6 2. d4 g5 3. Qh5# 1-0'


# --------------------------------------------------------------------------------------------
# Formulas


def test_win_percent_is_lichess_s_curve() -> None:
    assert analysis.win_percent(0) == pytest.approx(50.0)
    assert analysis.win_percent(100) == pytest.approx(59.1, abs=0.1)
    assert analysis.win_percent(1000) == pytest.approx(97.5, abs=0.1)
    for cp in (-800, -50, 0, 30, 400):
        assert analysis.win_percent(cp) + analysis.win_percent(-cp) == pytest.approx(100.0)
    values = [analysis.win_percent(cp) for cp in range(-1000, 1001, 50)]
    assert values == sorted(values) and values[0] > 0.0 and values[-1] < 100.0


def test_cp_loss_is_non_negative_and_capped() -> None:
    assert analysis.cp_loss(50, 20) == 30
    assert analysis.cp_loss(20, 50) == 0  # the engine's second opinion was better: never negative
    assert analysis.cp_loss(1000, -1000) == 1000
    assert analysis.cp_loss(0, 0) == 0


def test_accuracy_curve() -> None:
    assert analysis.accuracy(0.0) == pytest.approx(100.0, abs=0.01)
    assert analysis.accuracy(-5.0) == 100.0  # a gain clamps at the top
    assert analysis.accuracy(100.0) == 0.0  # and a total collapse at the bottom
    ten = analysis.accuracy(10.0)
    assert 60.0 < ten < 70.0
    assert ten == pytest.approx(103.1668 * math.exp(-0.4354) - 3.1669)


def test_judgement_thresholds() -> None:
    assert analysis.judge(30.0, None) == "blunder"
    assert analysis.judge(45.0, 1) == "blunder"  # the drop decides before the rank does
    assert analysis.judge(20.0, 2) == "mistake"
    assert analysis.judge(29.9, 2) == "mistake"
    assert analysis.judge(10.0, 2) == "inaccuracy"
    assert analysis.judge(5.0, 1) == "best"  # the engine's first choice
    assert analysis.judge(-2.0, None) == "best"  # nothing lost, whatever the rank
    assert analysis.judge(0.0, 3) == "best"
    assert analysis.judge(5.0, 2) == "good"
    assert analysis.judge(9.9, None) == "good"


def test_eval_folds_mates_and_flips_for_black() -> None:
    assert Eval(35, None).as_cp() == 35
    assert Eval(None, 3).as_cp() == 1000 and Eval(None, -1).as_cp() == -1000
    assert Eval(35, None).for_mover(chess.WHITE) == 35
    assert Eval(35, None).for_mover(chess.BLACK) == -35
    assert Eval(None, -2).for_mover(chess.BLACK) == 1000
    assert Eval(None, 3).to_dict() == {"cp": None, "mate": 3, "pov": "white"}

    assert analysis.eval_from_score(chess.engine.Cp(-40)) == Eval(-40, None)
    assert analysis.eval_from_score(chess.engine.Mate(3)) == Eval(None, 3)
    assert analysis.eval_from_score(chess.engine.Mate(-2)) == Eval(None, -2)
    # "mate 0" carries no sign of its own; it becomes the capped centipawn value.
    assert analysis.eval_from_score(chess.engine.MateGiven) == Eval(1000, None)
    assert analysis.eval_from_score(chess.engine.Mate(0)) == Eval(-1000, None)
    assert analysis.eval_from_score(chess.engine.Cp(5000)) == Eval(5000, None)


def test_terminal_eval() -> None:
    board = chess.Board()
    assert analysis.terminal_eval(board) is None
    for san in ("f3", "e5", "g4", "Qh4#"):
        board.push_san(san)
    assert analysis.terminal_eval(board) == Eval(-1000, None)  # Black delivered mate
    stalemate = chess.Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
    assert analysis.terminal_eval(stalemate) == Eval(0, None)
    mated_black = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
    assert analysis.terminal_eval(mated_black) == Eval(1000, None)


def _candidate(board: chess.Board, san: str, eval_: Eval) -> Candidate:
    move = board.parse_san(san)
    return Candidate(move.uci(), san, eval_, (san,))


def test_ply_report_grades_from_the_mover_s_side() -> None:
    board = chess.Board()
    board.push_san("e4")  # Black to move; scores stay White-POV, grades are Black's
    candidates = (
        _candidate(board, "c5", Eval(20, None)),
        _candidate(board, "e5", Eval(30, None)),
        _candidate(board, "e6", Eval(40, None)),
    )
    after = board.copy()
    after.push_san("e5")
    report = analysis.ply_report(
        board, board.parse_san("e5"), 2, candidates, Eval(50, None), after.fen(), 118.5
    )
    assert report.mover == "black" and report.move_number == 1 and report.ply == 2
    assert report.san == "e5" and report.uci == "e7e5"
    assert report.fen_before == board.fen() and report.fen_after == after.fen()
    assert report.rank == 2 and report.best.san == "c5"
    assert report.eval_before == Eval(20, None) and report.eval_after == Eval(50, None)
    # Black's side of White's +20 is -20; the played move left Black at -50: 30 cp given away.
    assert report.win_before == pytest.approx(analysis.win_percent(-20))
    assert report.win_after == pytest.approx(analysis.win_percent(-50))
    assert report.cp_loss == 30
    assert report.judgement == "good" and 80.0 < report.accuracy < 100.0
    assert report.clock_after == 118.5
    payload: Any = report.to_dict()
    assert payload["top"][0] == {"uci": "c7c5", "san": "c5", "eval": Eval(20, None).to_dict()}
    assert payload["best"]["line_san"] == ["c5"] and payload["eval_before"]["pov"] == "white"

    # A move outside the list has no rank; a big drop is a blunder even when it is "best".
    off_list = analysis.ply_report(
        board, board.parse_san("a5"), 2, candidates, Eval(-15, None), after.fen(), None
    )
    assert off_list.rank is None and off_list.cp_loss == 0 and off_list.judgement == "best"
    collapse = analysis.ply_report(
        board, board.parse_san("c5"), 2, candidates, Eval(None, 5), after.fen(), None
    )
    assert collapse.rank == 1 and collapse.cp_loss == 980 and collapse.judgement == "blunder"


def _report(mover: str, rank: int | None, cp_loss: int, drop: float, judgement: str) -> PlyReport:
    """A hand-made ply for the summary: only the graded fields matter."""
    board = chess.Board()
    move = next(iter(board.legal_moves))
    candidate = Candidate(move.uci(), board.san(move), Eval(0, None))
    return PlyReport(
        ply=1,
        move_number=1,
        mover="white" if mover == "white" else "black",
        san=candidate.san,
        uci=candidate.uci,
        fen_before=board.fen(),
        fen_after=board.fen(),
        eval_before=Eval(0, None),
        eval_after=Eval(0, None),
        best=candidate,
        top=(candidate,),
        rank=rank,
        cp_loss=cp_loss,
        win_before=50.0,
        win_after=50.0 - drop,
        accuracy=analysis.accuracy(drop),
        judgement=analysis.judge(drop, rank),
        clock_after=None,
    )


def test_summary_aggregates_one_side() -> None:
    plies = [
        _report("white", 1, 0, 0.0, "best"),
        _report("white", 2, 20, 5.0, "good"),
        _report("white", 3, 60, 12.0, "inaccuracy"),
        _report("white", None, 200, 25.0, "mistake"),
        _report("white", None, 500, 40.0, "blunder"),
        _report("black", 1, 10, 0.0, "best"),
        _report("black", 4, 30, 8.0, "good"),
    ]
    white = analysis.summarise(plies, "white", "Alice")
    assert white["name"] == "Alice" and white["moves"] == 5
    assert white["best_moves"] == 1 and white["best_move_pct"] == 20.0
    assert white["top3_moves"] == 3 and white["top3_pct"] == 60.0
    assert white["acpl"] == pytest.approx((0 + 20 + 60 + 200 + 500) / 5)
    expected = sum(analysis.accuracy(d) for d in (0.0, 5.0, 12.0, 25.0, 40.0)) / 5
    assert white["accuracy"] == pytest.approx(expected, abs=0.01)
    assert (white["inaccuracies"], white["mistakes"], white["blunders"]) == (1, 1, 1)
    black = analysis.summarise(plies, "black", "Bob")
    assert black["moves"] == 2 and black["best_moves"] == 1 and black["top3_moves"] == 1
    assert black["acpl"] == 20.0 and black["blunders"] == 0
    empty = analysis.summarise([], "white", "Nobody")
    assert empty["moves"] == 0 and empty["acpl"] == 0.0 and empty["best_move_pct"] == 0.0


def test_summary_counts_each_side_separately() -> None:
    """Regression: best-move and top-3 counts come from each side's own moves, never from the
    whole game (the two sides here have different rank distributions, so the counts differ)."""
    white_ranks = [1, 1, 2, None]
    black_ranks = [None, None, 3, 1]
    plies = []
    for white_rank, black_rank in zip(white_ranks, black_ranks, strict=True):
        plies.append(_report("white", white_rank, 0 if white_rank == 1 else 20, 2.0, "good"))
        plies.append(_report("black", black_rank, 0 if black_rank == 1 else 80, 8.0, "good"))
    white = analysis.summarise(plies, "white", "W")
    black = analysis.summarise(plies, "black", "B")
    assert white["moves"] == 4 and black["moves"] == 4
    assert (white["best_moves"], white["top3_moves"]) == (2, 3)
    assert (black["best_moves"], black["top3_moves"]) == (1, 2)
    assert (white["best_move_pct"], white["top3_pct"]) == (50.0, 75.0)
    assert (black["best_move_pct"], black["top3_pct"]) == (25.0, 50.0)
    assert white["acpl"] == 10.0 and black["acpl"] == 60.0


# --------------------------------------------------------------------------------------------
# Sources, without an engine


def test_parse_pgn_rejects_what_cannot_be_graded() -> None:
    game = analysis.parse_pgn(SHORT_PGN)
    assert sum(1 for _ in game.mainline_moves()) == 8
    assert game.headers["White"] == "Alice"
    with pytest.raises(GameError) as caught:
        analysis.parse_pgn("")
    assert caught.value.status == 400
    with pytest.raises(GameError, match="no moves"):
        analysis.parse_pgn("garbage [")
    with pytest.raises(GameError, match=r"(?i)fen"):
        analysis.parse_pgn('[SetUp "1"]\n[FEN "not a fen"]\n\n1. e4 *\n')
    with pytest.raises(GameError, match="too large"):
        analysis.parse_pgn("1. e4 e5 " * 200_000)


def test_resolve_pgn_file_stays_inside_the_allowed_directories(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    inside = archive / "one.pgn"
    inside.write_text(SHORT_PGN)
    assert analysis.resolve_pgn_file(ROOT, str(inside), [archive]) == inside.resolve()
    with pytest.raises(GameError, match="outside"):
        analysis.resolve_pgn_file(ROOT, str(inside))  # absolute, but no directory allows it
    with pytest.raises(GameError, match="outside"):
        analysis.resolve_pgn_file(ROOT, "../etc/passwd", [archive])
    with pytest.raises(GameError, match=r"\.pgn"):
        analysis.resolve_pgn_file(ROOT, "README.md", [archive])
    with pytest.raises(GameError) as caught:
        analysis.resolve_pgn_file(ROOT, "data/pgn/does-not-exist.pgn", [archive])
    assert caught.value.status == 404
    with pytest.raises(GameError, match="required"):
        analysis.resolve_pgn_file(ROOT, "  ", [archive])


def test_cache_key_depends_on_the_settings() -> None:
    game = analysis.parse_pgn(SHORT_PGN)
    base = analysis.cache_key(str(game), 18, 3)
    assert base != analysis.cache_key(str(game), 20, 3)
    assert base != analysis.cache_key(str(game), 18, 1)
    assert base == analysis.cache_key(str(analysis.parse_pgn(SHORT_PGN)), 18, 3)


def test_load_source_validation(tmp_path: Path) -> None:
    registry = Registry(games_dir=tmp_path)
    for source in (None, "x", {}, {"game_id": "a", "pgn": "b"}, {"pgn": 5}):
        with pytest.raises(GameError) as caught:
            analysis.load_source(registry, source)
        assert caught.value.status == 400
    with pytest.raises(GameError) as missing:
        analysis.load_source(registry, {"game_id": "nope"})
    assert missing.value.status == 404
    game, description = analysis.load_source(registry, {"pgn": SHORT_PGN})
    assert description == "pasted PGN" and game.headers["Black"] == "Bob"


# --------------------------------------------------------------------------------------------
# End to end, with Stockfish


class Client:
    def __init__(self, base: str) -> None:
        self.base = base

    def call(self, method: str, path: str, body: object | None = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def wait(self, job_id: str, timeout: float = 30.0) -> JsonDict:
        deadline = time.monotonic() + timeout
        state: JsonDict = {}
        while time.monotonic() < deadline:
            status, state = self.call("GET", f"/api/analysis/{job_id}")
            assert status == 200, state
            if state["status"] in ("done", "failed", "cancelled"):
                return state
            time.sleep(0.05)
        raise AssertionError(f"analysis {job_id} did not finish: {state.get('status')}")


@pytest.fixture(scope="module")
def archive(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("pgn")


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Registry]:
    registry = Registry(games_dir=tmp_path_factory.mktemp("games"), max_engines=2)
    yield registry
    registry.shutdown()


@pytest.fixture(scope="module")
def service(
    registry: Registry, archive: Path, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[AnalysisService]:
    service = AnalysisService(
        registry, cache_dir=tmp_path_factory.mktemp("cache"), pgn_dirs=[archive]
    )
    yield service
    service.shutdown()


@pytest.fixture(scope="module")
def client(registry: Registry, service: AnalysisService) -> Iterator[Client]:
    server, _ = serve("127.0.0.1", 0, registry, analysis=service)
    thread = run_in_thread(server)
    host, port = server.server_address[0], server.server_address[1]
    assert isinstance(host, str)
    yield Client(f"http://{host}:{port}")
    server.shutdown()
    server.server_close()
    thread.join(5)


def test_engine_endpoint_reports_availability(client: Client) -> None:
    status, engine = client.call("GET", "/api/analysis/engine")
    assert status == 200
    assert set(engine) == {"available", "path", "name", "reason"}
    if STOCKFISH is None:
        assert engine["available"] is False and engine["reason"]
    else:
        assert engine["available"] is True and engine["path"] == str(STOCKFISH)
        assert isinstance(engine["name"], str) and engine["name"] and engine["reason"] is None
    status, info = client.call("GET", "/api/info")
    assert status == 200
    assert info["analysis"] == {"available": engine["available"], "name": engine["name"]}


def test_bad_analysis_requests(client: Client) -> None:
    status, payload = client.call("POST", "/api/analysis", {"source": {"pgn": "garbage ["}})
    assert status == 400 and "moves" in payload["error"]
    status, payload = client.call("POST", "/api/analysis", {"source": {"file": "../x.pgn"}})
    assert status == 400 and "outside" in payload["error"]
    status, payload = client.call(
        "POST", "/api/analysis", {"source": {"pgn": SHORT_PGN}, "depth": 99}
    )
    assert status == 400 and "depth" in payload["error"]
    status, payload = client.call("POST", "/api/analysis", {})
    assert status == 400
    status, payload = client.call("GET", "/api/analysis/nope")
    assert status == 404
    status, payload = client.call("POST", "/api/analysis/engine")
    assert status == 405


def _check_result(result: JsonDict, plies: int, multipv: int) -> None:
    assert set(result) == {"engine", "headers", "start_fen", "pgn", "plies", "summary"}
    replay = chess.pgn.read_game(io.StringIO(result["pgn"]))
    assert replay is not None and not replay.errors
    assert [node.san() for node in replay.mainline()] == [ply["san"] for ply in result["plies"]]
    assert result["engine"]["depth"] == 8 and result["engine"]["multipv"] == multipv
    assert result["engine"]["name"].startswith("Stockfish")
    assert set(result["headers"]) == {"White", "Black", "Result", "Date", "Termination", "Event"}
    assert len(result["plies"]) == plies
    board = chess.Board(result["start_fen"])
    for index, ply in enumerate(result["plies"], start=1):
        assert ply["ply"] == index
        assert ply["mover"] == ("white" if board.turn == chess.WHITE else "black")
        assert ply["move_number"] == board.fullmove_number
        assert ply["fen_before"] == board.fen()
        move = chess.Move.from_uci(ply["uci"])
        assert move in board.legal_moves and board.san(move) == ply["san"]
        board.push(move)
        assert ply["fen_after"] == board.fen()
        if index < plies:
            assert ply["fen_after"] == result["plies"][index]["fen_before"]
            assert ply["eval_after"] == result["plies"][index]["eval_before"]
        for evaluation in (ply["eval_before"], ply["eval_after"], ply["best"]["eval"]):
            assert evaluation["pov"] == "white"
            assert (evaluation["cp"] is None) != (evaluation["mate"] is None)
        top = ply["top"]
        assert 1 <= len(top) <= multipv and top[0]["uci"] == ply["best"]["uci"]
        assert ply["best"]["eval"] == ply["eval_before"] and len(ply["best"]["line_san"]) <= 8
        assert ply["best"]["line_san"][:1] == [ply["best"]["san"]]
        listed = [candidate["uci"] for candidate in top]
        if ply["rank"] is None:
            assert ply["uci"] not in listed
        else:
            assert listed[ply["rank"] - 1] == ply["uci"]
        assert 0 <= ply["cp_loss"] <= 1000
        assert 0.0 <= ply["win_before"] <= 100.0 and 0.0 <= ply["win_after"] <= 100.0
        assert 0.0 <= ply["accuracy"] <= 100.0
        assert ply["judgement"] in {"best", "good", "inaccuracy", "mistake", "blunder"}
        drop = ply["win_before"] - ply["win_after"]
        if drop >= 30.0:
            assert ply["judgement"] == "blunder"
        elif ply["rank"] == 1 and drop < 10.0:
            assert ply["judgement"] == "best"
    for side in ("white", "black"):
        own = [ply for ply in result["plies"] if ply["mover"] == side]
        summary = result["summary"][side]
        assert summary["moves"] == len(own)
        assert summary["best_moves"] == sum(1 for ply in own if ply["rank"] == 1)
        assert summary["top3_moves"] == sum(
            1 for ply in own if ply["rank"] is not None and ply["rank"] <= 3
        )
        assert summary["inaccuracies"] + summary["mistakes"] + summary["blunders"] == sum(
            1 for ply in own if ply["judgement"] in ("inaccuracy", "mistake", "blunder")
        )
        if own:
            assert summary["acpl"] == pytest.approx(
                sum(ply["cp_loss"] for ply in own) / len(own), abs=0.01
            )
            assert summary["accuracy"] == pytest.approx(
                sum(ply["accuracy"] for ply in own) / len(own), abs=0.01
            )
            assert summary["best_move_pct"] == pytest.approx(
                100.0 * summary["best_moves"] / len(own), abs=0.01
            )


@needs_stockfish
def test_analyse_pasted_pgn_and_cache(
    client: Client, service: AnalysisService, registry: Registry
) -> None:
    body = {"source": {"pgn": SHORT_PGN}, "depth": 8, "multipv": 2}
    started = time.monotonic()
    status, submitted = client.call("POST", "/api/analysis", body)
    assert status == 202 and submitted["cached"] is False, submitted
    job_id = submitted["job_id"]
    state = client.wait(job_id)
    assert time.monotonic() - started < 30.0
    assert state["status"] == "done" and state["error"] is None, state
    assert state["progress"] == {"done": 9, "total": 9}
    result = state["result"]
    _check_result(result, plies=8, multipv=2)
    assert result["headers"]["White"] == "Alice" and result["headers"]["Black"] == "Bob"
    assert result["summary"]["white"]["name"] == "Alice"
    assert result["start_fen"] == chess.STARTING_FEN
    assert [ply["clock_after"] for ply in result["plies"]] == [
        119.0,
        118.0,
        117.0,
        116.0,
        115.0,
        114.0,
        113.0,
        112.0,
    ]
    assert [ply["san"] for ply in result["plies"]][:3] == ["e4", "e5", "Nf3"]

    status, jobs = client.call("GET", "/api/analysis/jobs")
    assert status == 200
    assert any(job["job_id"] == job_id and job["status"] == "done" for job in jobs["jobs"])
    assert all({"job_id", "status", "progress", "label"} <= set(job) for job in jobs["jobs"])

    # The same source and settings come straight back; a fresh service reads the file cache.
    status, again = client.call("POST", "/api/analysis", body)
    assert status == 202 and again == {"job_id": job_id, "cached": True}
    status, state = client.call("GET", f"/api/analysis/{job_id}")
    assert state["status"] == "done"
    cached_files = list(service.cache_dir.glob("*.json"))
    assert len(cached_files) == 1 and json.loads(cached_files[0].read_text())["plies"]
    fresh = AnalysisService(registry, cache_dir=service.cache_dir, pgn_dirs=[])
    job, cached = fresh.submit(body)
    assert cached is True and job.status == "done" and job.result == result
    # A result cached before "pgn" existed is completed on the way out of the cache.
    stale = json.loads(cached_files[0].read_text())
    del stale["pgn"]
    cached_files[0].write_text(json.dumps(stale))
    job, cached = AnalysisService(registry, cache_dir=service.cache_dir, pgn_dirs=[]).submit(body)
    assert cached is True and job.result is not None and job.result["pgn"] == result["pgn"]
    # Different settings are a different job.
    status, other = client.call("POST", "/api/analysis", {**body, "multipv": 1})
    assert status == 202 and other["cached"] is False and other["job_id"] != job_id
    assert client.wait(other["job_id"])["status"] == "done"


@needs_stockfish
def test_checkmate_is_the_outcome_not_a_search(client: Client) -> None:
    status, submitted = client.call(
        "POST", "/api/analysis", {"source": {"pgn": FOOLS_MATE}, "depth": 8, "multipv": 3}
    )
    assert status == 202
    state = client.wait(submitted["job_id"])
    assert state["status"] == "done", state
    result = state["result"]
    _check_result(result, plies=4, multipv=3)
    last = result["plies"][-1]
    assert last["san"] == "Qh4#" and last["eval_after"] == {
        "cp": -1000,
        "mate": None,
        "pov": "white",
    }
    assert last["eval_before"]["mate"] == -1  # Black to mate in one, White's point of view
    assert last["rank"] == 1 and last["judgement"] == "best" and last["cp_loss"] == 0
    assert result["plies"][2]["judgement"] == "blunder"  # 2. g4??
    assert result["summary"]["white"]["blunders"] >= 1
    assert result["headers"]["Result"] == "0-1"


@needs_stockfish
def test_sides_are_graded_separately(client: Client) -> None:
    """End to end: one side plays the engine's first choices, the other obvious rubbish; the
    summary must tell them apart (regression for identical per-side counts)."""
    body = {"source": {"pgn": LOPSIDED_PGN}, "depth": 8, "multipv": 3}
    status, submitted = client.call("POST", "/api/analysis", body)
    assert status == 202, submitted
    state = client.wait(submitted["job_id"])
    assert state["status"] == "done", state
    result = state["result"]
    _check_result(result, plies=5, multipv=3)
    plies = result["plies"]
    assert [ply["mover"] for ply in plies] == ["white", "black", "white", "black", "white"]
    assert [ply["rank"] for ply in plies if ply["mover"] == "black"] == [None, None]
    assert plies[-1]["rank"] == 1 and plies[-1]["san"] == "Qh5#"  # the only mate in one
    assert plies[3]["judgement"] == "blunder" and plies[3]["cp_loss"] > 500  # 2... g5??
    white, black = result["summary"]["white"], result["summary"]["black"]
    assert (white["name"], black["name"]) == ("Good", "Bad")
    assert (white["moves"], black["moves"]) == (3, 2)
    assert white["top3_moves"] == 3 and white["best_moves"] >= 2 and white["top3_pct"] == 100.0
    assert black["best_moves"] == 0 and black["top3_moves"] == 0 and black["top3_pct"] == 0.0
    assert (white["blunders"], black["blunders"]) == (0, 1)
    assert black["acpl"] > 400 > white["acpl"] and black["accuracy"] < white["accuracy"]
    assert result["pgn"].startswith('[Event "') and "Qh5#" in result["pgn"]


@needs_stockfish
def test_file_and_game_sources(client: Client, registry: Registry, archive: Path) -> None:
    path = archive / "short.pgn"
    path.write_text(SHORT_PGN, encoding="utf-8")
    (archive / "notes.txt").write_text("ignored")
    status, sources = client.call("GET", "/api/analysis/sources")
    assert status == 200
    files = [entry for entry in sources["files"] if entry["path"] == str(path.resolve())]
    assert len(files) == 1
    assert files[0]["white"] == "Alice" and files[0]["black"] == "Bob"
    assert files[0]["plies"] == 8 and files[0]["result"] == "*" and "Alice" in files[0]["label"]
    status, submitted = client.call(
        "POST", "/api/analysis", {"source": {"file": files[0]["path"]}, "depth": 8, "multipv": 1}
    )
    assert status == 202, submitted
    state = client.wait(submitted["job_id"])
    assert state["status"] == "done" and len(state["result"]["plies"]) == 8
    assert state["label"].startswith("Alice vs Bob")

    # A game the server played itself: the registry builds the PGN from its move list.
    game = registry.create(
        {
            "kind": "spectate",
            "white": "baselines/random",
            "black": "baselines/greedy",
            "base_ms": 2000,
            "increment_ms": 50,
            "ply_cap": 6,
        }
    )
    deadline = time.monotonic() + 30
    while game.status != "finished" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert game.status == "finished" and not game.error
    status, sources = client.call("GET", "/api/analysis/sources")
    listed = [entry for entry in sources["games"] if entry["id"] == game.id]
    assert len(listed) == 1
    assert listed[0]["finished"] is True and listed[0]["plies"] == len(game.moves)
    assert (
        listed[0]["white"] == "Baseline: random"
        and listed[0]["result"] == game.snapshot()["result_text"]
    )
    status, submitted = client.call(
        "POST", "/api/analysis", {"source": {"game_id": game.id}, "depth": 8, "multipv": 3}
    )
    assert status == 202, submitted
    state = client.wait(submitted["job_id"])
    assert state["status"] == "done", state
    result = state["result"]
    _check_result(result, plies=len(game.moves), multipv=3)
    assert result["headers"]["White"] == "Baseline: random"
    assert result["headers"]["Termination"] == game.termination
    assert all(ply["clock_after"] is not None for ply in result["plies"])
    status, _ = client.call("POST", "/api/analysis", {"source": {"game_id": "missing"}})
    assert status == 404


@needs_stockfish
def test_cancel_a_running_job(client: Client) -> None:
    long_game = chess.pgn.Game()
    node: chess.pgn.GameNode = long_game
    board = chess.Board()
    marshall = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7"
    for san in marshall.split(" "):
        move = board.parse_san(san)
        node = node.add_variation(move)
        board.push(move)
    status, submitted = client.call(
        "POST", "/api/analysis", {"source": {"pgn": str(long_game)}, "depth": 30, "multipv": 5}
    )
    assert status == 202 and submitted["cached"] is False
    job_id = submitted["job_id"]
    time.sleep(0.3)  # let the worker pick it up, so the stop happens mid-search
    status, payload = client.call("DELETE", f"/api/analysis/{job_id}")
    assert status == 204 and payload is None
    started = time.monotonic()
    state = client.wait(job_id, timeout=10.0)
    assert state["status"] == "cancelled" and state["result"] is None
    assert time.monotonic() - started < 5.0
    assert state["progress"]["total"] == 21
    # Cancelled work is not cached: the same request starts over.
    status, again = client.call(
        "POST", "/api/analysis", {"source": {"pgn": str(long_game)}, "depth": 30, "multipv": 5}
    )
    assert status == 202 and again["cached"] is False and again["job_id"] != job_id
    status, _ = client.call("DELETE", f"/api/analysis/{again['job_id']}")
    assert status == 204
    assert client.wait(again["job_id"], timeout=10.0)["status"] == "cancelled"
