# Can we flag an opponent who is in time trouble?

Yan's idea, tested 2026-09-08. **Short answer: no, and the 0.5 s increment is why.** One piece of
it is buildable and cheap, and the observation behind it points at a real defect — just not the one
it was aimed at.

Evidence is the four rated ladder games (rounds 67-70), whose PGNs carry `[%clk]` after every move
for both sides. Raw data in `data/pgn/ladder/`.

## The proposal

When the opponent is low on time and we are not, reply as fast as possible — microseconds per move
— so that they are forced to keep moving and run out of time.

## Why it does not work

**1. The 0.5 s increment refunds every move.** This is the decisive one. The clock is not sudden
death: a side only loses ground by spending *more* than 0.5 s on a move. Round 68 is exactly the
experiment, run for real:

| in round 68, while under 10 s on the clock | opponent (`Zero Elo`) | us |
|---|---|---|
| moves played under 10 s | **51** | 41 |
| mean spend per move | 0.563 s | 0.631 s |
| clock at the start of that stretch -> the end | 9.88 s -> 6.92 s | 9.43 s -> 4.67 s |
| net change over the whole stretch | **-2.96 s** | -4.77 s |
| moves that spent more than the 0.5 s increment | 35 of 51 | 28 of 41 |

The opponent's net drain was **0.063 s per move**. From 9.88 s that is **~157 more moves** to flag
them. The game hits the 600-ply cap long before, and the cap is scored a **draw**.

At the 0.5 s the proposal imagines, the position is not a death sentence, it is an equilibrium:
spend 0.4 s, end on 0.6 s. And any engine can return a legal move in about a millisecond — *ours
does*, via `panic_ms = 1650`, below which `agent.get_move` skips the search entirely. An opponent
doing the same **gains 0.499 s a move** and climbs back out.

**2. Our move speed is not an input to their spending.** Clocks are per side ("120 s + 0.5 s per
move, per side, on wall time"). Their clock only runs while they think, and how long they think is
decided by their own budget from their own clock. Our reply arriving in 1 ns rather than 3 s only
starts their turn sooner in wall-clock terms.

If anything it helps them: a move produced instantly is a worse move, which hands them a simpler
position, which their time manager will spend *less* on.

**3. There is no pondering to deny.** The obvious rescue — move fast so they cannot think on our
time — is already handled by the platform: "Your process is suspended while the opponent thinks, so
nothing you leave running gets any CPU." Nobody can ponder, so nobody can be denied it.

**4. We are not told their clock.** `get_move(fen, time_left_ms)` — "Your colour is the side to
move in the fen. There is no other input." (Circumventable; see below.)

**5. Shuffling fast walks into the draw rules.** Fast filler moves push toward the 600-ply cap and
the fifty-move rule, both draws. Round 68 ended as a fifty-move draw at exactly this. The strategy
converts wins into draws while flagging nobody.

**6. The situation barely arises.** Across all four rated games, moves where the opponent was under
20 s while we were over 60 s:

| game | result | our lowest | their lowest | moves where they <20 s and we >60 s |
|---|---|---|---|---|
| 67 | 1-0 checkmate | 86.1 s | 59.3 s | **0** |
| 68 | 1/2 fifty moves | 4.1 s | 5.1 s | **0** |
| 69 | 1-0 checkmate | 30.6 s | 13.9 s | **0** |
| 70 | 0-1 checkmate | 88.9 s | 70.2 s | **0** |

Zero, in four games. The one game where anyone was in real time trouble, **we** were worse off.

The idea would have real force at 120 + 0. The 0.5 s per move is what kills it, and that number is
in the agent contract.

## What is worth taking from it

**A. The opponent-clock estimator is buildable, cheap, and correct.** We are SIGSTOP'd while they
think, but `time.perf_counter()` is monotonic real time and keeps advancing while the process is
stopped. So the gap between finishing our move and being called for the next one *is* their
thinking time, and module state survives the game:

```
their_clock ~= 120_000 + 500 * (their moves played) - sum(measured gaps)
```

Accurate to the referee overhead, measured at **1.1 ms** (`docs/CALIBRATION.md`). About fifteen
lines of `agent.py`. Not useful for flagging, but it is the input to B.

**B. If they are short and we are rich, play *longer*, not faster.** The only lever on a clock with
an increment is making them spend above 0.5 s a move, sustained — which means hard positions: keep
pieces on, avoid simplification, decline repetitions. That costs us thinking time rather than
saving it. Concretely it would mean biasing the root away from draws when their estimated clock is
low, alongside the existing `DRAW_TIEBREAK_MARGIN = 300`. **Unmeasured, and hard to measure** — it
fires in a state that occurred zero times in four games, so the promotion rule would need thousands
of games to resolve it. Recorded, not recommended before Thursday.

**C. The real defect the observation points at: we underspend our own clock.** This is the useful
half, and it is the third independent sighting of the same constant.

| game | our moves | clock left at the end | of a total budget of |
|---|---|---|---|
| 67 | 18 | **87.5 s** | 129.0 s |
| 69 | 51 | **31.6 s** | 145.5 s |
| 70 | 23 | **90.2 s** | 131.5 s — while being mated |
| 68 | 113 | 4.7 s | 176.5 s — nearly flagged |

`moves_to_go` starts at 40 and floors at 12, so a 23-move game budgets as though 40 more moves are
coming and ends with 69 % of the clock unspent, while a 113-move game starves to 4.1 s. It is wrong
in both directions. `docs/CALIBRATION.md` already flagged the long-game half from round 68.

**`mikhail_letal/timing.py` is byte-identical in v1.0** — `moves_to_go_max = 40`,
`overhead_ms = 150` (measured need: **1.1 ms**), `next_iteration_fraction = 0.45` — so the flaw
shipped unchanged into the compiled engine.

When we have a lot of time, the answer is to **spend** it. Moving faster throws away the only
advantage we have.

## Method

Clock traces are reconstructed from the `[%clk]` tags: `spend = clock_before - clock_after + 0.5`,
the same arithmetic `docs/CALIBRATION.md` uses. Four games, 452 half-moves, every one carrying a
clock tag. No engine runs were needed for any of this; it is all in the published PGNs.
