"""Is the reordered tree cheaper because it is also *worse* at the same depth?

The gap this closes
-------------------
`tools/bench_conthist.py` establishes that the ordering bundle reaches depth 8 with 47% of the
nodes v1.2 needs, and asserts both builds reached that depth. **It never checks that they know the
same thing when they get there.** If the cheaper tree is also a worse-informed one, part of the
measured speedup is illusory and the ply conversion built on it overstates the change.

That is the failure that cost the network 67 Elo: it was better on four independent static
measurements because nobody had checked that the quantity being measured was the quantity that
matters.

Why the two builds are comparable at all
----------------------------------------
SEE and continuation history change **move ordering only** — neither touches the evaluation. Two
searches with the same evaluation and no pruning heuristics would return the identical score at
the identical depth. So every disagreement is the pruning heuristics (late-move reductions,
futility, reverse futility, aspiration) interacting with a different move order, which is exactly
the thing in question.

How it runs
-----------
One build per process, like `tools/bench_conthist.py`, because both builds are called
`mikhail_letal` and cannot be imported into one interpreter without aliasing that would silently
resolve their internal imports to whichever copy loaded first. Each run dumps its answers; a
separate pass compares them. The baseline dumps `--arbiter-plies` deeper than the feature build,
so a disagreement can be adjudicated.

    BASE=$(git merge-base main HEAD)
    .venv/bin/python tools/depth_quality.py --dump ordering --json dq-ordering.jsonl
    git checkout "$BASE" -- mikhail_letal/
    .venv/bin/python tools/depth_quality.py --dump baseline --json dq-baseline.jsonl --extra 3
    git checkout HEAD -- mikhail_letal/
    .venv/bin/python tools/depth_quality.py --compare dq-ordering.jsonl dq-baseline.jsonl

What it reports, per depth
--------------------------
* **move agreement** between the builds;
* **mean and worst absolute score difference**, in centipawns;
* where the moves differ, **which build's move the deeper baseline search prefers**. The arbiter
  is always the *baseline* searching deeper, never the feature build, because an oracle drawn
  from the change under test cannot embarrass it.

High agreement with small score differences means the cheaper tree knows the same things and the
speedup is real. Systematic disagreement that the deeper baseline settles in the baseline's favour
would mean the bundle buys cheapness by pruning away the answer, and the 1.65x should be
discounted accordingly.

**This is not an Elo claim and cannot become one.** Only a game screen decides strength. This
decides whether the benchmark measured what it was taken to measure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikhail_letal.fastboard import position_key
from mikhail_letal.fastsearch import FastEngine

ROOT = Path(__file__).resolve().parent.parent
OPENINGS = ROOT / "data" / "openings.txt"


def engine_fingerprint() -> dict[str, str]:
    """A hash per module of the engine source this process imported, so `--compare` can refuse a
    pair whose two halves turn out to be the same build. See tools/bench_conthist.py."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        for path in sorted((ROOT / "mikhail_letal").glob("*.py"))
    }


# Sharp positions, for `--sharp`. 86's point: if reordering degrades what the search knows, it
# will show up where the reductions and the futility cuts are doing the most work, not in a quiet
# opening. These are the tactical positions the test suite already uses for exactly that reason.
#
# And 86's caveat on its own suggestion, which belongs next to the sample rather than in the
# conversation that produced it: **this is a small, hand-picked, deliberately adversarial set.**
# A bad signed mean here is a reason to look, not a result. If `--sharp` comes back positive and
# the curated openings come back flat, that is a lead to chase on a larger sample -- it is not a
# finding, and it must not be written up as one.
SHARP = (
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",  # Kiwipete
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",  # open game
    "5r1k/4Nppp/8/8/7Q/8/6K1/3R4 w - - 0 1",  # mate in two
    "rnb1kbnr/pppp1ppp/8/4p3/7q/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 3",  # hanging queen
    "r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R2Q1RK1 w - - 4 10",  # opening middlegame
    "rnbq1rk1/pp2ppbp/2pp1np1/8/2PPP3/2N2N2/PP2BPPP/R1BQ1RK1 w - - 0 8",  # closed centre
    "8/5pk1/6p1/1p2P2p/1P1r1P1P/6P1/3R2K1/8 w - - 0 1",  # rook ending
    "r3k2r/1P6/8/1Pp5/8/3p4/4P3/R3K2R w KQkq c6 0 1",  # promotions and en passant
)


def curated(count: int, sharp: bool) -> list[str]:
    if sharp:
        return list(SHARP)[:count]
    fens = [
        line.strip().split("\t")[-1]
        for line in OPENINGS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not fens:
        raise SystemExit(f"no openings in {OPENINGS}")
    step = max(1, len(fens) // count)
    return fens[::step][:count]


def far() -> float:
    return time.perf_counter() + 3600.0


def dump(label: str, positions: int, max_depth: int, extra: int, sharp: bool) -> dict[str, object]:
    """Every (position, depth) answer this build gives, from a cold table each time."""
    engine = FastEngine()
    fens = curated(positions, sharp)
    deepest = max_depth + extra
    print(f"[{label}] {len(fens)} positions, depths 1..{deepest}")
    answers: dict[str, dict[str, list[object]]] = {}
    for fen in fens:
        by_depth: dict[str, list[object]] = {}
        for depth in range(1, deepest + 1):
            engine.new_game()
            board = chess.Board(fen)
            result = engine.search(
                board, [position_key(board)], far(), far(), max_depth=depth, node_limit=10**12
            )
            if result.move is None or result.depth != depth:
                raise SystemExit(f"[{label}] depth {depth} not reached on {fen}")
            by_depth[str(depth)] = [result.move.uci(), int(result.score)]
        answers[fen] = by_depth
        print(f"[{label}]   done {fen.split(' ')[0][:28]}")
    return {
        "label": label,
        "engine_source": engine_fingerprint(),
        "max_depth": max_depth,
        "extra": extra,
        "answers": answers,
    }


def compare(feature_path: Path, baseline_path: Path) -> int:
    feature = json.loads(feature_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if feature["engine_source"] == baseline["engine_source"]:
        raise SystemExit("both files came from the same engine source; nothing was swapped")
    moved = sorted(
        name
        for name in set(feature["engine_source"]) | set(baseline["engine_source"])
        if feature["engine_source"].get(name) != baseline["engine_source"].get(name)
    )
    print(f"modules differing between the builds: {', '.join(moved)}")

    fens = [fen for fen in feature["answers"] if fen in baseline["answers"]]
    max_depth = min(int(feature["max_depth"]), int(baseline["max_depth"]))
    arbiter_depth = max_depth + int(baseline["extra"])
    print(
        f"{len(fens)} shared positions, depths 1..{max_depth}, arbiter at depth {arbiter_depth}\n"
    )
    print(
        f"  {'depth':>5} {'agree':>9} {'mean signed':>12} {'mean abs':>9} {'arbiter favours':>24}"
    )

    for depth in range(1, max_depth + 1):
        agree = 0
        signed: list[int] = []
        for_feature = 0
        for_baseline = 0
        for fen in fens:
            move_f, score_f = feature["answers"][fen][str(depth)]
            move_b, score_b = baseline["answers"][fen][str(depth)]
            # Signed, feature minus baseline, and averageable -- 86's point that a raw
            # disagreement count alarms without informing. Two builds surface different
            # equal-value moves for ordinary reasons; what matters is whether the feature's score
            # is *systematically* displaced. A persistent positive mean is the shape to fear: a
            # search that prunes away a refutation comes back too optimistic.
            signed.append(int(score_f) - int(score_b))
            if move_f == move_b:
                agree += 1
                continue
            deep = baseline["answers"][fen].get(str(arbiter_depth))
            if deep is None:
                continue
            if deep[0] == move_f:
                for_feature += 1
            elif deep[0] == move_b:
                for_baseline += 1
        verdict = f"{for_feature} feature / {for_baseline} baseline"
        print(
            f"  {depth:>5} {agree:>4}/{len(fens):<4} {statistics.mean(signed):>+12.1f} "
            f"{statistics.mean(abs(d) for d in signed):>9.1f} {verdict:>24}"
        )

    print(
        "\nRead the signed column first. A mean near zero with scattered signs is two builds\n"
        "surfacing different equal-value moves, which is expected. A persistently positive mean\n"
        "means the feature build is systematically more optimistic at the same depth, which is\n"
        "what a search that prunes away refutations looks like -- and would mean part of the\n"
        "1.65x is bought rather than free.\n"
        "\nDisagreements the arbiter settles neither way are moves the deeper baseline did not\n"
        "choose either; they count in neither column."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", metavar="LABEL", help="record this build's answers")
    parser.add_argument("--json", type=Path, help="where --dump writes")
    parser.add_argument("--positions", type=int, default=12)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument(
        "--extra",
        type=int,
        default=0,
        help="depths beyond --max-depth to record; give the BASELINE 3 so it can arbitrate",
    )
    parser.add_argument(
        "--sharp",
        action="store_true",
        help="tactical positions instead of curated openings; where reordering would show",
    )
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("FEATURE", "BASELINE"))
    args = parser.parse_args()

    if args.compare:
        return compare(*args.compare)
    if not args.dump or not args.json:
        raise SystemExit("give either --dump LABEL --json PATH, or --compare FEATURE BASELINE")
    record = dump(args.dump, args.positions, args.max_depth, args.extra, args.sharp)
    args.json.write_text(json.dumps(record), encoding="utf-8")
    print(f"[{args.dump}] wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
