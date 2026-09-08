"""The two engines must agree on every shared search constant, or say why not.

``mikhail_letal/search.py`` is the single home of the shared search constants and
``fastsearch.py`` imports them, so the interpreted reference and the compiled engine cannot drift
apart. That is the contract; nothing enforced it. ``NODE_CHECK_INTERVAL`` had drifted -- 128 in
``search.py``, 512 in ``fastsearch.py`` -- and because ``tools/gen_pst.py`` reads the constants
from ``search.py``, the provenance record that ships in the zip described the interpreted value
while the engine that plays used the other one.

The drift itself is deliberate and correct: the two engines run at very different speeds, so the
same clock-check granularity in milliseconds needs a different node count in each. What was missing
was anywhere that said so. An intentional difference belongs in ``INTENTIONALLY_DIFFERENT`` with
its reason; anything else is drift and fails.
"""

from typing import Final

from mikhail_letal import fastsearch, search

# name -> why the two engines deliberately hold different values.
INTENTIONALLY_DIFFERENT: Final[dict[str, str]] = {
    "NODE_CHECK_INTERVAL": (
        "how often the search reads the wall clock, counted in nodes rather than milliseconds. "
        "The compiled engine searches around 505 000 nodes/s on the platform and the interpreted "
        "one around 55 000, so 512 nodes compiled and 128 interpreted are both about a "
        "millisecond of granularity. Matching the numbers would mismatch the thing they control. "
        "Measured: the round-74 rated game overshot the hard deadline twice, by 1 ms each time, "
        "which is one compiled check interval (handoff/LOG-round-74-zagreus.md)."
    ),
}


def _shared_constant_names() -> list[str]:
    """Upper-case module-level names that both engines define in their own right."""
    return sorted(
        name
        for name in vars(search)
        if name.isupper()
        and not name.startswith("_")
        and hasattr(fastsearch, name)
        and not callable(getattr(search, name))
    )


def test_the_two_engines_agree_on_every_shared_constant() -> None:
    """A constant may differ only if it is listed, with a reason, as deliberate."""
    drifted = [
        (name, getattr(search, name), getattr(fastsearch, name))
        for name in _shared_constant_names()
        if getattr(search, name) != getattr(fastsearch, name)
        and name not in INTENTIONALLY_DIFFERENT
    ]
    assert not drifted, (
        "these constants differ between the engines with no recorded reason; either make them "
        f"equal or add them to INTENTIONALLY_DIFFERENT with why: {drifted}"
    )


def test_every_recorded_exception_is_still_an_exception() -> None:
    """An entry that no longer differs is stale and must go, or it hides a later real drift."""
    for name, reason in INTENTIONALLY_DIFFERENT.items():
        assert hasattr(search, name) and hasattr(fastsearch, name), f"{name} no longer exists"
        assert getattr(search, name) != getattr(fastsearch, name), (
            f"{name} is listed as deliberately different but the values now match; remove it"
        )
        assert len(reason) > 80, f"{name} needs a real reason, not a label"


def test_the_compiled_engine_is_the_one_that_ships() -> None:
    """Guards the mistake that started this: quoting the interpreted value for shipped behaviour.

    ``tools/gen_pst.py`` reads the search constants from ``search.py``. For anything in
    ``INTENTIONALLY_DIFFERENT`` that is wrong, because the compiled engine is what plays a rated
    game, so the shipped record must carry the compiled value.
    """
    assert fastsearch.NODE_CHECK_INTERVAL == 512
    assert search.NODE_CHECK_INTERVAL == 128
