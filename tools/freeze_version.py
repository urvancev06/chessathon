"""Freeze the current shipping files under ``versions/<name>/`` and print the upload numbers.

A version is frozen so that the *next* one has something to be measured against: the promotion
rule needs the previous build kept in ``versions/`` as the opponent. Doing that by hand is a
copy of fourteen files that must match the zip exactly, at a moment (the morning of an upload)
when there is time pressure and no second chance -- so it is a script.

Two things it refuses to do, because both have nearly happened:

* **Freeze a dirty tree.** ``harness.package`` zips the *working tree*, not the commit that is
  checked out, so uncommitted work goes into the zip and into the freeze. A version frozen from a
  dirty tree is not the version its tag names.
* **Guess the file list.** The members come from ``harness.package.members``, the same function
  that builds the zip, so a module that would ship cannot be missing from the freeze and a module
  that would not ship cannot appear in it.

It ends by building a throwaway zip and printing the file count, the two sizes and the sha256 --
what ``docs/SUBMISSION_GUIDE.md`` records for each version. Only the first three reproduce: the zip
stores each file's modification time, so rebuilding the same commit gives identical contents and a
different hash. The hash identifies an upload; ``diff -r`` against the frozen version is what
verifies one.
"""

import argparse
import filecmp
import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from harness.package import DEFAULT_INCLUDES, build, members

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = ROOT / "versions"
# The paths the platform runs. A change under any of them changes the engine, so a freeze taken
# while one of them is modified would not be reproducible from the tag.
SHIPPING = ("agent.py", "mikhail_letal", "weights")


def dirty_shipping_paths() -> list[str]:
    """Shipping paths with uncommitted changes, as ``git status --porcelain`` reports them."""
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", *SHIPPING],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def freeze(name: str, *, force: bool = False) -> Path:
    """Copy every file that would be zipped into ``versions/<name>/`` and verify the copy.

    Returns the directory written. Raises ``SystemExit`` rather than overwriting an existing
    version, because a frozen version is the opponent of every later measurement: silently
    changing one would invalidate the results that already cite it.
    """
    destination = VERSIONS / name
    if destination.exists() and not force:
        raise SystemExit(
            f"{destination} already exists; pass --force only if you mean to replace it"
        )

    entries = list(members(ROOT, DEFAULT_INCLUDES))
    if destination.exists():
        shutil.rmtree(destination)
    for source, archive_name in entries:
        target = destination / archive_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    # Verify rather than trust the copy: a truncated or partially written file here would be
    # discovered as a mysteriously weak opponent in a match, weeks later.
    for source, archive_name in entries:
        target = destination / archive_name
        if not filecmp.cmp(source, target, shallow=False):
            raise SystemExit(f"copy of {archive_name} does not match the source")
    return destination


def upload_numbers(root: Path) -> tuple[int, int, int, str]:
    """Build a throwaway zip of ``root`` and return (files, zipped, unzipped, sha256)."""
    with tempfile.TemporaryDirectory() as directory:
        archive = Path(directory) / "submission.zip"
        written = build(root, archive, DEFAULT_INCLUDES)
        unzipped = sum((root / name).stat().st_size for name in written)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        return len(written), archive.stat().st_size, unzipped, digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name", help="version directory to write, e.g. v1.1")
    parser.add_argument("--force", action="store_true", help="replace an existing version")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="freeze even though shipping files have uncommitted changes (almost never right)",
    )
    arguments = parser.parse_args()

    dirty = dirty_shipping_paths()
    if dirty and not arguments.allow_dirty:
        print("Refusing to freeze: these shipping paths have uncommitted changes.")
        for line in dirty:
            print(f"  {line}")
        print("\nCommit them first. `harness.package` zips the working tree, not the checked-out")
        print("commit, so a version frozen now would not be reproducible from its tag.")
        raise SystemExit(1)

    destination = freeze(arguments.name, force=arguments.force)
    files, zipped, unzipped, digest = upload_numbers(ROOT)
    relative = destination.relative_to(ROOT)
    print(f"froze {files} files into {relative}\n")
    print("For docs/SUBMISSION_GUIDE.md section 0:")
    print(f"  files:    {files}")
    print(f"  zipped:   {zipped:,} bytes")
    print(f"  unzipped: {unzipped:,} bytes")
    print(f"  sha256:   {digest}   (of this build only -- see below)")
    print("\nThe count and the two sizes are decided by the contents, so they reproduce from the")
    print("tag. The sha256 does not: the zip stores each file's modification time, so an identical")
    print("rebuild has identical contents and a different hash. Record it to identify the upload,")
    print("never to check a rebuild against.")
    print("\nNext: tag the commit, run `python -m harness.package`, and check that")
    print(f"  unzip -q -d /tmp/zc submission.zip && diff -r /tmp/zc {relative} -x '__pycache__'")
    print("prints nothing. That compares contents, so it is the check that reproduces.")


if __name__ == "__main__":
    main()
