"""ferz — the engine package for this AI Chessathon entry.

A ferz is the medieval precursor of the chess queen. The name is distinctive on purpose: the zip
is first on ``sys.path``, so a package named after any stdlib or stack module would shadow it.

Stage 0 builds on python-chess for move generation and rules; the search, evaluation, time
management and game-state tracking are our own. See ``docs/DESIGN.md`` for the module contract.
"""

__version__ = "0.1.0"
