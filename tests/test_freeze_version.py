"""The freeze must produce exactly what the zip would contain, and refuse the two unsafe cases.

A frozen version is the opponent every later promotion match is measured against, so the failure
that matters is a silent one: a freeze that is missing a module, or that quietly replaces a
version other results already cite. Both are asserted here rather than trusted.
"""

from pathlib import Path

import pytest

from harness.package import DEFAULT_INCLUDES, members
from tools import freeze_version

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def versions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the freeze at a temporary directory, never the real ``versions/``."""
    monkeypatch.setattr(freeze_version, "VERSIONS", tmp_path)
    return tmp_path


def test_freeze_writes_exactly_what_the_zip_would_contain(versions: Path) -> None:
    """The file list comes from `harness.package`, so the two cannot drift apart."""
    destination = freeze_version.freeze("v-test")
    expected = {name for _, name in members(ROOT, DEFAULT_INCLUDES)}
    written = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert written == expected
    assert "agent.py" in written, "the platform imports agent.py by name"
    assert any(name.startswith("weights/") for name in written)


def test_frozen_files_are_byte_identical_to_the_source(versions: Path) -> None:
    destination = freeze_version.freeze("v-test")
    for source, name in members(ROOT, DEFAULT_INCLUDES):
        assert (destination / name).read_bytes() == source.read_bytes(), name


def test_an_existing_version_is_never_replaced_by_accident(versions: Path) -> None:
    """Overwriting a frozen version would invalidate every result that cites it."""
    freeze_version.freeze("v-test")
    with pytest.raises(SystemExit):
        freeze_version.freeze("v-test")
    # ... but it is allowed when the caller says so explicitly.
    assert freeze_version.freeze("v-test", force=True).is_dir()


def test_force_leaves_no_file_behind_from_the_previous_freeze(versions: Path) -> None:
    """A stale module left in place would ship in a match as part of the wrong build."""
    destination = freeze_version.freeze("v-test")
    stale = destination / "mikhail_letal" / "leftover.py"
    stale.write_text("# not part of any build\n", encoding="utf-8")
    freeze_version.freeze("v-test", force=True)
    assert not stale.exists()


def test_dirty_shipping_paths_reports_git_porcelain_lines() -> None:
    """Whatever it returns must be `git status --porcelain` lines, which the caller prints."""
    for line in freeze_version.dirty_shipping_paths():
        assert line.strip()
        assert len(line) > 3  # a status code, a space and a path


def test_upload_numbers_agree_with_the_files_on_disk() -> None:
    files, zipped, unzipped, digest = freeze_version.upload_numbers(ROOT)
    expected = list(members(ROOT, DEFAULT_INCLUDES))
    assert files == len(expected)
    assert unzipped == sum(source.stat().st_size for source, _ in expected)
    assert 0 < zipped < unzipped, "the zip is compressed, so it is smaller than its contents"
    assert len(digest) == 64 and set(digest) <= set("0123456789abcdef")
