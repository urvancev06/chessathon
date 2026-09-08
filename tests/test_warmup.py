"""The compilation budget that keeps the import inside the platform's 90-second limit.

Pure bookkeeping, so these tests need no engine and no numba: they check that a phase runs when
it is predicted to fit, that it is skipped when it is not, that the skip is recorded by name, and
that the slowdown the budget learns from the phases that ran is what it predicts the next one
with. The consequence of getting this wrong is not a bad move, it is every game lost as an init
failure, so the arithmetic is pinned here rather than left to the one integration test.
"""

import pathlib
import subprocess
import sys
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


def test_arm_discards_the_slowdown_it_measured() -> None:
    """Pinned because `agent._finish_warm_up` used to depend on the opposite.

    `arm` calls `reset`, which puts `slowdown` back to 1.0. That is right for the import, which
    starts the accounting fresh, but it means a *second* `arm` throws away the measurement the
    first one learned -- and on the cold-finish path that measurement is, by construction, the
    reason phases were skipped at all. A predictive bound armed here would be computed at 1.0x on
    a machine already known to be slower, which is why the cold finish no longer takes one.
    """
    limit = arm(time.perf_counter() + 100.0)
    limit.run("slow phase", 1.0, lambda: time.sleep(1.5))
    assert limit.slowdown > 1.0, "a phase that ran slower than reference must raise the slowdown"

    again = arm(time.perf_counter() + 100.0)
    assert again is limit, "arm re-arms the one shared budget"
    assert again.slowdown == 1.0, "re-arming discards it, so nothing may rely on it surviving"
    arm(None)


COLD_START_PROBE = """
import sys
sys.path.insert(0, {root!r})
import mikhail_letal.warmup as warmup

# Force the import warm-up to run out of budget almost immediately, so phases are skipped and the
# cold-finish path -- the one that has never executed on the platform or in any other test -- runs.
warmup.WARM_UP_BUDGET_S = 0.2

import agent

skipped_at_import = list(warmup.budget().skipped)
was_cold = agent._COLD
# A deliberately small clock. The bound this test guards against was a fraction of it
# (cold_finish_fraction = 0.25), so at six seconds it allows 1.5 s -- far less than a full
# compilation takes on any machine. With a full 120 s clock the old bounded path finishes
# anyway on a fast box and the test proves nothing; this is what makes it discriminate.
move = agent.get_move("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", 6_000)
left_after = list(warmup.budget().skipped)
never_compiled = [name for name, count in agent._signatures().items() if count == 0]

print("SKIPPED_AT_IMPORT", len(skipped_at_import))
print("WAS_COLD", was_cold)
print("MOVE", move)
print("LEFT_AFTER", len(left_after))
print("NEVER_COMPILED", len(never_compiled))
"""


def test_cold_finish_leaves_nothing_to_compile_inside_a_later_search() -> None:
    """The gate on the degraded path: after the cold finish, nothing compiles on the clock again.

    This is the failure the whole warm-up exists to prevent, and until now nothing exercised it.
    A jitted function first called inside ``ENGINE.search`` compiles *there*, where numba cannot be
    interrupted and no deadline applies -- measured at 15.9 s against a 10.2 s budget. Skipping a
    phase at import is survivable only because ``_finish_warm_up`` compiles it before the first
    search. If it leaves anything behind, the engine has not degraded gracefully; it has moved the
    overrun to whichever later move happens to touch that function, on a three-second budget.

    Run in a subprocess because the import is what does the warm-up: it cannot be repeated in a
    process that has already imported ``agent``.
    """
    root = str(pathlib.Path(__file__).resolve().parent.parent)
    finished = subprocess.run(
        [sys.executable, "-c", COLD_START_PROBE.format(root=root)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=root,
    )
    assert finished.returncode == 0, finished.stderr[-3000:]
    report = dict(
        line.split(" ", 1)
        for line in finished.stdout.splitlines()
        if " " in line and line[0].isupper()
    )

    assert report["WAS_COLD"] == "True", "the probe failed to force a degraded import"
    assert int(report["SKIPPED_AT_IMPORT"]) > 0, "no phase was skipped, so the path was not tested"
    assert len(report["MOVE"]) in (4, 5), f"no legal move returned: {report['MOVE']!r}"
    assert report["LEFT_AFTER"] == "0", "the cold finish left phases uncompiled"
    assert report["NEVER_COMPILED"] == "0", "a jitted function would still compile inside a search"
