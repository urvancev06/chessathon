"""Score an evaluation against GAME RESULTS instead of against an engine's numbers.

Why this exists. Three times on this project a held-out fit against Stockfish labels has said an
evaluation was better and real games have said otherwise: the Texel fit (-100 Elo), a variance
figure withdrawn the same morning, and the network (-67 Elo while scoring 2.6x better on held-out
MSE). The common defect is that the target and the judge are the same engine. Here the target is
the result of the game, which no engine chose.

WHAT THIS CAN AND CANNOT SHOW, written before it was run.

It rewards an evaluation for being right about WHO IS WINNING. That is not the same as being right
about WHICH MOVE IS BETTER, and the difference is the leading hypothesis for why the network lost:
we trained it to predict a search's verdict and then used it as the leaf of a search. So a good
score here is NECESSARY and not SUFFICIENT. An evaluation that wins on this measurement has earned
a screen, not a promotion.

Three further limits, also written in advance:

* The outcome depends on both players, not only on the position. A position that is objectively
  equal is scored as a loss if the player later blunders. That is noise rather than bias and it
  averages out over many games, but it puts a floor on how well anything can do.
* Late positions are easy -- by move 60 the result is largely settled -- so a single average is
  dominated by positions nobody needed an evaluation for. Results are therefore bucketed by move
  number, and the early bucket is the one that matters.
* Only positions in the hash-based HOLDOUT are used, so the network is never scored on a position
  it was trained on. Without that this comparison would be leakage again, in a new coat.
* The position set is chosen ONCE, by the hand-crafted evaluation, and every arm is scored on that
  same list. The first version of this tool chose positions inside each arm, using `is_quiet`,
  which compares a quiescence search against `evaluate` -- so with the network switched on the
  filter used the network, and the three arms were scored on three different position sets. The
  network arm got 110 positions where the others got 12 000. A filter that depends on the thing
  under test is the same defect as a held-out split that depends on the training set; it has now
  appeared twice in one day in two different disguises.

    python outcome_check.py --pgn-dir <dir> --label <name> --json <out>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import chess
import chess.pgn

CP_PER_LOGIT = 173.7  # the Texel sigmoid at K = 1: 174 cp is about a 73% score
SKIP_PLIES = 8


def is_holdout(fen: str) -> bool:
    """The same split the trainer uses, so the network is never scored on its own training data."""
    return hashlib.sha1(fen.encode(), usedforsecurity=False).digest()[0] * 100 // 256 < 5


def collect(pgn_dir: Path, limit: int) -> list[tuple[str, float, int]]:
    """(fen, result from the side to move's view, move number) for held-out quiet positions."""
    sys.path.insert(0, str(Path.cwd()))
    from mikhail_letal.search import Engine
    from tools.tune_texel import is_quiet

    engine = Engine()
    out: list[tuple[str, float, int]] = []
    for path in sorted(pgn_dir.rglob("*.pgn")):
        with path.open(encoding="utf-8", errors="replace") as handle:
            game = chess.pgn.read_game(handle)
        if game is None:
            continue
        result = game.headers.get("Result", "*")
        if result not in ("1-0", "0-1", "1/2-1/2"):
            continue
        white_score = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[result]
        board = game.board()
        for ply, move in enumerate(game.mainline_moves()):
            board.push(move)
            if ply < SKIP_PLIES or board.is_game_over() or board.is_check():
                continue
            fen = board.fen()
            if not is_holdout(fen) or not is_quiet(engine, board):
                continue
            mover = white_score if board.turn == chess.WHITE else 1.0 - white_score
            out.append((fen, mover, board.fullmove_number))
            if len(out) >= limit:
                return out
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgn-dir", type=Path, required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--limit", type=int, default=12000)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--network", action="store_true", help="evaluate with USE_NETWORK on")
    parser.add_argument("--positions", type=Path, help="read the fixed position list from here")
    parser.add_argument(
        "--write-positions", type=Path, help="collect and write the list, then stop"
    )
    args = parser.parse_args()

    sys.path.insert(0, str(Path.cwd()))
    from mikhail_letal import evaluation

    if hasattr(evaluation, "USE_NETWORK"):
        evaluation.USE_NETWORK = args.network
    from mikhail_letal.evaluation import evaluate

    if args.write_positions:
        # Collected with whatever evaluation this tree has and the network OFF, then reused by
        # every arm, so the sample is a property of the games rather than of the candidate.
        if hasattr(evaluation, "USE_NETWORK"):
            evaluation.USE_NETWORK = False
        collected = collect(args.pgn_dir, args.limit)
        args.write_positions.write_text(
            "\n".join(f"{f}\t{r}\t{m}" for f, r, m in collected), encoding="utf-8"
        )
        print(f"wrote {len(collected):,} positions to {args.write_positions}")
        return 0

    if not args.positions:
        raise SystemExit("give --positions (a fixed list) or --write-positions")
    positions = []
    for line in args.positions.read_text(encoding="utf-8").splitlines():
        fen, result, move = line.split("\t")
        positions.append((fen, float(result), int(move)))
    print(f"{args.label}: {len(positions):,} held-out quiet positions from finished games")

    buckets = {"moves 9-25": (9, 25), "moves 26-45": (26, 45), "moves 46+": (46, 10_000)}
    rows: dict[str, dict[str, float]] = {}
    for name, (low, high) in {**buckets, "all": (0, 10_000)}.items():
        chosen = [(f, r, m) for f, r, m in positions if low <= m <= high]
        if not chosen:
            continue
        brier = 0.0
        logloss = 0.0
        signed = 0
        decisive = 0
        for fen, actual, _ in chosen:
            score = evaluate(chess.Board(fen))
            predicted = 1.0 / (1.0 + math.exp(-score / CP_PER_LOGIT))
            brier += (predicted - actual) ** 2
            p = min(max(predicted, 1e-9), 1 - 1e-9)
            logloss -= actual * math.log(p) + (1 - actual) * math.log(1 - p)
            if actual != 0.5:
                decisive += 1
                if (score > 0) == (actual == 1.0):
                    signed += 1
        n = len(chosen)
        rows[name] = {
            "positions": n,
            "brier": brier / n,
            "logloss": logloss / n,
            "sign_accuracy": signed / decisive if decisive else float("nan"),
            "decisive": decisive,
        }

    print(f"  {'bucket':<14}{'n':>7}{'Brier':>9}{'log loss':>10}{'sign acc':>10}")
    for name, row in rows.items():
        print(
            f"  {name:<14}{row['positions']:>7,}{row['brier']:>9.4f}"
            f"{row['logloss']:>10.4f}{row['sign_accuracy']:>9.1%}"
        )
    print("  lower Brier and log loss are better; sign accuracy is over decisive games only")

    if args.json:
        args.json.write_text(json.dumps({"label": args.label, "buckets": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
