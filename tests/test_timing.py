"""Tests for the time budget formula (mikhail_letal/timing.py)."""

import dataclasses
import itertools

import pytest

from mikhail_letal.timing import DEFAULT_PARAMS, Budget, TimeParams, budget

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
    # moves_to_go = 40; soft = 119850 / 40 + 400 = 3396.25; hard = 3 * soft = 10188.75, which is
    # below both 0.25 * 120000 = 30000 and 120000 - 150 - 6000 = 113850.
    b = budget(120_000, 0)
    assert b.soft_ms == pytest.approx(3396.25)
    assert b.hard_ms == pytest.approx(10188.75)


def test_hand_computed_middlegame() -> None:
    # moves_to_go = 40 - 20 // 2 = 30; soft = 59850 / 30 + 400 = 2395; hard = 7185, below both
    # 0.25 * 60000 = 15000 and 60000 - 150 - 3000 = 56850.
    b = budget(60_000, 20)
    assert b.soft_ms == pytest.approx(2395.0)
    assert b.hard_ms == pytest.approx(7185.0)


def test_hand_computed_low_clock_is_capped_by_hard_fraction() -> None:
    # moves_to_go clamps to 12; soft = 4850 / 12 + 400 = 804.1666...; 3 * soft = 2412.5 exceeds
    # 0.25 * 5000 = 1250, so hard = 1250, and the reserve room 5000 - 150 - 1500 = 3350 is not
    # binding. soft stays below hard.
    b = budget(5_000, 60)
    assert b.hard_ms == pytest.approx(1250.0)
    assert b.soft_ms == pytest.approx(4850 / 12 + 400)


def test_no_time_to_plan_gives_zero_budget() -> None:
    # 1600 - 150 - 1500 < 0: the reserve is already breached, so both budgets are zero.
    assert budget(1_600, 80) == Budget(soft_ms=0.0, hard_ms=0.0)
    assert budget(200, 90) == Budget(soft_ms=0.0, hard_ms=0.0)


def test_moves_to_go_is_clamped() -> None:
    # 40 - 56 // 2 = 12 is the minimum; more moves played must not change anything.
    assert budget(30_000, 56) == budget(30_000, 100)
    # Integer halving: moves 0 and 1 give the same divisor.
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
    # With no overhead and no reserve: soft = 12000 / 40 + 400 = 700, hard = min(2100, 3000).
    b = budget(12_000, 0, generous)
    assert b.soft_ms == pytest.approx(700.0)
    assert b.hard_ms == pytest.approx(2100.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        generous.overhead_ms = 1  # type: ignore[misc]


def test_default_params_match_design() -> None:
    p = DEFAULT_PARAMS
    assert (p.increment_ms, p.overhead_ms) == (500, 150)
    assert (p.moves_to_go_max, p.moves_to_go_min) == (40, 12)
    assert (p.increment_fraction, p.hard_multiplier, p.hard_fraction) == (0.8, 3.0, 0.25)
    assert (p.floor_ms, p.floor_fraction, p.panic_ms) == (1500, 0.05, 1500)
    assert p.next_iteration_fraction == 0.45
