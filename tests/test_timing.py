"""Tests for the time budget formula (mikhail_letal/timing.py)."""

import dataclasses
import itertools
import json
from pathlib import Path

import pytest

from mikhail_letal.timing import (
    DEFAULT_PARAMS,
    Budget,
    TimeParams,
    budget,
    should_start_next_depth,
)

# (time_left_ms, own_moves_so_far): the opening move, a middlegame, a late scramble, and two
# clocks so low that no search should be planned at all.
CASES = [
    (120_000, 0),
    (90_000, 8),
    (60_000, 20),
    (30_000, 40),
    (10_000, 45),
    (5_000, 60),
    (2_500, 70),
    (1_600, 80),
    (200, 90),
    (0, 100),
    (-50, 100),
]


def _floor(time_left_ms: int, params: TimeParams) -> float:
    return max(params.floor_ms, params.floor_fraction * time_left_ms)


@pytest.mark.parametrize(("time_left_ms", "own_moves"), CASES)
def test_invariants(time_left_ms: int, own_moves: int) -> None:
    b = budget(time_left_ms, own_moves)
    p = DEFAULT_PARAMS
    assert isinstance(b, Budget)
    assert 0 <= b.soft_ms <= b.hard_ms
    # Never plan to run the clock below the reserve; when even the reserve is gone, plan nothing.
    reserve_room = time_left_ms - p.overhead_ms - _floor(time_left_ms, p)
    assert b.hard_ms <= max(0.0, reserve_room)
    # Never spend more than the fixed share of the clock on one move.
    assert b.hard_ms <= max(0.0, p.hard_fraction * time_left_ms)


def test_hand_computed_opening_move() -> None:
    # moves_to_go = 50; soft = 119950 / 50 + 400 = 2799; hard = 3 * soft = 8397, which is below
    # both 0.25 * 120000 = 30000 and 120000 - 50 - 6000 = 113950.
    b = budget(120_000, 0)
    assert b.soft_ms == pytest.approx(2799.0)
    assert b.hard_ms == pytest.approx(8397.0)


def test_hand_computed_middlegame() -> None:
    # moves_to_go = 50 - int(20 * 0.7) = 36; soft = 59950 / 36 + 400 = 2065.27...; hard =
    # 6195.83, below both 0.25 * 60000 = 15000 and 60000 - 50 - 3000 = 56950.
    b = budget(60_000, 20)
    assert b.soft_ms == pytest.approx(59_950 / 36 + 400)
    assert b.hard_ms == pytest.approx(3 * (59_950 / 36 + 400))


def test_hand_computed_low_clock_is_capped_by_hard_fraction() -> None:
    # moves_to_go clamps to 20; soft = 4950 / 20 + 400 = 647.5; 3 * soft = 1942.5 exceeds
    # 0.25 * 5000 = 1250, so hard = 1250, and the reserve room 5000 - 50 - 1500 = 3450 is not
    # binding. soft stays below hard.
    b = budget(5_000, 60)
    assert b.hard_ms == pytest.approx(1250.0)
    assert b.soft_ms == pytest.approx(4950 / 20 + 400)


def test_no_time_to_plan_gives_zero_budget() -> None:
    # 1550 - 50 - 1500 = 0: at and below overhead + floor the reserve is breached and both
    # budgets are zero. The agent never gets here: it plays the fallback below panic_ms = 1650.
    assert budget(1_550, 80) == Budget(soft_ms=0.0, hard_ms=0.0)
    assert budget(1_500, 80) == Budget(soft_ms=0.0, hard_ms=0.0)
    assert budget(200, 90) == Budget(soft_ms=0.0, hard_ms=0.0)
    # Just above it the plan is a sliver, and still inside the reserve.
    assert budget(1_600, 80) == Budget(soft_ms=50.0, hard_ms=50.0)


def test_moves_to_go_is_clamped() -> None:
    # 50 - int(43 * 0.7) = 20 is the minimum; more moves played must not change anything.
    assert budget(30_000, 43) == budget(30_000, 100)
    # The decay is integer-truncated: moves 0 and 1 give the same divisor.
    assert budget(120_000, 0) == budget(120_000, 1)
    # Fewer moves to go means more time per move.
    assert budget(60_000, 40).soft_ms > budget(60_000, 0).soft_ms


@pytest.mark.parametrize("own_moves", [0, 20, 60])
def test_budgets_grow_with_the_clock(own_moves: int) -> None:
    clocks = list(range(0, 130_000, 250))
    budgets = [budget(t, own_moves) for t in clocks]
    for earlier, later in itertools.pairwise(budgets):
        assert later.soft_ms >= earlier.soft_ms
        assert later.hard_ms >= earlier.hard_ms


def test_params_are_used_and_immutable() -> None:
    generous = dataclasses.replace(DEFAULT_PARAMS, overhead_ms=0, floor_ms=0, floor_fraction=0.0)
    # With no overhead and no reserve: soft = 12000 / 50 + 400 = 640, hard = min(1920, 3000).
    b = budget(12_000, 0, generous)
    assert b.soft_ms == pytest.approx(640.0)
    assert b.hard_ms == pytest.approx(1920.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        generous.overhead_ms = 1  # type: ignore[misc]


def test_default_params_match_design() -> None:
    p = DEFAULT_PARAMS
    assert (p.increment_ms, p.overhead_ms) == (500, 50)
    assert (p.moves_to_go_max, p.moves_to_go_min, p.moves_to_go_decay) == (50, 20, 0.7)
    assert (p.increment_fraction, p.hard_multiplier, p.hard_fraction) == (0.8, 3.0, 0.25)
    assert (p.floor_ms, p.floor_fraction, p.panic_ms) == (1500, 0.05, 1650)
    assert p.next_iteration_fraction == 0.45  # the fallback rule, not the normal one
    assert (p.iteration_ratio_default, p.iteration_ratio_min) == (4.5, 2.0)
    assert (p.iteration_ratio_max, p.ratio_measurable_s) == (8.0, 0.001)
    assert (p.unstable_factor, p.easy_factor) == (1.5, 0.7)
    assert (p.easy_stable_depths, p.easy_score_drop_cp) == (6, 30)
    assert p.iteration_target_factor == 1.35
    # Even the most generous target an iteration can be started for stays inside the ceiling.
    assert p.iteration_target_factor * p.unstable_factor < p.hard_multiplier
    # Once the divisor has reached its minimum the clock settles where spending equals the
    # increment: usage * ((T - overhead) / min + increment_fraction * increment) = increment, so
    # T = overhead + min * increment * (1 / usage - increment_fraction). Even at a full spend of
    # the soft budget that has to stay above the band where the agent gives up on searching and
    # plays the fallback (at 16 it lands exactly on it); at the 0.70 a move was measured to
    # spend, it is 6.4 s.
    for usage in (1.0, 0.70):
        settled = p.overhead_ms + p.moves_to_go_min * p.increment_ms * (
            1 / usage - p.increment_fraction
        )
        assert settled > p.panic_ms


# ----------------------------------------------------------------------------- draw deadlines (C)


def test_ply_cap_room_caps_moves_to_go() -> None:
    # Nine plies before the 600-ply draw: at most five more moves of ours, so the clock is
    # shared over five instead of fifty. (Two won queen endings were drawn at the cap before.)
    urgent = budget(120_000, 0, plies_to_cap=9)
    assert urgent.soft_ms == pytest.approx(119_950 / 5 + 400)
    assert urgent.soft_ms > budget(120_000, 0).soft_ms
    # An even number of plies: 12 plies -> 6 moves.
    assert budget(120_000, 0, plies_to_cap=12).soft_ms == pytest.approx(119_950 / 6 + 400)
    # The hard cap (a quarter of the clock) still binds however urgent the situation is.
    assert budget(120_000, 0, plies_to_cap=2).hard_ms == pytest.approx(30_000)
    # Never below one move, and never above the ordinary estimate.
    assert budget(120_000, 0, plies_to_cap=0) == budget(120_000, 0, plies_to_cap=1)
    # ... and one move's share (120 250 ms) is capped by the hard limit, so soft == hard there.
    assert budget(120_000, 0, plies_to_cap=1).soft_ms == pytest.approx(30_000)
    assert budget(120_000, 0, plies_to_cap=500) == budget(120_000, 0)


def test_fifty_move_room_caps_moves_to_go() -> None:
    # Eighteen plies of fifty-move room (halfmove clock 82): nine moves to force the mate in.
    urgent = budget(120_000, 0, fifty_move_room=18)
    assert urgent.soft_ms == pytest.approx(119_950 / 9 + 400)
    assert budget(120_000, 0, fifty_move_room=100) == budget(120_000, 0)
    # The tighter of the two deadlines wins.
    both = budget(120_000, 0, plies_to_cap=9, fifty_move_room=18)
    assert both == budget(120_000, 0, plies_to_cap=9)


@pytest.mark.parametrize(("time_left_ms", "own_moves"), CASES)
def test_urgent_budgets_keep_the_invariants(time_left_ms: int, own_moves: int) -> None:
    # Urgency raises the soft target but never the caps: the hard limit still respects the
    # fixed share of the clock and the reserve, so a mop-up cannot flag us.
    p = DEFAULT_PARAMS
    for b in (
        budget(time_left_ms, own_moves, plies_to_cap=1),
        budget(time_left_ms, own_moves, fifty_move_room=3),
    ):
        assert 0 <= b.soft_ms <= b.hard_ms
        assert b.hard_ms <= max(0.0, p.hard_fraction * time_left_ms)
        reserve_room = time_left_ms - p.overhead_ms - _floor(time_left_ms, p)
        assert b.hard_ms <= max(0.0, reserve_room)


# ------------------------------------------------------------- starting the next depth (D)

P = DEFAULT_PARAMS
# The target is `iteration_target_factor` times the soft budget (1.35), so a soft budget of S
# admits an iteration predicted to end by 1.35 * S. The tests below say which side of that
# boundary each case falls on, in the arithmetic rather than in a magic number.
FACTOR = P.iteration_target_factor


def soft_for(target_s: float) -> float:
    """The soft budget whose ordinary target is ``target_s``."""
    return target_s / FACTOR


def test_prediction_uses_the_measured_ratio() -> None:
    # Depth 5 took 0.4 s after depth 4's 0.1 s: the ratio is 4, so depth 6 is predicted to cost
    # 1.6 s and to end at 0.5 + 1.6 = 2.1 s.
    times = [0.1, 0.4]
    assert should_start_next_depth(0.5, times, soft_for(2.2), 9.0, 2, 0)
    assert not should_start_next_depth(0.5, times, soft_for(2.0), 9.0, 2, 0)
    # The boundary is the prediction itself, not a fixed share of the budget: the old rule stopped
    # at 0.45 of the soft budget, here 0.45 * 1.56 = 0.70 s, well before this iteration.
    assert should_start_next_depth(0.5, times, soft_for(2.1001), 9.0, 2, 0)


def test_the_ratio_is_clamped_at_both_ends() -> None:
    # A ratio of 40 (0.01 -> 0.4 s) is clamped to 8, so the prediction is 3.2 s, not 16 s.
    steep = [0.01, 0.4]
    assert should_start_next_depth(0.5, steep, soft_for(3.8), 9.0, 2, 0)
    assert not should_start_next_depth(0.5, steep, soft_for(3.6), 9.0, 2, 0)
    # A ratio of 1 is clamped up to 2, so a flat pair of iterations still predicts growth: 0.8 s.
    flat = [0.4, 0.4]
    assert should_start_next_depth(0.5, flat, soft_for(1.35), 9.0, 2, 0)
    assert not should_start_next_depth(0.5, flat, soft_for(1.25), 9.0, 2, 0)


def test_the_default_ratio_holds_before_two_iterations() -> None:
    # One completed iteration: 4.5 x 0.4 = 1.8 s predicted, ending at 2.2 s.
    assert should_start_next_depth(0.4, [0.4], soft_for(2.25), 9.0, 1, 0)
    assert not should_start_next_depth(0.4, [0.4], soft_for(2.15), 9.0, 1, 0)
    # A previous iteration too short to measure is not used as a denominator either: 0.0001 s
    # would give a ratio of 4000, and the default stands instead.
    assert should_start_next_depth(0.4, [0.0001, 0.4], soft_for(2.25), 9.0, 2, 0)


def test_the_fixed_fraction_is_the_fallback_when_nothing_is_measurable() -> None:
    # Depth 1 took 50 microseconds: it says nothing about depth 2, so the rule that preceded the
    # prediction applies -- start another depth while elapsed is below 0.45 of the soft budget
    # itself. Not of the stretched target: with nothing measured there is nothing to stretch for.
    limit = P.next_iteration_fraction  # of a 1 s soft budget
    assert should_start_next_depth(0.00005, [0.00005], 1.0, 9.0, 1, 0)
    assert should_start_next_depth(limit - 0.01, [0.00005], 1.0, 9.0, 1, 0)
    assert not should_start_next_depth(limit + 0.01, [0.00005], 1.0, 9.0, 1, 0)
    # The unstable stretch does not reach it either: a changed root move still gets 0.45 of soft.
    assert not should_start_next_depth(limit + 0.01, [0.00005, 0.00005], 1.0, 9.0, 0, 0)
    # ... and a hard window smaller than the soft budget binds it, like every other target.
    assert not should_start_next_depth(limit - 0.01, [0.00005], 1.0, 0.5, 1, 0)
    # And with no iterations at all (the caller asking before depth 1), the same rule.
    assert should_start_next_depth(0.0, [], 1.0, 9.0, 0, 0)


def test_an_unstable_root_move_stretches_the_target() -> None:
    times = [0.1, 0.4]  # ratio 4, so 1.6 s predicted, ending at 2.1 s
    settled = soft_for(2.0)
    assert not should_start_next_depth(0.5, times, settled, 9.0, 2, 0)
    # The best move changed at the last completed depth: the target stretches by half again.
    assert should_start_next_depth(0.5, times, settled, 9.0, 0, 0)
    # The stretch is bounded by the hard window, which is what protects the clock.
    assert not should_start_next_depth(0.5, times, settled, 2.05, 0, 0)


def test_a_settled_root_move_stops_early() -> None:
    times = [0.1, 0.4]  # ending at 2.1 s
    ordinary = soft_for(2.16)
    # Five iterations with the same best move is not yet easy: the full target applies.
    assert should_start_next_depth(0.5, times, ordinary, 9.0, P.easy_stable_depths - 1, 0)
    # Six of them, with a score that is not falling, cut the target to 0.7 of it.
    assert not should_start_next_depth(0.5, times, ordinary, 9.0, P.easy_stable_depths, 0)
    # A rising score is still easy; a falling one is not, and gets the full target back.
    assert not should_start_next_depth(0.5, times, ordinary, 9.0, 9, -40)
    assert should_start_next_depth(0.5, times, ordinary, 9.0, 9, P.easy_score_drop_cp + 1)


def test_nothing_starts_at_or_past_the_target() -> None:
    assert not should_start_next_depth(5.0, [0.1, 0.4], soft_for(3.0), 9.0, 2, 0)
    assert not should_start_next_depth(0.1, [0.05], 0.0, 0.0, 1, 0)
    assert not should_start_next_depth(0.1, [0.05], -1.0, -1.0, 1, 0)


@pytest.mark.parametrize("stable", [0, 1, 6, 9])
@pytest.mark.parametrize("drop", [-100, 0, 30, 500])
@pytest.mark.parametrize("times", [[], [0.0], [0.5], [0.2, 0.9], [1.0, 0.2], [0.0005, 2.0]])
def test_a_started_iteration_is_always_inside_the_hard_window(
    stable: int, drop: int, times: list[float]
) -> None:
    # The guarantee the flag safety rests on: whatever the history, the rule never starts an
    # iteration once the hard window is gone, because every target is clamped to it.
    for elapsed in (0.0, 0.5, 1.0, 2.0, 5.0):
        for soft, hard in ((1.0, 3.0), (3.0, 3.0), (2.0, 1.0), (0.5, 0.5), (10.0, 0.2)):
            if should_start_next_depth(elapsed, times, soft, hard, stable, drop):
                assert elapsed < hard


# ------------------------------------------------------------- the shipped provenance record (E)


def test_shipped_provenance_records_every_time_constant() -> None:
    """`weights/PROVENANCE.json` is the only provenance artefact inside the zip, and the brief
    asks for the time-management constants as well as the tables. The rows are generated from
    `TimeParams` itself (`tools/gen_pst.py:timing_rows`), so this test is what stops the shipped
    file drifting away from the constants the engine actually uses."""
    from tools.gen_pst import timing_rows  # a tool: imported here, never shipped

    path = Path(__file__).resolve().parent.parent / "weights" / "PROVENANCE.json"
    records = json.loads(path.read_text())
    shipped = [record for record in records if record["parameter"].startswith("timing.")]
    generated = timing_rows()
    assert [record["parameter"] for record in shipped] == [r["parameter"] for r in generated]
    for record, expected in zip(shipped, generated, strict=True):
        assert record["value_or_shape"] == expected["value_or_shape"], record["parameter"]
        assert set(record) == {
            "parameter",
            "value_or_shape",
            "produced_by",
            "data",
            "run_id",
            "note",
        }
    # Every field of TimeParams appears in one row or another, by name or by value.
    text = json.dumps(shipped)
    for field in dataclasses.fields(DEFAULT_PARAMS):
        assert field.name in text or str(getattr(DEFAULT_PARAMS, field.name)) in text, field.name
