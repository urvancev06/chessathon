"""Collect the curated opening positions that rated games on aichessathon.com start from.

Why this exists. Rated games do not start from the standard position but from a curated set of
near-level openings that the organisers do not publish. The agent contract says that finished
games reveal the position they were played from, and every game page is public. Local arena runs
are only representative of the ladder if they start from the same distribution, so this script
samples finished games and writes their starting FENs to ``data/openings.txt`` (one ``name<TAB>fen``
per line) plus a small report of what was seen.

How it works.

1. Fetch the qualifier leaderboard and read every ``/team/<uuid>`` link.
2. Pick a deterministic, evenly spaced sample of teams (sorted uuids), so a rerun visits the same
   pages and the cache makes it free.
3. Fetch each sampled team page and read its game table: ``<tr data-href="/game/<uuid>...">`` rows
   with a ``<td class="match-opening">`` cell. Each game is listed by both players, so game ids
   are deduplicated across teams.
4. Fetch game pages (round-robin over teams, up to a cap) and read the PGN that the page embeds in
   a ``href="data:application/x-chess-pgn;charset=utf-8,..."`` download link. The ``[FEN "..."]``
   header is the starting position. It is validated with ``chess.Board`` before it is kept.
5. Write ``data/openings.txt`` sorted by name then FEN, deduplicated on FEN, and a Markdown report.

Etiquette, which is not negotiable. One request per second (a full second of sleep between
requests), a descriptive User-Agent, the whole run stops on the first non-200 status or network
error (what was collected so far is still written), nothing is ever retried, redirects are not
followed (a redirect could lead somewhere robots.txt disallows), no path that robots.txt disallows
is ever requested, and every fetched page is cached under ``data/cache/<kind>/<id>.html`` so a
rerun downloads nothing it already has.

Only the standard library and ``chess`` are used. This is a tool; it never ships in the zip.
"""

from __future__ import annotations

import argparse
import datetime
import html
import http.client
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import chess

ROOT = Path(__file__).resolve().parent.parent

BASE_URL = "https://aichessathon.com"
LEADERBOARD_PATH = "/leaderboard?stage=qualifier"
USER_AGENT = (
    "aichessathon-entrant-openings-collector/0.1 "
    "(research for our own entry; one request per second)"
)
REQUEST_INTERVAL_S = 1.0
REQUEST_TIMEOUT_S = 30.0
# Copied from https://aichessathon.com/robots.txt on 6 Sep 2026. A path starting with any of these
# is never requested, whatever the crawl finds in a page.
DISALLOWED_PREFIXES = ("/api/", "/admin", "/dashboard", "/auth", "/join", "/signin")

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
TEAM_LINK_RE = re.compile(rf'href="/team/({UUID})')
# A game row is one <tr> carrying the game link; the opening name sits in a cell inside it.
GAME_ROW_RE = re.compile(rf'<tr data-href="/game/({UUID})[^"]*"(.*?)</tr>', re.DOTALL)
OPENING_CELL_RE = re.compile(r'<td class="match-opening">(.*?)</td>', re.DOTALL)
PGN_HREF_RE = re.compile(r'href="data:application/x-chess-pgn;charset=utf-8,([^"]*)"')
PGN_HEADER_RE = re.compile(r'^\[(\w+) "(.*)"\]$', re.MULTILINE)
# The game page also names the opening in a definition list; used to cross-check the team page.
GAME_OPENING_RE = re.compile(r"<dt>Opening</dt>\s*<dd>(.*?)</dd>", re.DOTALL)


class FetchError(Exception):
    """The first non-200 status, refused path or network failure. It ends the run; no retries."""


class RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """Turn every 3xx into an error.

    Only a 200 is acceptable, and following a redirect blindly could request a path that
    robots.txt disallows (a sign-in page, say). Returning None here makes urllib raise HTTPError.
    """

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> None:
        return None


OPENER = urllib.request.build_opener(RefuseRedirects)


@dataclass
class Fetcher:
    """Cached, rate-limited HTTP GET against the site. One instance per run."""

    cache_dir: Path
    requests_started: int = 0
    network_fetches: int = 0
    cache_hits: int = 0

    def get(self, kind: str, ident: str, path: str) -> str:
        """Return the page body for ``path``, from the cache when possible."""
        cache_file = self.cache_dir / kind / f"{ident}.html"
        if cache_file.is_file():
            self.cache_hits += 1
            return cache_file.read_text(encoding="utf-8")
        body = self._download(path)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        # Write next to the target and rename, so a run killed mid-write never leaves a truncated
        # page that a later run would trust.
        partial = cache_file.with_suffix(".part")
        partial.write_text(body, encoding="utf-8")
        partial.replace(cache_file)
        return body

    def _download(self, path: str) -> str:
        if not path.startswith("/") or path.startswith(DISALLOWED_PREFIXES):
            raise FetchError(f"refusing to request {path!r}: not an allowed site path")
        if self.requests_started > 0:
            # A full second between the end of one request and the start of the next keeps the
            # rate at or below one request per second whatever the server latency is.
            time.sleep(REQUEST_INTERVAL_S)
        self.requests_started += 1
        request = urllib.request.Request(BASE_URL + path, headers={"User-Agent": USER_AGENT})
        try:
            with OPENER.open(request, timeout=REQUEST_TIMEOUT_S) as response:
                status = int(response.status)
                raw: bytes = response.read()
        except urllib.error.HTTPError as exc:
            raise FetchError(f"GET {path}: HTTP {exc.code}") from exc
        except (OSError, http.client.HTTPException) as exc:
            # URLError, timeouts and TLS failures are OSErrors; IncompleteRead is an HTTPException.
            raise FetchError(f"GET {path}: {exc.__class__.__name__}: {exc}") from exc
        if status != 200:
            raise FetchError(f"GET {path}: HTTP {status}")
        self.network_fetches += 1
        return raw.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class GameStart:
    """What a game page tells us about the position the game started from."""

    fen: str
    setup: str | None
    opening: str | None


@dataclass
class Stats:
    """Everything the report prints. Updated as the crawl goes, so a stopped run still reports."""

    leaderboard_teams: int = 0
    teams_sampled: int = 0
    team_pages_read: int = 0
    game_rows_seen: int = 0
    unique_games_seen: int = 0
    games_selected: int = 0
    game_pages_read: int = 0
    games_with_fen: int = 0
    setup_header_missing: int = 0
    parse_failures: list[str] = field(default_factory=list)
    invalid_fens: list[str] = field(default_factory=list)
    name_mismatches: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# fen -> the set of names it was listed under (normally exactly one)
Openings = dict[str, set[str]]


def parse_team_ids(page: str) -> list[str]:
    """All team uuids linked from the leaderboard, sorted and unique."""
    return sorted(set(TEAM_LINK_RE.findall(page)))


def sample_evenly(items: Sequence[str], count: int) -> list[str]:
    """``count`` items spread evenly through ``items``, always starting with the first.

    Deterministic by construction: no randomness, so the same leaderboard gives the same sample and
    a rerun is served entirely from the cache.
    """
    if count <= 0:
        return []
    if count >= len(items):
        return list(items)
    return [items[i * len(items) // count] for i in range(count)]


def parse_team_games(page: str) -> list[tuple[str, str]]:
    """(game uuid, opening name) for every row of a team's game table, newest first."""
    games: list[tuple[str, str]] = []
    for game_id, row in GAME_ROW_RE.findall(page):
        cell = OPENING_CELL_RE.search(row)
        if cell is None:
            continue
        name = html.unescape(cell.group(1)).strip()
        if name:
            games.append((game_id, name))
    return games


def interleave(per_team: Sequence[Sequence[tuple[str, str]]]) -> list[tuple[str, str]]:
    """Round-robin merge: everyone's first game, then everyone's second, and so on.

    A capped run then covers many teams instead of every game of a few, which spreads the sample
    over more rounds and more opponents. Each game is listed by both players, so a game id is kept
    only the first time it is seen.
    """
    seen: set[str] = set()
    merged: list[tuple[str, str]] = []
    longest = max((len(games) for games in per_team), default=0)
    for index in range(longest):
        for games in per_team:
            if index >= len(games):
                continue
            game_id, name = games[index]
            if game_id not in seen:
                seen.add(game_id)
                merged.append((game_id, name))
    return merged


def parse_game_page(page: str) -> GameStart | None:
    """The starting FEN (and SetUp tag, and displayed opening name) from a game page, or None."""
    link = PGN_HREF_RE.search(page)
    if link is None:
        return None
    # The href is HTML attribute text holding a percent-encoded PGN: undo both layers in order.
    pgn = urllib.parse.unquote(html.unescape(link.group(1)))
    headers = dict(PGN_HEADER_RE.findall(pgn))
    fen = headers.get("FEN")
    if fen is None:
        return None
    shown = GAME_OPENING_RE.search(page)
    opening = html.unescape(shown.group(1)).strip() if shown is not None else None
    return GameStart(fen=fen.strip(), setup=headers.get("SetUp"), opening=opening)


def fen_problem(fen: str) -> str | None:
    """None when ``fen`` is a well-formed, legal position; otherwise the reason it is not."""
    try:
        board = chess.Board(fen)
    except ValueError as exc:
        return f"unparseable: {exc}"
    if not board.is_valid():
        return f"illegal position: {board.status()!r}"
    return None


def crawl(
    fetcher: Fetcher, team_count: int, max_games: int, stats: Stats, openings: Openings
) -> None:
    """Run the four fetch stages, filling ``stats`` and ``openings`` as it goes.

    Raises FetchError at the first network problem; the caller still writes what was collected.
    """
    leaderboard = fetcher.get("leaderboard", "qualifier", LEADERBOARD_PATH)
    team_ids = parse_team_ids(leaderboard)
    stats.leaderboard_teams = len(team_ids)
    sampled = sample_evenly(team_ids, team_count)
    stats.teams_sampled = len(sampled)
    print(f"leaderboard: {len(team_ids)} teams, sampling {len(sampled)}", file=sys.stderr)

    per_team: list[list[tuple[str, str]]] = []
    for team_id in sampled:
        games = parse_team_games(fetcher.get("team", team_id, f"/team/{team_id}"))
        stats.team_pages_read += 1
        stats.game_rows_seen += len(games)
        per_team.append(games)
    selected = interleave(per_team)
    stats.unique_games_seen = len(selected)
    del selected[max_games:]
    stats.games_selected = len(selected)
    print(
        f"team pages: {stats.team_pages_read}, unique games {stats.unique_games_seen}, "
        f"fetching {stats.games_selected}",
        file=sys.stderr,
    )

    for number, (game_id, listed_name) in enumerate(selected, start=1):
        page = fetcher.get("game", game_id, f"/game/{game_id}")
        stats.game_pages_read += 1
        start = parse_game_page(page)
        if start is None:
            stats.parse_failures.append(game_id)
            continue
        stats.games_with_fen += 1
        if start.setup != "1":
            stats.setup_header_missing += 1
        if start.opening is not None and start.opening != listed_name:
            stats.name_mismatches.append(
                f"{game_id}: team page {listed_name!r}, game page {start.opening!r}"
            )
        problem = fen_problem(start.fen)
        if problem is not None:
            stats.invalid_fens.append(f"{game_id}: {start.fen!r} ({problem})")
            continue
        openings.setdefault(start.fen, set()).add(listed_name)
        if number % 25 == 0 or number == len(selected):
            print(
                f"game pages: {number}/{len(selected)}, distinct FENs {len(openings)}",
                file=sys.stderr,
            )


def opening_lines(openings: Openings) -> list[str]:
    """``name<TAB>fen`` lines, one per distinct FEN, sorted by name then FEN.

    A FEN listed under several names (it should not happen) keeps the alphabetically first name so
    the output is a deterministic function of the pages read.
    """
    rows = sorted((min(names), fen) for fen, names in openings.items())
    return [f"{name}\t{fen}" for name, fen in rows]


def write_openings(path: Path, openings: Openings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(line + "\n" for line in opening_lines(openings)), encoding="utf-8")


def build_report(stats: Stats, openings: Openings, fetcher: Fetcher, out: Path) -> str:
    """The Markdown report: counts, the one-name-many-FENs table, and every problem seen."""
    names_to_fens: defaultdict[str, set[str]] = defaultdict(set)
    for fen, names in openings.items():
        for name in names:
            names_to_fens[name].add(fen)
    multi_fen = {name: fens for name, fens in names_to_fens.items() if len(fens) > 1}
    multi_name = {fen: names for fen, names in openings.items() if len(names) > 1}
    stamp = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Opening collection report",
        "",
        f"Generated by `tools/collect_openings.py` on {stamp}. Source: public game pages on",
        f"`{BASE_URL}` reached from the qualifier leaderboard. Output: `{out.name}` with",
        f"{len(openings)} distinct starting FENs.",
        "",
        "## Counts",
        "",
        "| Item | Count |",
        "|---|---:|",
        f"| Teams linked from the leaderboard | {stats.leaderboard_teams} |",
        f"| Teams sampled (evenly spaced over sorted uuids) | {stats.teams_sampled} |",
        f"| Team pages read | {stats.team_pages_read} |",
        f"| Game rows on those pages (before dedup) | {stats.game_rows_seen} |",
        f"| Unique games seen | {stats.unique_games_seen} |",
        f"| Games selected for fetching (cap applied) | {stats.games_selected} |",
        f"| Game pages read | {stats.game_pages_read} |",
        f"| Game pages with a FEN header | {stats.games_with_fen} |",
        f'| Game pages without `[SetUp "1"]` | {stats.setup_header_missing} |',
        f"| Distinct valid FENs | {len(openings)} |",
        f"| Distinct opening names | {len(names_to_fens)} |",
        f"| Names mapping to more than one FEN | {len(multi_fen)} |",
        f"| FENs listed under more than one name | {len(multi_name)} |",
        f"| HTTP requests made this run | {fetcher.network_fetches} |",
        f"| Pages served from the cache this run | {fetcher.cache_hits} |",
        f"| Parse failures (no PGN or no FEN on the page) | {len(stats.parse_failures)} |",
        f"| Invalid FENs rejected | {len(stats.invalid_fens)} |",
        f"| Opening-name mismatches (team page vs game page) | {len(stats.name_mismatches)} |",
        f"| Fatal errors (run stopped) | {len(stats.errors)} |",
        "",
        "## Names mapping to more than one FEN",
        "",
    ]
    if multi_fen:
        lines += ["| Name | Distinct FENs |", "|---|---:|"]
        lines += [f"| {name} | {len(fens)} |" for name, fens in sorted(multi_fen.items())]
    else:
        lines.append("None.")
    lines += ["", "## FENs per name", "", "| Name | Distinct FENs |", "|---|---:|"]
    lines += [f"| {name} | {len(fens)} |" for name, fens in sorted(names_to_fens.items())]

    def problem_section(title: str, items: Sequence[str]) -> list[str]:
        body = [f"- {item}" for item in items] if items else ["None."]
        return ["", f"## {title}", "", *body]

    lines += problem_section("Fatal errors", stats.errors)
    lines += problem_section("Parse failures (game ids)", stats.parse_failures)
    lines += problem_section("Invalid FENs", stats.invalid_fens)
    lines += problem_section("Opening-name mismatches", stats.name_mismatches)
    lines += problem_section(
        "FENs listed under more than one name",
        [f"{fen}: {sorted(names)}" for fen, names in sorted(multi_name.items())],
    )
    return "\n".join(lines) + "\n"


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--teams", type=int, default=80, help="teams to sample (default 80)")
    parser.add_argument(
        "--max-games", type=int, default=400, help="cap on game pages to read (default 400)"
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=ROOT / "data" / "cache", help="page cache directory"
    )
    parser.add_argument(
        "--out", type=Path, default=ROOT / "data" / "openings.txt", help="name<TAB>fen output"
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "data" / "openings_report.md", help="Markdown report"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    fetcher = Fetcher(cache_dir=args.cache_dir)
    stats = Stats()
    openings: Openings = {}
    try:
        crawl(fetcher, args.teams, args.max_games, stats, openings)
    except FetchError as exc:
        # Stop at once, keep what we have. Nothing is retried; a human decides whether to rerun.
        stats.errors.append(str(exc))
        print(f"stopped: {exc}", file=sys.stderr)
    write_openings(args.out, openings)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(build_report(stats, openings, fetcher, args.out), encoding="utf-8")
    print(
        f"wrote {len(openings)} openings to {args.out} and the report to {args.report} "
        f"({fetcher.network_fetches} requests, {fetcher.cache_hits} cache hits)",
        file=sys.stderr,
    )
    return 1 if stats.errors else 0


if __name__ == "__main__":
    sys.exit(main())
