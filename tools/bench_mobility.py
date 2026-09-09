"""What the mobility term costs the compiled search, in nodes per second.

Two measurements, because they answer different questions and one of them lies under load.

The **ratio** is the figure to trust. Each position is searched to a fixed depth twice in a row,
once with the term on and once with it off, alternating which arm goes first; both arms therefore
meet the same machine, and a background process that halves the node rate halves it for both. A
session measured 1.11x and 1.07x wall clock for the same 1.12x node count on this box under
contention, which is why seconds are only ever compared within a pair.

The **absolute** nodes per second is what the ratio is a ratio of, and it is only meaningful on an
idle machine. It is printed with a warning if the load average says otherwise.

The term is switched with ``fasteval.TABLES.misc[E_MOBILITY_ON]``, a single array entry the
compiled code reads at run time. Nothing is recompiled between the arms, so the two runs are the
same machine code reaching a different branch -- which is exactly the cost being measured.

Note what the node *counts* mean. Turning the term off changes the evaluation, so the two arms
search different trees and reach a fixed depth after different numbers of nodes. That difference
is a search-quality effect, not a speed cost, and it is reported separately.

    .venv/bin/python tools/bench_mobility.py --depth 7 --rounds 3
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikhail_letal import fasteval
from mikhail_letal.fastboard import position_key
from mikhail_letal.fasteval import E_MOBILITY_ON
from mikhail_letal.fastsearch import FastEngine

ROOT = Path(__file__).resolve().parent.parent
OPENINGS = ROOT / "data" / "openings.txt"


def curated_positions(count: int) -> list[str]:
    """An evenly spaced sample of the curated openings, which is where rated games start."""
    fens = []
    for line in OPENINGS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            fens.append(line.split("\t")[-1])
    if not fens:
        raise SystemExit(f"no openings in {OPENINGS}")
    step = max(1, len(fens) // count)
    return fens[::step][:count]


def search_once(engine: FastEngine, fen: str, depth: int, mobility_on: bool) -> tuple[int, float]:
    """Nodes and seconds for one fixed-depth search. Returns wall time measured around the call.

    ``new_game`` before every search: a transposition table carried over from the previous arm
    would make whichever arm ran second look faster, which is the whole measurement.
    """
    fasteval.TABLES.misc[E_MOBILITY_ON] = 1 if mobility_on else 0
    engine.new_game()
    board = chess.Board(fen)
    far = time.perf_counter() + 3600.0
    started = time.perf_counter()
    result = engine.search(
        board, [position_key(board)], far, far, max_depth=depth, node_limit=10**12
    )
    elapsed = time.perf_counter() - started
    if result.aborted:
        raise SystemExit(f"search aborted, which a fixed-depth run must never do: {fen}")
    if result.depth != depth:
        raise SystemExit(f"reached depth {result.depth}, not {depth}: {fen}")
    return result.nodes, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--positions", type=int, default=12)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true", help="print every pair")
    args = parser.parse_args()

    load = os.getloadavg()[0]
    fens = curated_positions(args.positions)
    engine = FastEngine()

    print(f"depth {args.depth}, {len(fens)} curated positions, {args.rounds} rounds")
    print(f"load average at start: {load:.2f} on {os.cpu_count()} cores")
    if load > 1.5:
        print("  WARNING: the box is busy. The ratio survives this; the absolute nps does not.")
    print()

    # The first round is run and thrown away. One search per position costs far more the first
    # time it is made than ever again -- measured here at 1.119 s against 0.118 s for the *same
    # search*, same node count, in the two rounds that followed -- and one such search left in a
    # total is worth more than the whole effect being measured. Node counts are deterministic per
    # arm, so a repeat is genuinely the same work and the comparison is sound.
    print("warm-up round (run, not counted)")
    for fen in fens:
        for on in (True, False):
            search_once(engine, fen, args.depth, mobility_on=on)

    ratios: list[float] = []
    total_nodes: dict[bool, int] = {True: 0, False: 0}
    total_seconds: dict[bool, float] = {True: 0.0, False: 0.0}
    for round_index in range(args.rounds):
        # Alternate which arm goes first, so a machine that drifts slower over the run does not
        # charge the drift to whichever arm always ran second.
        arms = [True, False] if round_index % 2 == 0 else [False, True]
        for fen in fens:
            measured = {}
            for on in arms:
                nodes, elapsed = search_once(engine, fen, args.depth, mobility_on=on)
                measured[on] = (nodes, elapsed)
                total_nodes[on] += nodes
                total_seconds[on] += elapsed
            on_nps = measured[True][0] / measured[True][1]
            off_nps = measured[False][0] / measured[False][1]
            ratios.append(on_nps / off_nps)
            if args.verbose:
                print(
                    f"  {fen.split(' ')[0][:20]:<20} "
                    f"on {measured[True][0]:>8,}n {measured[True][1]:6.3f}s {on_nps:>9,.0f} "
                    f"| off {measured[False][0]:>8,}n {measured[False][1]:6.3f}s {off_nps:>9,.0f} "
                    f"| {on_nps / off_nps:.3f}"
                )
        print(f"round {round_index + 1}: {len(fens)} paired searches done")

    print()
    for on in (False, True):
        label = "with mobility   " if on else "without mobility"
        rate = total_nodes[on] / total_seconds[on]
        print(
            f"{label}: {total_nodes[on]:>12,} nodes "
            f"{total_seconds[on]:8.2f} s {rate:>10,.0f} nodes/s"
        )

    # The median, not the mean. One search that met a busy moment is a factor-of-seven outlier
    # -- the first run of this tool produced exactly that -- and a mean over a few dozen pairs
    # carries it straight into the answer. The spread below is what says whether it happened.
    median = statistics.median(ratios)
    mean = statistics.mean(ratios)
    print()
    print(f"paired nps ratio (on / off): median {median:.4f}  mean {mean:.4f}")
    print(f"                             min {min(ratios):.4f}  max {max(ratios):.4f}")
    print(f"                             over {len(ratios)} pairs")
    pooled = (total_nodes[True] / total_seconds[True]) / (total_nodes[False] / total_seconds[False])
    print(f"same ratio from the pooled totals: {pooled:.4f}")
    print(f"cost of the term:            {(1 - median) * 100:.1f}% of the node rate")
    print()
    nodes_ratio = total_nodes[True] / total_nodes[False]
    print(f"nodes to depth {args.depth} (on / off): {nodes_ratio:.4f}")
    print("  a different evaluation searches a different tree; this is not a speed cost.")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "depth": args.depth,
                    "rounds": args.rounds,
                    "positions": len(fens),
                    "load_average_at_start": load,
                    "nps_with": total_nodes[True] / total_seconds[True],
                    "nps_without": total_nodes[False] / total_seconds[False],
                    "paired_ratio_median": median,
                    "paired_ratio_mean": mean,
                    "paired_ratio_min": min(ratios),
                    "paired_ratio_max": max(ratios),
                    "pairs": len(ratios),
                    "pooled_ratio": pooled,
                    "nodes_ratio": nodes_ratio,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
