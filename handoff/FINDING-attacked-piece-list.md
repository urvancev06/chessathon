# The piece-list `attacked()` is exact and 4.85x slower. Rejected.

Proposed by external research as the top item: rewrite `fastboard.attacked` to walk the attacker's
piece list with a delta-table lookup instead of scanning eight rays outward from the square.
Estimated 8-18% of node rate, and — being **exact** — shippable on a bench plus an equivalence
test rather than on a screening slot, which made it the best Elo-per-slot item on the board.

**It is exact. It is also much slower.**

    equivalence   no disagreements over 80 positions x 64 squares x 2 colours
    timing        median of 80 per-position ratios: 4.851   (min 4.383, max 8.867)
                  -> 385% slower per call

## Why the estimate was wrong

The reasoning was: `attacked` "costs the same whatever the material is" by its own docstring, so a
piece-list scan that costs one lookup per piece must win in thin positions. Both halves are true
and the conclusion does not follow.

**The outward scan returns on its first hit and its first test is the most common attacker.** It
checks two pawn squares, then knights, then kings, then walks rays that in any real position
terminate after one or two squares. A square that is attacked at all is usually attacked cheaply,
and a square that is not is refuted by eighteen array reads and eight short walks.

**The piece-list form pays for every piece before it can answer.** Up to sixteen iterations of
plist read, delta, bounds test, board read for the kind, mask lookup and comparison — and only
then, for sliders, a blocker walk. There is no early exit against the common case, because the
attacker that answers the question may be the last one in the list.

## What this cost and what it bought

Four hours of writing, and it was caught by the gate it was written with rather than by a screen:
the tool checks equivalence first and refuses to report timing until it passes, then reports the
median of per-position ratios. **The change was correct and useless**, which is the outcome the
two-stage gate exists to separate from correct and valuable.

`attacked_from_list` and its tables are removed. The equivalence test goes with it. The delta-table
construction is recorded here in case a future term wants "could a piece of type T attack along
delta D" as a cheap precomputed answer -- that part is sound and reusable, it is just not a faster
way to answer the question `attacked` asks.

**Do not re-derive this.** The published figure that motivated it was about bitboard engines
popcounting attack sets they already hold. We are a mailbox and we do not hold them.
