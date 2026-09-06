"""HTTP server for the local web app: static files plus a small JSON API.

Standard library only (``http.server`` with ``ThreadingHTTPServer``). Run from the repository root:

    python -m tools.webapp.server [--host 127.0.0.1] [--port 8000] [--max-engines 4]

The server binds to the loopback interface unless told otherwise and never opens a browser.
"""

from __future__ import annotations

import argparse
import atexit
import json
import mimetypes
import signal
import sys
import threading
import traceback
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from harness.rules import PLY_CAP
from tools.webapp import games
from tools.webapp.games import GameError, Registry

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY_BYTES = 1_000_000
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}

JsonObject = dict[str, object]


class WebApp:
    """The request-independent application: repository root plus the game registry."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.root = registry.root

    def info(self) -> JsonObject:
        return {
            **games.engine_identity(self.root),
            "git": games.git_info(self.root),
            "results": games.results_status(self.root),
            "contract": games.contract(),
            "engines": [engine.to_dict() for engine in games.list_engines(self.root)],
            "time_controls": [
                {"label": label, "base_ms": base, "increment_ms": increment}
                for label, base, increment in games.TIME_CONTROLS
            ],
            "ply_cap": PLY_CAP,
            "engine_slots": {
                "max": self.registry.max_engines,
                "used": self.registry.live_engines,
            },
            "root": str(self.root),
            "games_dir": str(self.registry.games_dir),
        }

    # -- API dispatch ------------------------------------------------------------------------

    def api(self, method: str, path: str, body: JsonObject | None) -> tuple[int, object]:
        parts = [part for part in path.split("/") if part]  # ["api", "games", id, action]
        if len(parts) < 2 or parts[0] != "api":
            raise GameError(404, f"no such endpoint: {path}")
        resource = parts[1]
        if method == "GET" and len(parts) == 2:
            simple: dict[str, Callable[[], object]] = {
                "info": self.info,
                "engines": lambda: [e.to_dict() for e in games.list_engines(self.root)],
                "docs": lambda: games.docs_list(self.root),
                "weights": lambda: games.weights(self.root),
                "openings": lambda: games.openings(self.root),
                "games": self.registry.summaries,
            }
            if resource in simple:
                return 200, simple[resource]()
            raise GameError(404, f"no such endpoint: {path}")
        if resource != "games":
            raise GameError(404, f"no such endpoint: {path}")
        if method == "POST" and len(parts) == 2:
            game = self.registry.create(body or {})
            return 201, game.snapshot()
        if len(parts) < 3:
            raise GameError(405, f"{method} is not allowed on {path}")
        game = self.registry.get(parts[2])
        action = parts[3] if len(parts) > 3 else None
        if method == "GET" and action is None:
            return 200, game.snapshot()
        if method == "GET" and action == "pgn":
            return 200, game.pgn()
        if method == "DELETE" and action is None:
            self.registry.remove(game.id)
            return 200, {"ok": True}
        if method == "POST" and action == "move":
            payload = body or {}
            uci = payload.get("uci")
            if not isinstance(uci, str):
                raise GameError(400, "uci is required")
            spent = payload.get("spent_ms", 0)
            if isinstance(spent, bool) or not isinstance(spent, int | float):
                raise GameError(400, "spent_ms must be a number")
            game.human_move(uci.strip(), float(spent))
            return 200, game.snapshot()
        if method == "POST" and action == "takeback":
            game.takeback()
            return 200, game.snapshot()
        if method == "POST" and action == "resign":
            game.resign()
            return 200, game.snapshot()
        if method == "POST" and action == "stop":
            game.stop("aborted")
            return 200, game.snapshot()
        raise GameError(404, f"no such endpoint: {method} {path}")


def make_handler(app: WebApp, quiet: bool = True) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "MikhailLeTalWebapp/1.0"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def do_DELETE(self) -> None:
            self._dispatch("DELETE")

        def log_message(self, format: str, *args: object) -> None:
            if not quiet:
                super().log_message(format, *args)

        # -- plumbing ----------------------------------------------------------------------

        def _dispatch(self, method: str) -> None:
            try:
                path = urlsplit(self.path).path
                if path.startswith("/api/"):
                    body = self._read_json() if method in ("POST", "DELETE") else None
                    status, payload = app.api(method, path, body)
                    if isinstance(payload, str):
                        headers = {}
                        if path.endswith("/pgn"):
                            game_id = path.split("/")[3]
                            name = app.registry.get(game_id).pgn_filename()
                            headers["Content-Disposition"] = f'attachment; filename="{name}"'
                        self._send(
                            status, payload.encode("utf-8"), "application/x-chess-pgn", headers
                        )
                    else:
                        self._json(status, payload)
                    return
                if method != "GET":
                    raise GameError(405, f"{method} is not allowed on {path}")
                if path in ("/", "/index.html"):
                    self._static("index.html")
                elif path.startswith("/static/"):
                    self._static(path[len("/static/") :])
                else:
                    # Hash routing lives in the browser; anything else is a typo.
                    raise GameError(404, f"not found: {path}")
            except GameError as error:
                self._json(error.status, {"error": error.message})
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception as error:  # a bug must answer 500, never kill the thread silently
                traceback.print_exc()
                self._json(500, {"error": f"internal error: {type(error).__name__}: {error}"})

        def _read_json(self) -> JsonObject | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return None
            if length > MAX_BODY_BYTES:
                raise GameError(413, "request body too large")
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GameError(400, f"request body is not valid JSON: {exc}") from None
            if not isinstance(payload, dict):
                raise GameError(400, "request body must be a JSON object")
            return {str(key): value for key, value in payload.items()}

        def _static(self, name: str) -> None:
            target = (STATIC / name).resolve()
            if STATIC not in target.parents or not target.is_file():
                raise GameError(404, f"not found: /static/{name}")
            content_type = CONTENT_TYPES.get(
                target.suffix.lower(),
                mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            )
            self._send(200, target.read_bytes(), content_type, {"Cache-Control": "no-cache"})

        def _json(self, status: int, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, data, "application/json; charset=utf-8")

        def _send(
            self,
            status: int,
            data: bytes,
            content_type: str,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(data)

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    registry: Registry | None = None,
    quiet: bool = True,
) -> tuple[Server, WebApp]:
    """Bind and return the server without running it; ``server.serve_forever()`` starts it."""
    registry = registry if registry is not None else Registry()
    app = WebApp(registry)
    server = Server((host, port), make_handler(app, quiet=quiet))
    return server, app


def run_in_thread(server: Server) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, name="webapp-http", daemon=True)
    thread.start()
    return thread


def _raise_interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.webapp.server",
        description="Local web app for playing against, watching and inspecting the engine.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default loopback)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--max-engines", type=int, default=4, help="cap on concurrently running agent processes"
    )
    parser.add_argument(
        "--idle-minutes",
        type=float,
        default=30.0,
        help="stop a game's agents after this long without a request",
    )
    parser.add_argument("--verbose", action="store_true", help="log every request")
    arguments = parser.parse_args(argv)

    registry = Registry(max_engines=arguments.max_engines, idle_seconds=arguments.idle_minutes * 60)
    atexit.register(registry.shutdown)
    registry.start_reaper()
    # SIGTERM (kill, systemd, a supervisor) would otherwise end the interpreter without atexit,
    # leaving suspended agent processes behind. Route it through the same path as Ctrl-C.
    signal.signal(signal.SIGTERM, _raise_interrupt)
    try:
        server, _ = serve(arguments.host, arguments.port, registry, quiet=not arguments.verbose)
    except OSError as error:
        print(f"could not bind {arguments.host}:{arguments.port}: {error}", file=sys.stderr)
        return 1
    host, port = server.server_address[0], server.server_address[1]
    shown = "localhost" if host in ("127.0.0.1", "::1") else str(host)
    print(f"Mikhail LeTal webapp: http://{shown}:{port}/  (Ctrl-C to stop)", flush=True)
    print(f"repository: {registry.root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping agents...")
    finally:
        server.server_close()
        registry.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
