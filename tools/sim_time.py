"""Simulate the clock over whole games, so the ``moves_to_go`` constants are chosen from numbers.

No search and no games: this iterates the budget formula the way a game does -- spend what the
plan allows, then collect the increment -- over the *measured* distribution of game lengths on the
ladder (``data/pgn/ladder-top``, 249 finished games of the five highest-rated teams, plus
``ladder-top50`` when present). It is deterministic and re-runnable::

    .venv/bin/python -m tools.sim_time                 # the length data, the fit, and a grid
    .venv/bin/python -m tools.sim_time --usage 0.7     # at the spending rate measured on the engine

Two numbers drive the calibration. The first is how many of our moves are *left* at each point of
a game, conditioned on the game having got there: that is what ``moves_to_go`` estimates, and the
ladder games measure it directly. The second is the share of the soft budget a move actually
spends, which is 0.70 for the predictive iteration control (docs/CALIBRATION.md, 2026-09-08); it
matters because the clock a long game settles at is where spending equals the increment.

Our own five rated games (``data/pgn/ours``: 18, 23, 51, 105 and 113 of our moves, ending on 87.5,
90.2, 31.6, 6.0 and 4.7 seconds) are the check that the model is right before it is trusted.
"""

from __future__ import annotations

import argparse
import dataclasses
import math
import statistics
from collections.abc import Sequence
from pathlib import Path

import chess.pgn

from mikhail_letal.timing import DEFAULT_PARAMS, TimeParams, budget

REPO = Path(__file__).resolve().parent.parent
LADDER = ("ladder-top", "ladder-top50")

# Our five rated games under v1.0 (`data/pgn/ours`, clocks verified against the platform's log):
# game, our moves, seconds left at the end.
MEASURED: tuple[tuple[str, int, float], ...] = (
    ("1e1c9922", 18, 87.5),
    ("3ebceb52", 23, 90.2),
    ("cf4043b1", 51, 31.6),
    ("f43e60b5", 105, 6.0),
    ("5504d7fa", 113, 4.7),
)

START_MS = 120_000


def game_lengths(directories: Sequence[str] = LADDER) -> list[int]:
    """Our own moves per game, from every ladder PGN that is present."""
    lengths: list[int] = []
    for name in directories:
        folder = REPO / "data" / "pgn" / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.pgn")):
            with path.open() as handle:
                while (game := chess.pgn.read_game(handle)) is not None:
                    plies = sum(1 for _ in game.mainline_moves())
                    if plies:
                        lengths.append((plies + 1) // 2)  # the side that moves first
    return lengths


def moves_left(lengths: Sequence[int], at: int) -> tuple[int, float, float]:
    """Games that reached our move ``at``, and the mean and median of our moves still to play."""
    remaining = [length - at for length in lengths if length > at]
    if not remaining:
        return 0, 0.0, 0.0
    return len(remaining), statistics.mean(remaining), statistics.median(remaining)


def play(params: TimeParams, our_moves: int, usage: float) -> list[float]:
    """The clock in ms after each of our moves, before the increment lands.

    ``usage`` is the share of the soft target a move actually spends: 0.70 is what the predictive
    iteration control was measured to spend, 1.0 a move that stops exactly on target.
    """
    clock = float(START_MS)
    after: list[float] = []
    for played in range(our_moves):
        if clock < params.panic_ms:
            spend = 0.0  # the agent skips the engine and plays the fallback, which is instant
        else:
            plan = budget(int(clock), played, params)
            spend = min(usage * plan.soft_ms, plan.hard_ms)
        clock -= spend
        after.append(clock)
        clock += params.increment_ms
    return after


PHASES = ((0, 20), (20, 50), (50, 80), (80, 10_000))


def per_phase(params: TimeParams, our_moves: int, usage: float) -> list[float]:
    """Mean seconds spent on our moves in each phase of ``PHASES``, over one game (0 if empty)."""
    clocks = [START_MS, *(c + params.increment_ms for c in play(params, our_moves, usage))]
    spends = [(clocks[i] - clocks[i + 1] + params.increment_ms) / 1000 for i in range(our_moves)]
    return [
        statistics.mean(spends[start:stop]) if spends[start:stop] else 0.0 for start, stop in PHASES
    ]


def evaluate(params: TimeParams, lengths: Sequence[int], usage: float) -> dict[str, float]:
    """How a set of constants behaves over the measured distribution of game lengths."""
    left: list[float] = []
    lowest: list[float] = []
    starved = 0
    total = 0
    phases: list[list[float]] = [[] for _ in PHASES]
    spent_share: list[float] = []
    log_spend: list[float] = []
    for length in lengths:
        after = play(params, length, usage)
        left.append(after[-1] / 1000)
        lowest.append(min(after) / 1000)
        starved += sum(1 for clock in after if clock < params.panic_ms)
        total += length
        budgeted = START_MS + params.increment_ms * length
        spent_share.append(100.0 * (budgeted - after[-1] - params.increment_ms) / budgeted)
        clocks = [START_MS, *(c + params.increment_ms for c in after)]
        for index in range(length):
            spend = (clocks[index] - clocks[index + 1] + params.increment_ms) / 1000
            # Depth grows like the logarithm of the time spent, so the mean of the logarithm over
            # every move of every game is the quantity that stands in for mean depth. A fallback
            # move (no search at all) is floored rather than allowed to be minus infinity.
            log_spend.append(math.log2(max(spend, 0.05)))
        for bucket, mean in zip(phases, per_phase(params, length, usage), strict=True):
            if mean:
                bucket.append(mean)
    result = {
        "left_mean": statistics.mean(left),
        "left_median": statistics.median(left),
        "lowest_min": min(lowest),
        "lowest_median": statistics.median(lowest),
        "fallback_share": 100.0 * starved / total,
        "spent_share": statistics.mean(spent_share),
        "geometric_s": 2 ** statistics.mean(log_spend),
    }
    for index, bucket in enumerate(phases):
        result[f"phase{index}"] = statistics.mean(bucket) if bucket else 0.0
    return result


def header() -> str:
    return (
        f"{'max min decay':>15} {'soft@0':>7} {'left mean':>9} {'left med':>9} {'low min':>8} "
        f"{'low med':>8} {'used':>6} {'geo s':>6} {'s@0-19':>7} {'s@20-49':>8} {'s@50-79':>8} "
        f"{'s@80+':>7}"
    )


def row(params: TimeParams, lengths: Sequence[int], usage: float) -> str:
    result = evaluate(params, lengths, usage)
    name = (
        f"{params.moves_to_go_max:>3} {params.moves_to_go_min:>3} {params.moves_to_go_decay:>5.2f}"
    )
    plan = budget(START_MS, 0, params)
    return (
        f"{name:>15} {plan.soft_ms:>7.0f} {result['left_mean']:>9.1f} "
        f"{result['left_median']:>9.1f} "
        f"{result['lowest_min']:>8.1f} {result['lowest_median']:>8.1f} "
        f"{result['spent_share']:>5.0f}% {result['geometric_s']:>6.2f} "
        f"{result['phase0']:>7.2f} {result['phase1']:>8.2f} "
        f"{result['phase2']:>8.2f} {result['phase3']:>7.2f}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max", type=int, nargs="+", default=[40, 55, 65, 70, 80])
    parser.add_argument("--min", type=int, nargs="+", default=[12, 20, 25, 30, 40])
    parser.add_argument("--decay", type=float, nargs="+", default=[0.5, 1.0])
    parser.add_argument("--usage", type=float, default=0.7, help="share of the soft budget spent")
    parser.add_argument(
        "--min-moves",
        type=int,
        default=0,
        help="only score games with at least this many of our moves (the long tail)",
    )
    arguments = parser.parse_args(argv)

    lengths = [length for length in game_lengths() if length >= arguments.min_moves]
    if not lengths:
        print("no ladder PGNs found under data/pgn; nothing to calibrate against")
        return 1
    print(
        f"{len(lengths)} ladder games: mean {statistics.mean(lengths):.1f} of our moves, "
        f"median {statistics.median(lengths):.0f}, longest {max(lengths)}"
    )
    print("\nour moves still to play, given the game reached that move:")
    print(f"{'at move':>8} {'games':>6} {'mean left':>10} {'median left':>12} {'formula':>8}")
    for at in range(0, 101, 10):
        count, mean, median = moves_left(lengths, at)
        formula = max(
            DEFAULT_PARAMS.moves_to_go_min,
            min(
                DEFAULT_PARAMS.moves_to_go_max,
                DEFAULT_PARAMS.moves_to_go_max - int(at * DEFAULT_PARAMS.moves_to_go_decay),
            ),
        )
        print(f"{at:>8} {count:>6} {mean:>10.1f} {median:>12.1f} {formula:>8}")

    print(f"\nclock over those games, spending {arguments.usage:.2f} of the soft budget a move")
    print(header())
    for decay in arguments.decay:
        for maximum in arguments.max:
            for minimum in arguments.min:
                if minimum > maximum:
                    continue
                params = dataclasses.replace(
                    DEFAULT_PARAMS,
                    moves_to_go_max=maximum,
                    moves_to_go_min=minimum,
                    moves_to_go_decay=decay,
                )
                print(row(params, lengths, arguments.usage))

    print("\ncurrent defaults:")
    print(header())
    print(row(DEFAULT_PARAMS, lengths, arguments.usage))

    print("\nour five rated games under v1.0's constants, as a check on the model:")
    v10 = dataclasses.replace(
        DEFAULT_PARAMS,
        overhead_ms=150,
        moves_to_go_max=40,
        moves_to_go_min=12,
        moves_to_go_decay=0.5,
    )
    for game, moves, measured in MEASURED:
        modelled = play(v10, moves, arguments.usage)[-1] / 1000
        print(f"  {game}: {moves:>3} moves, measured {measured:>5.1f} s, model {modelled:>5.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
