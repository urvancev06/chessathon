"""End-to-end tests for the local web app: the server runs in a thread on an ephemeral port and the
tests speak plain HTTP to it with urllib, playing real baseline agents through the harness."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import chess
import chess.pgn
import pytest

from harness.rules import OPENINGS
from tools.webapp import games
from tools.webapp.games import GameError, Registry
from tools.webapp.server import run_in_thread, serve

STANDARD = chess.STARTING_FEN
JsonDict = dict[str, Any]


class Client:
    def __init__(self, base: str) -> None:
        self.base = base

    def raw(self, method: str, path: str, body: object | None = None) -> tuple[int, bytes, str]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read(), response.headers.get("Content-Type", "")
        except urllib.error.HTTPError as error:
            return error.code, error.read(), error.headers.get("Content-Type", "")

    def get(self, path: str) -> tuple[int, Any]:
        status, payload, _ = self.raw("GET", path)
        return status, json.loads(payload)

    def post(self, path: str, body: object | None = None) -> tuple[int, Any]:
        status, payload, _ = self.raw("POST", path, body if body is not None else {})
        return status, json.loads(payload)

    def wait(self, game_id: str, done: str, timeout: float = 20.0) -> JsonDict:
        """Poll the game until ``done`` holds: 'running', 'idle' (not thinking) or 'finished'."""
        deadline = time.monotonic() + timeout
        state: JsonDict = {}
        while time.monotonic() < deadline:
            status, state = self.get(f"/api/games/{game_id}")
            assert status == 200, state
            if state["status"] == "finished":
                return state
            if done == "running" and state["status"] == "running":
                return state
            if done == "idle" and state["status"] == "running" and not state["thinking"]:
                return state
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {done}: {state.get('status')}")


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Registry]:
    registry = Registry(games_dir=tmp_path_factory.mktemp("webapp_games"), max_engines=4)
    yield registry
    registry.shutdown()


@pytest.fixture(scope="module")
def client(registry: Registry) -> Iterator[Client]:
    server, _ = serve("127.0.0.1", 0, registry)
    thread = run_in_thread(server)
    host, port = server.server_address[0], server.server_address[1]
    assert isinstance(host, str)
    yield Client(f"http://{host}:{port}")
    server.shutdown()
    server.server_close()
    thread.join(5)


def runner_children() -> list[int]:
    """PIDs of harness runner processes whose parent is this process (Linux /proc only)."""
    proc = Path("/proc")
    if not proc.is_dir():
        return []
    me = os.getpid()
    found: list[int] = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            status = (entry / "status").read_text()
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        parent = next(
            (line.split()[1] for line in status.splitlines() if line.startswith("PPid:")), ""
        )
        if parent == str(me) and b"runner.py" in cmdline:
            found.append(int(entry.name))
    return found


# --------------------------------------------------------------------------------------------
# Static pages and read-only endpoints


def test_index_and_static(client: Client) -> None:
    status, body, content_type = client.raw("GET", "/")
    assert status == 200 and content_type.startswith("text/html")
    assert b"<title>Mikhail LeTal</title>" in body
    assert b"cdn." not in body and b"https://" not in body  # offline: nothing external
    status, body, content_type = client.raw("GET", "/js/main.js")
    assert status == 200 and "javascript" in content_type
    status, body, content_type = client.raw("GET", "/css/tokens.css")
    assert status == 200 and content_type.startswith("text/css") and b"--paper" in body
    status, _, content_type = client.raw("GET", "/favicon.svg")
    assert status == 200 and content_type.startswith("image/svg+xml")
    status, _, content_type = client.raw("GET", "/pieces/cburnett/wK.svg")
    assert status == 200 and content_type.startswith("image/svg+xml")
    for path in ("/../server.py", "/js/../../tools/webapp/server.py", "/static/app.js", "/nope"):
        status, _, _ = client.raw("GET", path)
        assert status == 404, path


def test_info(client: Client) -> None:
    status, info = client.get("/api/info")
    assert status == 200
    assert info["name"] == "Mikhail LeTal"
    assert isinstance(info["version"], str)
    assert isinstance(info["git"], dict) and "commit" in info["git"] and "built" in info["git"]
    assert any(row["label"] == "Time control" for row in info["contract"])
    assert any(engine["path"] == "baselines/greedy" for engine in info["engines"])
    assert info["engine_slots"]["max"] == 4
    assert info["time_controls"][0]["base_ms"] == 120_000


def test_docs(client: Client) -> None:
    status, docs = client.get("/api/docs")
    assert status == 200 and docs
    assert docs[0]["name"] == "DESIGN"
    assert all(isinstance(doc["content"], str) for doc in docs)


def test_weights_handles_missing(client: Client, tmp_path: Path) -> None:
    missing = games.weights(tmp_path)
    assert missing["present"] is False and missing["pst"] is None and missing["errors"] == []
    (tmp_path / "weights").mkdir()
    (tmp_path / "weights" / "pst.json").write_text("{not json")
    broken = games.weights(tmp_path)
    assert broken["present"] is True and broken["pst"] is None and broken["errors"]
    status, payload = client.get("/api/weights")
    assert status == 200 and isinstance(payload["present"], bool)
    if payload["present"] and payload["pst"]:
        assert len(payload["pst"]["pst_mg"]["P"]) == 64


def test_openings(client: Client, tmp_path: Path) -> None:
    status, payload = client.get("/api/openings")
    assert status == 200 and isinstance(payload["present"], bool)
    assert len(payload["harness"]) == len(OPENINGS)
    absent = games.openings(tmp_path)
    assert absent["present"] is False and absent["count"] == 0
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "openings.txt").write_text(
        f"Test\t{OPENINGS[0][1]}\nBroken\tnot a fen\n", encoding="utf-8"
    )
    parsed = games.openings(tmp_path)
    assert parsed["count"] == 2 and parsed["invalid"] == 1
    rows = parsed["openings"]
    assert isinstance(rows, list)
    assert rows[0]["name"] == "Test" and rows[0]["valid"] is True


def test_bad_requests(client: Client) -> None:
    status, payload = client.post("/api/games", {"kind": "play", "engine": "../outside"})
    assert status == 400 and "outside" in payload["error"]
    status, payload = client.post("/api/games", {"kind": "play", "engine": "docs"})
    assert status == 400 and "agent.py" in payload["error"]
    status, payload = client.post(
        "/api/games", {"kind": "play", "engine": "baselines/greedy", "fen": "garbage"}
    )
    assert status == 400 and "FEN" in payload["error"]
    status, payload = client.post(
        "/api/games", {"kind": "play", "engine": "baselines/greedy", "base_ms": 1}
    )
    assert status == 400
    status, payload = client.get("/api/games/nope")
    assert status == 404
    status, payload, _ = client.raw("POST", "/api/games", None)
    request = urllib.request.Request(client.base + "/api/games", data=b"{bad", method="POST")
    try:
        urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as error:
        assert error.code == 400
    else:
        raise AssertionError("malformed JSON was accepted")
    status, payload, _ = client.raw("GET", "/api/nothing")
    assert status == 404


def test_log_parsing() -> None:
    fields = games.parse_log_line("m e2e4 d 5/9 n 31240 nps 10413 t 3001 s 3300 h 9900 c 118500 x")
    assert fields["m"] == "e2e4" and fields["d"] == "5/9" and fields["_tail"] == "x"
    record = games.make_record(3, 12.5, "warmup done\nm e2e4 d 5/9 n 31240 nps 10413 t 3001\n")
    payload = record.to_dict()
    assert payload["known"] == {
        "move": "e2e4",
        "depth": "5/9",
        "nodes": "31240",
        "nps": "10413",
        "time_ms": "3001",
    }
    assert payload["raw"] == ["warmup done", "m e2e4 d 5/9 n 31240 nps 10413 t 3001"]
    assert games.new_output("abc", "abcdef") == "def"
    head = "x" * 300
    assert games.new_output(head + "old", "..." + head + "old\nnew line\n") == "\nnew line\n"
    assert games.make_record(1, 0.0, "").raw == [] and games.make_record(1, 0.0, "").fields == {}


# --------------------------------------------------------------------------------------------
# Games


def test_play_game_vs_greedy(client: Client, registry: Registry) -> None:
    status, state = client.post(
        "/api/games",
        {
            "kind": "play",
            "engine": "baselines/greedy",
            "human": "white",
            "base_ms": 2000,
            "increment_ms": 50,
        },
    )
    assert status == 201, state
    game_id = state["id"]
    assert state["kind"] == "play" and state["human"] == "white" and state["fen"] == STANDARD
    state = client.wait(game_id, "running")
    assert state["black"]["kind"] == "engine" and state["black"]["init_ok"] is True
    assert state["black"]["init_ms"] <= state["black"]["init_budget_ms"]
    assert state["clocks"] == {"white": 2000, "black": 2000}
    assert set(state["legal_moves"]) == {move.uci() for move in chess.Board().legal_moves}

    status, state = client.post(f"/api/games/{game_id}/move", {"uci": "e2e4", "spent_ms": 100})
    assert status == 200, state
    state = client.wait(game_id, "idle")
    assert [move["uci"] for move in state["moves"]][:1] == ["e2e4"]
    assert len(state["moves"]) == 2 and state["turn"] == "white"
    board = chess.Board()
    board.push_uci("e2e4")
    reply = state["moves"][1]
    assert chess.Move.from_uci(reply["uci"]) in board.legal_moves
    board.push_uci(reply["uci"])
    assert state["fen"] == board.fen() and state["ply"] == 2
    assert state["moves"][0]["san"] == "e4" and reply["by"] == "black"
    assert state["clocks"]["white"] == 2000 - 100 + 50
    assert 1050 < state["clocks"]["black"] <= 2050  # decreased by wall time, then the increment
    assert reply["clock_ms"] == state["clocks"]["black"]
    assert reply["spent_ms"] >= 0 and reply["log"] is not None and reply["log"]["raw"] == []
    assert set(state["legal_moves"]) == {move.uci() for move in board.legal_moves}
    status, payload = client.post(f"/api/games/{game_id}/move", {"uci": "e2e4"})
    assert status == 400  # no longer legal

    status, state = client.post(f"/api/games/{game_id}/takeback")
    assert status == 200, state
    assert state["moves"] == [] and state["fen"] == STANDARD
    assert state["clocks"] == {"white": 2000, "black": 2000} and state["turn"] == "white"

    status, state = client.post(f"/api/games/{game_id}/move", {"uci": "d2d4", "spent_ms": 0})
    assert status == 200
    client.wait(game_id, "idle")
    status, payload, content_type = client.raw("GET", f"/api/games/{game_id}/pgn")
    assert status == 200 and "chess-pgn" in content_type and b"1. d4" in payload

    status, state = client.post(f"/api/games/{game_id}/resign")
    assert status == 200 and state["status"] == "finished"
    assert state["result"] == "black" and state["termination"] == "resignation"
    assert state["result_text"] == "0-1" and state["failed"] is False
    pgn_path = Path(state["pgn_path"])
    assert pgn_path.is_file() and pgn_path.parent == registry.games_dir
    text = pgn_path.read_text()
    assert '[Termination "resignation"]' in text and "%clk" in text and '[Result "0-1"]' in text
    assert state["black"]["alive"] is False
    assert registry.live_engines == 0
    assert runner_children() == []
    status, payload = client.post(f"/api/games/{game_id}/move", {"uci": "g1f3"})
    assert status == 409


def test_spectate_game(client: Client, registry: Registry) -> None:
    status, state = client.post(
        "/api/games",
        {
            "kind": "spectate",
            "white": "baselines/greedy",
            "black": "baselines/random",
            "base_ms": 1000,
            "increment_ms": 50,
            "ply_cap": 20,
            "opening": "Test opening",
        },
    )
    assert status == 201, state
    game_id = state["id"]
    assert state["human"] is None and state["kind"] == "spectate"
    state = client.wait(game_id, "finished", timeout=30)
    assert state["status"] == "finished"
    assert state["termination"] in {"ply_cap", "checkmate", "stalemate", "insufficient_material"}
    if state["termination"] == "ply_cap":
        assert state["ply"] == 20 and len(state["moves"]) == 20 and state["result"] == "draw"
    board = chess.Board()
    for record in state["moves"]:
        move = chess.Move.from_uci(record["uci"])
        assert move in board.legal_moves
        board.push(move)
    assert board.fen() == state["fen"]
    assert all(record["clock_ms"] > 0 for record in state["moves"])
    pgn_path = Path(state["pgn_path"])
    assert pgn_path.is_file()
    with pgn_path.open() as handle:
        game = chess.pgn.read_game(handle)
    assert game is not None
    assert (
        game.headers["White"] == "Baseline: greedy" and game.headers["Black"] == "Baseline: random"
    )
    assert game.headers["Opening"] == "Test opening"
    assert game.headers["Result"] == state["result_text"]
    assert len(list(game.mainline_moves())) == len(state["moves"])
    assert state["white"]["alive"] is False and state["black"]["alive"] is False
    assert registry.live_engines == 0
    assert runner_children() == []
    status, summaries = client.get("/api/games")
    assert any(summary["id"] == game_id for summary in summaries)


def test_pause_and_resume(client: Client, registry: Registry) -> None:
    status, state = client.post(
        "/api/games",
        {
            "kind": "spectate",
            "white": "baselines/random",
            "black": "baselines/random",
            "base_ms": 5000,
            "increment_ms": 50,
            "ply_cap": 40,
        },
    )
    assert status == 201, state
    game_id = state["id"]
    client.wait(game_id, "running")
    status, state = client.post(f"/api/games/{game_id}/pause")
    assert status == 200 and state["paused"] is True
    time.sleep(0.3)  # the move in flight finishes; after that nothing moves
    status, frozen = client.get(f"/api/games/{game_id}")
    time.sleep(0.4)
    status, later = client.get(f"/api/games/{game_id}")
    assert later["status"] == "running" and later["paused"] is True
    assert later["ply"] == frozen["ply"] and later["clocks"] == frozen["clocks"]
    status, state = client.post(f"/api/games/{game_id}/resume")
    assert status == 200 and state["paused"] is False
    state = client.wait(game_id, "finished", timeout=30)
    assert state["ply"] > frozen["ply"]
    assert registry.live_engines == 0 and runner_children() == []
    # Only spectate games pause; a play game says so.
    status, play = client.post(
        "/api/games", {"kind": "play", "engine": "baselines/random", "base_ms": 1000}
    )
    assert status == 201
    status, _ = client.post(f"/api/games/{play['id']}/pause")
    assert status == 409
    client.post(f"/api/games/{play['id']}/stop")
    client.wait(play["id"], "finished")


def test_resign_by_flag(client: Client, registry: Registry) -> None:
    status, state = client.post(
        "/api/games", {"kind": "play", "engine": "baselines/random", "base_ms": 1000}
    )
    assert status == 201, state
    game_id = state["id"]
    client.wait(game_id, "idle")
    status, _ = client.post(f"/api/games/{game_id}/resign", {"reason": "nonsense"})
    assert status == 400
    status, state = client.post(f"/api/games/{game_id}/resign", {"reason": "flag"})
    assert status == 200 and state["status"] == "finished"
    assert state["termination"] == "flag" and state["result"] == "black"
    assert (
        state["clocks"]["white"] == 0 and state["failed"] is True
    )  # the referee counts a flag as a failure
    assert registry.live_engines == 0 and runner_children() == []


def test_stop_while_thinking(client: Client, registry: Registry) -> None:
    status, state = client.post(
        "/api/games",
        {
            "kind": "spectate",
            "white": "baselines/minimax",
            "black": "baselines/minimax",
            "base_ms": 120_000,
            "increment_ms": 500,
        },
    )
    assert status == 201, state
    game_id = state["id"]
    client.wait(game_id, "running")
    time.sleep(0.2)
    started = time.monotonic()
    status, state = client.post(f"/api/games/{game_id}/stop")
    assert status == 200
    state = client.wait(game_id, "finished", timeout=10)
    assert time.monotonic() - started < 5
    assert state["termination"] == "aborted" and state["result"] == "void"
    assert registry.live_engines == 0
    assert runner_children() == []


def test_engine_cap(tmp_path: Path) -> None:
    small = Registry(games_dir=tmp_path, max_engines=1)
    try:
        game = small.create({"kind": "play", "engine": "baselines/random", "base_ms": 1000})
        with pytest.raises(GameError) as caught:
            small.create({"kind": "play", "engine": "baselines/random", "base_ms": 1000})
        assert caught.value.status == 429
        game.stop()
        deadline = time.monotonic() + 5
        while game.status != "finished" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert small.live_engines == 0
    finally:
        small.shutdown()
