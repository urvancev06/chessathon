"""Mikhail LeTal — the engine package for this AI Chessathon entry.

The name is a pun on Mikhail Tal, the attacking world champion. The Python package is
``mikhail_letal`` because package names must be lowercase identifiers. It is distinctive on
purpose: the zip is first on ``sys.path``, so a package named after any stdlib or stack module
would shadow it.

Stage 0 builds on python-chess for move generation and rules; the search, evaluation, time
management and game-state tracking are our own. See ``docs/DESIGN.md`` for the module contract.
"""

import os

ENGINE_NAME = "Mikhail LeTal"
__version__ = "0.2.0"


def feature_flag(name: str, default: bool) -> bool:
    """Read a feature switch from the environment, falling back to ``default``.

    Every strength feature of the engine sits behind a module-level boolean so that a regression
    can be bisected feature by feature. The booleans default to the shipped setting; the arena
    tool's ``--env LETAL_...=0`` turns one off for every agent process of a run. The shipped
    engine never sets these variables, so on the platform every default applies.
    """
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "off", "no", "")
