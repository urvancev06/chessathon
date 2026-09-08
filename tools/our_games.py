"""Download our own finished rated games, so each new ladder round can be reviewed.

Rated rounds run hourly, 08:00-22:00. Our team page lists every finished game; each game page
embeds the full PGN, with ``[%clk]`` after every move for both sides. This keeps a local mirror in
``data/pgn/ours/`` and prints only what is new since the last run, so an hourly pass has something
short to read.

It reuses ``collect_openings``'s fetcher, so the same etiquette applies: one request a second, a
descriptive User-Agent, no disallowed path, and the run stops on the first error. One deliberate
difference: our own *team page* is re-fetched every time, because its whole purpose is to show
games that did not exist an hour ago. Game pages stay cached forever -- a finished game never
changes.

    .venv/bin/python -m tools.our_games            # fetch new games, list them
    .venv/bin/python -m tools.our_games --list     # what is already on disk, no network

These games are evidence about our own play. Nothing here ships, and nothing here becomes a table
the agent consults at runtime.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.parse
from pathlib import Path

from tools.collect_openings import PGN_HREF_RE, Fetcher, parse_team_games

# Our team on the qualifier ladder, read from the leaderboard page ("Mikhail LeTal", Warwick).
OUR_TEAM_ID = "1cc6bad3-460a-44a9-ad94-adc6d708f9ea"

RESULT_RE = re.compile(r'\[Result "([^"]+)"\]')
WHITE_RE = re.compile(r'\[White "([^"]+)"\]')
BLACK_RE = re.compile(r'\[Black "([^"]+)"\]')
DATE_RE = re.compile(r'\[(?:UTCDate|Date) "([^"]+)"\]')
FEN_RE = re.compile(r'\[FEN "([^"]+)"\]')
TERMINATION_RE = re.compile(r'\[Termination "([^"]+)"\]')
CLK_RE = re.compile(r"\[%clk ([0-9:.]+)\]")


def game_pgn(page: str) -> str | None:
    """The full PGN embedded in a game page's download link."""
    link = PGN_HREF_RE.search(page)
    if link is None:
        return None
    return urllib.parse.unquote(html.unescape(link.group(1)))


def _tag(pattern: re.Pattern[str], pgn: str) -> str:
    found = pattern.search(pgn)
    return found.group(1) if found else "?"


def summarise(pgn: str) -> str:
    """One line per game: who, result, how it ended, and the clock each side finished on."""
    white, black = _tag(WHITE_RE, pgn), _tag(BLACK_RE, pgn)
    ours_is_white = "letal" in white.lower()
    opponent = black if ours_is_white else white
    colour = "W" if ours_is_white else "B"

    clocks = CLK_RE.findall(pgn)
    # Clocks alternate, but rated games start from a curated position and most of ours start with
    # Black to move -- so the first clock belongs to the FEN's side to move, not to White. Getting
    # this backwards silently swaps the two clocks; it did, until round 70's known 90.2 s caught it.
    first_is_white = _tag(FEN_RE, pgn).split(" ")[1:2] != ["b"]
    offset = 0 if ours_is_white == first_is_white else 1
    ours = clocks[offset::2]
    theirs = clocks[1 - offset :: 2]
    last_ours = ours[-1] if ours else "?"
    last_theirs = theirs[-1] if theirs else "?"

    return (
        f"{_tag(DATE_RE, pgn)}  as {colour} vs {opponent:<24.24}  "
        f"{_tag(RESULT_RE, pgn):>7}  {_tag(TERMINATION_RE, pgn):<22.22}  "
        f"{len(clocks)} plies  clock left {last_ours} / {last_theirs}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--team", default=OUR_TEAM_ID, help="team uuid to collect")
    parser.add_argument("--out", type=Path, default=Path("data/pgn/ours"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument(
        "--list", action="store_true", help="summarise what is already on disk, fetch nothing"
    )
    arguments = parser.parse_args(argv)
    arguments.out.mkdir(parents=True, exist_ok=True)

    if arguments.list:
        for path in sorted(arguments.out.glob("*.pgn")):
            print(f"{path.name[:12]}  {summarise(path.read_text(encoding='utf-8'))}")
        return 0

    fetcher = Fetcher(cache_dir=arguments.cache_dir)
    # Force the team page to be fetched fresh; a cached copy cannot contain this round's game.
    stale = arguments.cache_dir / "team" / f"{arguments.team}.html"
    stale.unlink(missing_ok=True)

    page = fetcher.get("team", arguments.team, f"/team/{arguments.team}")
    games = parse_team_games(page)
    if not games:
        print("no games parsed from the team page; the layout may have changed", file=sys.stderr)
        return 1

    fresh: list[str] = []
    for game_id, opening in games:
        target = arguments.out / f"{game_id[:12]}.pgn"
        if target.is_file():
            continue
        pgn = game_pgn(fetcher.get("game", game_id, f"/game/{game_id}"))
        if pgn is None:
            continue
        target.write_text(pgn + "\n", encoding="utf-8")
        fresh.append(f"{game_id[:12]}  {summarise(pgn)}  [{opening}]")

    print(f"{len(games)} finished games listed, {len(fresh)} new")
    for line in fresh:
        print(f"  NEW  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
