"""Fit the eight structural weights to the labelled positions, one at a time and jointly.

This is **not** the Texel run in `RESULTS.md`. That fit moved 768 piece-square parameters and lost
100 Elo: enough capacity to fit the labeller rather than the game. This fits **eight scalars**,
which is a different risk profile, and every number it reports is held out — the weights are
chosen on a train split and scored on positions the fit never saw.

The model. Everything the evaluation computes that is *not* one of the eight is a constant with
respect to them, so for one position

    white_evaluation = base + sum_k w_k * c_k

where `c_k` is how often weight k is used, phase-scaled exactly as `evaluate` blends its two
tables (`tune_texel.features` builds the same counts and is checked against `evaluate` on every
position it fits). `base` is obtained by evaluating with all eight weights set to zero, so it is
measured rather than reconstructed and cannot drift from what the engine does. That makes the fit
an ordinary least-squares problem in eight unknowns and the line searches exact.

Two choices in here are the whole reason to read the code before the numbers.

**The king-danger term stays ON.** `tune_texel.white_evaluation` switches it off, because a capped
quadratic cannot be represented in a linear model of counts. Here it does not need to be: it is
part of `base`. Switching it off would leave `king_shield` free to absorb the job of a term the
engine actually has, and `king_shield` is exactly the weight whose fitted value looks too large.
`--king-danger off` reproduces the other convention so the difference can be seen.

**Mobility can be added as two more columns** with `--with-mobility`, even though this branch's
engine has no mobility term. A rook on an open file is a rook with a great deal of mobility, so a
fit with no mobility column has to explain that variance with `rook_open_file` and will inflate
it. The point is not to fit mobility here; it is to find out how much of `rook_open_file`'s
apparent gain is mobility wearing its coat.

    .venv/bin/python tools/fit_structure.py --train 3000 --test 3000
    .venv/bin/python tools/fit_structure.py --train 3000 --test 3000 --with-mobility
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import chess
import numpy as np
import numpy.typing as npt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikhail_letal import evaluation
from mikhail_letal.evaluation import PHASE_TOTAL, evaluate, game_phase
from tools import tune_texel

Vector = npt.NDArray[np.float64]
Matrix = npt.NDArray[np.float64]

NAMES: Final = tuple(tune_texel.STRUCTURE_NAMES)
MOBILITY_NAMES: Final = ("mobility_mg", "mobility_eg")
MATERIAL_NAMES: Final = ("mg_material_scale", "eg_material_scale")
"""Two columns that let the fit rescale the shipped material values by phase.

They exist to answer a question about the *other* columns rather than to propose changing the
piece values. `base` carries material at the untuned textbook tables, so if those tables are wrong
the error has to come out somewhere, and it comes out through whichever fitted column correlates
with material. In the endgame `mobility_eg` correlates with it at +0.85, which is why holding
material fixed drives that weight negative. A coefficient of c here means endgame (or middlegame)
material is being scaled by 1 + c/100.
"""


def mobile_squares(board: chess.Board, colour: chess.Color) -> int:
    """Plain mobility for one colour: squares its knights, bishops, rooks and queens attack and
    do not stand on. Defined here rather than imported because this branch's engine has no
    mobility term; it is a candidate column, not a shipped one."""
    own = board.occupied_co[colour]
    return sum(
        (board.attacks_mask(square) & ~own).bit_count()
        for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
        for square in board.pieces(piece_type, colour)
    )


def material_difference(board: chess.Board) -> int:
    """White material less Black's, in centipawns, at the shipped middlegame piece values."""
    values = evaluation.TABLES.piece_values_mg
    return sum(
        values[piece_type]
        * (len(board.pieces(piece_type, chess.WHITE)) - len(board.pieces(piece_type, chess.BLACK)))
        for piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )


def counts(board: chess.Board, with_mobility: bool, with_material: bool = False) -> Vector:
    """How often each weight is used in `board`, from White's view, phase-scaled as `evaluate`
    blends its tables. The eight are `tune_texel.features`' structure block, restated here over
    eight columns instead of 776 so that this file can be read on its own."""
    mg_share = game_phase(board) / PHASE_TOTAL
    eg_share = 1.0 - mg_share

    def difference(count: Callable[[chess.Board, chess.Color], int]) -> int:
        return count(board, chess.WHITE) - count(board, chess.BLACK)

    passed = difference(tune_texel.passed_pawn_advance)
    values = [
        passed * mg_share,  # passed_pawn_mg
        passed * eg_share,  # passed_pawn_eg
        # The evaluation subtracts the two pawn penalties, so their counts enter negative and the
        # fitted weights stay positive numbers, as in the dict.
        -difference(tune_texel.doubled_pawns),
        -difference(tune_texel.isolated_pawns),
        difference(tune_texel.bishop_pair),
        difference(tune_texel.rooks_on_open_files),
        difference(tune_texel.rooks_on_semi_open_files),
        difference(tune_texel.king_shield_pawns) * mg_share,  # middlegame only
    ]
    if with_mobility:
        mobile = difference(mobile_squares)
        values += [mobile * mg_share, mobile * eg_share]
    if with_material:
        # Divided by 100 so a coefficient reads as a percentage of the shipped material value.
        material = material_difference(board) / 100.0
        values += [material * mg_share, material * eg_share]
    return np.array(values, dtype=np.float64)


def white_score(board: chess.Board) -> int:
    """`evaluate` from White's point of view, with whatever term switches are currently set."""
    score = evaluate(board)
    return score if board.turn == chess.WHITE else -score


def build(
    fens: list[str], labels: list[int], with_mobility: bool, with_material: bool = False
) -> tuple[Matrix, Vector, Vector]:
    """(design, base, y), where `base` is everything the evaluation computes that is not one of
    the fitted weights, in blended centipawns and **not** rounded.

    `base` is assembled from `material_pst` and `king_danger` rather than by evaluating with the
    weights zeroed, and the two reasons are both traps that cost a debugging pass each.

    *The weights are never changed.* `evaluation._PAWN_CACHE` memoises `pawn_structure` by the two
    pawn bitboards, and `pawn_structure` has the weights baked into the numbers it returns. Zero
    the weights without clearing that cache and the next position repeating a pawn structure is
    scored with the **old** weights, silently: it put the reconstruction 12 cp out. Building
    `base` from the parts touches no weight, so the cache cannot go stale.

    *There is one rounding, not two.* `evaluate` truncates the phase blend once, toward zero. A
    `base` that was itself a truncated evaluation would round a second time, and on a position
    where `base` is positive and the score negative the two roundings bias in opposite directions
    — an error of up to 2 cp, which is what broke the 1 cp check the second time. Keeping `base`
    unblended and unrounded leaves the model exact to the engine's single truncation.
    """
    shipped = np.array([float(evaluation.STRUCTURE_WEIGHTS[n]) for n in NAMES], dtype=np.float64)
    rows, bases, ys = [], [], []
    for fen, label in zip(fens, labels, strict=True):
        board = chess.Board(fen)
        if not board.pawns:
            continue  # the mop-up term and the insufficient-material draw are not in this model
        phase = game_phase(board)  # clamped, as `evaluate_running` clamps it
        mg, eg, _ = evaluation.material_pst(board)
        if evaluation.KING_DANGER_TERM:
            white_pawns = board.pawns & board.occupied_co[chess.WHITE]
            black_pawns = board.pawns & board.occupied_co[chess.BLACK]
            mg += evaluation.king_danger(board, white_pawns, black_pawns)
        base = (mg * phase + eg * (PHASE_TOTAL - phase)) / PHASE_TOTAL

        row = counts(board, with_mobility, with_material)
        # The check that makes every number below mean anything: at the shipped weights the model
        # must reproduce what the engine actually computes, to within the one truncation.
        rebuilt = base + float(row[: len(NAMES)] @ shipped)
        actual = white_score(board)
        if abs(rebuilt - actual) >= 1.0:
            raise AssertionError(
                f"the model does not reproduce evaluate() for {fen}: {rebuilt:.3f} vs {actual}"
            )
        rows.append(row)
        bases.append(base)
        ys.append(float(label))
    return np.array(rows), np.array(bases), np.array(ys)


def mse(design: Matrix, base: Vector, y: Vector, weights: Vector) -> float:
    return float(np.mean((base + design @ weights - y) ** 2))


def best_single(design: Matrix, base: Vector, y: Vector, weights: Vector, index: int) -> float:
    """The value of one weight that minimises training error with the others held fixed."""
    column = design[:, index]
    denominator = float(column @ column)
    if denominator == 0.0:
        return float(weights[index])  # the feature never occurs; leave it alone
    others = base + design @ weights - column * weights[index]
    return float((column @ (y - others)) / denominator)


def summarise(values: list[float]) -> str:
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
    return f"{mean:>8.1f} +-{sd:>6.1f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=int, default=3000)
    parser.add_argument("--test", type=int, default=3000)
    parser.add_argument("--repeats", type=int, default=20, help="independent train/test splits")
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--with-mobility", action="store_true")
    parser.add_argument("--king-danger", choices=("on", "off"), default="on")
    parser.add_argument(
        "--with-material",
        action="store_true",
        help="add two columns that rescale shipped material by phase; see MATERIAL_NAMES",
    )
    parser.add_argument(
        "--free",
        default=None,
        help=(
            "comma-separated weights to fit JOINTLY while every other weight is held at its "
            "shipped value. Distinct from both other modes: the one-at-a-time column frees a "
            "single weight, and the joint fit frees all of them. Two correlated weights fitted "
            "together are not the same as each fitted alone."
        ),
    )
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    evaluation.KING_DANGER_TERM = args.king_danger == "on"
    names = (
        NAMES
        + (MOBILITY_NAMES if args.with_mobility else ())
        + (MATERIAL_NAMES if args.with_material else ())
    )

    fens, labels, labeller = tune_texel.read_labels()
    print(f"labels: {labeller}")
    print(
        f"king danger {args.king_danger}, mobility column "
        f"{'yes' if args.with_mobility else 'no'}, "
        f"{args.repeats} splits of {args.train} train / {args.test} test"
    )

    # Built once over every labelled position, then splits are drawn from it. One split is one
    # noisy number; the spread over many is what says whether a weight has really moved.
    design, base, y = build(fens, labels, args.with_mobility, args.with_material)
    print(
        f"design {design.shape[0]} positions x {design.shape[1]} columns "
        f"(pawnless positions dropped)\n"
    )

    shipped = np.array(
        [float(evaluation.STRUCTURE_WEIGHTS.get(n, 0)) for n in names], dtype=np.float64
    )
    rng = random.Random(args.seed)
    pool = list(range(len(y)))
    if args.train + args.test > len(pool):
        raise SystemExit(f"asked for {args.train + args.test} positions, have {len(pool)}")

    free_names = [n.strip() for n in args.free.split(",")] if args.free else []
    unknown = [n for n in free_names if n not in names]
    if unknown:
        raise SystemExit(f"not columns in this run: {unknown}; have {list(names)}")
    free_idx = [names.index(n) for n in free_names]
    subset_fit: dict[str, list[float]] = {n: [] for n in free_names}
    subset_delta: list[float] = []

    singles: dict[str, list[float]] = {n: [] for n in names}
    single_delta: dict[str, list[float]] = {n: [] for n in names}
    joints: dict[str, list[float]] = {n: [] for n in names}
    joint_delta: list[float] = []
    baselines: list[float] = []

    for _ in range(args.repeats):
        rng.shuffle(pool)
        tr, te = pool[: args.train], pool[args.train : args.train + args.test]
        trd, trb, try_ = design[tr], base[tr], y[tr]
        ted, teb, tey = design[te], base[te], y[te]
        baseline = mse(ted, teb, tey, shipped)
        baselines.append(baseline)
        for i, name in enumerate(names):
            candidate = shipped.copy()
            candidate[i] = best_single(trd, trb, try_, shipped, i)
            singles[name].append(candidate[i])
            single_delta[name].append(mse(ted, teb, tey, candidate) - baseline)
        if free_idx:
            # Everything not being freed contributes at its shipped value, so subtract that
            # contribution and fit the freed columns to what is left.
            held = shipped.copy()
            held[free_idx] = 0.0
            fitted, *_ = np.linalg.lstsq(trd[:, free_idx], try_ - trb - trd @ held, rcond=None)
            candidate = shipped.copy()
            candidate[free_idx] = fitted
            for name, value in zip(free_names, fitted, strict=True):
                subset_fit[name].append(float(value))
            subset_delta.append(mse(ted, teb, tey, candidate) - baseline)

        joint, *_ = np.linalg.lstsq(trd, try_ - trb, rcond=None)
        for i, name in enumerate(names):
            joints[name].append(float(joint[i]))
        joint_delta.append(mse(ted, teb, tey, joint) - baseline)

    print(f"held-out MSE at the shipped weights: {np.mean(baselines):,.0f}\n")
    print("one at a time, everything else shipped        joint fit of all columns")
    print(f"  {'weight':<21}{'shipped':>8}{'fitted':>17}{'held-out dMSE':>19}{'fitted':>17}")
    for name in names:
        print(
            f"  {name:<21}{evaluation.STRUCTURE_WEIGHTS.get(name, 0):>8}"
            f"{summarise(singles[name]):>17}{summarise(single_delta[name]):>19}"
            f"{summarise(joints[name]):>17}"
        )
    print(f"\n  joint held-out dMSE: {summarise(joint_delta)}")

    if free_idx:
        print(f"\n  {', '.join(free_names)} fitted together, every other weight held shipped:")
        for name in free_names:
            print(f"    {name:<19}{summarise(subset_fit[name])}")
        print(f"    {'held-out dMSE':<19}{summarise(subset_delta)}")

    print("\n  a weight is worth moving only if its dMSE is negative by more than its own")
    print("  spread; anything else is a number that changed because the split changed.")
    movers = [
        n
        for n in names
        if np.mean(single_delta[n]) < -2.0 * (np.std(single_delta[n], ddof=1) or 1e9)
    ]
    print(f"  clears that bar: {movers or 'none'}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "king_danger": args.king_danger,
                    "with_mobility": args.with_mobility,
                    "train": args.train,
                    "test": args.test,
                    "repeats": args.repeats,
                    "positions": int(design.shape[0]),
                    "baseline_test_mse": float(np.mean(baselines)),
                    "single": {
                        n: {
                            "fitted_mean": float(np.mean(singles[n])),
                            "fitted_sd": float(np.std(singles[n], ddof=1)),
                            "delta_mse_mean": float(np.mean(single_delta[n])),
                            "delta_mse_sd": float(np.std(single_delta[n], ddof=1)),
                        }
                        for n in names
                    },
                    "joint": {
                        n: {
                            "fitted_mean": float(np.mean(joints[n])),
                            "fitted_sd": float(np.std(joints[n], ddof=1)),
                        }
                        for n in names
                    },
                    "free": free_names,
                    "free_fit": {
                        n: {
                            "mean": float(np.mean(subset_fit[n])),
                            "sd": float(np.std(subset_fit[n], ddof=1)),
                        }
                        for n in free_names
                    },
                    "free_delta_mse_mean": float(np.mean(subset_delta)) if subset_delta else None,
                    "joint_delta_mse_mean": float(np.mean(joint_delta)),
                    "joint_delta_mse_sd": float(np.std(joint_delta, ddof=1)),
                    "movers": movers,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
