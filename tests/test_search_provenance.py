"""The shipped provenance record must describe the search constants that actually ship.

`weights/PROVENANCE.json` is the only provenance artefact inside the submission zip --
`docs/PROVENANCE.md` does not ship -- and the brief asks for the search margins and the table
size by name. These are also the constants a judge is most likely to suspect were copied from
another engine, so a record that has quietly drifted from the code is worse than none.

`tools/gen_pst.py:search_rows` reads every value from the module that uses it, and this test
asserts the file on disk matches. Change a constant without regenerating and this fails.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROVENANCE = ROOT / "weights" / "PROVENANCE.json"


def _shipped() -> dict[str, dict[str, str]]:
    records = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    return {row["parameter"]: row for row in records}


def test_the_shipped_record_matches_the_search_constants() -> None:
    from tools.gen_pst import search_rows  # a tool: imported here, never shipped

    shipped = _shipped()
    for row in search_rows():
        name = row["parameter"]
        assert name in shipped, f"{name} is missing from weights/PROVENANCE.json"
        assert shipped[name]["value_or_shape"] == row["value_or_shape"], (
            f"{name} ships as {shipped[name]['value_or_shape']!r} but the code now says "
            f"{row['value_or_shape']!r}; re-run tools/gen_pst.py"
        )


def test_every_shipped_record_carries_the_six_required_fields() -> None:
    """Brief §10 fixes the columns: parameter, value, what produced it, the data behind it, a run
    id and a note. A row missing one cannot answer the question the record exists to answer."""
    required = {"parameter", "value_or_shape", "produced_by", "data", "run_id", "note"}
    for row in json.loads(PROVENANCE.read_text(encoding="utf-8")):
        assert required <= set(row), f"{row.get('parameter')} is missing {required - set(row)}"
        assert all(str(row[field]).strip() for field in required), f"{row['parameter']} has a blank"


def test_the_search_half_is_actually_present() -> None:
    """Guards the failure this file was written for: the record covered the evaluation tables
    alone, so nothing in the zip documented a single search or time-management constant."""
    names = set(_shipped())
    assert any(n.startswith("search.") for n in names), "no search constants in the shipped record"
    assert any(n.startswith("timing.") for n in names), "no timing constants in the shipped record"
    assert "search.transposition_table" in names, "the brief names the table size explicitly"
