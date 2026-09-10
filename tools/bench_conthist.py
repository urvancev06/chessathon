"""What one-ply continuation history costs the compiled search, in nodes per second.

Why this tool is shaped differently from ``tools/bench_mobility.py``
-------------------------------------------------------------------
That one switches its feature with ``fasteval.TABLES.misc[E_MOBILITY_ON]``, an array entry the
compiled code reads at run time, so both arms live in one process and every pair meets the same
machine at the same moment. ``search.CONTINUATION_HISTORY`` is a plain module constant that numba
folds at compile time -- which is the right thing for the engine, because the "off" arm then costs
literally nothing -- and that makes the same trick impossible here: the two arms are different
machine code and cannot coexist in one process.

So this tool measures **one** build and prints a JSON line. The arms are paired in *time* instead:
run it, swap ``mikhail_letal/`` to the other build, run it again, and alternate which build goes
first. Each pair is then a minute apart rather than simultaneous, which controls slow drift but
not an instantaneous background spike -- hence the load check below, and hence per-round ratios
rather than one pooled number, so a spike shows up as scatter instead of as an answer.

**Name the baseline by commit, never by branch.** `main` moves several times a day on this
repository, and the first version of this docstring said ``git checkout main -- mikhail_letal/``
-- which by the time it was run would have measured continuation history against a pruning batch
that landed after the branch point, and reported the difference as the cost of continuation
history. The baseline is the branch's merge base, which ``git merge-base main HEAD`` prints:

    BASE=$(git merge-base main HEAD)
    .venv/bin/python tools/bench_conthist.py --label conthist --json bench.jsonl
    git checkout "$BASE" -- mikhail_letal/
    .venv/bin/python tools/bench_conthist.py --label baseline --json bench.jsonl
    git checkout HEAD -- mikhail_letal/          # ... and alternate which arm goes first
    .venv/bin/python tools/bench_conthist.py --report bench.jsonl

``--report`` records the hash of the engine source each arm imported and refuses a pair whose two
arms share one. Note what that check does *not* do: it proves the arms differ, not that they
differ only in the thing under test. Two builds separated by an unrelated feature also have two
distinct hashes and satisfy it perfectly, which is why it prints the per-file breakdown as well.

What the two numbers mean
-------------------------
**Nodes per second** is the cost being measured: the same tree walked with a little more work per
node. **Nodes to a fixed depth** is a different question -- the ordering has changed, so the two
builds search different trees -- and it is a search-quality diagnostic, not a speed cost and not
an Elo claim. Only a game screen decides strength.

The first round is run and thrown away. A position searched for the first time in a process costs
far more than the same search ever costs again (the mobility session measured 9x, and reported its
feature as four times *faster* before it noticed), and one such search left in a total is worth
more than the whole effect being measured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    """A hash per module of the engine source this process actually imported.

    Not the git commit. The two arms are produced by swapping ``mikhail_letal/`` under a fixed
    ``HEAD``, so ``git rev-parse HEAD`` says the same thing for both and would identify neither;
    and `main` moves several times a day under people measuring against it, so a number without
    something identifying its source is not comparable to anything. This hashes the files that
    were imported, which is true regardless of what the branch says.

    Per module rather than one hash for the tree, because one hash answers a narrower question
    than it appears to. It proves the two arms *differ*; it cannot say they differ **only in the
    thing under test**, and two builds separated by an unrelated feature satisfy it perfectly.
    The per-module map lets ``--report`` print exactly which modules moved, so a baseline that
    has drifted somewhere unexpected is visible rather than merely hashed.
    """
    fingerprint = {}
    for path in sorted((ROOT / "mikhail_letal").glob("*.py")):
        fingerprint[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return fingerprint


def overall(fingerprint: dict[str, str]) -> str:
    """One short hash standing for a whole engine source, for printing and equality."""
    joined = "".join(f"{name}:{digest}" for name, digest in sorted(fingerprint.items()))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def curated_positions(count: int) -> list[str]:
    """An evenly spaced sample of the curated openings, which is where rated games start."""
    fens = [
        line.strip().split("\t")[-1]
        for line in OPENINGS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not fens:
        raise SystemExit(f"no openings in {OPENINGS}")
    step = max(1, len(fens) // count)
    return fens[::step][:count]


def search_once(engine: FastEngine, fen: str, depth: int) -> tuple[int, float]:
    """Nodes and seconds for one fixed-depth search.

    ``new_game`` before every search: a transposition table, killer list or history table carried
    over from the previous search would make the later one look faster, and with this feature the
    carried-over table is the very thing under test.
    """
    engine.new_game()
    board = chess.Board(fen)
    far = time.perf_counter() + 3600.0
    started = time.perf_counter()
    result = engine.search(
        board, [position_key(board)], far, far, max_depth=depth, node_limit=10**12
    )
    elapsed = time.perf_counter() - started
    if result.aborted:
        raise SystemExit(f"search aborted, which a fixed-depth run must never do: {fen}")
    if result.depth != depth:
        raise SystemExit(f"reached depth {result.depth}, not {depth}: {fen}")
    return result.nodes, elapsed


def measure(
    label: str, depth: int, rounds: int, positions: int, verbose: bool
) -> dict[str, object]:
    fens = curated_positions(positions)
    engine = FastEngine()

    fingerprint = engine_fingerprint()
    load = os.getloadavg()[0]
    print(f"[{label}] engine source {overall(fingerprint)} ({len(fingerprint)} modules)")
    print(f"[{label}] depth {depth}, {len(fens)} curated positions, {rounds} measured rounds")
    print(f"[{label}] load average at start: {load:.2f} on {os.cpu_count()} cores")
    if load > 1.5:
        print(f"[{label}]   WARNING: the box is busy; nodes per second is not meaningful here.")

    print(f"[{label}] warm-up round (run, not counted)")
    for fen in fens:
        search_once(engine, fen, depth)

    # Per POSITION, per round -- not accumulated. An earlier version summed across positions and
    # reported ratios of the two sums, which is the wrong estimator: a pooled ratio is carried by
    # whichever position happens to have the largest tree, and `tools/bench_mobility.py` produced
    # 0.96, 1.13, 1.58 and 2.19 for the same quantity that way. Keeping the samples lets `report`
    # pair them position by position and take a median, which is what the nps figure needed too.
    per_round: list[list[dict[str, float]]] = []
    for index in range(rounds):
        samples: list[dict[str, float]] = []
        for fen in fens:
            got, took = search_once(engine, fen, depth)
            samples.append({"fen": fen, "nodes": got, "seconds": took})  # type: ignore[dict-item]
            if verbose:
                print(f"[{label}]   {fen.split(' ')[0][:24]:<24} {got:>9,}n {took:7.3f}s")
        per_round.append(samples)
        nodes = sum(int(s["nodes"]) for s in samples)
        seconds = sum(float(s["seconds"]) for s in samples)
        print(
            f"[{label}] round {index + 1}: {nodes:>11,} nodes {seconds:7.2f} s "
            f"{nodes / seconds:>10,.0f} nodes/s pooled"
        )

    return {
        "label": label,
        "engine_source": fingerprint,
        "depth": depth,
        "positions": len(fens),
        "load_at_start": load,
        "rounds": per_round,
    }


def report(path: Path) -> int:
    """Compare the runs recorded in ``path``, pairing them in the order they were taken."""
    runs = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    labels = sorted({run["label"] for run in runs})
    if len(labels) != 2:
        raise SystemExit(f"expected exactly two labels in {path}, found {labels}")
    # The FIRST run recorded is the feature arm, which is the order the usage above prescribes.
    # This used to sort the labels with the feature identified by the literal name "conthist", so
    # any other pair of labels fell through to alphabetical order and could put the baseline in
    # the feature slot -- reporting the reciprocal, in which a 3% cost reads as a 3% gain. The
    # ratio's direction is the whole output; it must not depend on what the arms were called.
    feature = str(runs[0]["label"])
    baseline = next(name for name in labels if name != feature)

    by_label = {name: [run for run in runs if run["label"] == name] for name in labels}
    if len({len(v) for v in by_label.values()}) != 1:
        raise SystemExit(f"unequal numbers of runs: { {k: len(v) for k, v in by_label.items()} }")

    # The check that a swap-based harness most needs: if the source that was actually imported is
    # the same on both sides, the swap did not happen and the whole comparison is of one build
    # against itself -- which would report a ratio of about 1.000 and look entirely reasonable.
    sources: dict[str, dict[str, str]] = {}
    for name in labels:
        seen = {overall(run["engine_source"]): run["engine_source"] for run in by_label[name]}
        if len(seen) != 1:
            raise SystemExit(
                f"'{name}' was measured on more than one engine source: {sorted(seen)}. The tree "
                "changed between its runs, so they are not repeats of one measurement."
            )
        sources[name] = next(iter(seen.values()))
    if overall(sources[feature]) == overall(sources[baseline]):
        raise SystemExit(
            f"both arms imported the same engine source ({overall(sources[feature])}): the source "
            "was never swapped, so this compares a build with itself"
        )

    # Which modules actually moved between the arms. The equality check above proves only that
    # they differ; this is what shows whether they differ *only* in the thing under test. A
    # baseline picked by branch rather than by merge base shows up right here, as modules nobody
    # expected to be in the comparison.
    moved = sorted(
        name
        for name in set(sources[feature]) | set(sources[baseline])
        if sources[feature].get(name) != sources[baseline].get(name)
    )
    print(f"pairing {len(by_label[feature])} run(s) of each, in the order taken")
    for name in (baseline, feature):
        print(f"  {name:>10}: engine source {overall(sources[name])}")
    print(f"  modules differing between the arms: {', '.join(moved) if moved else 'none'}")
    print("  everything listed is inside this comparison. If a module you did not change is")
    print("  there, the baseline is not the branch's merge base and the number means something")
    print("  other than what you are about to call it.")
    print()
    # Paired PER POSITION, and both quantities the same way. The earlier version paired the nps
    # per round -- a median over three timing repeats of a rate already pooled across positions,
    # which measured only whether the clock was steady -- and reported the tree ratio as a ratio
    # of two pooled sums, which is carried by whichever position has the largest tree. Both looked
    # precise for the same wrong reason: they were medians of the wrong variance.
    nps_ratios: list[float] = []
    node_ratios: list[float] = []
    totals = {name: [0, 0.0] for name in labels}
    for index, (one, two) in enumerate(zip(by_label[feature], by_label[baseline], strict=True)):
        for run, name in ((one, feature), (two, baseline)):
            for round_samples in run["rounds"]:
                for entry in round_samples:
                    totals[name][0] += int(entry["nodes"])
                    totals[name][1] += float(entry["seconds"])
        for a_round, b_round in zip(one["rounds"], two["rounds"], strict=True):
            for a, b in zip(a_round, b_round, strict=True):
                if a["fen"] != b["fen"]:
                    raise SystemExit("position lists differ between the arms; cannot pair")
                nps_ratios.append(
                    (int(a["nodes"]) / float(a["seconds"]))
                    / (int(b["nodes"]) / float(b["seconds"]))
                )
                node_ratios.append(int(a["nodes"]) / int(b["nodes"]))
        print(f"  pair {index + 1}: load {one['load_at_start']:.2f} / {two['load_at_start']:.2f}")

    for name in (baseline, feature):
        nodes, seconds = totals[name]
        print(
            f"\n{name:>10}: {nodes:>12,} nodes {seconds:8.2f} s {nodes / seconds:>10,.0f} nodes/s"
        )

    def summarise(what: str, ratios: list[float], pooled: float) -> float:
        median = statistics.median(ratios)
        print(f"\n{what} ({feature} / {baseline}), paired per position")
        print(
            f"  median {median:.4f}   pooled {pooled:.4f}   "
            f"min {min(ratios):.4f} max {max(ratios):.4f}   over {len(ratios)} pairs"
        )
        if abs(median - pooled) > 0.02:
            print("  WARNING: median and pooled disagree by more than 2%, so one position is")
            print("           carrying the pooled figure. Quote the median; the pooled number")
            print("           is the estimator that gave bench_mobility 0.96 through 2.19.")
        return median

    nps_median = summarise(
        "node rate",
        nps_ratios,
        (totals[feature][0] / totals[feature][1]) / (totals[baseline][0] / totals[baseline][1]),
    )
    # Spelled out rather than signed: a signed percentage against the word "cost" makes the reader
    # work out whether +32% means it cost that or gained it, and this gets quoted on its own.
    change = (nps_median - 1) * 100
    if change < 0:
        print(f"  {feature} is {-change:.1f}% SLOWER per node than {baseline}")
    else:
        print(f"  {feature} is {change:.1f}% FASTER per node than {baseline}")

    node_median = summarise(
        f"nodes to depth {runs[0]['depth']}",
        node_ratios,
        totals[feature][0] / totals[baseline][0],
    )
    print("  Deterministic per position, so the spread here is between POSITIONS, not runs.")
    print("  A different ordering searches a different tree. Not an Elo claim; a screen decides.")
    print(
        f"\ncombined: time to depth {runs[0]['depth']} = {node_median / nps_median:.4f} of baseline"
    )
    print("  (nodes-to-depth median divided by node-rate median, both paired per position)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="conthist", help="which build this run measures")
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--positions", type=int, default=10)
    parser.add_argument("--json", type=Path, default=None, help="append the result here")
    parser.add_argument("--report", type=Path, default=None, help="compare a results file instead")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.report is not None:
        return report(args.report)

    result = measure(args.label, args.depth, args.rounds, args.positions, args.verbose)
    if args.json is not None:
        with args.json.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result) + "\n")
        print(f"[{args.label}] appended to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
