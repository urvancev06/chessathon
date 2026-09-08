"""Compute the promotion decision from the chunk JSONs, mechanically.

Written *before* the match finished, for the same reason the rule was pre-registered: at 03:40
somebody tired will be reading numbers, and every step that is arithmetic rather than judgement is
a step that cannot drift toward the answer we want. This script makes the decision; nobody makes it
by hand.

It reports the verdict under **both** safety gates, because ``docs/DECISIONS.md`` commits to
publishing both:

* the **original** gate (written before any result existed): no ``flag``, and the run minimum
  ``agent_low_clock_ms`` above 5 000 ms;
* the **adopted** gate (authored blind by ``chessathon-64`` after the original was found to be
  n-dependent): no ``flag``, and at most 2 % of games below 5 000 ms.

The original is n-dependent by construction -- a minimum can only fall as games are added -- which
is why it was replaced. Both are printed so a judge can apply either, along with the underlying
distribution so they can apply a threshold of their own.

    .venv/bin/python -m tools.promotion_verdict <chunk>.json [<chunk>.json ...]

Reads only; writes nothing; never ships.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics as stats
from collections import Counter
from pathlib import Path
from typing import Any

from tools.arena_openings import elo_from_score, statistics

# From docs/DECISIONS.md. Duplicated here deliberately rather than imported from the engine: these
# are the terms of a decision, not a runtime constant, and they must not change if the engine does.
LOW_CLOCK_MS = 5_000.0  # "near the panic floor": three times panic_ms
PANIC_MS = 1_650.0  # below this get_move abandons the search and plays a fallback
ADOPTED_RATE = 0.02  # at most 2 % of games below LOW_CLOCK_MS
BASE_MARGIN_ELO = -40.0  # non-inferiority margin at the full 300 games
BASE_GAMES = 300
# The match is 300 games in three chunks. Fewer than this is an *interim* look, and
# docs/DECISIONS.md (amendment 4) makes interim looks reject-only: a chunk may stop the match for
# futility, no chunk may promote. This script enforces that rather than trusting whoever runs it at
# 23:20 not to read a promotion out of chunk A.
FUTILITY_UPPER_BOUND = 0.50  # stop iff the optimistic end of the interval is still a regression


def load_games(paths: list[Path]) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    for path in paths:
        record = json.loads(path.read_text())
        games.extend(record["results"])
    return games


def tally(games: list[dict[str, Any]]) -> tuple[int, int, int]:
    """(wins, draws, losses) from the agent's point of view."""
    wins = sum(1 for g in games if g["result"] == g["colour"])
    draws = sum(1 for g in games if g["result"] == "draw")
    losses = sum(
        1 for g in games if g["result"] in ("white", "black") and g["result"] != g["colour"]
    )
    return wins, draws, losses


def clocks(games: list[dict[str, Any]]) -> list[float]:
    return [g["agent_low_clock_ms"] for g in games if g["agent_low_clock_ms"] is not None]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks", nargs="+", type=Path)
    arguments = parser.parse_args(argv)

    games = load_games(arguments.chunks)
    # Void games (both agents failed) are excluded from the score by arena_openings, so they must
    # be excluded from n too. Counting them would inflate n in two places: it tightens the margin
    # harmlessly, but it also lets three chunks with two voids reach n == 300 on 298 scored games,
    # so a match short of the pre-registered sample would be treated as the full look and the
    # reject-only protection of amendment 4 would stop applying exactly where it must hold.
    scored = [g for g in games if g["result"] != "void"]
    voids = len(games) - len(scored)
    games = scored
    n = len(games)
    wins, draws, losses = tally(games)
    terminations = Counter(g["termination"] for g in games)
    low = clocks(games)

    print(
        f"pooled over {n} scored games from {len(arguments.chunks)} chunk(s)"
        + (f" ({voids} void excluded)" if voids else "")
    )
    print(f"  +{wins} ={draws} -{losses}")
    print(f"  terminations: {dict(terminations)}")

    # --- the distribution, published so a judge can apply any threshold they prefer -------------
    below_low = [c for c in low if c < LOW_CLOCK_MS]
    below_panic = [c for c in low if c < PANIC_MS]
    print("\nclock distribution (agent_low_clock_ms, per game):")
    if low:
        worst = min(low)
        # `index` is 0-based *within a run*, and the chunks are three separate runs, so there are
        # three game 5s in the pool. `seed` is index + seed_offset and is unique across them, which
        # is what makes this line point at a game a judge can actually go and find.
        worst_seed = next(g["seed"] for g in games if g["agent_low_clock_ms"] == worst)
        print(f"  minimum      {worst:9.0f} ms   (seed {worst_seed})")
        if len(low) >= 10:
            print(f"  p10          {stats.quantiles(low, n=10)[0]:9.0f} ms")
        print(f"  median       {stats.median(low):9.0f} ms")
        print(
            f"  below {LOW_CLOCK_MS:.0f} ms {len(below_low):6d} of {len(low)}"
            f"   ({len(below_low) / len(low):.2%})"
        )
        print(f"  below {PANIC_MS:.0f} ms {len(below_panic):6d} of {len(low)}")
    else:
        print("  no clock data")

    # --- the two safety gates -------------------------------------------------------------------
    flagged = terminations.get("flag", 0)
    original_ok = flagged == 0 and bool(low) and min(low) > LOW_CLOCK_MS
    adopted_ok = flagged == 0 and bool(low) and len(below_low) <= ADOPTED_RATE * len(low)
    allowed = int(ADOPTED_RATE * len(low))
    print("\nsafety gates:")
    min_ok = bool(low) and min(low) > LOW_CLOCK_MS
    print(
        f"  original (pre-registered, n-dependent): {'PASS' if original_ok else 'FAIL'}"
        f"   [no flag: {flagged == 0}; min > {LOW_CLOCK_MS:.0f}: {min_ok}]"
    )
    print(
        f"  adopted  (authored blind, rate-based) : {'PASS' if adopted_ok else 'FAIL'}"
        f"   [no flag: {flagged == 0}; {len(below_low)} below <= {allowed} allowed]"
    )
    if original_ok != adopted_ok:
        print("  *** the two gates DISAGREE -- docs/DECISIONS.md requires this be recorded as a")
        print("      finding, not a footnote ***")

    # --- the Elo decision, one look on the pooled total ------------------------------------------
    result = statistics(wins, draws, losses)
    margin = BASE_MARGIN_ELO * math.sqrt(BASE_GAMES / n)
    print(f"\nElo, one look on the pooled {n}:")
    print(f"  score {result.score:.1%}" + (f" +- {result.margin:.1%}" if result.margin else ""))
    if result.elo is None:
        print("  interval touches 0% or 100%: Elo undefined")
    else:
        point = elo_from_score(result.score)
        print(f"  {point:+.0f} ({result.elo_low:+.0f} to {result.elo_high:+.0f})")
    print(f"  non-inferiority margin at n={n}: {margin:+.1f}")

    if result.elo_low is not None and result.elo_low > 0:
        elo_case = "promote (interval above zero)"
    elif result.score < 0.5 or (result.elo_low is not None and result.elo_low <= margin):
        elo_case = "REVERT (point estimate negative, or lower bound at/below the margin)"
    else:
        elo_case = "promote on the SAFETY criterion, not the Elo rule (interval straddles zero)"
    print(f"  Elo case: {elo_case}")

    if n < BASE_GAMES:
        # Interim look. No promotion may be read out of it, whatever the numbers say above.
        print(f"\nINTERIM LOOK -- {n} of {BASE_GAMES} games. This look is REJECT-ONLY.")
        print("  No promotion may be taken from a partial match (docs/DECISIONS.md, amendment 4:")
        print("  three looks inflate the false-promotion rate from 2.60% to 5.71%, and the case-3")
        print("  gate from 51.22% to 70.35%). The Elo lines above are informational only.")
        upper = result.score + result.margin if result.margin is not None else 1.0
        if upper <= FUTILITY_UPPER_BOUND:
            print(
                f"\n  FUTILITY: upper bound {upper:.1%} <= {FUTILITY_UPPER_BOUND:.0%}."
                " Stop the match and revert; v1.0 ships."
            )
        else:
            print(
                f"\n  futility not met (upper bound {upper:.1%} > {FUTILITY_UPPER_BOUND:.0%})."
                " Keep running."
            )
        return 0

    print("\nverdict:")
    for name, ok in (("original gate", original_ok), ("adopted gate", adopted_ok)):
        if not ok:
            print(f"  under the {name}: NO PROMOTION (safety gate fails; Elo is not reached)")
        elif elo_case.startswith("REVERT"):
            print(f"  under the {name}: REVERT")
        else:
            print(f"  under the {name}: PROMOTE -- {elo_case}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
