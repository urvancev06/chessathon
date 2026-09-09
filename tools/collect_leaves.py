"""Collect the positions a real search actually evaluates, and compare them to game positions.

The hypothesis: the network was trained on positions from played games, but a search asks about
LEAF nodes -- unbalanced positions reached by move sequences no player would choose. A hand-crafted
evaluation degrades gracefully out there because material still counts; a network's error
off-distribution is unbounded. That would explain a net that wins every game-position metric and
still loses 67 Elo.

Leaves are captured by wrapping `searchboard.evaluate_running`, which is what `SearchBoard.evaluate`
calls, so these are exactly the positions the search asked about -- not a proxy built from random
walks, which would beg the question.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import chess

sys.path.insert(0, str(Path.cwd()))

import mikhail_letal.searchboard as searchboard
from mikhail_letal.search import Engine

INFINITY = float("inf")


def collect_leaves(fens: list[str], depth: int, per_position: int) -> list[str]:
    seen: list[str] = []
    # Monkeypatching a re-exported name: mypy cannot see it as an attribute of the module, so
    # the accesses are annotated rather than the tool restructured. Wrapping this function is
    # the whole point -- it is what SearchBoard.evaluate calls, so what it sees is exactly what
    # the search asked about.
    original = searchboard.evaluate_running  # type: ignore[attr-defined]

    def recording(board: chess.Board, mg: int, eg: int, phase: int) -> int:
        seen.append(board.fen())
        return int(original(board, mg, eg, phase))

    searchboard.evaluate_running = recording  # type: ignore[attr-defined]
    try:
        for fen in fens:
            before = len(seen)
            engine = Engine()
            board = chess.Board(fen)
            engine.search(board, {}, INFINITY, INFINITY, max_depth=depth, node_limit=per_position)
            print(f"  {fen.split(' ')[0][:24]:<24} {len(seen) - before:,} leaves")
    finally:
        searchboard.evaluate_running = original  # type: ignore[attr-defined]
    return seen


def main() -> int:
    root = Path.cwd()
    openings = [
        line.split("\t")[-1]
        for line in (root / "data" / "openings.txt").read_text().splitlines()
        if line.strip()
    ]
    rng = random.Random(20260909)
    starts = rng.sample(openings, 8)

    print("collecting search leaves at depth 6, 60k nodes per position")
    leaves = collect_leaves(starts, depth=6, per_position=60_000)
    print(f"{len(leaves):,} evaluations recorded")

    # Deduplicate and drop anything the network was trained on, so this measures distribution
    # rather than memory.
    trained = set()
    for name in ("nnue_labels_quiet.csv", "labels.csv"):
        path = root / "data" / "tuning" / name
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines()[2:]:
                trained.add(line.split(",")[0])
    unique = list(dict.fromkeys(leaves))
    fresh = [f for f in unique if f not in trained]
    print(f"{len(unique):,} unique, {len(fresh):,} not in the training set")

    rng.shuffle(fresh)
    keep = fresh[:1500]
    out = root.parent / "leaf_positions.epd"
    out.write_text("\n".join(keep) + "\n", encoding="utf-8")
    print(f"wrote {len(keep):,} to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
