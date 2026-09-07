"""Mikhail LeTal — the engine package for this AI Chessathon entry.

The name is a pun on Mikhail Tal, the attacking world champion. The Python package is
``mikhail_letal`` because package names must be lowercase identifiers. It is distinctive on
purpose: the zip is first on ``sys.path``, so a package named after any stdlib or stack module
would shadow it.

Stage 0 builds on python-chess for move generation and rules; the search, evaluation, time
management and game-state tracking are our own. See ``docs/DESIGN.md`` for the module contract.
"""

ENGINE_NAME = "Mikhail LeTal"
__version__ = "0.2.0"
