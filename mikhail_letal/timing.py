"""Time budget: how many milliseconds to spend on the move we are about to play.

The clock is 120 s plus 0.5 s per move, on wall time, and a flag fall loses the game. So the
budget has two jobs: spend enough to search well, and never plan to run the clock down to a
point where one slow move loses. Every constant lives in ``TimeParams`` so that calibration
against the platform's own timing (docs/CALIBRATION.md) changes one dataclass and nothing else.

The formula, from ``docs/DESIGN.md``::

    moves_to_go = clamp(moves_to_go_max - moves_to_go_decay * own_moves_so_far,
                        moves_to_go_min, moves_to_go_max)
    moves_to_go = min(moves_to_go, moves left before the 600-ply cap and, in a mop-up, before
                      the fifty-move draw)
    soft  = (time_left_ms - overhead_ms) / moves_to_go + increment_fraction * increment_ms
    hard  = min(hard_multiplier * soft, hard_fraction * time_left_ms)
    floor = max(floor_ms, floor_fraction * time_left_ms)
    hard  = min(hard, time_left_ms - overhead_ms - floor)  # never plan below the floor
    soft  = min(soft, hard)
    both clamped to >= 0

``soft`` is the target and ``hard`` is the abort point: the search stops mid-iteration when the
hard deadline is reached. Whether to *start* another iteration is decided by
``should_start_next_depth`` below, from the time the completed iterations took, rather than by a
fixed fraction of ``soft``.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class TimeParams:
    """Every tunable number of the time manager, in one frozen record.

    ``frozen=True`` makes the defaults immutable, so a calibrated variant is a new instance
    (``dataclasses.replace``) rather than a hidden mutation of the shared default.
    """

    increment_ms: int = 500  # the platform adds this after every move we play
    # Process wake-up, JSON, Board(fen). Measured on the platform over 25 rated moves: 0-2 ms,
    # mean 1.1 (docs/CALIBRATION.md, 2026-09-08). CALIBRATION's own rule is max + 50, so 50 ms is
    # twenty-five times the worst measurement and still costs at most 2 ms of budget a move.
    overhead_ms: int = 50
    # How many of our moves the clock is shared over: `max - decay * moves played`, floored at
    # `min`. All three come from the ladder games collected on 2026-09-08 (1697 of them, and
    # counting; `tools/sim_time.py` re-reads whatever is on disk), which measure
    # how many of our moves are actually left at each point: the median is 67 at move 0, falling
    # by about one per move to 25 at move 50 and staying there. The line is that curve scaled by
    # 0.7, because a move spends 0.7 of its soft budget (docs/CALIBRATION.md), so the realised
    # spending is the even split of the clock over the moves that are really left.
    moves_to_go_max: int = 50
    # The floor is 20 rather than the 17 the median would give, because the deep tail is where
    # our two longest rated games ended (6.0 s and 4.7 s, one of them a fifty-move draw) and the
    # remaining-moves distribution there is skewed: median 27 but mean 40. Two criteria are met
    # at 20 and not at 16. The soft formula alone balances the increment at
    # `overhead_ms + moves_to_go_min * increment_ms * (1 / usage - increment_fraction)`, which at
    # full spend is 2050 ms, above `panic_ms`, where 16 lands exactly on it; and over the
    # ladder games of at least 90 of our moves the lowest clock is 5.9 s rather than 4.6 s (3.3 s
    # rather than 2.6 s if a move spends 0.85 of its budget instead of the measured 0.70). Every
    # one of these constants also ships in `weights/PROVENANCE.json` (tools/gen_pst.py).
    moves_to_go_min: int = 20
    moves_to_go_decay: float = 0.7
    increment_fraction: float = 0.8  # spend most of the increment every move, keep a little
    hard_multiplier: float = 3.0  # an iteration may overrun the soft target by this factor
    hard_fraction: float = 0.25  # but never spend more than this share of the clock on one move
    floor_ms: int = 1500  # the reserve we never plan to dip into, in ms ...
    floor_fraction: float = 0.05  # ... or this share of the clock, whichever is larger
    # Below this the agent skips the engine and plays the fallback: at that clock the budget
    # formula has almost nothing left to plan with (hard reaches 0 at overhead_ms + floor_ms =
    # 1550). Deliberately left at the value the platform measured under v1.0, so lowering
    # overhead_ms cannot change behaviour anywhere near the flag.
    panic_ms: int = 1650
    # The fallback rule for starting another depth, used only when the last completed iteration
    # was too short to predict from (see should_start_next_depth). The prediction below replaced
    # it as the normal rule: at 0.45 the engine either stopped with a third of its budget unspent
    # or started a depth that ran to the ceiling, with nothing in between (docs/CALIBRATION.md).
    next_iteration_fraction: float = 0.45
    # Cost of depth d+1 as a multiple of depth d. The default holds before two iterations have
    # been timed; the measured ratio is clamped to the range, because one mis-timed iteration
    # must not let the search either stop early or start a depth it cannot finish. The platform's
    # own per-move logs give 4-5x per depth (docs/CALIBRATION.md, 2026-09-08).
    iteration_ratio_default: float = 4.5
    iteration_ratio_min: float = 2.0
    iteration_ratio_max: float = 8.0
    ratio_measurable_s: float = 0.001  # shorter than this, an iteration time is start-up noise
    # How far past the soft budget the next iteration may be predicted to end. Iteration costs
    # grow geometrically, so a rule that insists the next depth finish before the soft budget
    # stops a factor of `ratio` short of it and spends a third of the clock: measured over six
    # middlegame positions at two clocks, 0.70 of the budget at 1.0 against 0.80 at 1.35, for
    # 0.34 more depth, while 1.75 reached the hard ceiling (docs/CALIBRATION.md). At 1.35 the worst
    # case an iteration can be *started* for is 2.03 soft (with the unstable stretch), against a
    # hard ceiling of 3.0 soft, so the abort path is no likelier to be needed than before.
    iteration_target_factor: float = 1.35
    # A root move that changed at the last completed depth is worth this much more than the soft
    # target -- never more than the hard ceiling, which is unchanged.
    unstable_factor: float = 1.5
    # ... and a move that has been the best for `easy_stable_depths` iterations with the score not
    # falling by more than `easy_score_drop_cp` banks part of the budget for later moves. Measured
    # over the same six: 6 iterations and 0.7 cost 0.17 of a ply and saved 16 % of the time,
    # where the first attempt (4 and 0.5) fired on nearly every move and spent 0.41 of the budget,
    # less than the fixed rule it replaced.
    easy_factor: float = 0.7
    easy_stable_depths: int = 6
    easy_score_drop_cp: int = 30


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
    # The line is fitted to how many of our moves are really left at each point of 1697 ladder
    # games, scaled by the share of its budget a move spends (see `moves_to_go_max` above): it
    # reaches the minimum after 43 of our moves, which is where the measured curve flattens too.
    moves_to_go = params.moves_to_go_max - int(own_moves_so_far * params.moves_to_go_decay)
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


def should_start_next_depth(
    elapsed_s: float,
    iteration_times_s: Sequence[float],
    soft_s: float,
    hard_s: float,
    stable_depths: int,
    score_drop_cp: int,
    params: TimeParams = DEFAULT_PARAMS,
) -> bool:
    """Whether iterative deepening should start one more depth.

    Every argument is measured from the start of the search: ``elapsed_s`` is how long it has run,
    ``iteration_times_s`` how long each completed depth took in order, and ``soft_s`` / ``hard_s``
    are the two budgets as windows in seconds. ``stable_depths`` counts the completed iterations
    whose best move equalled the previous one's (so ``0`` means the root move just changed), and
    ``score_drop_cp`` is how far the score fell at the last iteration (negative when it rose).

    The rule predicts rather than guesses. Each depth costs a few times the previous, and the
    factor is a property of the position, so it is measured from the last two iterations and the
    next one is started only if it is expected to finish inside the target. A fixed fraction of the
    target cannot do that: on the platform it made every move either stop at a third of its budget
    or run to the ceiling (docs/CALIBRATION.md, 2026-09-08).

    The target is the soft budget, stretched by ``unstable_factor`` when the best move just changed
    and cut by ``easy_factor`` when it has been stable and the score is not falling.

    Guarantee: a ``True`` return implies ``elapsed_s < hard_s``. The target is clamped to the hard
    window, so nothing here can plan past the abort point, and the abort point is what protects the
    clock.
    """
    target = soft_s * params.iteration_target_factor
    completed = len(iteration_times_s)
    if completed >= 2 and stable_depths == 0:
        target *= params.unstable_factor  # the root is unsettled: worth more of the clock
    elif stable_depths >= params.easy_stable_depths and score_drop_cp <= params.easy_score_drop_cp:
        target *= params.easy_factor  # an easy move: bank the rest for a position that needs it
    target = min(target, hard_s)  # a stretch never reaches past the abort point
    if target <= 0.0 or elapsed_s >= target:
        return False

    last = iteration_times_s[-1] if completed else 0.0
    if last < params.ratio_measurable_s:
        # No iteration long enough to predict from (a depth that took microseconds says nothing
        # about the next one): fall back to the rule that preceded this one, which is a fraction
        # of the *soft budget itself*, not of the stretched target -- with nothing measured there
        # is no reason to spend more than the plain budget allows.
        return elapsed_s < params.next_iteration_fraction * min(soft_s, hard_s)

    previous = iteration_times_s[-2] if completed >= 2 else 0.0
    if previous >= params.ratio_measurable_s:
        measured = last / previous
        ratio = min(max(measured, params.iteration_ratio_min), params.iteration_ratio_max)
    else:
        ratio = params.iteration_ratio_default
    return elapsed_s + ratio * last <= target
