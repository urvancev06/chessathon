"""Probe one engine build: critical positions, node rate, and evaluation symmetry.

Usage: python handoff/probe.py <engine-dir> <label>

Run as a subprocess per build, because two copies of ``mikhail_letal`` cannot be imported into
one interpreter. Platform seconds are converted to local seconds by the 2.3x speed factor
measured in docs/CALIBRATION.md, so "3.4 s" below is what the engine really gets on the ladder.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]).resolve()))

import chess  # noqa: E402

from mikhail_letal.evaluation import evaluate  # noqa: E402
from mikhail_letal.gamestate import GameState  # noqa: E402
from mikhail_letal.search import Engine  # noqa: E402

LABEL = sys.argv[2]
SPEED_FACTOR = 2.3

# (name, fen, the move played on the ladder, what Stockfish wanted, cp thrown away)
CASES = [
    ("r70 move 20", "2kr1b1r/Q3p1pp/2p1qp2/3pNbN1/3P1n2/2P5/PP3PPP/R4RK1 b - - 5 20", "Ne2+", "fxg5", 191),
    ("r70 move 22", "2kr1b1r/Q3p1pp/2p1q3/3pNbp1/3P4/2P5/PP2nPPP/R3R2K b - - 1 22", "Nxd4", "Nf4", 665),
    ("r70 move 24", "2k2b1r/Q3p1pp/2prq3/3pNbp1/3P4/8/PP3PPP/R3R1K1 b - - 2 24", "Qf6", "Kd8", 405),
    ("r70 move 8", "r2qkb1r/pp2pppp/2n2n2/3p4/3P1Bb1/1QPB4/PP3PPP/RN2K1NR b KQkq - 4 7", "Qd7", "Qd7", 8),
    ("r68 move 10", "r2qkb1r/5ppp/p2pbn2/1p2p3/4P3/1NN1B2P/PPP2PP1/R2QKB1R w KQkq - 0 9", "-", "-", 0),
]

NPS_POSITIONS = [
    ("start", chess.STARTING_FEN),
    ("middlegame", "r1bq1rk1/pp1nbppp/2p1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R1BQ1RK1 w - - 0 9"),
]


def choose(fen: str, platform_seconds: float) -> tuple[str, int, int, int]:
    local = platform_seconds / SPEED_FACTOR
    board = chess.Board(fen)
    state = GameState()
    state.observe(board)
    engine = Engine()
    now = time.perf_counter()
    result = engine.search(
        board, state.history, soft_deadline=now + local * 0.45, hard_deadline=now + local
    )
    return board.san(result.move), result.score, result.depth, result.nodes


def main() -> None:
    print(f"===== {LABEL} =====")
    for name, fen, played, best, cost in CASES[:4]:
        line = []
        for budget in (3.4, 10.0):
            san, score, depth, _ = choose(fen, budget)
            mark = "OK " if san == best else ("BAD" if san == played else "?? ")
            line.append(f"{budget:>5.1f}s {mark} {san:<6} {score:+6d} d{depth}")
        print(f"  {name:<12} played {played:<6} want {best:<6} (-{cost}cp) | " + " | ".join(line))

    for name, fen in NPS_POSITIONS:
        board = chess.Board(fen)
        state = GameState()
        state.observe(board)
        engine = Engine()
        now = time.perf_counter()
        r = engine.search(board, state.history, soft_deadline=now + 3.0, hard_deadline=now + 3.2)
        print(
            f"  nps {name:<11} {int(r.nodes / r.elapsed):>7} nps  "
            f"move {board.san(r.move):<6} d{r.depth}/{r.seldepth} n{r.nodes}"
        )

    # A position and its colour-swapped mirror must score exactly opposite, or the term is
    # asymmetric and one colour gets a bonus the other does not.
    bad = 0
    for _, fen, *_rest in CASES:
        board = chess.Board(fen)
        if evaluate(board) != evaluate(board.mirror()):
            bad += 1
    print(f"  mirror symmetry: {'OK' if bad == 0 else f'BROKEN on {bad} positions'}")


main()
