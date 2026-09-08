"""Download the finished games of the highest-rated ladder teams, for scouting the field.

The site publishes every finished game, and `robots.txt` allows `/leaderboard`, `/team/` and
`/game/`. This reuses `collect_openings`'s fetcher, so the same etiquette applies: one request a
second, a descriptive User-Agent, every page cached so a rerun costs nothing, and the run stops on
the first error rather than hammering.

What the games are for: understanding the field we play against. They are evidence, not a source
of moves. Shipping a table of anybody's moves or evaluations for the agent to consult at runtime
is banned by the contract, and nothing here goes near the submission.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.parse
from pathlib import Path

from tools.collect_openings import (
    PGN_HREF_RE,
    UUID,
    Fetcher,
    parse_team_games,
)

# The leaderboard is a Next.js payload: the rows arrive as escaped JSON, in rank order. Document
# order is the ranking, so the first match is rank 1.
RANKED_TEAM_RE = re.compile(rf'data-href\\?"?:\\?"?/team/({UUID})\?from=lb')
TEAM_NAME_RE = re.compile(r'"ladder-team"[^}]*?"children":"([^"]+)"')


def ranked_team_ids(page: str) -> list[str]:
    """Team uuids in leaderboard order, highest rated first, duplicates removed."""
    seen: dict[str, None] = {}
    for team_id in RANKED_TEAM_RE.findall(page):
        seen.setdefault(team_id, None)
    return list(seen)


def game_pgn(page: str) -> str | None:
    """The full PGN embedded in a game page's download link."""
    link = PGN_HREF_RE.search(page)
    if link is None:
        return None
    return urllib.parse.unquote(html.unescape(link.group(1)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teams", type=int, default=5, help="how many top teams to collect")
    parser.add_argument("--max-games", type=int, default=400, help="cap on game pages fetched")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/cache"))
    parser.add_argument("--out", type=Path, default=Path("data/pgn/ladder-top"))
    arguments = parser.parse_args(argv)

    fetcher = Fetcher(cache_dir=arguments.cache_dir)
    board = fetcher.get("leaderboard", "qualifier", "/leaderboard?stage=qualifier")
    ranked = ranked_team_ids(board)
    if not ranked:
        print("no teams parsed from the leaderboard; the page layout has changed", file=sys.stderr)
        return 1
    top = ranked[: arguments.teams]
    print(f"{len(ranked)} teams on the leaderboard; taking the top {len(top)}")

    arguments.out.mkdir(parents=True, exist_ok=True)
    written = 0
    for rank, team_id in enumerate(top, start=1):
        page = fetcher.get("team", team_id, f"/team/{team_id}")
        games = parse_team_games(page)
        print(f"  rank {rank} {team_id[:8]}: {len(games)} finished games")
        for game_id, _opening in games:
            if written >= arguments.max_games:
                break
            pgn = game_pgn(fetcher.get("game", game_id, f"/game/{game_id}"))
            if pgn is None:
                continue
            (arguments.out / f"rank{rank:02d}-{game_id[:12]}.pgn").write_text(
                pgn + "\n", encoding="utf-8"
            )
            written += 1

    print(f"\n{written} PGNs written to {arguments.out}")
    print(f"{fetcher.network_fetches} pages downloaded, {fetcher.cache_hits} served from cache")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
