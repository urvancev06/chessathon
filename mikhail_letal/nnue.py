"""A trained evaluation: 768 -> W per perspective, clipped ReLU, linear output.

This module is the **specification**, in the same sense `evaluation.py` is: plain Python that says
exactly what the network computes, with `fasteval` as the compiled port and `tests/test_nnue.py`
comparing them integer for integer. Nothing here is a float. The net is trained in floating point
offline (`tools/train_nnue.py`) and *quantised* to integers before it ships, because the engine is
int32 throughout and the two ports have to agree exactly.

**The shape, and why it is this shape.** A conventional NNUE has a deep output head -- 2W inputs
into 32, into 32, into 1. Measured under numba (`tools/bench_accumulator.py`) that head costs
900-1500 ns, against a whole node of 1270 ns: it would cost a quarter to a third of our node rate,
because numba gives us no SIMD intrinsics and the head runs at about four multiply-adds a cycle.
A single hidden layer with a linear output costs 26 ns at W = 128 and is free at our node rate. So
the architecture is bounded from both ends -- the accumulator update grows with width, the head
grows with depth -- and the whole budget goes into width.

**The accumulator.** The first layer is the expensive one only if it is recomputed. Instead the
sum of the columns of the active features is kept incrementally: a move changes two features per
perspective (a piece leaves a square and arrives at another) plus one for a capture and one more
for a promotion, so the first layer costs a few hundred integer adds rather than a matrix multiply.
`refresh` builds one from scratch and is the definition; `apply` is the incremental step, and the
two must agree at every node -- which is what `tests/test_nnue.py` asserts, because an accumulator
that drifts from the position is the characteristic bug of this design and it shows up as a
slightly worse move rather than as an error.

**Perspectives.** Each side gets its own accumulator, built from its own point of view: squares are
mirrored for Black, and a feature says "a friendly knight on e4" rather than "a white knight on
e4". The evaluation reads the side to move's accumulator first and the opponent's second, so one
network serves both colours and a position and its mirror evaluate to exactly opposite scores.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import chess
import numpy as np
import numpy.typing as npt

# 2 (friendly, enemy) x 6 piece types x 64 squares, from one perspective.
SQUARES: Final = 64
PIECE_TYPES: Final = 6
FEATURES: Final = 2 * PIECE_TYPES * SQUARES

# How many features a single move can change, per perspective: the piece leaves its square and
# arrives at another (2), a capture removes a third, and a promotion means the arriving piece is a
# different type from the departing one, which the two entries above already express. Castling
# moves two pieces, so it needs four. The buffer is sized for the worst case.
MAX_CHANGES: Final = 6

# ----------------------------------------------------------------------------- quantisation
#
# Every scale here is a power of two, so that de-scaling is a shift and the two ports cannot
# disagree about a rounding. Writing `a` for the float pre-activation and `h = clamp(a, 0, 1)` for
# the float hidden value that `tools/train_nnue.py` trains:
#
#   feature weights   int16, scaled by QA << ACC_SHIFT = 8192, so acc = a * 8192
#   hidden value      clamp(acc >> ACC_SHIFT, 0, CLIP_MAX) = h * 128, give or take one
#   output weights    int16, scaled by QB = 64
#   output            (bias + sum h_int * w_int) >> OUT_SHIFT, and QA * QB = 2^13 = OUT_SHIFT
#
# so the output lands in centipawns and the float model is trained to predict centipawns directly.
QA: Final = 128  # hidden scale: h in [0, 1] is stored as 0..127
QB: Final = 64  # output weight scale
ACC_SHIFT: Final = 6  # spare precision carried in the accumulator below the hidden scale
OUT_SHIFT: Final = 13  # log2(QA * QB); de-scales the output sum to centipawns
CLIP_MAX: Final = QA - 1  # clipped ReLU ceiling, so hidden values are 0..127
FEATURE_SCALE: Final = QA << ACC_SHIFT  # 8192; what a float feature weight is multiplied by

# Overflow bound, checked by `tools/train_nnue.py` when it quantises rather than trusted here:
# the output sum is at most 2 * width * CLIP_MAX * max|output weight|, and it must fit int32.
# At width 256 that is 512 * 127 * max|w|, so max|w| must stay under about 32 000 -- comfortably
# inside int16, but not automatically, which is why the trainer asserts it.


class Network:
    """The quantised weights. Loaded once at import and never mutated."""

    def __init__(
        self,
        feature_weights: npt.NDArray[np.int16],
        feature_bias: npt.NDArray[np.int32],
        output_weights: npt.NDArray[np.int16],
        output_bias: int,
    ) -> None:
        if feature_weights.shape[0] != FEATURES:
            raise ValueError(f"expected {FEATURES} feature rows, got {feature_weights.shape[0]}")
        self.width = int(feature_weights.shape[1])
        if output_weights.shape[0] != 2 * self.width:
            raise ValueError("output layer must read both perspectives")
        self.feature_weights = feature_weights
        self.feature_bias = feature_bias
        self.output_weights = output_weights
        self.output_bias = int(output_bias)

    @classmethod
    def load(cls, path: Path) -> Network:
        with np.load(path) as data:
            return cls(
                data["feature_weights"].astype(np.int16),
                data["feature_bias"].astype(np.int32),
                data["output_weights"].astype(np.int16),
                int(data["output_bias"]),
            )

    def save(self, path: Path) -> None:
        np.savez_compressed(
            path,
            feature_weights=self.feature_weights,
            feature_bias=self.feature_bias,
            output_weights=self.output_weights,
            output_bias=np.int32(self.output_bias),
        )


def feature_index(
    perspective: chess.Color, colour: chess.Color, piece_type: int, square: int
) -> int:
    """Where the piece sits in ``perspective``'s input vector.

    Two things are relative to the perspective and that is the whole trick: whether the piece is
    friendly or enemy, and which square it stands on. Black sees the board mirrored (``square ^ 56``
    flips the rank), so "my knight on my third rank" is one feature for both colours and the
    network learns each pattern once rather than twice.
    """
    friendly = colour == perspective
    relative_square = square if perspective == chess.WHITE else square ^ 56
    return ((0 if friendly else 1) * PIECE_TYPES + (piece_type - 1)) * SQUARES + relative_square


def refresh(net: Network, board: chess.Board) -> npt.NDArray[np.int32]:
    """Build both accumulators from scratch. The definition the incremental path is checked against.

    Kings are included like any other piece: a plain piece-square input, with no king bucketing.
    Bucketing is what makes a real NNUE strong and it multiplies the weight table by the number of
    buckets, which is a size and a training-data cost we cannot pay in the time available.
    """
    acc = np.zeros((2, net.width), dtype=np.int32)
    for perspective in (chess.WHITE, chess.BLACK):
        row = 0 if perspective == chess.WHITE else 1
        acc[row] = net.feature_bias
        for square, piece in board.piece_map().items():
            index = feature_index(perspective, piece.color, piece.piece_type, square)
            acc[row] += net.feature_weights[index]
    return acc


def apply_changes(
    net: Network,
    acc: npt.NDArray[np.int32],
    removed: list[tuple[chess.Color, int, int]],
    added: list[tuple[chess.Color, int, int]],
) -> None:
    """Subtract the features that left and add the ones that arrived, in place.

    ``removed`` and ``added`` are (colour, piece type, square) triples in *absolute* terms; the
    perspective mirroring happens here, once per perspective, so a caller never has to think about
    it.
    """
    for perspective in (chess.WHITE, chess.BLACK):
        row = 0 if perspective == chess.WHITE else 1
        for colour, piece_type, square in removed:
            acc[row] -= net.feature_weights[feature_index(perspective, colour, piece_type, square)]
        for colour, piece_type, square in added:
            acc[row] += net.feature_weights[feature_index(perspective, colour, piece_type, square)]


def clipped(value: int) -> int:
    """Clipped ReLU on an accumulator entry: shift down, then clamp to 0..CLIP_MAX."""
    shifted = value >> ACC_SHIFT
    if shifted < 0:
        return 0
    return CLIP_MAX if shifted > CLIP_MAX else shifted


def forward(net: Network, acc: npt.NDArray[np.int32], turn: chess.Color) -> int:
    """Centipawns from the side to move's point of view.

    The side to move's accumulator is read first and the opponent's second, so the network sees
    "me" and "them" rather than "White" and "Black" and one net serves both colours.
    """
    own = 0 if turn == chess.WHITE else 1
    total = net.output_bias
    for offset, row in ((0, own), (net.width, 1 - own)):
        for j in range(net.width):
            total += clipped(int(acc[row, j])) * int(net.output_weights[offset + j])
    return total >> OUT_SHIFT


def evaluate(net: Network, board: chess.Board) -> int:
    """The network's evaluation of a position, from scratch. Tests and tools only: the search
    keeps an accumulator instead and never rebuilds it per node."""
    return forward(net, refresh(net, board), board.turn)
