"""The compilation budget that keeps the import inside the platform's 90-second limit.

Pure bookkeeping, so these tests need no engine and no numba: they check that a phase runs when
it is predicted to fit, that it is skipped when it is not, that the skip is recorded by name, and
that the slowdown the budget learns from the phases that ran is what it predicts the next one
with. The consequence of getting this wrong is not a bad move, it is every game lost as an init
failure, so the arithmetic is pinned here rather than left to the one integration test.
"""

import time

from mikhail_letal.warmup import WARM_UP_BUDGET_S, WarmUpBudget, arm, budget


def test_no_deadline_runs_everything() -> None:
    """The default is no limit: the tests and the tools must get a fully compiled engine."""
    limit = WarmUpBudget()
    assert limit.deadline is None
    ran = []
    for name in ("a", "b", "c"):
        assert limit.run(name, 1000.0, lambda name=name: ran.append(name))  # type: ignore[misc]
    assert ran == ["a", "b", "c"]
    assert limit.skipped == []


def test_expired_deadline_skips_every_phase() -> None:
    limit = WarmUpBudget()
    limit.deadline = time.perf_counter() - 1.0
    assert not limit.run("first", 0.0, lambda: None)
    assert not limit.run("second", 0.0, lambda: None)
    assert limit.skipped == ["first", "second"]


def test_a_phase_that_would_overrun_is_not_started() -> None:
    """The point of the prediction: a phase is skipped while there is still time on the clock,
    because `negamax` alone is twelve seconds and starting it late would blow the budget."""
    limit = WarmUpBudget()
    limit.deadline = time.perf_counter() + 5.0
    assert limit.run("small", 1.0, lambda: None)
    assert not limit.run("large", 60.0, lambda: None)
    assert limit.skipped == ["large"]


def test_skipping_one_phase_does_not_stop_the_cheaper_ones_after_it() -> None:
    """Each phase is judged on its own cost, so an expensive phase that does not fit does not
    take a cheap one with it -- `fastboard.perft` is last precisely because it is skippable."""
    limit = WarmUpBudget()
    limit.deadline = time.perf_counter() + 5.0
    assert not limit.run("large", 60.0, lambda: None)
    assert limit.run("small", 0.1, lambda: None)
    assert limit.skipped == ["large"]


def test_not_ready_skips_and_is_recorded() -> None:
    """A phase whose dependency was skipped must not run: the sample searches would compile the
    `negamax` the budget just declined to compile."""
    limit = WarmUpBudget()
    ran = []
    assert not limit.run("samples", 0.1, lambda: ran.append("samples"), ready=False)
    assert ran == []
    assert limit.skipped == ["samples"]


def test_slowdown_is_learned_from_the_phases_that_ran() -> None:
    limit = WarmUpBudget()
    limit.run("slow", 1.0, lambda: time.sleep(0.05))
    # A phase declared at one reference second that took 0.05 s is a machine 20x *faster* than
    # the reference, and the factor is clamped to 1 so predictions never shrink below reference.
    assert limit.slowdown == 1.0
    limit.run("slower", 0.05, lambda: time.sleep(0.2))
    # 0.25 s spent against 1.05 reference seconds is still under 1.0 and stays clamped.
    assert limit.slowdown == 1.0

    other = WarmUpBudget()
    other.run("slow", 1.0, lambda: time.sleep(1.5))
    assert 1.3 < other.slowdown < 1.9


def test_slowdown_ignores_phases_too_short_to_measure() -> None:
    limit = WarmUpBudget()
    limit.run("tiny", 0.001, lambda: time.sleep(0.05))
    assert limit.slowdown == 1.0  # under a reference second: noise, not a measurement


def test_arm_sets_the_shared_deadline_and_clears_the_accounting() -> None:
    shared = budget()
    try:
        when = time.perf_counter() + 1.0
        assert arm(when) is shared
        assert shared.deadline == when
        shared.run("gone", 60.0, lambda: None)
        assert shared.skipped == ["gone"]
        arm(None)
        assert shared.deadline is None
        assert shared.skipped == []
        assert shared.slowdown == 1.0
    finally:
        arm(None)


def test_budget_leaves_the_platform_room_to_spare() -> None:
    """The number itself: the import has 90 s, and the warm-up may not claim all of it. See the
    constant's docstring for the arithmetic behind 70."""
    assert 30.0 <= WARM_UP_BUDGET_S <= 75.0
