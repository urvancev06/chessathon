"""Train the evaluation network on Stockfish-labelled positions, then quantise it to integers.

Legal by the rules as written: *"The network has to be one the team trained, and training it on
positions an engine labelled is a normal way to do that."* Nothing of anyone else's network is
here; `data/tuning/labels.csv` is our own positions with Stockfish depth-10 scores, and
`docs/PROVENANCE.md` records how it was made.

The float model is exactly the integer one in `mikhail_letal/nnue.py`, written so that quantising
is a multiplication rather than a redesign: a feature-sum first layer, `clamp(a, 0, 1)` as the
activation -- that is the clipped ReLU, whose ceiling exists precisely so the hidden values fit a
small integer -- and a linear output that predicts centipawns directly.

**Held-out loss is evidence to screen, never evidence to ship.** A net that fits the labeller is
the 768-parameter Texel failure an order of magnitude larger, and that row is still in
`RESULTS.md`. This script prints held-out loss because it is the only signal available while
training; only a screen decides whether the net plays better chess.

    .venv/bin/python tools/train_nnue.py --width 128 --epochs 30
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
import time
from pathlib import Path

import chess
import numpy as np
import numpy.typing as npt
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikhail_letal.nnue import (
    FEATURE_SCALE,
    FEATURES,
    QA,
    QB,
    Network,
    feature_index,
)
from tools import tune_texel

ROOT = Path(__file__).resolve().parent.parent
torch.set_num_threads(1)  # one core, as on the platform

# What int16 can hold once the quantisation scales are applied. A float feature weight is
# multiplied by FEATURE_SCALE and an output weight by QB, and both land in an int16 array.
FEATURE_LIMIT = 32767.0 / FEATURE_SCALE  # about 4.0
OUTPUT_LIMIT = 32767.0 / QB  # about 512

# Centipawns per logit for the win-probability transform. This is the Texel sigmoid at K = 1:
# 1/(1 + 10^(-cp/400)) is sigmoid(cp / 173.7), so a 174 cp advantage is about a 73% score. The
# constant is a convention rather than a fit; fitting it to our own games is a separate question
# and would need games, not positions.
CP_PER_LOGIT = 173.7


def is_holdout(fen: str, percent: int) -> bool:
    """Whether a position belongs to the held-out set, decided by the position itself.

    A shuffled index split is only valid for comparing two nets when both were trained on the
    *same* list. Filter the dataset and the shuffle draws a different test set, so a net trained on
    the larger dataset is scored partly on positions it was trained on -- which is exactly what
    happened here: the unfiltered net scored 13,824 against the filtered net's 21,998 on a split
    drawn from the filtered data, and the gap was leakage, not quality.

    Hashing the position instead makes the split a property of the position rather than of the
    dataset, so every net trained from any subset of this pool is scored on the same held-out
    positions and none of them has ever seen one. sha1 rather than `hash()`, which is salted per
    process and would silently change the split between runs.
    """
    digest = hashlib.sha1(fen.encode("utf-8"), usedforsecurity=False).digest()
    return digest[0] * 100 // 256 < percent


def read_all(paths: list[Path] | None) -> tuple[list[str], list[int], str]:
    """Positions and labels from one or more CSVs, deduplicated by FEN.

    Deduplication matters when two sets overlap: a position labelled twice would otherwise get two
    votes, and the two sets here were labelled at different depths, so the duplicate would also be
    inconsistent. The first file listed wins, so put the deeper labels first.
    """
    if not paths:
        return tune_texel.read_labels()
    seen: dict[str, int] = {}
    descriptions = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            descriptions.append(handle.readline().lstrip("# ").strip())
            for row in csv.DictReader(handle):
                seen.setdefault(row["fen"], int(row["cp"]))
    fens = list(seen)
    return fens, [seen[f] for f in fens], " + ".join(descriptions)


def encode(fens: list[str]) -> tuple[npt.NDArray[np.int32], npt.NDArray[np.int32]]:
    """(white_features, black_features): one row per position, 32 feature indices padded with -1.

    Both perspectives are stored because the network reads the side to move's accumulator first,
    and which one that is changes from position to position.
    """
    white = np.full((len(fens), 32), -1, dtype=np.int32)
    black = np.full((len(fens), 32), -1, dtype=np.int32)
    for row, fen in enumerate(fens):
        board = chess.Board(fen)
        for slot, (square, piece) in enumerate(board.piece_map().items()):
            white[row, slot] = feature_index(chess.WHITE, piece.color, piece.piece_type, square)
            black[row, slot] = feature_index(chess.BLACK, piece.color, piece.piece_type, square)
    return white, black


class Model(nn.Module):
    """The float twin of `nnue.forward`, structured so quantisation is a scaling."""

    def __init__(self, width: int) -> None:
        super().__init__()
        # padding_idx = FEATURES is the -1 slot, held at zero so absent pieces contribute nothing.
        self.features = nn.EmbeddingBag(
            FEATURES + 1, width, mode="sum", padding_idx=FEATURES, include_last_offset=False
        )
        self.feature_bias = nn.Parameter(torch.zeros(width))
        self.output = nn.Linear(2 * width, 1)
        nn.init.normal_(self.features.weight, std=0.01)
        with torch.no_grad():
            self.features.weight[FEATURES].zero_()

    def clip_(self) -> None:
        """Keep every weight inside the range int16 can hold once scaled.

        Not a regulariser -- a hard requirement of the target. Trained unconstrained, this net
        reached a feature weight of 74 616 after scaling, against an int16 ceiling of 32 767, and
        quantising it would have silently wrapped. Clipping during training means the weights the
        loss is computed on are the weights that ship.
        """
        with torch.no_grad():
            self.features.weight.clamp_(-FEATURE_LIMIT, FEATURE_LIMIT)
            self.feature_bias.clamp_(-FEATURE_LIMIT, FEATURE_LIMIT)
            self.output.weight.clamp_(-OUTPUT_LIMIT, OUTPUT_LIMIT)
            self.features.weight[FEATURES].zero_()

    def forward(self, own: torch.Tensor, other: torch.Tensor) -> torch.Tensor:
        a_own = self.features(own) + self.feature_bias
        a_other = self.features(other) + self.feature_bias
        hidden = torch.cat([a_own.clamp(0.0, 1.0), a_other.clamp(0.0, 1.0)], dim=1)
        out: torch.Tensor = self.output(hidden).squeeze(1)
        return out


def quantise(model: Model, width: int) -> Network:
    """Scale the float weights into int16 and check nothing overflows on the way."""
    with torch.no_grad():
        fw = model.features.weight[:FEATURES].numpy() * FEATURE_SCALE
        fb = model.feature_bias.numpy() * FEATURE_SCALE
        ow = model.output.weight.numpy().reshape(-1) * QB
        # The bias joins the output sum, which carries the scale QA * QB before OUT_SHIFT.
        ob = float(model.output.bias.item()) * QA * QB

    for name, array, limit in (("feature", fw, 32767), ("output", ow, 32767)):
        largest = float(np.abs(array).max())
        if largest > limit:
            raise SystemExit(f"{name} weights overflow int16 after scaling: {largest:.0f}")
    # The output sum must fit int32: 2 * width * 127 * max|output weight|.
    bound = 2 * width * 127 * float(np.abs(ow).max())
    if bound > 2**31 - 1:
        raise SystemExit(f"output sum could overflow int32: bound {bound:.3g}")
    print(f"  largest feature weight {np.abs(fw).max():.0f}, output {np.abs(ow).max():.0f}")
    print(f"  worst-case output sum {bound:.3g} against int32 max 2.15e9")

    return Network(
        np.rint(fw).astype(np.int16),
        np.rint(fb).astype(np.int32),
        np.rint(ow).astype(np.int16),
        round(ob),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument(
        "--loss",
        choices=("cp", "wdl"),
        default="cp",
        help="'cp' is mean squared error on centipawns; 'wdl' is the same error measured after "
        "the win-probability sigmoid, which stops the gradient being spent on decided positions",
    )
    parser.add_argument(
        "--holdout-percent",
        type=int,
        default=5,
        help="percent of positions held out, chosen by hashing the position so the split is the "
        "same for every dataset drawn from this pool",
    )
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--out", type=Path, default=ROOT / "weights" / "net.npz")
    parser.add_argument(
        "--labels",
        type=Path,
        nargs="*",
        default=None,
        help="label CSVs to train on; the Texel set is used when none are given",
    )
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    fens, labels, labeller = read_all(args.labels)
    print(f"labels: {labeller}")
    print(f"{len(fens):,} positions, width {args.width}\n")

    white, black = encode(fens)
    y = np.array(labels, dtype=np.float32)
    turns = np.array([chess.Board(f).turn == chess.WHITE for f in fens])
    # The network always reads the side to move first, so swap the two perspectives where Black
    # is to move, and flip the label to the side to move's point of view at the same time.
    own = np.where(turns[:, None], white, black)
    other = np.where(turns[:, None], black, white)
    y = np.where(turns, y, -y)

    holdout = np.array([is_holdout(f, args.holdout_percent) for f in fens])
    test_idx = np.flatnonzero(holdout)
    train_idx = np.flatnonzero(~holdout)
    print(f"train {len(train_idx):,}, held out {len(test_idx):,} (by position hash, not by index)")
    pad = FEATURES

    def tensors(idx: npt.NDArray[np.int64]) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        o = torch.from_numpy(np.where(own[idx] < 0, pad, own[idx]).astype(np.int64))
        t = torch.from_numpy(np.where(other[idx] < 0, pad, other[idx]).astype(np.int64))
        return o, t, torch.from_numpy(y[idx])

    train_own, train_other, train_y = tensors(train_idx)
    test_own, test_other, test_y = tensors(test_idx)

    def objective(predicted: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
        """The training loss.

        Why `wdl` exists. The labels are centipawns clipped to +-1500, and squared error on them
        spends most of its gradient where the error is largest -- which is positions already
        decided, where being 300 cp wrong changes nothing about the move. Measuring the same error
        after the win-probability sigmoid weights a position by how much its evaluation could still
        matter, which is what a Texel fit has always done and what NNUE training does.

        The network still OUTPUTS centipawns: only the loss is transformed. So the quantisation
        scales are untouched -- I had thought this change would disturb them and it does not. What
        it can disturb is the output RANGE, because the sigmoid saturates and stops constraining
        predictions far from zero, so a wdl-trained net is free to emit very large centipawn values.
        `quantise` already bounds the output weights; the run reports the range so a net that has
        drifted somewhere the engine's mate thresholds care about is visible rather than silent.
        """
        if args.loss == "cp":
            return nn.functional.mse_loss(predicted, target)
        return nn.functional.mse_loss(
            torch.sigmoid(predicted / CP_PER_LOGIT), torch.sigmoid(target / CP_PER_LOGIT)
        )

    model = Model(args.width)
    model.clip_()
    optimiser = torch.optim.Adam(model.parameters(), lr=args.lr)
    started = time.perf_counter()
    best_held = float("inf")
    best_epoch = -1
    best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    for epoch in range(args.epochs):
        model.train()
        shuffle = torch.randperm(len(train_y))
        total = 0.0
        for start in range(0, len(shuffle), args.batch):
            batch = shuffle[start : start + args.batch]
            optimiser.zero_grad()
            predicted = model(train_own[batch], train_other[batch])
            loss = objective(predicted, train_y[batch])
            loss.backward()  # type: ignore[no-untyped-call]  # torch ships no stub for this
            optimiser.step()
            model.clip_()
            total += float(loss.item()) * len(batch)
        model.eval()
        with torch.no_grad():
            held = float(objective(model(test_own, test_other), test_y).item())
        # Keep the epoch that was best on held-out data, not the last one. Held-out loss here
        # bottoms out and then climbs while training loss keeps falling, which is the net
        # memorising 22 000 positions rather than learning chess.
        if held < best_held:
            best_held, best_epoch = held, epoch
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        if epoch % 20 == 0 or epoch == args.epochs - 1:
            print(
                f"  epoch {epoch:>3}  train MSE {total / len(train_y):>10,.0f}"
                f"  held-out MSE {held:>10,.0f}"
            )
    print(f"\ntrained in {time.perf_counter() - started:.0f} s")
    print(f"best held-out MSE {best_held:,.0f} at epoch {best_epoch}; that epoch is what is saved")
    print(f"final train MSE {total / len(train_y):,.0f} against held-out {held:,.0f}: the gap is")
    print("the net memorising the training positions, and the reason more data is the next step.")
    model.load_state_dict(best_state)

    with torch.no_grad():
        span = model(test_own, test_other)
    print(
        f"\npredicted centipawns on held-out data: min {span.min():.0f}, max {span.max():.0f}, "
        f"mean |x| {span.abs().mean():.0f}"
    )
    print("\nquantising:")
    net = quantise(model, args.width)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    net.save(args.out)
    size = args.out.stat().st_size
    print(f"  wrote {args.out.relative_to(ROOT)}, {size / 1024:.0f} KiB")
    print("\nHeld-out MSE is evidence to screen, not evidence to ship.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
