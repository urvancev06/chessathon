"""What the trained network costs the compiled search, in nodes per second.

The same instrument as `tools/bench_mobility.py` and for the same reasons. Each position is
searched to a fixed depth twice in a row, once with the network and once with the hand-crafted
evaluation, alternating which arm goes first, so both meet the same machine and a background
process that halves the node rate halves it for both. The **median of the paired ratios** is the
figure to trust and the pooled total is printed beside it: when the two disagree, an outlier is
carrying the answer.

The first round is run and discarded. One search costs far more the first time it is made than
ever again -- measured at 1.119 s against 0.118 s for the *same search* in a later round -- and one
such search left in a total is worth more than the whole effect being measured.

The switch is `fasteval.TABLES.misc[E_NNUE_ON]`, one array entry the compiled code reads at run
time, so nothing is recompiled between the arms: the two runs are the same machine code reaching a
different branch, which is exactly the cost being measured.

Everything before this was a model -- kernel microbenchmarks times measured call rates. A model
cannot see a 196 KB weight table competing with the transposition table for cache. This can.

    .venv/bin/python tools/bench_network.py --depth 7 --rounds 5 --positions 24
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
from mikhail_letal.fasteval import E_NNUE_ON
from mikhail_letal.fastsearch import FastEngine

ROOT = Path(__file__).resolve().parent.parent
OPENINGS = ROOT / "data" / "openings.txt"


def curated_positions(count: int) -> list[str]:
    fens = [line.split("\t")[-1] for line in OPENINGS.read_text().splitlines() if line.strip()]
    step = max(1, len(fens) // count)
    return fens[::step][:count]


def search_once(engine: FastEngine, fen: str, depth: int, network: bool) -> tuple[int, float]:
    """Nodes and seconds for one fixed-depth search.

    `new_game` before every search: a transposition table carried over from the previous arm would
    make whichever ran second look faster, which is the whole measurement.
    """
    fasteval.TABLES.misc[E_NNUE_ON] = 1 if network else 0
    engine.new_game()
    board = chess.Board(fen)
    far = time.perf_counter() + 3600.0
    started = time.perf_counter()
    result = engine.search(
        board, [position_key(board)], far, far, max_depth=depth, node_limit=10**12
    )
    elapsed = time.perf_counter() - started
    if result.aborted or result.depth != depth:
        raise SystemExit(f"fixed-depth search did not complete at depth {depth}: {fen}")
    return result.nodes, elapsed


def summarise(values: list[float]) -> str:
    return f"median {statistics.median(values):.4f}  mean {statistics.mean(values):.4f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--positions", type=int, default=24)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not fasteval.NET_PATH.exists():
        raise SystemExit(f"no network at {fasteval.NET_PATH}")

    load = os.getloadavg()[0]
    fens = curated_positions(args.positions)
    engine = FastEngine()
    width = int(fasteval.TABLES.net.scalars[fasteval.N_WIDTH])
    print(f"depth {args.depth}, {len(fens)} curated positions, {args.rounds} rounds, width {width}")
    print(f"load average at start: {load:.2f} on {os.cpu_count()} cores")
    if load > 1.5:
        print("  WARNING: the box is busy. The ratio survives this; absolute nodes/s does not.")

    print("warm-up round (run, not counted)")
    for fen in fens:
        for network in (True, False):
            search_once(engine, fen, args.depth, network)

    ratios: list[float] = []
    nodes: dict[bool, int] = {True: 0, False: 0}
    seconds: dict[bool, float] = {True: 0.0, False: 0.0}
    for index in range(args.rounds):
        arms = [True, False] if index % 2 == 0 else [False, True]
        for fen in fens:
            measured: dict[bool, tuple[int, float]] = {}
            for network in arms:
                n, s = search_once(engine, fen, args.depth, network)
                measured[network] = (n, s)
                nodes[network] += n
                seconds[network] += s
            with_net = measured[True][0] / measured[True][1]
            without = measured[False][0] / measured[False][1]
            ratios.append(with_net / without)
            if args.verbose:
                print(
                    f"  {fen.split(' ')[0][:22]:<22} net {with_net:>9,.0f}  hand {without:>9,.0f}"
                )
        print(f"round {index + 1}: {len(fens)} paired searches done")

    print()
    for network in (False, True):
        label = "network        " if network else "hand-crafted   "
        rate = nodes[network] / seconds[network]
        print(f"{label}: {nodes[network]:>12,} nodes {seconds[network]:8.2f} s {rate:>10,.0f} n/s")

    median = statistics.median(ratios)
    pooled = (nodes[True] / seconds[True]) / (nodes[False] / seconds[False])
    print()
    print(f"paired node-rate ratio (network / hand-crafted): {summarise(ratios)}")
    print(f"                          min {min(ratios):.4f}  max {max(ratios):.4f}")
    print(f"same ratio from the pooled totals: {pooled:.4f}")
    print(f"cost of the network: {(1 - median) * 100:.1f}% of the node rate")
    print()
    print(f"nodes to depth {args.depth} (network / hand-crafted): {nodes[True] / nodes[False]:.4f}")
    print("  a different evaluation searches a different tree; this is not a speed cost.")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "depth": args.depth,
                    "rounds": args.rounds,
                    "positions": len(fens),
                    "width": width,
                    "load_at_start": load,
                    "nps_network": nodes[True] / seconds[True],
                    "nps_hand_crafted": nodes[False] / seconds[False],
                    "ratio_median": median,
                    "ratio_pooled": pooled,
                    "ratio_min": min(ratios),
                    "ratio_max": max(ratios),
                    "pairs": len(ratios),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
