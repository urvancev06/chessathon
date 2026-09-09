"""How often would late move pruning skip the move that turns out to be best?

The question this exists to settle
----------------------------------
The pruning batch measured -21 Elo. Two hypotheses explain that, and a 300-game screen cannot tell
them apart, because it resolves +-39 Elo and late move pruning's plausible value is a fraction of
that. "Did not screen positive" is compatible with clearly negative and with solidly positive.

    (A) the ordering is inadequate -- the best move is often late in the quiet list, so a
        count-based cut removes it;
    (B) the technique does not suit this engine -- the best move is early, LMP rarely removes it,
        and it loses anyway for some other reason.

Those make *opposite* predictions about one number that needs no games: **where in the quiet move
list the best move sits, at the nodes where LMP is active.** This tool measures that number, under
two different move orderings, so the comparison is direct.

Why it probes a child position and not the position it was given
----------------------------------------------------------------
LMP fires at interior nodes, and this measures a node's ordering by making that node a search
root. A root is only a fair proxy if it has the two things an interior node has: a previous move,
and tables warmed by a shallower search.

The previous move is the part that is easy to get wrong. ``FastEngine.search`` sets
``cont_base[0]`` to "no previous move" -- correct, because a FEN carries none -- so continuation
history contributes **nothing** at a root. Probing the given position directly would therefore
have reported continuation history as making no difference to the ordering, as a pure artefact of
where the probe was taken. So each sample plays one move first and probes the position it reaches,
with ``cont_base[0]`` set to that move's own row, which is exactly what the node would hold had
the search arrived there itself.

What it does, per sample
------------------------
1. Play one move from an opening, giving a child position with a known previous move.
2. Search the child to ``depth - 1``, filling the table, the killers and both history tables the
   way iterative deepening fills them before iteration ``depth``.
3. Restore the previous move's continuation row, then order the child's moves with exactly the
   engine's own machinery: ``gen_pseudo``, ``_score_moves``, ``_pick_best``.
4. Search the child to ``depth`` to get the move the engine actually believes in.
5. Find that move in the ordering and count how many **quiet** moves precede it.

A move is beyond LMP's reach only if it is quiet, is not the table move and is not a killer --
LMP excludes those three by construction. For the rest, LMP would have skipped it exactly when its
quiet index is at or past ``LATE_MOVE_PRUNING_COUNTS[depth]``.

What this measures and what it does not
---------------------------------------
It measures the **cost** side of LMP: how often the cut removes the answer. It says nothing about
the benefit, which is the extra depth the saved nodes buy, and no fixed-depth probe can see that.
A low number here does not make LMP good; it only rules hypothesis (A) out.

Two limitations that remain, and neither is one a game screen escapes either:

* The probed node gets a **full window** where most LMP-eligible interior nodes get a null one,
  and its killers are ply 0's rather than a real ply's. Both make the ordering here worse than a
  real interior node's, so this number is an **upper bound** on how often LMP removes the answer.
* "Best" is the engine's own answer at ``depth``, not ground truth -- which is the right standard
  anyway, since the question is whether LMP removes the move the search would otherwise return.

Nodes where the best move is the table move, a capture or a killer are reported separately rather
than folded into the headline, because LMP cannot touch them.

Late move pruning must be switched **off** in whichever build is being probed. ``measure`` refuses
to run otherwise, and the comment there says why. Both arms are edited the same way, and the
``engine_source`` hashes record that the edit happened, so the two runs stay comparable.

    # 1. in mikhail_letal/search.py set LATE_MOVE_PRUNING = False, then
    .venv/bin/python tools/lmp_probe.py --label ordering --json lmp.jsonl
    # 2. restore the baseline engine source (the branch's merge base, never "main", which moves),
    #    set LATE_MOVE_PRUNING = False in it as well, then
    .venv/bin/python tools/lmp_probe.py --label baseline --json lmp.jsonl
    # 3. restore this branch's engine source, then
    .venv/bin/python tools/lmp_probe.py --report lmp.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mikhail_letal.fastboard import (
    NO_MOVE,
    PROMO_MASK,
    PROMO_SHIFT,
    from_fen,
    gen_pseudo,
    move_from_chess,
    position_key,
    running_key,
    set_from_board,
)
from mikhail_letal.fastsearch import FastEngine, _pick_best, _score_moves, _tt_probe, _victim
from mikhail_letal.search import (
    LATE_MOVE_PRUNING,
    LATE_MOVE_PRUNING_COUNTS,
    LATE_MOVE_PRUNING_MAX_DEPTH,
)

ROOT = Path(__file__).resolve().parent.parent
OPENINGS = ROOT / "data" / "openings.txt"

# The baseline arm may be a build with no continuation history at all, in which case `SearchState`
# has no such field and there is no row to restore. Probed rather than assumed, because the whole
# point of the tool is to compare two builds that differ.
try:  # pragma: no cover - depends on which engine source is in place
    from mikhail_letal.fastsearch import _cont_base

    HAS_CONTINUATION = True
except ImportError:  # pragma: no cover
    HAS_CONTINUATION = False


def engine_fingerprint() -> dict[str, str]:
    """A hash per module of the engine source this process imported. See tools/bench_conthist.py:
    the arms are made by swapping ``mikhail_letal/``, so the branch name identifies neither."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        for path in sorted((ROOT / "mikhail_letal").glob("*.py"))
    }


def openings(count: int) -> list[str]:
    fens = [
        line.strip().split("\t")[-1]
        for line in OPENINGS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not fens:
        raise SystemExit(f"no openings in {OPENINGS}")
    step = max(1, len(fens) // count)
    return fens[::step][:count]


def children(fen: str, branch: int) -> list[tuple[str, str]]:
    """``(child fen, uci of the move that reached it)`` for the first ``branch`` legal moves."""
    board = chess.Board(fen)
    out = []
    for move in list(board.legal_moves)[:branch]:
        board.push(move)
        if not board.is_game_over():
            out.append((board.fen(), move.uci()))
        board.pop()
    return out


def far() -> float:
    return time.perf_counter() + 3600.0


def is_quiet(pos: object, move: int) -> bool:
    return _victim(pos, move) == 0 and ((move >> PROMO_SHIFT) & PROMO_MASK) == 0


def probe_one(
    engine: FastEngine, parent_fen: str, uci: str, child_fen: str, depth: int
) -> dict[str, object] | None:
    """One (position, depth) sample. ``None`` when the node cannot answer the question."""
    board = chess.Board(child_fen)
    keys = [position_key(board)]
    engine.new_game()

    # The continuation row for the move that reached this position, computed on the parent, where
    # the from-square still holds the moving piece.
    base = None
    if HAS_CONTINUATION:
        parent = from_fen(parent_fen)
        base = int(_cont_base(parent, move_from_chess(parent, chess.Move.from_uci(uci))))

    # (2) Fill the tables the way iteration `depth - 1` would have left them.
    if depth > 1:
        engine.search(board, keys, far(), far(), max_depth=depth - 1)

    # (3) The table move and the continuation row as the node would really hold them, then the
    # ordering that follows.
    st, pos = engine.state, engine.position
    # `set_from_board` unconditionally, not only when the warm search was skipped. At depth 1
    # there is no warm search, so nothing else would ever load this position into `pos` -- the
    # ordering below would be built from whatever the previous sample left behind, `best` would
    # not be found in it, and every depth-1 sample would be dropped as unusable. Silently: the
    # per-depth table would simply show a zero row.
    set_from_board(pos, board)
    if base is not None:
        st.cont_base[0] = base
    slot = int(_tt_probe(st, running_key(pos)))
    tt_move = int(st.tt_data[slot, 3]) if slot >= 0 else NO_MOVE
    count = int(gen_pseudo(pos, st.moves[0]))
    _score_moves(pos, st, 0, count, tt_move)
    order = []
    for index in range(count):
        _pick_best(st, 0, index, count)
        order.append(int(st.moves[0, index]))
    killers = {int(st.killers[0, 0]), int(st.killers[0, 1])}

    # (4) What the engine actually believes at this depth.
    result = engine.search(board, keys, far(), far(), max_depth=depth)
    if result.move is None:
        return None
    best = int(move_from_chess(engine.position, result.move))

    # (5) Where that move sits, counting only the quiet moves ahead of it.
    quiet_index = 0
    found = False
    for move in order:
        if move == best:
            found = True
            break
        if is_quiet(pos, move):
            quiet_index += 1
    if not found:
        return None  # ordering and search disagree about the move list; not a usable sample

    best_quiet = is_quiet(pos, best)
    reachable = best_quiet and best != tt_move and best not in killers
    return {
        "fen": child_fen,
        "depth": depth,
        "quiet_index": quiet_index,
        "reachable": reachable,
        "is_tt_move": best == tt_move,
        "is_quiet": best_quiet,
        "would_skip": bool(reachable and quiet_index >= LATE_MOVE_PRUNING_COUNTS[depth]),
    }


def measure(label: str, count: int, branch: int) -> dict[str, object]:
    # Late move pruning must be OFF in the build being probed, and this refuses rather than warns
    # because the contamination runs the wrong way. Step 4 asks the engine for the best move. With
    # LMP on, that search can itself have skipped the true best move -- so the probe would find
    # whatever inferior move survived, note that it sorted early, and record "LMP would not have
    # skipped it". It would systematically *understate* the thing it exists to measure, and the
    # understatement points at "the ordering is fine, drop the pruning" -- the direction that
    # closes the question. The threshold below is still the real LATE_MOVE_PRUNING_COUNTS; only
    # the search that establishes the best move has to be free of the cut being judged.
    if LATE_MOVE_PRUNING:
        raise SystemExit(
            "set search.LATE_MOVE_PRUNING = False in the build being probed and re-run.\n"
            "With it on, the search that decides the best move has already been able to prune\n"
            "that move away, and the probe measures a survivor rather than the answer."
        )
    engine = FastEngine()
    nodes = [
        (parent, uci, child)
        for parent in openings(count)
        for child, uci in children(parent, branch)
    ]
    print(f"[{label}] {len(nodes)} nodes x depths 1..{LATE_MOVE_PRUNING_MAX_DEPTH}")
    print(f"[{label}] continuation history present in this build: {HAS_CONTINUATION}")
    samples = []
    for depth in range(1, LATE_MOVE_PRUNING_MAX_DEPTH + 1):
        for parent, uci, child in nodes:
            sample = probe_one(engine, parent, uci, child, depth)
            if sample is not None:
                samples.append(sample)
        print(f"[{label}] depth {depth} done ({len(samples)} samples so far)")
    return {
        "label": label,
        "engine_source": engine_fingerprint(),
        "continuation_history": HAS_CONTINUATION,
        "samples": samples,
    }


def summarise(run: dict[str, object]) -> None:
    samples: list[dict[str, object]] = run["samples"]  # type: ignore[assignment]
    print(f"\n{run['label']} (continuation history: {run.get('continuation_history')})")
    print(f"  {'depth':>5} {'nodes':>6} {'LMP can reach':>14} {'would skip best':>16} {'count':>6}")
    for depth in range(1, LATE_MOVE_PRUNING_MAX_DEPTH + 1):
        at_depth = [s for s in samples if s["depth"] == depth]
        if not at_depth:
            continue
        reachable = [s for s in at_depth if s["reachable"]]
        skipped = [s for s in reachable if s["would_skip"]]
        share = f"{100 * len(skipped) / len(reachable):.1f}%" if reachable else "n/a"
        print(
            f"  {depth:>5} {len(at_depth):>6} {len(reachable):>14} "
            f"{share:>16} {LATE_MOVE_PRUNING_COUNTS[depth]:>6}"
        )
    reachable = [s for s in samples if s["reachable"]]
    skipped = [s for s in reachable if s["would_skip"]]
    print(f"  best move was the table move:          {sum(1 for s in samples if s['is_tt_move'])}")
    print(f"  best move was a capture or promotion:  {sum(1 for s in samples if not s['is_quiet'])}")
    if reachable:
        print(
            f"  OVERALL: LMP would have skipped the best move at "
            f"{100 * len(skipped) / len(reachable):.1f}% of the nodes it can reach "
            f"({len(skipped)}/{len(reachable)})"
        )


def side_by_side(first: dict[str, object], second: dict[str, object]) -> None:
    """Both arms in one table, counts beside every rate.

    The denominators are here and not in an appendix on purpose. Every table this project has
    produced today reported a rate without the count it was taken over, and a thin row reads
    exactly like a real effect until you go looking for how many samples made it. Reading the
    counts first is the rule; putting them in the same row is what makes the rule easy to keep.
    """
    labels = (str(first["label"]), str(second["label"]))
    print(f"\n{'':>5}  {labels[0]:^26}  {labels[1]:^26}")
    print(f"{'depth':>5}  {'reach   skip    share':^26}  {'reach   skip    share':^26}")
    for depth in range(1, LATE_MOVE_PRUNING_MAX_DEPTH + 1):
        cells = []
        for run in (first, second):
            samples: list[dict[str, object]] = run["samples"]  # type: ignore[assignment]
            reachable = [s for s in samples if s["depth"] == depth and s["reachable"]]
            skipped = [s for s in reachable if s["would_skip"]]
            share = f"{100 * len(skipped) / len(reachable):.1f}%" if reachable else "n/a"
            cells.append(f"{len(reachable):>5}  {len(skipped):>5}  {share:>8}")
        print(f"{depth:>5}  {cells[0]:^26}  {cells[1]:^26}")
    totals = []
    for run in (first, second):
        samples = run["samples"]  # type: ignore[assignment]
        reachable = [s for s in samples if s["reachable"]]
        skipped = [s for s in reachable if s["would_skip"]]
        share = f"{100 * len(skipped) / len(reachable):.1f}%" if reachable else "n/a"
        totals.append(f"{len(reachable):>5}  {len(skipped):>5}  {share:>8}")
    print(f"{'all':>5}  {totals[0]:^26}  {totals[1]:^26}")
    print(
        "\n'reach' is the nodes LMP could touch at all: the best move was quiet, was not the table\n"
        "move and was not a killer. 'skip' is those where its quiet index reached the pruning\n"
        "count. A row whose 'reach' is far below its neighbours is not a finding, it is a thin\n"
        "sample -- distrust it rather than explain it."
    )


def report(path: Path) -> int:
    runs = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    for run in runs:
        summarise(run)
    if len(runs) == 2:
        side_by_side(runs[0], runs[1])
        moved = sorted(
            name
            for name in set(runs[0]["engine_source"]) | set(runs[1]["engine_source"])
            if runs[0]["engine_source"].get(name) != runs[1]["engine_source"].get(name)
        )
        print(f"\nmodules differing between the two runs: {', '.join(moved) if moved else 'none'}")
        if not moved:
            raise SystemExit("both runs used the same engine source; nothing was swapped")
        print(
            "\nRead it this way. If the better ordering skips the best move markedly less often,\n"
            "the -21 is consistent with an ordering that was not good enough for a count-based\n"
            "cut, and late move pruning is worth re-screening on top of it. If the two are close,\n"
            "better ordering does not rescue it and the technique is the problem. Neither reading\n"
            "is an Elo claim, and this measures only what LMP costs, never what its saved nodes\n"
            "buy back in depth."
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="ordering")
    parser.add_argument("--positions", type=int, default=30)
    parser.add_argument("--branch", type=int, default=3, help="child nodes probed per opening")
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    if args.report is not None:
        return report(args.report)

    run = measure(args.label, args.positions, args.branch)
    summarise(run)
    if args.json is not None:
        with args.json.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run) + "\n")
        print(f"[{args.label}] appended to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
