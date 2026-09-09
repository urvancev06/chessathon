"""Node cost of quiescence checks (`search.QS_CHECK_PLIES`), at a fixed depth.

Quiescence checks buy tactical sight and pay for it in nodes, and the price has to be known
before any strength claim is worth making: every check searched hands its child a position where
the side to move is in check, and the child then searches every legal evasion. This measures the
multiplier on the curated opening positions the engine actually plays from.

Each setting runs in its own process. `QS_CHECK_PLIES` reaches the compiled search as a module
global, and numba freezes a module global into the machine code the first time a function is
compiled, so changing it inside a live process changes nothing. The child sets it on
`mikhail_letal.search` *before* `mikhail_letal.fastsearch` imports the name, which is the only
moment it can be changed.

    .venv/bin/python tools/bench_qchecks.py --depth 7 --positions 24
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_positions(count: int) -> list[str]:
    """Curated openings, evenly spaced so the sample spans the whole file rather than its head."""
    lines = (ROOT / "data" / "openings.txt").read_text().splitlines()
    fens = [line.split("\t")[1] for line in lines if "\t" in line]
    if count >= len(fens):
        return fens
    step = len(fens) / count
    return [fens[int(i * step)] for i in range(count)]


def _measure(plies: int, depth: int, count: int) -> dict[str, float]:
    """Search every position to `depth` in this process, with checks capped at `plies`."""
    import chess

    from mikhail_letal import search as search_module

    search_module.QS_CHECK_PLIES = plies  # must precede the fastsearch import; see the docstring

    from mikhail_letal import fastsearch
    from mikhail_letal.fastboard import position_key

    assert plies == fastsearch.QS_CHECK_PLIES, "the constant did not reach the compiled engine"

    engine = fastsearch.FastEngine()
    fastsearch.warm_up(engine)

    nodes = 0
    seldepth = 0
    elapsed = 0.0
    picks: list[str] = []
    scores: list[int] = []
    for fen in _load_positions(count):
        board = chess.Board(fen)
        engine.new_game()
        far = time.perf_counter() + 3600.0
        started = time.perf_counter()
        result = engine.search(board, [position_key(board)], far, far, max_depth=depth)
        elapsed += time.perf_counter() - started
        assert not result.aborted, f"search aborted on {fen}"
        nodes += result.nodes
        seldepth = max(seldepth, result.seldepth)
        # The move and the score are what decide whether the extra nodes bought anything: a
        # feature that never changes the answer is cost with no benefit, however cheap it is.
        picks.append(result.move.uci() if result.move is not None else "none")
        scores.append(int(result.score))
    return {
        "plies": plies,
        "nodes": nodes,
        "seconds": elapsed,
        "seldepth": seldepth,
        "picks": picks,
        "scores": scores,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, default=7)
    parser.add_argument("--positions", type=int, default=24)
    parser.add_argument("--plies", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--child", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child is not None:
        print(json.dumps(_measure(args.child, args.depth, args.positions)))
        return 0

    rows: list[dict[str, float]] = []
    for plies in args.plies:
        done = subprocess.run(
            [
                sys.executable,
                __file__,
                "--child",
                str(plies),
                "--depth",
                str(args.depth),
                "--positions",
                str(args.positions),
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        if done.returncode != 0:
            sys.stderr.write(done.stdout + done.stderr)
            raise SystemExit(f"QS_CHECK_PLIES={plies} failed")
        rows.append(json.loads(done.stdout.strip().splitlines()[-1]))

    base = rows[0]["nodes"]
    base_s = rows[0]["seconds"]
    base_picks = rows[0]["picks"]
    base_scores = rows[0]["scores"]
    print(f"\n{args.positions} curated openings, fixed depth {args.depth}\n")
    print(f"{'QS_CHECK_PLIES':>15} {'nodes':>14} {'x':>7} {'seconds':>9} {'x':>7} {'seldepth':>9}")
    for row in rows:
        print(
            f"{int(row['plies']):>15} {int(row['nodes']):>14,} "
            f"{row['nodes'] / base:>7.2f} {row['seconds']:>9.1f} "
            f"{row['seconds'] / base_s:>7.2f} {int(row['seldepth']):>9}"
        )

    # Cost is only half the question. A feature that never changes the move it picks, nor the
    # score it reports, has bought nothing whatever the multiplier says.
    print(
        f"\n{'QS_CHECK_PLIES':>15} {'moves changed':>14} "
        f"{'scores changed':>15} {'max cp shift':>13}"
    )
    for row in rows[1:]:
        moved = sum(a != b for a, b in zip(base_picks, row["picks"], strict=True))
        shifted = [abs(a - b) for a, b in zip(base_scores, row["scores"], strict=True) if a != b]
        print(
            f"{int(row['plies']):>15} {moved:>7}/{len(base_picks):<6} "
            f"{len(shifted):>8}/{len(base_scores):<6} {max(shifted, default=0):>13}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
