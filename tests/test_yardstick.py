"""Tests for tools/yardstick (the Stockfish seat) and its place in the web app.

The engine is a local instrument: everything that needs the binary is skipped when none resolves.
The fallback path (no engine at all) runs in a subprocess with an empty PATH and a HOME with no
Stockfish in it, so it exercises the real import-time code without touching this process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import chess
import pytest

from harness.referee import FAILED_TERMINATIONS, play_match
from harness.sandbox import local
from tools.webapp import games
from tools.webapp.games import GameError, Registry, stockfish_path
from tools.webapp.server import run_in_thread, serve

ROOT = Path(__file__).resolve().parent.parent
YARDSTICK = ROOT / "tools" / "yardstick"
RANDOM = ROOT / "baselines" / "random"
STOCKFISH = stockfish_path()
needs_stockfish = pytest.mark.skipif(STOCKFISH is None, reason="no local Stockfish binary")
JsonDict = dict[str, Any]


def _run_yardstick(
    script: str, tmp_path: Path, **environment: str
) -> subprocess.CompletedProcess[str]:
    """Import the yardstick in a fresh interpreter (its engine opens at import) and run
    ``script``; the working directory is not the repository root, whose agent.py is the real
    engine and would shadow the yardstick's."""
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(YARDSTICK), "HOME": str(tmp_path), **environment},
        cwd=tmp_path,
        timeout=60,
        check=False,
    )


def test_fallback_without_an_engine_never_raises(tmp_path: Path) -> None:
    # Every resolution step is closed off: no YARDSTICK_ENGINE, nothing on PATH, and the
    # conventional path under neither $HOME nor the account's real home (pwd is patched before
    # the import, which is when the yardstick looks).
    script = (
        "import pwd, types\n"
        f"pwd.getpwuid = lambda uid: types.SimpleNamespace(pw_dir={str(tmp_path)!r})\n"
        "import agent, chess, json\n"
        "moves = [agent.get_move(chess.STARTING_FEN, 1000), agent.get_move('bad fen', 1000),"
        " agent.get_move('7k/8/8/8/8/8/8/7K w - - 0 1', 5)]\n"
        "print(json.dumps({'engine': agent.ENGINE is None, 'moves': moves}))\n"
    )
    completed = _run_yardstick(
        script, tmp_path, PATH="", YARDSTICK_ENGINE=str(tmp_path / "missing")
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload["engine"] is True
    assert payload["moves"] == ["a2a3", "0000", "h1g1"]  # first legal move in UCI order
    assert "no UCI engine found" in completed.stderr
    assert "yardstick full a2a3" in completed.stderr


@needs_stockfish
def test_process_exits_cleanly_with_the_engine(tmp_path: Path) -> None:
    # python-chess's engine thread is not a daemon: a plain exit must not hang on it.
    script = "import agent, chess\nprint(agent.get_move(chess.STARTING_FEN, 1000))\n"
    started = time.monotonic()
    completed = _run_yardstick(
        script, tmp_path, YARDSTICK_ENGINE=str(STOCKFISH), YARDSTICK_MOVETIME_MS="50"
    )
    assert completed.returncode == 0, completed.stderr
    assert time.monotonic() - started < 20.0
    assert chess.Move.from_uci(completed.stdout.strip()) in chess.Board().legal_moves
    assert "yardstick: Stockfish" in completed.stderr


@needs_stockfish
def test_yardstick_plays_a_refereed_game(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARDSTICK_MOVETIME_MS", "50")
    monkeypatch.setenv("YARDSTICK_ELO", "1400")
    white, black = local(RANDOM, 1), local(YARDSTICK, 2)
    started = time.monotonic()
    outcome = play_match(white, black, base_ms=5000, increment_ms=100, ply_cap=4)
    assert time.monotonic() - started < 30.0
    assert outcome.termination not in FAILED_TERMINATIONS, black.stderr_log
    assert outcome.result in {"white", "black", "draw"}
    assert "yardstick 1400 " in black.stderr_log  # one log line per move, with the level
    assert "level 1400" in black.stderr_log
    assert '[Termination "ply_cap"]' in outcome.pgn or '[Termination "checkmate"]' in outcome.pgn


def test_arena_env_flag_is_parsed_and_recorded() -> None:
    from tools import arena_openings as tool

    settings = tool.parse_args(["--env", "YARDSTICK_ELO=1600", "--env", "X=a=b"])
    assert settings.env == {"YARDSTICK_ELO": "1600", "X": "a=b"}
    assert tool.parse_args([]).env == {}
    with pytest.raises(SystemExit):
        tool.parse_args(["--env", "novalue"])
    record = tool.RunRecord(
        label="",
        agent=".",
        opponent="tools/yardstick",
        base_ms=120_000,
        increment_ms=500,
        ply_cap=600,
        games=2,
        workers=1,
        seed_offset=0,
        openings_source="harness.rules.OPENINGS",
        openings_count=8,
        started_at="",
        finished_at="",
        load_start=None,
        load_end=None,
        results=[],
        terminations={},
        failed={},
        statistics=None,
        low_clock_ms=None,
        low_clock_game=None,
        env=settings.env,
    )
    assert "| tools/yardstick (YARDSTICK_ELO=1600 X=a=b) |" in tool.results_row(record)


def test_stockfish_ids_are_parsed_and_validated() -> None:
    assert games.stockfish_level("baselines/random") is None
    assert games.stockfish_level("stockfish:1600") == "1600"
    assert games.stockfish_level("stockfish:full") == "full"
    for bad in ("stockfish:9999", "stockfish:abc", "stockfish:", "stockfish:1000"):
        with pytest.raises(GameError) as caught:
            games.stockfish_level(bad)
        assert caught.value.status == 400
    assert games.stockfish_environment("1600", Path("/sf"), None) == {
        "YARDSTICK_ENGINE": "/sf",
        "YARDSTICK_ELO": "1600",
    }
    assert games.stockfish_environment("full", Path("/sf"), 250) == {
        "YARDSTICK_ENGINE": "/sf",
        "YARDSTICK_MOVETIME_MS": "250",
    }
    info = games.stockfish_info("Stockfish 19", "1600")
    assert info.id == "stockfish:1600" and info.label == "Stockfish 19 · Elo 1600"
    assert info.kind == "stockfish" and info.path == "tools/yardstick"
    assert games.stockfish_info("Stockfish 19", "full").label == "Stockfish 19 · full strength"


# --------------------------------------------------------------------------------------------
# Through the web app


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
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Registry]:
    registry = Registry(games_dir=tmp_path_factory.mktemp("games"), max_engines=2)
    yield registry
    registry.shutdown()


@pytest.fixture(scope="module")
def client(registry: Registry) -> Iterator[Client]:
    server, app = serve("127.0.0.1", 0, registry)
    thread = run_in_thread(server)
    host, port = server.server_address[0], server.server_address[1]
    assert isinstance(host, str)
    yield Client(f"http://{host}:{port}")
    server.shutdown()
    server.server_close()
    app.analysis.shutdown()
    thread.join(5)


def test_info_lists_stockfish_seats_when_available(client: Client) -> None:
    status, info = client.call("GET", "/api/info")
    assert status == 200
    engines = {engine["id"]: engine for engine in info["engines"]}
    assert engines["baselines/greedy"]["kind"] == "baseline"
    assert engines["baselines/greedy"]["path"] == "baselines/greedy"
    assert all({"id", "label", "kind", "path"} <= set(engine) for engine in info["engines"])
    stockfish = [engine for engine in info["engines"] if engine["kind"] == "stockfish"]
    if STOCKFISH is None:
        assert stockfish == [] and info["analysis"]["available"] is False
        status, payload = client.call(
            "POST", "/api/games", {"kind": "play", "engine": "stockfish:1600"}
        )
        assert status == 503
        return
    assert info["analysis"]["available"] is True
    assert [engine["id"] for engine in stockfish] == [
        f"stockfish:{elo}" for elo in (1400, 1600, 1800, 2000, 2200, 2400, 2600)
    ] + ["stockfish:full"]
    assert engines["stockfish:1600"]["label"].endswith(" · Elo 1600")
    assert engines["stockfish:1600"]["label"].startswith(info["analysis"]["name"])
    assert engines["stockfish:full"]["label"].endswith(" · full strength")
    assert all(engine["path"] == "tools/yardstick" for engine in stockfish)
    status, payload = client.call(
        "POST", "/api/games", {"kind": "play", "engine": "stockfish:9999"}
    )
    assert status == 400 and "Elo" in payload["error"]


@needs_stockfish
def test_stockfish_seat_plays_through_the_webapp(client: Client, registry: Registry) -> None:
    status, state = client.call(
        "POST",
        "/api/games",
        {
            "kind": "spectate",
            "white": "baselines/random",
            "black": "stockfish:1400",
            "base_ms": 5000,
            "increment_ms": 100,
            "ply_cap": 4,
            "stockfish_movetime_ms": 50,
        },
    )
    assert status == 201, state
    assert state["black"]["id"] == "stockfish:1400" and state["black"]["engine_kind"] == "stockfish"
    assert state["black"]["path"] == "tools/yardstick"
    deadline = time.monotonic() + 30
    while state["status"] != "finished" and time.monotonic() < deadline:
        time.sleep(0.05)
        status, state = client.call("GET", f"/api/games/{state['id']}")
    assert state["status"] == "finished", state
    assert state["failed"] is False, state["black"]
    assert state["black"]["init_ok"] is True
    assert "level 1400" in state["black"]["init_log"]
    played = [move for move in state["moves"] if move["by"] == "black"]
    assert played and all(
        any(line.startswith("yardstick 1400 ") for line in move["log"]["raw"]) for move in played
    )
    board = chess.Board()
    for move in state["moves"]:
        board.push_uci(move["uci"])
    assert board.fen() == state["fen"]
    assert registry.live_engines == 0
    # The server's own environment was never touched: the seat got its variables privately.
    assert "YARDSTICK_ELO" not in os.environ and "YARDSTICK_MOVETIME_MS" not in os.environ
