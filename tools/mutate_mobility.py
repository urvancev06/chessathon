"""Break the mobility term one way at a time and report which tests notice.

A test that would pass whatever the implementation did is a claim, not a check. This tool makes
that testable: it copies the repository to a temporary directory, applies one plausible mistake to
the term, runs the mobility tests and the compiled-vs-Python parity gate, and records which tests
failed. A mutation that nothing catches is a hole in the suite; a test that no mutation makes fail
is a test that is not yet a check.

Run it per test, not per suite. When this was first run, every mutation was caught and the suite
looked healthy -- and two of the eleven tests had still never failed under any of them, hidden
behind the parity gate catching everything. The summary below is therefore by test as well as by
mutation, and the exit code is non-zero if either list has an entry.

    .venv/bin/python tools/mutate_mobility.py

The repository is copied rather than edited, so an interrupted run cannot leave a mutated engine
behind. It takes a few minutes: numba recompiles in each of the twelve runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ElementTree
from collections import defaultdict
from pathlib import Path
from typing import Final, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
EVAL = Path("mikhail_letal") / "evaluation.py"
FAST = Path("mikhail_letal") / "fasteval.py"

# Selects the mobility tests plus the parity gate the compiled port is held to.
SELECT: Final = "mobility or matches_python"


class Mutation(NamedTuple):
    """One plausible way to get the term wrong, as an exact source substitution."""

    what: str
    path: Path
    old: str
    new: str


_SLIDER_BLOCKER = """                        else:
                            if (target >> COLOUR_SHIFT) != colour:
                                count += 1
                            break
"""

MUTATIONS: Final[tuple[Mutation, ...]] = (
    Mutation(
        "slider ray does not stop at the first piece",
        FAST,
        _SLIDER_BLOCKER,
        """                        else:
                            if (target >> COLOUR_SHIFT) != colour:
                                count += 1
""",
    ),
    Mutation(
        "slider counts the square its own piece stands on",
        FAST,
        _SLIDER_BLOCKER,
        """                        else:
                            count += 1
                            break
""",
    ),
    Mutation(
        "slider does not count the enemy piece it can capture",
        FAST,
        _SLIDER_BLOCKER,
        """                        else:
                            break
""",
    ),
    Mutation(
        "knight off-board test is a range check, not 0x88",
        FAST,
        """                    if (to & OFF_BOARD_MASK) != 0:
                        continue
""",
        """                    if to < 0 or to > 127:
                        continue
""",
    ),
    Mutation(
        "knight counts the squares its own pieces stand on",
        FAST,
        """                    if target == EMPTY or (target >> COLOUR_SHIFT) != colour:
                        count += 1
""",
        """                    count += 1
""",
    ),
    Mutation(
        "the compiled evaluation never calls the term",
        FAST,
        """    if ev.misc[E_MOBILITY_ON] != 0:
        mobile = _mobility(pos)
        mg += ev.weights[W_MOBILITY_MG] * mobile
        eg += ev.weights[W_MOBILITY_EG] * mobile
""",
        "",
    ),
    Mutation(
        "safe mobility: enemy-pawn-attacked squares excluded",
        EVAL,
        """            count += (board.attacks_mask(lsb.bit_length() - 1) & ~own).bit_count()
""",
        """            pawn_attacks = 0
            for pawn in board.pieces(chess.PAWN, not colour):
                pawn_attacks |= chess.BB_PAWN_ATTACKS[not colour][pawn]
            square = lsb.bit_length() - 1
            count += (board.attacks_mask(square) & ~own & ~pawn_attacks).bit_count()
""",
    ),
    Mutation(
        "Black's count added instead of subtracted",
        EVAL,
        """        total += count if colour == chess.WHITE else -count
""",
        """        total += count
""",
    ),
    Mutation(
        "pawns and kings counted as mobile pieces",
        EVAL,
        """        bb = own & (board.knights | board.bishops | board.rooks | board.queens)
""",
        """        bb = own
""",
    ),
    Mutation(
        "the term is added to the middlegame only",
        EVAL,
        """        mg += STRUCTURE_WEIGHTS["mobility_mg"] * mobile
        eg += STRUCTURE_WEIGHTS["mobility_eg"] * mobile
""",
        """        mg += STRUCTURE_WEIGHTS["mobility_mg"] * mobile
""",
    ),
    Mutation(
        "the MOBILITY_TERM switch is ignored",
        EVAL,
        """    if MOBILITY_TERM:
        mobile = mobility(board)
""",
        """    if MOBILITY_TERM or True:
        mobile = mobility(board)
""",
    ),
)


def failing_tests(repo: Path) -> set[str]:
    """Names of the selected tests that failed, from the JUnit report pytest writes."""
    report = repo / "mutation-report.xml"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_evaluation.py",
            "tests/test_fasteval.py",
            "-k",
            SELECT,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            f"--junit-xml={report}",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    tree = ElementTree.parse(report)
    return {
        (case.get("name") or "").split("[")[0]
        for case in tree.iter("testcase")
        if case.find("failure") is not None or case.find("error") is not None
    }


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mutate-mobility-") as tmp:
        repo = Path(tmp) / "repo"
        shutil.copytree(
            ROOT, repo, symlinks=True, ignore=shutil.ignore_patterns(".git", "__pycache__")
        )

        baseline = failing_tests(repo)
        if baseline:
            print(f"the suite is not green before any mutation: {sorted(baseline)}")
            return 1
        print("baseline green\n")

        caught_by: dict[str, list[str]] = defaultdict(list)
        uncaught: list[str] = []
        for mutation in MUTATIONS:
            target = repo / mutation.path
            original = target.read_text(encoding="utf-8")
            if original.count(mutation.old) != 1:
                print(f"anchor no longer matches exactly once: {mutation.what}")
                return 1
            target.write_text(original.replace(mutation.old, mutation.new), encoding="utf-8")
            try:
                failed = failing_tests(repo)
            finally:
                target.write_text(original, encoding="utf-8")
            for name in failed:
                caught_by[name].append(mutation.what)
            if not failed:
                uncaught.append(mutation.what)
            print(f"{mutation.what}\n    caught by {len(failed)} test(s)")

    print("\n--- by test: how many mutations each one catches ---")
    dead = []
    for name in sorted(set(caught_by) | {t for t in _selected_test_names()}):
        hits = len(caught_by.get(name, []))
        print(f"{hits:3d}  {name}{'   <-- NEVER FAILED' if not hits else ''}")
        if not hits:
            dead.append(name)

    print(f"\nmutations not caught by anything: {uncaught or 'none'}")
    print(f"tests that never failed:          {dead or 'none'}")
    return 1 if uncaught or dead else 0


def _selected_test_names() -> set[str]:
    """The test names this tool judges, so one that never fails is named rather than absent."""
    names = set()
    for path in ("tests/test_evaluation.py", "tests/test_fasteval.py"):
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
            if not line.startswith("def test_"):
                continue
            # The function name only. Matching the whole line caught `test_bishop_pair_bonus`,
            # which takes the `mobility_off` fixture and so has "mobility" in its parameter list
            # but is not selected by `-k` and is not a mobility test; it was then reported as a
            # test that never fails, which is the exact false alarm this tool exists to avoid.
            name = line[len("def ") :].split("(")[0]
            if "mobility" in name:
                names.add(name)
    return names


if __name__ == "__main__":
    sys.exit(main())
