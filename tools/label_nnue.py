"""Positions and Stockfish labels for the network, kept apart from the Texel data.

Why a separate file rather than growing ``data/tuning/labels.csv``: that file's sha256 is recorded
in ``docs/PROVENANCE.md`` as the input to the Texel experiment, and overwriting it would falsify a
record rather than extend a dataset. This writes ``nnue_positions.epd`` and ``nnue_labels.csv``
beside it, in the same format and with the same conventions -- White's point of view, clipped to
the same +-1500 -- so the trainer reads either without knowing the difference.

**Positions come from real games, not self-play.** ``tools/tune_texel.py`` generates its set by
having our own interpreted engine play itself, which is slow and produces positions only as varied
as a weak engine's play. The ladder PGNs already collected are 1 600+ games between engines
stronger than ours, which is a better distribution to learn from and costs nothing to read. Those
files are gitignored -- they are large and never ship -- so ``--pgn-dir`` points at wherever they
live; the default is this repository's own ``data/pgn``.

Positions are filtered the way training data has to be: the side to move is not in check (a forced
reply says nothing about the position's value), the first plies of each game are skipped (opening
book, over-represented and near-equal), and duplicates are dropped by FEN so a position repeated in
two hundred games does not get two hundred votes.

The rules sanction this explicitly: the network must be one we trained, and training it on
positions an engine labelled is a normal way to do that. Stockfish labels the data and nothing of
Stockfish ships.

    .venv/bin/python tools/label_nnue.py extract --pgn-dir ../chessathon/data/pgn
    .venv/bin/python tools/label_nnue.py label --workers 14 --depth 8
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Final

import chess
import chess.engine
import chess.pgn

ROOT = Path(__file__).resolve().parent.parent
POSITIONS_PATH = ROOT / "data" / "tuning" / "nnue_positions.epd"
LABELS_PATH = ROOT / "data" / "tuning" / "nnue_labels.csv"
STOCKFISH_PATH = Path.home() / ".local" / "opt" / "stockfish" / "stockfish"

LABEL_CLIP: Final = 1500  # centipawns, as in tune_texel; a mate label becomes +-LABEL_CLIP
MATE_SCORE: Final = 100_000
SKIP_PLIES: Final = 8  # opening book: over-represented across games and nearly all equal


def extract(pgn_dir: Path, limit: int, seed: int) -> list[str]:
    """Every quiet, non-book, unique position from the games under ``pgn_dir``."""
    files = sorted(pgn_dir.rglob("*.pgn"))
    if not files:
        raise SystemExit(f"no PGN files under {pgn_dir}")
    seen: set[str] = set()
    fens: list[str] = []
    games = 0
    for path in files:
        with path.open(encoding="utf-8", errors="replace") as handle:
            while True:
                game = chess.pgn.read_game(handle)
                if game is None:
                    break
                games += 1
                board = game.board()
                for ply, move in enumerate(game.mainline_moves()):
                    board.push(move)
                    if ply < SKIP_PLIES or board.is_check() or board.is_game_over():
                        continue
                    # The key drops the halfmove and fullmove counters, which do not change the
                    # evaluation but would defeat deduplication.
                    key = board.board_fen() + " " + ("w" if board.turn else "b")
                    if key in seen:
                        continue
                    seen.add(key)
                    fens.append(board.fen())
    print(f"{games} games in {len(files)} files -> {len(fens)} unique positions")
    if len(fens) > limit:
        random.Random(seed).shuffle(fens)
        fens = fens[:limit]
        print(f"sampled down to {len(fens)}")
    return fens


def label(fens: list[str], workers: int, depth: int, threads: int) -> tuple[list[int], str]:
    """Score every position with Stockfish, one engine process per worker thread."""
    engines: list[chess.engine.SimpleEngine] = []
    local = threading.local()
    lock = threading.Lock()
    done = [0]
    started = time.perf_counter()

    def engine_for_this_thread() -> chess.engine.SimpleEngine:
        engine: chess.engine.SimpleEngine | None = getattr(local, "engine", None)
        if engine is None:
            engine = chess.engine.SimpleEngine.popen_uci(str(STOCKFISH_PATH))
            engine.configure({"Threads": threads, "Hash": 16})
            local.engine = engine
            with lock:
                engines.append(engine)
        return engine

    def score(fen: str) -> int:
        info = engine_for_this_thread().analyse(chess.Board(fen), chess.engine.Limit(depth=depth))
        centipawns = info["score"].white().score(mate_score=MATE_SCORE)
        with lock:
            done[0] += 1
            if done[0] % 20_000 == 0:
                rate = done[0] / (time.perf_counter() - started)
                left = (len(fens) - done[0]) / rate
                print(f"  {done[0]:>8,}/{len(fens):,}  {rate:>6.0f}/s  {left / 60:>5.1f} min left")
        return max(-LABEL_CLIP, min(LABEL_CLIP, centipawns))

    print(f"labelling {len(fens):,} positions: {workers} Stockfish processes, depth {depth}")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        labels = list(pool.map(score, fens, chunksize=32))
    name = engines[0].id.get("name", "unknown") if engines else "unknown"
    for engine in engines:
        engine.quit()
    return labels, name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="PGN games -> nnue_positions.epd")
    ex.add_argument("--pgn-dir", type=Path, default=ROOT / "data" / "pgn")
    ex.add_argument("--limit", type=int, default=1_000_000)
    ex.add_argument("--seed", type=int, default=20260909)
    lb = sub.add_parser("label", help="Stockfish labels -> nnue_labels.csv")
    lb.add_argument("--workers", type=int, default=12)
    lb.add_argument("--depth", type=int, default=8)
    lb.add_argument("--threads", type=int, default=1)
    lb.add_argument("--limit", type=int, default=0, help="label only the first N (a probe)")
    lb.add_argument("--out", type=Path, default=LABELS_PATH)
    args = parser.parse_args()

    if args.command == "extract":
        fens = extract(args.pgn_dir, args.limit, args.seed)
        POSITIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        POSITIONS_PATH.write_text("\n".join(fens) + "\n", encoding="utf-8")
        print(f"wrote {POSITIONS_PATH.relative_to(ROOT)}")
        return 0

    fens = POSITIONS_PATH.read_text(encoding="utf-8").split("\n")
    fens = [f for f in fens if f.strip()]
    if args.limit:
        fens = fens[: args.limit]
    started = time.perf_counter()
    labels, labeller = label(fens, args.workers, args.depth, args.threads)
    elapsed = time.perf_counter() - started
    print(f"labelled {len(fens):,} in {elapsed / 60:.1f} min ({len(fens) / elapsed:.0f}/s)")

    with args.out.open("w", encoding="utf-8", newline="") as handle:
        handle.write(
            f"# {labeller}, depth {args.depth}, Threads {args.threads}, "
            f"White-point-of-view centipawns clipped to +-{LABEL_CLIP}\n"
        )
        writer = csv.writer(handle)
        writer.writerow(["fen", "cp"])
        writer.writerows(zip(fens, labels, strict=True))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
