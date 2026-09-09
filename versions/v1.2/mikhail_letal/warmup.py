"""The wall-clock budget that the import's numba compilation has to fit inside.

Compiling the engine is the single most expensive thing this agent does. On the development
machine it costs 17-29 s depending on what else is running, and the platform is measured at 2.3x
slower (docs/CALIBRATION.md), which puts the whole import somewhere between 40 s and 66 s against
a **hard 90 s** start-up budget. Everything below is argued from the slow end of that range,
because the slow end is the one that can lose games: an import that overruns the budget does not
merely play badly, the platform records an init failure and *every* game is lost. Twenty-four
seconds of margin, on a machine we cannot benchmark before we ship, is not enough to bet the
whole entry on.

So the compilation is bounded rather than open-ended. Each `warm_up()` in `fastboard`, `fasteval`
and `fastsearch` is cut into phases, ordered by how much the search needs them, and asks the one
shared `WarmUpBudget` before each phase whether it still fits. What does not fit is skipped, and
`agent.get_move` compiles it on its first real move instead, before it searches, out of the
opening's 120-second clock. That costs one slow move, which is survivable; losing every game
outright is not.

The check is a prediction, not just "has the deadline passed": the phases are lumpy (compiling
`negamax` alone is twelve seconds here), so stopping only once the clock has run out would still
let one last phase run far past it. Each phase declares what it costs on the development machine
(`docs/PROVENANCE.md` records the measurements), and the budget scales that by the slowdown it
has observed from the phases that already ran. A phase starts only if it is predicted to finish
before the deadline.
"""

import time
from collections.abc import Callable
from typing import Final

WARM_UP_BUDGET_S: Final = 70.0
"""Seconds from the start of the import that the warm-up may spend, wall clock.

Why 70. Take the slow end of the range above: 28 s of compilation here, plus about 0.4 s of
interpreter, `chess` and `numpy` start-up in front of it. Scaled by the platform's measured 2.3x
that is a 65 s import, so a 70 s budget does not bite on the platform we actually ship to: the
engine still arrives fully compiled. Scale the same sequence by 3x instead -- a slower machine
than any we have seen -- and the phases end at 1.2 s, 9.1 s, ... , 39.4 s, at which point
`negamax` is predicted to need 37.5 s more and would run to 77 s. It is not started, so the import
finishes at about 40 s and the agent plays with a cold `negamax` that costs one slow move. Either
way the import is well inside 90 s: 65 s at 2.3x with everything compiled, about 40 s at 3x with
the tail skipped, against an 85 s import if nothing bounded it at all.

The bound holds because no phase begins unless it is *predicted* to end by the deadline, so the
worst case is the deadline plus one phase's prediction error, not the deadline plus a whole
phase. The one thing it cannot cover is a machine so slow that the first phase alone overruns
90 s: that would need roughly 20x, and nothing on the platform is remotely that slow.
"""


class WarmUpBudget:
    """How much wall clock the warm-up has left, and how fast this machine is compiling.

    One instance is shared by all three modules' `warm_up()` calls, because the slowdown measured
    while `fastboard` compiles is exactly what predicts how long `fastsearch` will take.
    """

    def __init__(self) -> None:
        self.deadline: float | None = None
        """`perf_counter()` time the warm-up must be finished by, or `None` for no limit.

        `None` is the default on purpose: the tests and the tools call `warm_up()` directly and
        must always get a fully compiled engine. Only `agent.py` arms a deadline, because only
        `agent.py` is running against the platform's 90-second clock.
        """
        self.slowdown = 1.0
        """This machine's compile time divided by the development machine's, so far."""
        self.skipped: list[str] = []
        """Names of the phases that did not fit, in order, for the log line."""
        self._reference = 0.0  # development-machine seconds of the phases that have run
        self._actual = 0.0  # what those phases actually cost here

    def run(
        self, name: str, reference_s: float, work: Callable[[], None], *, ready: bool = True
    ) -> bool:
        """Run `work`, unless it is predicted to overrun the deadline; say whether it ran.

        `reference_s` is what this phase costs on the development machine. `ready` is `False` when
        an earlier phase this one depends on was skipped -- running the sample searches without a
        compiled `negamax` would simply compile `negamax`, which is the cost we were avoiding.
        """
        if not ready or not self._fits(reference_s):
            self.skipped.append(name)
            return False
        started = time.perf_counter()
        work()
        self._reference += reference_s
        self._actual += time.perf_counter() - started
        # Below a second of reference work the ratio is mostly measurement noise; and a machine
        # faster than the development one is clamped to 1.0, so the prediction never shrinks.
        if self._reference >= 1.0:
            self.slowdown = max(1.0, self._actual / self._reference)
        return True

    def _fits(self, reference_s: float) -> bool:
        if self.deadline is None:
            return True
        return time.perf_counter() + reference_s * self.slowdown <= self.deadline

    def reset(self, deadline: float | None) -> None:
        """Set the deadline and start the accounting again."""
        self.deadline = deadline
        self.slowdown = 1.0
        self.skipped = []
        self._reference = 0.0
        self._actual = 0.0


_BUDGET = WarmUpBudget()


def budget() -> WarmUpBudget:
    """The one budget every `warm_up()` in the package shares."""
    return _BUDGET


def arm(deadline: float | None) -> WarmUpBudget:
    """Set the deadline and start the accounting again. Called once, by `agent.py`, before the
    first compiled module is imported; called with `None` by the tests to lift the limit."""
    _BUDGET.reset(deadline)
    return _BUDGET
