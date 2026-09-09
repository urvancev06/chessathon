"""Is the piece-list `attacked` exact, and is it faster? Two questions, in that order.

`fastboard.attacked` walks eight rays outward from a square; `fastboard.attacked_from_list` walks
the attacker's piece list and consults a delta table. They must return the same answer on every
position -- that is what makes the change exact, and an exact change ships on a bench rather than
on nine hours of games.

    .venv/bin/python -m tools.bench_attacked            # equivalence, then timing
    .venv/bin/python -m tools.bench_attacked --quick    # fewer positions

Reports the MEDIAN OF PER-POSITION RATIOS, never a pooled sum. Two benchmark tools in this repo
computed one quantity as a paired median and another as a pooled sum in the same file, and the
pooled figure is what produced ratios spanning 0.96 to 2.19 on a quantity that was being quoted to
three decimal places. Any ratio across positions is a median of per-position ratios here.
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from pathlib import Path

import chess

from mikhail_letal import fastboard as fb

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENINGS = REPO_ROOT / "data" / "openings.txt"


def corpus(quick: bool) -> list[chess.Board]:
    """Positions from the collected openings, plus random playouts from each.

    The openings are where games start; the playouts are the middlegames and endgames the search
    actually spends its time in, and they are where the two scans differ most -- an outward scan
    costs the same whatever the material is, so a thin board is exactly where the piece list wins.
    """
    boards: list[chess.Board] = []
    if OPENINGS.exists():
        for line in OPENINGS.read_text().splitlines():
            parts = line.split("\t")
            if len(parts) == 2:
                boards.append(chess.Board(parts[1]))
    if not boards:
        boards.append(chess.Board())
    rng = random.Random(20260910)
    walks = 3 if quick else 8
    out: list[chess.Board] = []
    for board in boards[: 20 if quick else len(boards)]:
        out.append(board.copy())
        for _ in range(walks):
            walk = board.copy()
            for _ in range(rng.randint(4, 70)):
                moves = list(walk.legal_moves)
                if not moves:
                    break
                walk.push(rng.choice(moves))
            out.append(walk.copy())
    return out


def equivalence(boards: list[chess.Board]) -> int:
    """Every square, both colours, every position. Returns the number of disagreements."""
    bad = 0
    for board in boards:
        pos = fb.from_board(board)
        for rank in range(8):
            for file in range(8):
                square = rank * 16 + file
                for colour in (fb.WHITE, fb.BLACK):
                    if int(fb.attacked(pos.board, square, colour)) != int(
                        fb.attacked_from_list(pos, square, colour)
                    ):
                        bad += 1
                        if bad <= 5:
                            print(f"  DISAGREE 0x{square:02x} colour={colour}  {board.fen()}")
    return bad


def timing(boards: list[chess.Board], repeats: int) -> None:
    """Per-position ratio of piece-list time to outward time, reported as a median."""
    squares = [rank * 16 + file for rank in range(8) for file in range(8)]
    ratios: list[float] = []
    for board in boards:
        pos = fb.from_board(board)
        # Warm both on this position before timing either, so neither pays a first-touch cost.
        for square in squares[:4]:
            fb.attacked(pos.board, square, fb.WHITE)
            fb.attacked_from_list(pos, square, fb.WHITE)
        start = time.perf_counter()
        for _ in range(repeats):
            for square in squares:
                fb.attacked(pos.board, square, fb.WHITE)
                fb.attacked(pos.board, square, fb.BLACK)
        outward = time.perf_counter() - start
        start = time.perf_counter()
        for _ in range(repeats):
            for square in squares:
                fb.attacked_from_list(pos, square, fb.WHITE)
                fb.attacked_from_list(pos, square, fb.BLACK)
        by_list = time.perf_counter() - start
        if outward > 0:
            ratios.append(by_list / outward)
    ratios.sort()
    median = statistics.median(ratios)
    pooled_note = "" if len(ratios) < 3 else f"   min {ratios[0]:.3f}  max {ratios[-1]:.3f}"
    print(f"\npiece-list / outward, median of {len(ratios)} per-position ratios: {median:.4f}")
    print(pooled_note)
    if median < 1.0:
        print(f"  piece-list is {(1 - median) * 100:.1f}% faster per call at the median position")
    else:
        print(f"  piece-list is {(median - 1) * 100:.1f}% SLOWER per call at the median position")
    print("\nA per-call ratio is not a node-rate ratio. `attacked` runs inside every make_move and")
    print("every in_check, but the search does far more than call it, so the engine-level saving")
    print("is a fraction of this. Measure that with a paired search benchmark before believing an")
    print("Elo figure.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="fewer positions and repeats")
    args = parser.parse_args()
    boards = corpus(args.quick)
    print(f"{len(boards)} positions")
    fb.warm_up()
    print("checking equivalence ...")
    bad = equivalence(boards)
    if bad:
        print(f"\nFAILED: {bad} disagreements. The change is not exact and must not ship.")
        raise SystemExit(1)
    print(f"  no disagreements over {len(boards)} positions x 64 squares x 2 colours")
    timing(boards, repeats=20 if args.quick else 60)


if __name__ == "__main__":
    main()
