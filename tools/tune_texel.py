"""Texel-style tuning of the evaluation weights: closed-form ridge regression toward the prior.

The idea, for the judge. Our static evaluation is *linear in its weights* once the position is
known: score = sum over features of (feature count x weight), where a feature is "a white knight
on f3, middlegame share" (count +1 x share), "a black rook on an open file" (count -1) or "White's
passed pawns have advanced five ranks in total, endgame share" (count 5 x share). So given
positions labelled with a trusted score, the weights that best reproduce the labels are an ordinary
least-squares problem, solved exactly by one linear system: no gradient descent, no learning rate,
one regularisation strength chosen by cross-validation.

Three steps, each a subcommand so a step can be re-run alone (``all`` runs them in order):

1. ``positions``: our engine plays itself from every opening in ``data/openings.txt`` (a few fast
   games each with a little *seeded* randomness among the near-best moves so the games differ; the
   shipped engine has no randomness), keeps the quiet positions (side to move not in check and the
   engine's quiescence search agrees with the static evaluation, so no capture is pending) and
   samples at most a few dozen per game. The quiet positions of the archived games under
   ``data/pgn/`` are added. Written to ``data/tuning/positions.epd``, one FEN per line.
2. ``label``: Stockfish (a local install, never shipped) evaluates every position at a fixed depth;
   the White-point-of-view centipawn score clipped to +-1500 is the label. Written to
   ``data/tuning/labels.csv``.
3. ``fit``: build the feature matrix, choose the ridge penalty lambda by 5-fold cross-validation,
   solve for the weights, round them to integers and write ``weights/pst.json``,
   ``weights/PROVENANCE.json`` and the ``STRUCTURE_WEIGHTS`` values in
   ``mikhail_letal/evaluation.py``. The penalty pulls every weight toward its *prior* value from
   ``tools/gen_pst.py`` rather than toward zero, so a square that is rarely occupied keeps its
   hand-set value and a common one moves as far as the labels justify. The pawn's middlegame value
   stays at 100 as the scale anchor.

``check`` refits with the recorded lambda and verifies that the shipped tables are exactly that
fit; ``tests/test_evaluation.py`` does the same.

The rules allow tuning on positions labelled by an existing engine; nothing of Stockfish's ships.
The zip carries only our tuned tables, and the engine never imports this module.
"""

from __future__ import annotations

import argparse
import csv
import datetime
import hashlib
import json
import multiprocessing
import random
import re
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine
import chess.pgn
import numpy as np
import numpy.typing as npt

from mikhail_letal import evaluation
from mikhail_letal.evaluation import MATE_SCORE, PHASE_TOTAL, evaluate, game_phase, is_mate_score
from mikhail_letal.search import Engine
from tools import gen_pst

Vector = npt.NDArray[np.float64]
Matrix = npt.NDArray[np.float64]

ROOT = Path(__file__).resolve().parent.parent
OPENINGS_PATH = ROOT / "data" / "openings.txt"
PGN_DIR = ROOT / "data" / "pgn"
TUNING_DIR = ROOT / "data" / "tuning"
POSITIONS_PATH = TUNING_DIR / "positions.epd"
LABELS_PATH = TUNING_DIR / "labels.csv"
REPORT_PATH = TUNING_DIR / "fit_report.json"
PST_PATH = gen_pst.PST_PATH
PROVENANCE_PATH = gen_pst.PROVENANCE_PATH
EVALUATION_PATH = ROOT / "mikhail_letal" / "evaluation.py"
STOCKFISH_PATH = Path.home() / ".local" / "opt" / "stockfish" / "stockfish"
GENERATOR = "tools/tune_texel.py"

SEED = 2026
INFINITY = float("inf")

# Step 1, position generation.
GAMES_PER_OPENING = 4
NODE_LIMIT = 2000  # nodes per move for the self-play engine: fast, weak and varied
RANDOM_MOVE_PROBABILITY = 0.2  # share of moves drawn at random among the near-best moves
RANDOM_MOVE_MARGIN = 30  # centipawns behind the best one-ply score that still counts as near-best
GAME_PLY_CAP = 200
MAX_POSITIONS_PER_GAME = 30

# Step 2, labelling.
STOCKFISH_DEPTH = 10
STOCKFISH_THREADS = 1
LABEL_WORKERS = 8
LABEL_CLIP = 1500  # centipawns; a mate label becomes +-LABEL_CLIP

# Step 3, fitting.
CV_FOLDS = 5
LAMBDA_GRID = (1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0)

# ------------------------------------------------------------------ the parameter vector
#
# Every weight the evaluation uses, in one flat vector: the piece values (both phases), the
# piece-square tables (both phases) and the structural weights. ``features`` builds the matching
# row of counts for a position, so that ``features(board) @ weights`` is the evaluation from
# White's point of view (up to the integer truncation of the phase blend).

PIECES = "PNBRQK"
VALUE_PIECES = "PNBRQ"  # the king has no material value
STRUCTURE_NAMES = tuple(gen_pst.STRUCTURE_PRIOR)
MG, EG = 0, 1
PHASES = (("mg", MG), ("eg", EG))

N_VALUES = 2 * len(VALUE_PIECES)
N_PST = 2 * len(PIECES) * 64
N_PARAMETERS = N_VALUES + N_PST + len(STRUCTURE_NAMES)


def value_index(piece: str, phase: int) -> int:
    return phase * len(VALUE_PIECES) + VALUE_PIECES.index(piece)


def pst_index(piece: str, square: int, phase: int) -> int:
    return N_VALUES + (phase * len(PIECES) + PIECES.index(piece)) * 64 + square


def structure_index(name: str) -> int:
    return N_VALUES + N_PST + STRUCTURE_NAMES.index(name)


# The pawn's middlegame value never moves: it is the unit every other weight is measured in.
ANCHOR = value_index("P", MG)


def parameter_names() -> list[str]:
    names = [""] * N_PARAMETERS
    for phase_name, phase in PHASES:
        for piece in VALUE_PIECES:
            names[value_index(piece, phase)] = f"piece_values_{phase_name}.{piece}"
        for piece in PIECES:
            for square in range(64):
                names[pst_index(piece, square, phase)] = (
                    f"pst_{phase_name}.{piece}.{chess.square_name(square)}"
                )
    for name in STRUCTURE_NAMES:
        names[structure_index(name)] = f"structure.{name}"
    return names


def weights_vector(tables: dict[str, Any], structure: dict[str, int]) -> Vector:
    """Flatten a ``pst.json``-shaped table set plus structural weights into the parameter vector."""
    w = np.zeros(N_PARAMETERS)
    for phase_name, phase in PHASES:
        values = tables[f"piece_values_{phase_name}"]
        pst = tables[f"pst_{phase_name}"]
        for piece in VALUE_PIECES:
            w[value_index(piece, phase)] = values[piece]
        for piece in PIECES:
            for square in range(64):
                w[pst_index(piece, square, phase)] = pst[piece][square]
    for name in STRUCTURE_NAMES:
        w[structure_index(name)] = structure[name]
    return w


def prior_vector() -> Vector:
    """The hand-set prior from ``tools/gen_pst.py``: what the fit is regularised toward."""
    pst_mg, pst_eg = gen_pst.build_tables()
    tables = {
        "piece_values_mg": gen_pst.PIECE_VALUES_MG,
        "piece_values_eg": gen_pst.PIECE_VALUES_EG,
        "pst_mg": pst_mg,
        "pst_eg": pst_eg,
    }
    return weights_vector(tables, {k: p.value for k, p in gen_pst.STRUCTURE_PRIOR.items()})


def shipped_vector() -> Vector:
    """What ``evaluate`` uses right now: ``weights/pst.json`` plus ``STRUCTURE_WEIGHTS``."""
    tables = json.loads(PST_PATH.read_text(encoding="utf-8"))
    return weights_vector(tables, evaluation.STRUCTURE_WEIGHTS)


def tables_from_vector(w: Vector) -> dict[str, Any]:
    """The ``pst.json`` table objects (integers) for a parameter vector; phase weights and the
    mop-up term are not part of the linear model and stay at the prior."""
    tables: dict[str, Any] = {}
    for phase_name, phase in PHASES:
        tables[f"piece_values_{phase_name}"] = {
            piece: int(w[value_index(piece, phase)]) for piece in VALUE_PIECES
        } | {"K": 0}
        tables[f"pst_{phase_name}"] = {
            piece: [int(w[pst_index(piece, square, phase)]) for square in range(64)]
            for piece in PIECES
        }
    tables["phase_weights"] = gen_pst.PHASE_WEIGHTS
    tables["mopup"] = {"edge": gen_pst.P["mopup_edge"], "close": gen_pst.P["mopup_close"]}
    return tables


def structure_from_vector(w: Vector) -> dict[str, int]:
    return {name: int(w[structure_index(name)]) for name in STRUCTURE_NAMES}


# ------------------------------------------------------------------ features of a position
#
# Plain python-chess counting, written for readability rather than speed. ``build_dataset``
# checks on every position that these counts reproduce ``evaluate`` exactly, so the two
# implementations (bitboards in evaluation.py, loops here) verify each other.


def passed_pawn_advance(board: chess.Board, colour: chess.Color) -> int:
    """Ranks advanced (2nd rank = 1 ... 7th = 6), summed over the colour's passed pawns: those with
    no enemy pawn ahead of them on their own file or a neighbouring one."""
    enemy_pawns = board.pieces(chess.PAWN, not colour)
    total = 0
    for square in board.pieces(chess.PAWN, colour):
        file, rank = chess.square_file(square), chess.square_rank(square)
        ranks_ahead = range(rank + 1, 8) if colour == chess.WHITE else range(rank)
        files = [f for f in (file - 1, file, file + 1) if 0 <= f < 8]
        if not any(chess.square(f, r) in enemy_pawns for r in ranks_ahead for f in files):
            total += rank if colour == chess.WHITE else 7 - rank
    return total


def doubled_pawns(board: chess.Board, colour: chess.Color) -> int:
    """Extra pawns on a file: two pawns on one file count one, three count two."""
    per_file = [0] * 8
    for square in board.pieces(chess.PAWN, colour):
        per_file[chess.square_file(square)] += 1
    return sum(count - 1 for count in per_file if count > 1)


def isolated_pawns(board: chess.Board, colour: chess.Color) -> int:
    """Pawns with no own pawn on either neighbouring file."""
    pawns = board.pieces(chess.PAWN, colour)
    files = {chess.square_file(square) for square in pawns}
    return sum(
        1
        for square in pawns
        if not files & {chess.square_file(square) - 1, chess.square_file(square) + 1}
    )


def bishop_pair(board: chess.Board, colour: chess.Color) -> int:
    return 1 if len(board.pieces(chess.BISHOP, colour)) >= 2 else 0


def rooks_on_open_files(board: chess.Board, colour: chess.Color) -> int:
    """Rooks on a file with no pawn of either colour."""
    return sum(
        1
        for square in board.pieces(chess.ROOK, colour)
        if not board.pawns & chess.BB_FILES[chess.square_file(square)]
    )


def rooks_on_semi_open_files(board: chess.Board, colour: chess.Color) -> int:
    """Rooks on a file that holds an enemy pawn but no own pawn (an open file is not semi-open)."""
    own_pawns = board.pieces_mask(chess.PAWN, colour)
    count = 0
    for square in board.pieces(chess.ROOK, colour):
        file_bb = chess.BB_FILES[chess.square_file(square)]
        if board.pawns & file_bb and not own_pawns & file_bb:
            count += 1
    return count


def king_shield_pawns(board: chess.Board, colour: chess.Color) -> int:
    """Own pawns on the king's file or a neighbouring file, one or two ranks ahead of the king."""
    king = board.king(colour)
    if king is None:
        return 0
    file, rank = chess.square_file(king), chess.square_rank(king)
    step = 1 if colour == chess.WHITE else -1
    own_pawns = board.pieces(chess.PAWN, colour)
    return sum(
        1
        for f in (file - 1, file, file + 1)
        if 0 <= f < 8
        for r in (rank + step, rank + 2 * step)
        if 0 <= r < 8 and chess.square(f, r) in own_pawns
    )


def features(board: chess.Board) -> Vector:
    """One row of the design matrix: how often each weight is used in ``board``, from White's
    view (White +1, Black -1, Black squares mirrored), every middlegame use scaled by the
    middlegame share of the phase and every endgame use by the endgame share, exactly as
    ``evaluate`` blends its two tables."""
    x = np.zeros(N_PARAMETERS)
    mg_share = game_phase(board) / PHASE_TOTAL
    eg_share = 1.0 - mg_share
    for square, piece in board.piece_map().items():
        sign = 1.0 if piece.color == chess.WHITE else -1.0
        letter = chess.piece_symbol(piece.piece_type).upper()
        own_view = square if piece.color == chess.WHITE else square ^ 56
        if letter != "K":
            x[value_index(letter, MG)] += sign * mg_share
            x[value_index(letter, EG)] += sign * eg_share
        x[pst_index(letter, own_view, MG)] += sign * mg_share
        x[pst_index(letter, own_view, EG)] += sign * eg_share

    def difference(count: Callable[[chess.Board, chess.Color], int]) -> int:
        return count(board, chess.WHITE) - count(board, chess.BLACK)

    passed = difference(passed_pawn_advance)
    x[structure_index("passed_pawn_mg")] = passed * mg_share
    x[structure_index("passed_pawn_eg")] = passed * eg_share
    # The evaluation subtracts the two pawn penalties, so their counts enter with a minus sign
    # and the fitted weights stay positive numbers, as in the dict.
    x[structure_index("doubled_pawn")] = -difference(doubled_pawns)
    x[structure_index("isolated_pawn")] = -difference(isolated_pawns)
    x[structure_index("bishop_pair")] = difference(bishop_pair)
    x[structure_index("rook_open_file")] = difference(rooks_on_open_files)
    x[structure_index("rook_semi_open_file")] = difference(rooks_on_semi_open_files)
    x[structure_index("king_shield")] = difference(king_shield_pawns) * mg_share
    return x


def white_evaluation(board: chess.Board) -> int:
    """``evaluate`` turned to White's point of view."""
    score = evaluate(board)
    return score if board.turn == chess.WHITE else -score


# ------------------------------------------------------------------ step 1: positions


@dataclass(frozen=True)
class GameTask:
    opening: str
    fen: str
    seed: int


def read_openings() -> list[tuple[str, str]]:
    """``name<TAB>fen`` lines of ``data/openings.txt``."""
    openings = []
    for line in OPENINGS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, fen = line.split("\t", 1)
            openings.append((name.strip(), fen.strip()))
    return openings


def quiescence_score(engine: Engine, board: chess.Board) -> int:
    """The engine's own quiescence value of ``board`` (side to move), with no node limit.

    Borrows the engine's private capture search rather than duplicating it, and sets the
    per-search bookkeeping that ``Engine.search`` would otherwise have initialised.
    """
    engine._nodes = 0
    engine._seldepth = 0
    engine._node_limit = None
    engine._hard_deadline = INFINITY
    return engine._quiescence(
        board.copy(stack=False), -MATE_SCORE, MATE_SCORE, 0, board.is_check(), 0
    )


def is_quiet(engine: Engine, board: chess.Board) -> bool:
    """A position whose static evaluation the search would trust as it stands: the side to move
    is not in check, no capture sequence changes the score, and there are pawns on the board (the
    mop-up term for bare kings is outside the linear model)."""
    if board.is_check() or not board.pawns:
        return False
    return quiescence_score(engine, board) == evaluate(board)


def near_best_moves(
    engine: Engine, board: chess.Board, history: dict[Any, int]
) -> list[chess.Move]:
    """Legal moves whose one-ply score is within ``RANDOM_MOVE_MARGIN`` of the best one."""
    scored = []
    for move in board.legal_moves:
        board.push(move)
        score = -engine.search(board, history, INFINITY, INFINITY, max_depth=1).score
        board.pop()
        scored.append((score, move))
    best = max(score for score, _ in scored)
    return [move for score, move in scored if score >= best - RANDOM_MOVE_MARGIN]


def play_game(task: GameTask) -> list[str]:
    """One self-play game at ``NODE_LIMIT`` nodes per move; returns a sample of its quiet FENs.

    The randomness (which moves are drawn from the near-best set, and which quiet positions are
    kept) is seeded per game, so the whole position set is reproducible.
    """
    rng = random.Random(task.seed)
    engine = Engine()
    board = chess.Board(task.fen)
    history: dict[Any, int] = {board._transposition_key(): 1}
    quiet: list[str] = []
    while board.ply() < GAME_PLY_CAP and not board.is_game_over(claim_draw=True):
        result = engine.search(board, history, INFINITY, INFINITY, node_limit=NODE_LIMIT)
        if result.move is None or is_mate_score(result.score):
            break  # a forced mate is not a position a static evaluation should be fitted to
        if is_quiet(engine, board):
            quiet.append(board.fen())
        move = result.move
        if rng.random() < RANDOM_MOVE_PROBABILITY:
            move = rng.choice(near_best_moves(engine, board, history))
        board.push(move)
        key = board._transposition_key()
        history[key] = history.get(key, 0) + 1
    if len(quiet) > MAX_POSITIONS_PER_GAME:
        chosen = sorted(rng.sample(range(len(quiet)), MAX_POSITIONS_PER_GAME))
        quiet = [quiet[i] for i in chosen]
    return quiet


def pgn_positions() -> list[str]:
    """Quiet positions of every game under ``data/pgn/``, in file order."""
    engine = Engine()
    fens: list[str] = []
    for path in sorted(PGN_DIR.rglob("*.pgn")):
        with path.open(encoding="utf-8") as fh:
            while (game := chess.pgn.read_game(fh)) is not None:
                board = game.board()
                for move in game.mainline_moves():
                    if is_quiet(engine, board):
                        fens.append(board.fen())
                    board.push(move)
    return fens


def dedupe(fens: Iterable[str]) -> list[str]:
    """Drop repeats of the same position (placement, side to move, castling, en passant), keeping
    the first occurrence and its order."""
    seen: set[str] = set()
    unique = []
    for fen in fens:
        key = " ".join(fen.split()[:4])
        if key not in seen:
            seen.add(key)
            unique.append(fen)
    return unique


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate_positions(workers: int) -> None:
    openings = read_openings()
    tasks = [
        GameTask(name, fen, SEED * 100_000 + index)
        for index, (name, fen) in enumerate(
            opening for opening in openings for _ in range(GAMES_PER_OPENING)
        )
    ]
    print(f"{len(openings)} openings x {GAMES_PER_OPENING} games on {workers} workers")
    from_games: list[str] = []
    with multiprocessing.Pool(workers) as pool:
        for done, quiet in enumerate(pool.imap(play_game, tasks, chunksize=1), start=1):
            from_games.extend(quiet)
            if done % 100 == 0 or done == len(tasks):
                print(f"  {done}/{len(tasks)} games, {len(from_games)} quiet positions", flush=True)
    from_pgn = pgn_positions()
    unique = dedupe(from_games + from_pgn)
    TUNING_DIR.mkdir(parents=True, exist_ok=True)
    POSITIONS_PATH.write_text("\n".join(unique) + "\n", encoding="utf-8")
    print(
        f"{len(from_games)} from self-play + {len(from_pgn)} from data/pgn -> {len(unique)} unique"
    )
    print(f"wrote {POSITIONS_PATH.relative_to(ROOT)} sha256 {sha256_of(POSITIONS_PATH)}")


# ------------------------------------------------------------------ step 2: labels


def read_positions() -> list[str]:
    return [
        line for line in POSITIONS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def label_positions(workers: int) -> None:
    """Score every position with Stockfish at ``STOCKFISH_DEPTH``, one engine process per thread."""
    fens = read_positions()
    engines: list[chess.engine.SimpleEngine] = []
    local = threading.local()
    lock = threading.Lock()

    def engine_for_this_thread() -> chess.engine.SimpleEngine:
        engine: chess.engine.SimpleEngine | None = getattr(local, "engine", None)
        if engine is None:
            engine = chess.engine.SimpleEngine.popen_uci(str(STOCKFISH_PATH))
            engine.configure({"Threads": STOCKFISH_THREADS, "Hash": 16})
            local.engine = engine
            with lock:
                engines.append(engine)
        return engine

    def label(fen: str) -> int:
        info = engine_for_this_thread().analyse(
            chess.Board(fen), chess.engine.Limit(depth=STOCKFISH_DEPTH)
        )
        cp = info["score"].white().score(mate_score=MATE_SCORE)
        return max(-LABEL_CLIP, min(LABEL_CLIP, cp))

    print(
        f"labelling {len(fens)} positions: {workers} Stockfish processes, depth {STOCKFISH_DEPTH}"
    )
    with ThreadPoolExecutor(max_workers=workers) as pool:
        labels = list(pool.map(label, fens, chunksize=32))
    labeller = engines[0].id.get("name", "unknown")
    for engine in engines:
        engine.quit()

    with LABELS_PATH.open("w", encoding="utf-8", newline="") as fh:
        fh.write(
            f"# {labeller}, depth {STOCKFISH_DEPTH}, Threads {STOCKFISH_THREADS}, "
            f"White-point-of-view centipawns clipped to +-{LABEL_CLIP}\n"
        )
        writer = csv.writer(fh)
        writer.writerow(["fen", "cp"])
        writer.writerows(zip(fens, labels, strict=True))
    print(f"wrote {LABELS_PATH.relative_to(ROOT)} sha256 {sha256_of(LABELS_PATH)}")


def read_labels() -> tuple[list[str], list[int], str]:
    """(fens, centipawn labels, labeller description) from ``labels.csv``."""
    with LABELS_PATH.open(encoding="utf-8", newline="") as fh:
        labeller = fh.readline().lstrip("# ").strip()
        rows = list(csv.DictReader(fh))
    return [row["fen"] for row in rows], [int(row["cp"]) for row in rows], labeller


# ------------------------------------------------------------------ step 3: the fit


@dataclass
class Dataset:
    fens: list[str]
    design: Matrix  # one row per position, one column per weight
    y: Vector  # labels, White's point of view, centipawns


def build_dataset(fens: Sequence[str], labels: Sequence[int]) -> Dataset:
    """Feature rows for every position, checked against the shipped ``evaluate`` as we go."""
    shipped = shipped_vector()
    rows = []
    kept_fens = []
    kept_labels = []
    for fen, label in zip(fens, labels, strict=True):
        board = chess.Board(fen)
        if not board.pawns:  # the mop-up term for bare kings is outside the linear model
            continue
        x = features(board)
        reconstructed = float(x @ shipped)
        if abs(reconstructed - white_evaluation(board)) > 1.0:  # 1 = the phase blend's truncation
            raise AssertionError(
                f"features do not reproduce evaluate() for {fen}: "
                f"{reconstructed:.2f} vs {white_evaluation(board)}"
            )
        rows.append(x)
        kept_fens.append(fen)
        kept_labels.append(label)
    return Dataset(kept_fens, np.array(rows), np.array(kept_labels, dtype=np.float64))


def ridge_solve(gram: Matrix, moment: Vector, lam: float) -> Vector:
    """The deviation ``d`` from the prior minimising ||design d - r||^2 + lambda ||d||^2, given
    ``gram`` = X^T X and ``moment`` = X^T r (r = labels minus what the prior predicts)."""
    return np.linalg.solve(gram + lam * np.eye(len(moment)), moment)


def fit(design: Matrix, y: Vector, prior: Vector, lam: float) -> Vector:
    """Ridge regression toward ``prior`` with the anchor weight held fixed."""
    free = np.arange(N_PARAMETERS) != ANCHOR
    residual = y - design @ prior
    design_free = design[:, free]
    w = prior.copy()
    w[free] += ridge_solve(design_free.T @ design_free, design_free.T @ residual, lam)
    return w


def cross_validate(
    design: Matrix, y: Vector, prior: Vector, lambdas: Sequence[float], folds: int, seed: int
) -> dict[float, float]:
    """Validation mean squared error of the fit for every lambda, averaged over ``folds`` folds.

    Each fold's X^T X and X^T r are computed once; the training matrices for a fold are the
    totals minus that fold, so the whole curve costs one pass over the data.
    """
    rng = np.random.default_rng(seed)
    fold_of = np.empty(len(y), dtype=np.int64)
    fold_of[rng.permutation(len(y))] = np.arange(len(y)) % folds
    free = np.arange(N_PARAMETERS) != ANCHOR
    residual = y - design @ prior
    design_free = design[:, free]
    grams = [design_free[fold_of == k].T @ design_free[fold_of == k] for k in range(folds)]
    moments = [design_free[fold_of == k].T @ residual[fold_of == k] for k in range(folds)]
    total_gram = sum(grams[1:], grams[0])
    total_moment = sum(moments[1:], moments[0])
    curve = {}
    for lam in lambdas:
        squared_errors = 0.0
        for k in range(folds):
            d = ridge_solve(total_gram - grams[k], total_moment - moments[k], lam)
            held_out = fold_of == k
            squared_errors += float(np.sum((residual[held_out] - design_free[held_out] @ d) ** 2))
        curve[lam] = squared_errors / len(y)
    return curve


def mse(design: Matrix, y: Vector, w: Vector) -> float:
    return float(np.mean((design @ w - y) ** 2))


def biggest_changes(before: Vector, after: Vector, count: int) -> list[dict[str, Any]]:
    names = parameter_names()
    order = np.argsort(-np.abs(after - before), kind="stable")[:count]
    return [
        {"parameter": names[i], "prior": int(before[i]), "fitted": int(after[i])}
        for i in order
        if after[i] != before[i]
    ]


# ------------------------------------------------------------------ writing the results


def write_structure_weights(structure: dict[str, int], tuned_by: str) -> None:
    """Rewrite the values of ``STRUCTURE_WEIGHTS`` and its ``# tuned-by:`` line in evaluation.py."""
    source = EVALUATION_PATH.read_text(encoding="utf-8")
    for name, value in structure.items():
        source, replaced = re.subn(
            rf'^(\s+"{name}": )-?\d+(,.*)$', rf"\g<1>{value}\g<2>", source, flags=re.MULTILINE
        )
        if replaced != 1:
            raise RuntimeError(f"STRUCTURE_WEIGHTS[{name!r}] not found exactly once")
    source, replaced = re.subn(r"^# tuned-by: .*$", f"# tuned-by: {tuned_by}", source, flags=re.M)
    if replaced != 1:
        raise RuntimeError("the '# tuned-by:' line above STRUCTURE_WEIGHTS is missing")
    EVALUATION_PATH.write_text(source, encoding="utf-8")


def provenance_rows(
    tables: dict[str, Any],
    structure: dict[str, int],
    prior: Vector,
    fitted: Vector,
    produced_by: str,
    data: str,
    run_id: str,
) -> list[dict[str, str]]:
    """The ``weights/PROVENANCE.json`` records: one per parameter group."""
    names = parameter_names()

    def largest_change(indices: list[int]) -> str:
        i = max(indices, key=lambda i: abs(fitted[i] - prior[i]))
        if fitted[i] == prior[i]:
            return "unchanged from the prior"
        return f"largest change {names[i].split('.')[-1]} {int(prior[i])} -> {int(fitted[i])}"

    rows = []
    for phase_name, phase in PHASES:
        indices = [value_index(piece, phase) for piece in VALUE_PIECES]
        rows.append(
            {
                "parameter": f"piece_values_{phase_name}",
                "value_or_shape": json.dumps(tables[f"piece_values_{phase_name}"]),
                "produced_by": produced_by,
                "data": data,
                "run_id": run_id,
                "note": f"ridge fit toward the textbook prior; {largest_change(indices)}"
                + ("; P fixed at 100 as the scale anchor" if phase == MG else ""),
            }
        )
    for phase_name, phase in PHASES:
        for piece in PIECES:
            table = tables[f"pst_{phase_name}"][piece]
            indices = [pst_index(piece, square, phase) for square in range(64)]
            rows.append(
                {
                    "parameter": f"pst_{phase_name}.{piece}",
                    "value_or_shape": f"64 ints, min {min(table)}, max {max(table)}",
                    "produced_by": produced_by,
                    "data": data,
                    "run_id": run_id,
                    "note": f"ridge fit toward the geometric prior; {largest_change(indices)}",
                }
            )
    rows.append(
        {
            "parameter": "structure_weights",
            "value_or_shape": json.dumps(structure),
            "produced_by": produced_by,
            "data": data,
            "run_id": run_id,
            "note": "ridge fit toward the hand-chosen prior; written into evaluation.py; "
            + largest_change([structure_index(name) for name in STRUCTURE_NAMES]),
        }
    )
    for name, note in (
        ("phase_weights", "sum over the full board is 24 = PHASE_TOTAL"),
        ("mopup", "drive the bare king to the edge, bring ours close; not in the linear model"),
    ):
        rows.append(
            {
                "parameter": name,
                "value_or_shape": json.dumps(tables[name]),
                "produced_by": "tools/gen_pst.py (unchanged prior)",
                "data": "none: parametric prior",
                "run_id": run_id,
                "note": note,
            }
        )
    return rows


def fit_command(lambda_scale: float) -> None:
    fens, labels, labeller = read_labels()
    prior = prior_vector()
    shipped = shipped_vector()
    dataset = build_dataset(fens, labels)
    design, y = dataset.design, dataset.y
    print(f"{len(y)} positions with pawns out of {len(fens)} labelled; {N_PARAMETERS} weights")

    curve = cross_validate(design, y, prior, LAMBDA_GRID, CV_FOLDS, SEED)
    best_lambda = min(curve, key=lambda lam: curve[lam])
    lam = best_lambda * lambda_scale
    fitted = fit(design, y, prior, lam)
    rounded = np.rint(fitted)
    rounded[ANCHOR] = prior[ANCHOR]
    validation = (
        cross_validate(design, y, prior, (lam,), CV_FOLDS, SEED)[lam]
        if lambda_scale != 1
        else curve[lam]
    )

    report_mse = {
        "prior_train": mse(design, y, prior),
        "shipped_train": mse(design, y, shipped),
        "fitted_train": mse(design, y, fitted),
        "rounded_train": mse(design, y, rounded),
        "fitted_validation_cv": validation,
    }
    print("5-fold validation MSE by lambda (prior: {:.0f}):".format(report_mse["prior_train"]))
    for grid_lambda, error in curve.items():
        marker = "  <- chosen" if grid_lambda == best_lambda else ""
        print(f"  lambda {grid_lambda:>8g}: {error:10.1f}{marker}")
    if lambda_scale != 1:
        print(f"  lambda scaled x{lambda_scale:g} -> {lam:g} (validation {validation:.1f})")
    for name, value in report_mse.items():
        print(f"  {name:>22}: {value:10.1f}  (rmse {value**0.5:6.1f} cp)")
    changes = biggest_changes(prior, rounded, 25)
    print("biggest changes from the prior:")
    for change in changes:
        print(f"  {change['parameter']:>28}: {change['prior']:5d} -> {change['fitted']:5d}")

    tables = tables_from_vector(rounded)
    structure = structure_from_vector(rounded)
    for phase_name, _ in PHASES:
        for piece in PIECES:
            print(f"{phase_name} {piece} (value {tables[f'piece_values_{phase_name}'][piece]})")
            print(gen_pst.grid(tables[f"pst_{phase_name}"][piece]))
    print(f"structure weights {structure}")

    commit = gen_pst.git_commit()
    today = datetime.date.today().isoformat()
    run_id = f"texel-{today}-lambda{lam:g}"
    positions_sha = sha256_of(POSITIONS_PATH)
    labels_sha = sha256_of(LABELS_PATH)
    tables_sha = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    provenance = {
        "generator": GENERATOR,
        "git_commit": commit,
        "date": today,
        "run_id": run_id,
        "note": (
            "Texel-style ridge regression of every table entry and structural weight toward the "
            "tools/gen_pst.py prior, on quiet self-play positions labelled by Stockfish; "
            "pawn middlegame value anchored at 100; fitted values rounded to integers"
        ),
        "tables_sha256": tables_sha,
        "data": {
            "positions": {
                "path": str(POSITIONS_PATH.relative_to(ROOT)),
                "sha256": positions_sha,
                "count": len(fens),
                "used": len(y),
                "how": (
                    f"mikhail_letal.search.Engine self-play at {NODE_LIMIT} nodes/move from "
                    f"data/openings.txt, {GAMES_PER_OPENING} seeded games per opening, a move "
                    f"drawn among the near-best (within {RANDOM_MOVE_MARGIN} cp at one ply) with "
                    f"probability {RANDOM_MOVE_PROBABILITY}; quiet positions only, at most "
                    f"{MAX_POSITIONS_PER_GAME} per game; plus the quiet positions of "
                    "data/pgn/**/*.pgn; seed "
                    f"{SEED}"
                ),
            },
            "labels": {
                "path": str(LABELS_PATH.relative_to(ROOT)),
                "sha256": labels_sha,
                "labeller": labeller,
                "depth": STOCKFISH_DEPTH,
                "threads": STOCKFISH_THREADS,
                "clip_cp": LABEL_CLIP,
                "point_of_view": "White",
            },
        },
        "fit": {
            "lambda": lam,
            "lambda_scale": lambda_scale,
            "cv_folds": CV_FOLDS,
            "cv_curve": {f"{k:g}": v for k, v in curve.items()},
            "mse": report_mse,
            "anchor": "piece_values_mg.P = 100",
        },
        "prior": {
            "generator": "tools/gen_pst.py",
            "parameters": {
                name: {"value": p.value, "why": p.why} for name, p in gen_pst.PARAMETERS.items()
            },
            "structure": {
                name: {"value": p.value, "why": p.why}
                for name, p in gen_pst.STRUCTURE_PRIOR.items()
            },
        },
        "structure_weights": structure,
    }
    document = {"_provenance": provenance, **tables}
    PST_PATH.write_text(gen_pst.dump_json(document, 0) + "\n", encoding="utf-8")

    produced_by = f"{GENERATOR} @ {commit} (prior: tools/gen_pst.py)"
    data = (
        f"{POSITIONS_PATH.relative_to(ROOT)} sha256 {positions_sha}; "
        f"{LABELS_PATH.relative_to(ROOT)} sha256 {labels_sha} "
        f"({labeller}, depth {STOCKFISH_DEPTH}, Threads {STOCKFISH_THREADS}, "
        f"White-POV cp clipped to +-{LABEL_CLIP})"
    )
    rows = provenance_rows(tables, structure, prior, rounded, produced_by, data, run_id)
    PROVENANCE_PATH.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    write_structure_weights(structure, f"{GENERATOR} @ {commit[:12]} run {run_id}")

    report = {
        "run_id": run_id,
        "git_commit": commit,
        "date": today,
        "positions": {"count": len(fens), "used": len(y), "sha256": positions_sha},
        "labels": {"sha256": labels_sha, "labeller": labeller},
        "lambda": lam,
        "lambda_scale": lambda_scale,
        "cv_curve": {f"{k:g}": v for k, v in curve.items()},
        "mse": report_mse,
        "biggest_changes": changes,
        "structure_weights": structure,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {PST_PATH.relative_to(ROOT)}, {PROVENANCE_PATH.relative_to(ROOT)}, "
        f"{EVALUATION_PATH.relative_to(ROOT)} (STRUCTURE_WEIGHTS), {REPORT_PATH.relative_to(ROOT)}"
    )


# ------------------------------------------------------------------ check the shipped file


def recorded_fit() -> tuple[dict[str, Any], dict[str, int]]:
    """Redo the fit recorded in ``weights/pst.json``'s ``_provenance`` (same data files, same
    lambda) and return the integer tables and structural weights it produces."""
    provenance = json.loads(PST_PATH.read_text(encoding="utf-8"))["_provenance"]
    if provenance["generator"] != GENERATOR:
        raise RuntimeError(f"weights/pst.json was written by {provenance['generator']}")
    for key, path in (("positions", POSITIONS_PATH), ("labels", LABELS_PATH)):
        recorded = provenance["data"][key]["sha256"]
        if sha256_of(path) != recorded:
            raise RuntimeError(f"{path.relative_to(ROOT)} differs from the recorded sha256")
    fens, labels, _ = read_labels()
    dataset = build_dataset(fens, labels)
    fitted = fit(dataset.design, dataset.y, prior_vector(), float(provenance["fit"]["lambda"]))
    rounded = np.rint(fitted)
    rounded[ANCHOR] = prior_vector()[ANCHOR]
    return tables_from_vector(rounded), structure_from_vector(rounded)


def check_command() -> int:
    tables, structure = recorded_fit()
    shipped = json.loads(PST_PATH.read_text(encoding="utf-8"))
    mismatches = [key for key in tables if shipped[key] != tables[key]]
    if structure != evaluation.STRUCTURE_WEIGHTS:
        mismatches.append("STRUCTURE_WEIGHTS")
    if mismatches:
        print(f"MISMATCH: {', '.join(mismatches)} differ from the recorded fit")
        return 1
    print("ok: weights/pst.json and STRUCTURE_WEIGHTS equal the recorded fit")
    return 0


# ------------------------------------------------------------------ command line


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    positions = sub.add_parser(
        "positions", help="self-play position set -> data/tuning/positions.epd"
    )
    positions.add_argument("--workers", type=int, default=multiprocessing.cpu_count())
    label = sub.add_parser("label", help="Stockfish labels -> data/tuning/labels.csv")
    label.add_argument("--workers", type=int, default=LABEL_WORKERS)
    fit_parser = sub.add_parser("fit", help="ridge fit -> weights/pst.json, evaluation.py")
    fit_parser.add_argument(
        "--lambda-scale",
        type=float,
        default=1.0,
        help="multiply the cross-validated lambda by this (the fallback experiment uses 4)",
    )
    everything = sub.add_parser("all", help="positions, label, fit")
    everything.add_argument("--workers", type=int, default=multiprocessing.cpu_count())
    everything.add_argument("--lambda-scale", type=float, default=1.0)
    sub.add_parser("check", help="verify the shipped tables equal the recorded fit")
    args = parser.parse_args(argv)

    if args.command in ("positions", "all"):
        generate_positions(args.workers)
    if args.command in ("label", "all"):
        label_positions(LABEL_WORKERS if args.command == "all" else args.workers)
    if args.command in ("fit", "all"):
        fit_command(args.lambda_scale)
    if args.command == "check":
        return check_command()
    return 0


if __name__ == "__main__":
    sys.exit(main())
