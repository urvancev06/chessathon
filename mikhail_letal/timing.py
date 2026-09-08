"""Time budget: how many milliseconds to spend on the move we are about to play.

The clock is 120 s plus 0.5 s per move, on wall time, and a flag fall loses the game. So the
budget has two jobs: spend enough to search well, and never plan to run the clock down to a
point where one slow move loses. Every constant lives in ``TimeParams`` so that calibration
against the platform's own timing (docs/CALIBRATION.md) changes one dataclass and nothing else.

The formula, from ``docs/DESIGN.md``::

    moves_to_go = clamp(moves_to_go_max - own_moves_so_far // 2, moves_to_go_min, moves_to_go_max)
    moves_to_go = min(moves_to_go, moves left before the 600-ply cap and, in a mop-up, before
                      the fifty-move draw)
    soft  = (time_left_ms - overhead_ms) / moves_to_go + increment_fraction * increment_ms
    hard  = min(hard_multiplier * soft, hard_fraction * time_left_ms)
    floor = max(floor_ms, floor_fraction * time_left_ms)
    hard  = min(hard, time_left_ms - overhead_ms - floor)  # never plan below the floor
    soft  = min(soft, hard)
    both clamped to >= 0

``soft`` is the target: iterative deepening does not start a new depth once a fraction of it has
elapsed. ``hard`` is the abort point: the search stops mid-iteration when it is reached.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeParams:
    """Every tunable number of the time manager, in one frozen record.

    ``frozen=True`` makes the defaults immutable, so a calibrated variant is a new instance
    (``dataclasses.replace``) rather than a hidden mutation of the shared default.
    """

    increment_ms: int = 500  # the platform adds this after every move we play
    overhead_ms: int = 150  # process wake-up, JSON, Board(fen): calibrated (docs/CALIBRATION.md)
    moves_to_go_max: int = 40  # at the start, assume the game has this many of our moves left
    moves_to_go_min: int = 12  # late in the game, never assume fewer than this many remain
    increment_fraction: float = 0.8  # spend most of the increment every move, keep a little
    hard_multiplier: float = 3.0  # an iteration may overrun the soft target by this factor
    hard_fraction: float = 0.25  # but never spend more than this share of the clock on one move
    floor_ms: int = 1500  # the reserve we never plan to dip into, in ms ...
    floor_fraction: float = 0.05  # ... or this share of the clock, whichever is larger
    # Below this the agent skips the engine and plays the fallback. It equals overhead_ms +
    # floor_ms: under that the budget formula has no time left to plan with (hard would be 0).
    panic_ms: int = 1650
    next_iteration_fraction: float = 0.45  # start another depth only before this share of soft
    # If the import's numba warm-up ran out of its own budget, the first real move finishes the
    # compiling before it searches, and may spend this share of the clock doing it. numba cannot
    # be interrupted, so a function compiled inside the search blows straight through the hard
    # deadline; doing it here instead keeps every search inside its budget and pays the cost once,
    # on the fullest clock of the game. Normally zero moves are affected, because the warm-up
    # finishes at import (mikhail_letal/warmup.py).
    cold_finish_fraction: float = 0.25


@dataclass(frozen=True)
class Budget:
    """The two deadlines for one move, in milliseconds from the start of ``get_move``."""

    soft_ms: float
    hard_ms: float


DEFAULT_PARAMS = TimeParams()


def budget(
    time_left_ms: int,
    own_moves_so_far: int,
    params: TimeParams = DEFAULT_PARAMS,
    plies_to_cap: int | None = None,
    fifty_move_room: int | None = None,
) -> Budget:
    """Return the soft and hard budgets for the next move.

    ``plies_to_cap`` is how many plies remain before the referee's 600-ply draw and
    ``fifty_move_room`` how many before the fifty-move draw (100 minus the halfmove clock). Either
    one, when given, caps the number of moves the clock is shared over, so a win that has to be
    forced before a rule draw gets the time it needs. The caller passes ``fifty_move_room`` only
    when the game is a mop-up (no pawns, one side a bare king): elsewhere a capture or pawn move
    resets the clock in the normal course of play and the deadline is not real.

    Guarantees, for any inputs (including negative or tiny clocks):

    * ``0 <= soft_ms <= hard_ms``;
    * ``hard_ms <= time_left_ms - overhead_ms - floor`` whenever that quantity is non-negative,
      where ``floor = max(floor_ms, floor_fraction * time_left_ms)``; when it is negative there
      is no time to plan with, and both budgets are ``0``.
    """
    # The fewer moves we expect to still have to play, the more of the clock each one may take.
    # Halving the count of moves played keeps the estimate from collapsing in a long game: after
    # 56 of our moves the divisor has reached its minimum and stays there.
    moves_to_go = params.moves_to_go_max - own_moves_so_far // 2
    moves_to_go = max(params.moves_to_go_min, min(params.moves_to_go_max, moves_to_go))

    # Urgency near a rule draw: with n plies left, we get at most (n + 1) // 2 more moves, and
    # the clock is worth nothing after the draw. Both engines drew won queen endings at the
    # normal pace before this clamp existed (docs/DECISIONS.md, 2026-09-07).
    if plies_to_cap is not None:
        moves_to_go = min(moves_to_go, max(1, (plies_to_cap + 1) // 2))
    if fifty_move_room is not None:
        moves_to_go = min(moves_to_go, max(1, (fifty_move_room + 1) // 2))

    # Share the clock (less the fixed per-move overhead) evenly over the remaining moves, and add
    # most of the increment, because it arrives after the move whatever we spend now.
    soft = (time_left_ms - params.overhead_ms) / moves_to_go
    soft += params.increment_fraction * params.increment_ms

    # The hard limit lets a promising iteration finish, but caps any single move at a fixed
    # share of the clock so one long think cannot flag us.
    hard = min(params.hard_multiplier * soft, params.hard_fraction * time_left_ms)

    # Keep a reserve: after this move, at least ``floor`` must remain (plus the overhead we know
    # this move will cost outside the search).
    floor = max(float(params.floor_ms), params.floor_fraction * time_left_ms)
    hard = min(hard, time_left_ms - params.overhead_ms - floor)

    # The target can never exceed the abort point, and neither can be negative.
    soft = min(soft, hard)
    return Budget(soft_ms=max(0.0, soft), hard_ms=max(0.0, hard))
