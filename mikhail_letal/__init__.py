"""Mikhail LeTal — the engine package for this AI Chessathon entry.

The name is a pun on Mikhail Tal, the attacking world champion. The Python package is
``mikhail_letal`` because package names must be lowercase identifiers. It is distinctive on
purpose: the zip is first on ``sys.path``, so a package named after any stdlib or stack module
would shadow it.

Stage 0 builds on python-chess for move generation and rules; the search, evaluation, time
management and game-state tracking are our own. See ``docs/DESIGN.md`` for the module contract.
"""

ENGINE_NAME = "Mikhail LeTal"
# Bumped for every frozen version. `agent.py`'s init line is the ONLY in-band evidence of which
# build the platform is running, and v1.0 and v1.1 both shipped reading "1.0.0" -- so a rated game
# could not be attributed to a build from its log, only from upload timing. Found 9 September.
__version__ = "1.2.0-dev"
