"""Move-generation throughput of `mikhail_letal.fastboard` against `python-chess`.

Perft is the measurement because it is pure move generation and make/unmake with nothing else in
it: no evaluation, no ordering, no transposition table. The ratio it reports is therefore the
ceiling on what the compiled search can gain over the interpreted one, not a promise of it.

Both sides count the same tree. `python-chess` gets bulk counting at the last ply
(`legal_moves.count()`), which is the fastest honest way to run perft with it; the compiled side
does not, so if anything the ratio is understated.

    .venv/bin/python tools/bench_fastboard.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikhail_letal import fastboard as fb

POSITIONS: list[tuple[str, str, int]] = [
    ("initial", chess.STARTING_FEN, 5),
    ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 4),
    ("middlegame", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", 4),
    ("endgame", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 5),
]


def chess_perft(board: chess.Board, depth: int) -> int:
    if depth <= 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    total = 0
    for move in board.legal_moves:
        board.push(move)
        total += chess_perft(board, depth - 1)
        board.pop()
    return total


def measure_import_cost() -> tuple[float, float]:
    """Import the module in a fresh interpreter and read back its compile cost.

    A fresh process is the only honest measurement: numba compiles once per process, so importing
    a second time in this one would report zero.
    """
    root = Path(__file__).resolve().parent.parent
    script = (
        "import time; t = time.perf_counter();"
        " from mikhail_letal import fastboard;"
        " print(time.perf_counter() - t, fastboard.WARM_UP_SECONDS)"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    return float(out[0]), float(out[1])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3, help="best of this many timed runs")
    args = parser.parse_args()

    total_import, compile_seconds = measure_import_cost()
    print(f"import of mikhail_letal.fastboard: {total_import:.2f} s")
    print(f"  of which warm_up() compilation:  {compile_seconds:.2f} s")
    print()
    print(f"{'position':<12}{'depth':>6}{'nodes':>12}{'fastboard':>14}{'python-chess':>14}{'x':>7}")

    fast_total = 0.0
    slow_total = 0.0
    node_total = 0
    for name, fen, depth in POSITIONS:
        pos = fb.from_fen(fen)
        stack = fb.new_move_stack(depth + 1)
        board = chess.Board(fen)

        fast = float("inf")
        nodes = 0
        for _ in range(args.repeats):
            started = time.perf_counter()
            nodes = int(fb.perft(pos, stack, depth, 0))
            fast = min(fast, time.perf_counter() - started)

        slow = float("inf")
        oracle = 0
        for _ in range(args.repeats):
            started = time.perf_counter()
            oracle = chess_perft(board, depth)
            slow = min(slow, time.perf_counter() - started)

        if nodes != oracle:
            raise SystemExit(f"{name} depth {depth}: {nodes} != python-chess {oracle}")
        fast_total += fast
        slow_total += slow
        node_total += nodes
        print(
            f"{name:<12}{depth:>6}{nodes:>12,}"
            f"{nodes / fast / 1e6:>11.2f} M/s"
            f"{nodes / slow / 1e6:>11.2f} M/s"
            f"{slow / fast:>6.0f}x"
        )

    print()
    print(
        f"overall: {node_total:,} nodes, "
        f"{node_total / fast_total / 1e6:.2f} M/s compiled vs "
        f"{node_total / slow_total / 1e6:.2f} M/s python-chess, "
        f"{slow_total / fast_total:.0f}x"
    )


if __name__ == "__main__":
    main()
