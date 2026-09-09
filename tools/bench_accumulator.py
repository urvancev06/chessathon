"""Is an incrementally updated NNUE accumulator affordable in this engine, under numba?

One question, two budgets, and a net is dead if it fails either.

**Node rate.** The accumulator has to be updated on every make and unmake, not on every evaluation
-- the search skips evaluation at many nodes (there is an eval cache) but it can never skip keeping
the accumulator in step with the board. So the incremental cost is paid *more often* than the
current evaluation is. A node costs about 1.27 us measured (tools/bench_mobility.py, depth 7) and
the whole hand-crafted evaluation costs about 204 ns (docs/PROVENANCE.md).

**Import budget.** Every jitted function must be compiled at import, inside a 70 s warm-up budget
against a hard 90 s, and the import already costs 33-36 s. A forward pass and an accumulator update
are more functions to compile. Compile time is measured here as carefully as run time, because
overrunning the start-up budget does not lose a game, it loses every game.

Nothing here touches the engine. It is deliberately a standalone kernel benchmark: if the answer is
no, that is two hours of work rather than twelve, which is the point of asking first.

    .venv/bin/python tools/bench_accumulator.py
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Final

import numpy as np
import numpy.typing as npt
from numba import njit

# A piece-square input: 12 piece types x 64 squares, one perspective each for White and Black.
# No king bucketing, which is the simplest thing that could work and the cheapest to update.
FEATURES: Final = 768
HIDDEN2: Final = 32
QUIET_MOVE_CHANGES: Final = 2  # a piece leaves a square and arrives at another, per perspective


@njit(cache=False)
def accumulator_update(
    acc: npt.NDArray[np.int32],
    weights: npt.NDArray[np.int16],
    removed: npt.NDArray[np.int32],
    added: npt.NDArray[np.int32],
) -> None:
    """Subtract the columns of the features that left, add the ones that arrived.

    This is the whole incremental trick: a move changes a couple of features per perspective, so
    the first layer is a few hundred integer adds rather than a matrix multiply.
    """
    width = acc.shape[1]
    for side in range(2):
        for k in range(removed.shape[1]):
            index = removed[side, k]
            if index >= 0:
                for j in range(width):
                    acc[side, j] -= weights[index, j]
        for k in range(added.shape[1]):
            index = added[side, k]
            if index >= 0:
                for j in range(width):
                    acc[side, j] += weights[index, j]


@njit(cache=False)
def accumulator_refresh(
    acc: npt.NDArray[np.int32],
    weights: npt.NDArray[np.int16],
    bias: npt.NDArray[np.int32],
    active: npt.NDArray[np.int32],
) -> None:
    """Rebuild an accumulator from scratch: the cost paid at the root and after a null move."""
    width = acc.shape[1]
    for side in range(2):
        for j in range(width):
            acc[side, j] = bias[j]
        for k in range(active.shape[1]):
            index = active[side, k]
            if index >= 0:
                for j in range(width):
                    acc[side, j] += weights[index, j]


@njit(cache=False)
def forward(
    acc: npt.NDArray[np.int32],
    w2: npt.NDArray[np.int8],
    b2: npt.NDArray[np.int32],
    w3: npt.NDArray[np.int8],
    b3: npt.NDArray[np.int32],
    w4: npt.NDArray[np.int8],
    b4: int,
) -> int:
    """Clipped ReLU on the accumulator, then 2*W -> 32 -> 32 -> 1, all in int32.

    Integer throughout, and every shift is on a non-negative value: `test_fasteval` compares the
    two engines integer for integer, so a float anywhere would make that gate unmeetable.
    """
    width = acc.shape[1]
    hidden = np.empty(2 * width, dtype=np.int32)
    for side in range(2):
        for j in range(width):
            value = acc[side, j] >> 6
            if value < 0:
                value = 0
            elif value > 127:
                value = 127
            hidden[side * width + j] = value

    layer2 = np.empty(HIDDEN2, dtype=np.int32)
    for o in range(HIDDEN2):
        total = b2[o]
        for i in range(2 * width):
            total += hidden[i] * w2[o, i]
        total >>= 6
        if total < 0:
            total = 0
        elif total > 127:
            total = 127
        layer2[o] = total

    layer3 = np.empty(HIDDEN2, dtype=np.int32)
    for o in range(HIDDEN2):
        total = b3[o]
        for i in range(HIDDEN2):
            total += layer2[i] * w3[o, i]
        total >>= 6
        if total < 0:
            total = 0
        elif total > 127:
            total = 127
        layer3[o] = total

    out = b4
    for i in range(HIDDEN2):
        out += layer3[i] * w4[i]
    return out >> 6


@njit(cache=False)
def forward_linear(acc: npt.NDArray[np.int32], wout: npt.NDArray[np.int16], bout: int) -> int:
    """Clipped ReLU on the accumulator, then straight to one output.

    One hidden layer: 768 -> W per perspective -> clipped ReLU -> 1. Far weaker than a deep head
    and still far stronger than a piece-square table, because the hidden layer is shared across
    the whole position instead of one number per square. This is the shape that fits the budget.
    """
    width = acc.shape[1]
    out = bout
    for side in range(2):
        for j in range(width):
            value = acc[side, j] >> 6
            if value < 0:
                value = 0
            elif value > 127:
                value = 127
            out += value * wout[side * width + j]
    return out >> 6


@njit(cache=False)
def drive_linear(
    acc: npt.NDArray[np.int32], wout: npt.NDArray[np.int16], bout: int, repeats: int
) -> int:
    total = 0
    for _ in range(repeats):
        total += forward_linear(acc, wout, bout)
    return total


@njit(cache=False)
def drive_update(
    acc: npt.NDArray[np.int32],
    weights: npt.NDArray[np.int16],
    removed: npt.NDArray[np.int32],
    added: npt.NDArray[np.int32],
    repeats: int,
) -> int:
    """Loop inside compiled code so the measurement is the kernel, not the Python call."""
    for _ in range(repeats):
        accumulator_update(acc, weights, removed, added)
    return int(acc[0, 0])


@njit(cache=False)
def drive_forward(
    acc: npt.NDArray[np.int32],
    w2: npt.NDArray[np.int8],
    b2: npt.NDArray[np.int32],
    w3: npt.NDArray[np.int8],
    b3: npt.NDArray[np.int32],
    w4: npt.NDArray[np.int8],
    b4: int,
    repeats: int,
) -> int:
    total = 0
    for _ in range(repeats):
        total += forward(acc, w2, b2, w3, b3, w4, b4)
    return total


@njit(cache=False)
def drive_refresh(
    acc: npt.NDArray[np.int32],
    weights: npt.NDArray[np.int16],
    bias: npt.NDArray[np.int32],
    active: npt.NDArray[np.int32],
    repeats: int,
) -> int:
    for _ in range(repeats):
        accumulator_refresh(acc, weights, bias, active)
    return int(acc[0, 0])


def measure(width: int, repeats: int = 200_000) -> dict[str, float]:
    rng = np.random.default_rng(20260909)
    weights = rng.integers(-64, 64, size=(FEATURES, width), dtype=np.int16)
    bias = rng.integers(-64, 64, size=width, dtype=np.int32)
    acc = np.zeros((2, width), dtype=np.int32)
    w2 = rng.integers(-64, 64, size=(HIDDEN2, 2 * width), dtype=np.int8)
    b2 = rng.integers(-64, 64, size=HIDDEN2, dtype=np.int32)
    w3 = rng.integers(-64, 64, size=(HIDDEN2, HIDDEN2), dtype=np.int8)
    b3 = rng.integers(-64, 64, size=HIDDEN2, dtype=np.int32)
    w4 = rng.integers(-64, 64, size=HIDDEN2, dtype=np.int8)

    removed = rng.integers(0, FEATURES, size=(2, QUIET_MOVE_CHANGES), dtype=np.int32)
    added = rng.integers(0, FEATURES, size=(2, QUIET_MOVE_CHANGES), dtype=np.int32)
    active = rng.integers(0, FEATURES, size=(2, 32), dtype=np.int32)
    wout = rng.integers(-64, 64, size=2 * width, dtype=np.int16)

    out: dict[str, float] = {}
    started = time.perf_counter()
    drive_update(acc, weights, removed, added, 1)
    drive_forward(acc, w2, b2, w3, b3, w4, 0, 1)
    drive_refresh(acc, weights, bias, active, 1)
    drive_linear(acc, wout, 0, 1)
    out["compile_s"] = time.perf_counter() - started

    def fastest(call: Callable[[int], object]) -> float:
        """Nanoseconds per operation, from the fastest of five runs.

        The fastest run, not the mean: every source of error here is additive -- a scheduler
        slice, a page fault, a neighbour on the box -- so the minimum is the closest estimate
        of the kernel's own cost.
        """
        best = float("inf")
        for _ in range(5):
            started = time.perf_counter()
            call(repeats)
            best = min(best, time.perf_counter() - started)
        return best / repeats * 1e9

    out["update_ns"] = fastest(lambda n: drive_update(acc, weights, removed, added, n))
    out["forward_ns"] = fastest(lambda n: drive_forward(acc, w2, b2, w3, b3, w4, 0, n))
    out["refresh_ns"] = fastest(lambda n: drive_refresh(acc, weights, bias, active, n))
    out["linear_ns"] = fastest(lambda n: drive_linear(acc, wout, 0, n))
    return out


def main() -> int:
    print("A node costs about 1270 ns measured; the hand-crafted evaluation about 204 ns.")
    print("The accumulator update is paid at EVERY make and unmake; the forward pass only")
    print("at nodes that are actually evaluated.\n")
    print(
        f"  {'width':>6}{'compile s':>11}{'update ns':>11}{'refresh ns':>12}"
        f"{'deep head ns':>14}{'linear head ns':>16}"
    )
    results = {}
    for width in (128, 256):
        r = measure(width)
        results[width] = r
        print(
            f"  {width:>6}{r['compile_s']:>11.1f}{r['update_ns']:>11.0f}"
            f"{r['refresh_ns']:>12.0f}{r['forward_ns']:>14.0f}{r['linear_ns']:>16.0f}"
        )

    print("\nPer node, against a 1270 ns node, assuming half of nodes are evaluated.")
    print("The hand-crafted evaluation this would replace costs 204 ns at those same nodes,")
    print("so its per-node cost is about 102 ns.\n")
    for width, r in results.items():
        for head, key in (("deep 2W-32-32-1", "forward_ns"), ("linear 2W-1", "linear_ns")):
            added = r["update_ns"] + 0.5 * r[key]
            print(
                f"  width {width:>3}, {head:<16} {added:>7.0f} ns/node "
                f"({added - 102:+.0f} against the hand-crafted evaluation), "
                f"node rate {1270 / (1270 + added - 102) * 100:>3.0f}%"
            )
    print("\nCompile time is added to an import already costing 33-36 s against a 70 s budget.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
