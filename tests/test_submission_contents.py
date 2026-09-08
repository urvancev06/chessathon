"""What goes in the zip, pinned. The upload is the deliverable and it is built from the filesystem.

``harness/package.py`` collects every root-level ``*.py`` and then follows their imports, so the
submission's contents are decided by what happens to be lying in the working tree at the moment
``make zip`` runs -- not by any list a person maintains. That is convenient and it is exactly how
an accident ships. Three real ways it goes wrong, all of which these tests would catch:

* **A stray script at the root.** One appeared this evening: a ``fixedtime2.py`` someone left while
  timing something, running at 102 % CPU and sitting one ``make zip`` away from the upload.
* **An accidental import from ``tools/``.** CLAUDE.md warns about it because the packager follows
  imports: one ``from tools.something import ...`` in a shipped module and a whole directory of
  research code, Stockfish drivers included, lands in the zip a judge reads.
* **A file named after a module we import.** The agent's zip is first on ``sys.path`` on the
  platform, so a ``chess.py`` or ``types.py`` at the root shadows the real one, and the failure
  looks like anything except its cause.

These tests read the packager's own ``members()``, so they describe the zip that would actually be
built rather than a parallel idea of it. When the shipped file set legitimately changes, the
expected set below changes with it in the same commit -- that is the point: the list is a decision,
made deliberately, not a description of the tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

from harness.package import DEFAULT_INCLUDES, MAX_UNZIPPED_BYTES, members

ROOT = Path(__file__).resolve().parent.parent

# Exactly what ships, and nothing else. Fourteen files: the entry point, the engine package, and
# the two weight files. Adding to this set is a deliberate act; discovering something new in it is
# the bug these tests exist to catch.
EXPECTED = {
    "agent.py",
    "mikhail_letal/__init__.py",
    "mikhail_letal/evaluation.py",
    "mikhail_letal/fallback.py",
    "mikhail_letal/fastboard.py",
    "mikhail_letal/fasteval.py",
    "mikhail_letal/fastsearch.py",
    "mikhail_letal/gamestate.py",
    "mikhail_letal/search.py",
    "mikhail_letal/searchboard.py",
    "mikhail_letal/timing.py",
    "mikhail_letal/warmup.py",
    "weights/PROVENANCE.json",
    "weights/pst.json",
}

# Directories that exist to support the engine and must never reach the platform. `tools/` matters
# most: it drives Stockfish, and shipping an engine's driver alongside our own invites exactly the
# question the rules ask about whose engine this is.
NEVER_SHIPPED = ("tools/", "tests/", "docs/", "versions/", "data/", "harness/", "handoff/", "app/")


def packaged() -> set[str]:
    """The archive names ``make zip`` would write, from the packager itself."""
    return {name for _, name in members(ROOT, DEFAULT_INCLUDES)}


def test_the_zip_contains_exactly_the_expected_files() -> None:
    found = packaged()
    unexpected = found - EXPECTED
    missing = EXPECTED - found
    assert not unexpected, (
        f"the zip would carry files nobody decided to ship: {sorted(unexpected)}. "
        "If that is deliberate, add them to EXPECTED in the same commit."
    )
    assert not missing, f"the zip is missing files it needs: {sorted(missing)}"


def test_no_stray_python_file_at_the_repo_root() -> None:
    """The packager takes every root-level ``*.py``, so a scratch script at the root ships."""
    at_root = {path.name for path in ROOT.glob("*.py")}
    assert at_root == {"agent.py"}, (
        f"unexpected Python files at the repo root: {sorted(at_root - {'agent.py'})}. "
        "harness/package.py collects every one of them into the submission."
    )


def test_nothing_ships_from_a_support_directory() -> None:
    for name in packaged():
        for forbidden in NEVER_SHIPPED:
            assert not name.startswith(forbidden), (
                f"{name} would ship from {forbidden}, which never goes to the platform. "
                "The usual cause is an import of it from a shipped module."
            )


def test_no_shipped_module_shadows_one_we_import() -> None:
    """The zip is first on ``sys.path`` there, so a root module shadows the real one silently."""
    # The stack the platform preinstalls, plus the standard library.
    reserved = {"chess", "numpy", "numba", "torch", "onnxruntime"} | set(sys.stdlib_module_names)
    shipped_top_level = {
        name.split("/")[0].removesuffix(".py") for name in packaged() if name.endswith(".py")
    }
    clashes = shipped_top_level & reserved
    assert not clashes, (
        f"these shipped modules shadow something we import: {sorted(clashes)}. "
        "On the platform the zip is first on sys.path, so the real module never loads."
    )


def test_no_native_binaries() -> None:
    """The contract rejects native binaries; weights and Python source only."""
    binaries = [
        name for name in packaged() if Path(name).suffix in {".so", ".pyd", ".dll", ".dylib", ".a"}
    ]
    assert not binaries, f"native binaries are rejected at upload: {binaries}"


def test_unzipped_size_is_inside_the_cap() -> None:
    unzipped = sum((ROOT / name).stat().st_size for name in packaged())
    assert unzipped <= MAX_UNZIPPED_BYTES, (
        f"{unzipped:,} bytes unzipped, over the {MAX_UNZIPPED_BYTES:,} limit"
    )
