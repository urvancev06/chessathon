# What a screen costs, measured

Nobody had ever recorded this, and both `chessathon-d9` and `chessathon-4c` planned around a
number they had estimated rather than measured — on the same day, in the same direction, by the
same missing term. Written down so the next person planning a screen does not repeat it.

## The measurement

From the 1000-game real-clock screen of 2026-09-09 (`ct-ordering` vs `versions/v1.2`, 120 s + 0.5 s,
12 workers, otherwise idle 16-core box):

```
1.74 - 1.80 games per minute        measured over the first 33 games
~9.5 hours for 1000 games
~346 s mean per game of engine play (from the tool's own per-game line)
```

## The term everybody forgets

The arithmetic that looks right is `games x seconds-per-game / workers`. It is wrong by about
17%, and the missing term is the same one in every version of the mistake:

**Every game starts two fresh agent processes, and every process pays the numba warm-up.**

Measured on this box: **18 s idle, 31 s under load, per process.** A 1000-game screen therefore
pays that cost **2000 times** and amortises it over nothing. At the fast control it is the
*dominant* term — a 10 s + 0.1 s game is roughly 30 s of chess sitting on 40-60 s of start-up.

Two consequences worth having in front of you before you plan anything:

1. **Game count scales linearly with a cost you cannot reduce.** 3000 fast games is most of a
   night, and most of what you are buying is process start-up rather than chess.
2. **Raising the time control is far cheaper than the clocks suggest.** A real-clock game is about
   **3.6x** a fast one, not the ~12x the clock ratio implies, because the fixed cost does not move.
   Predicted 3.7x from the model above; measured 3.6x on 24 games. That is the finding that moved
   all screening to the real time control, since a fast screen never satisfied the promotion rule
   anyway and the cost that justified the substitute had never been priced.

## Planning numbers

| games | real clock, 12 workers | resolves about |
|---|---|---|
| 300 | ~2.5 h | ±39 Elo |
| 800 | ~7.7 h | ±24 Elo |
| 1000 | ~9.5 h | ±21 Elo |

**Do not run 300 games on something you expect to be worth +20 to +30.** It will straddle zero,
and the row then sits in `RESULTS.md` looking like evidence. A result that cannot resolve the
question is worse than no result once it is written down, because the next reader reads a table
and not an interval.

## If you need the number early

The PGNs are written per game as each finishes, so a truncated run is a valid smaller sample —
score what has been played rather than waiting for the tool's summary, which only writes the
`RESULTS.md` row at the end. Do not restart a run to shorten it: you discard the games *and* the
warm-ups already paid for, which is the one cost you cannot get back.
