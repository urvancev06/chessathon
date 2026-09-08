# Plan for the remaining time

Written Monday 8 September. Uploads close Thursday 11 September, 11:00 London. Four working
sessions left, so everything here is ordered by strength gained per hour of risk.

## Where the engine stands

| | |
|---|---|
| Speed | about 55,000 positions per second, interpreted Python |
| Depth | 9 in three seconds from the opening position |
| Strength | roughly 2050 on the CCRL scale, interval 1940–2170 |
| Safety | no crash, illegal move or flag in about 2,000 recorded games |

## The one thing that matters most

Everything runs in interpreted Python. That is the ceiling, and it is a low one. numba is the only
compiled-code route the rules allow, and it is the difference between 55,000 positions a second
and something in the high hundreds of thousands. Three or four extra plies of search is worth more
than every evaluation term, tuning run and endgame table on this list put together.

It was deferred for one reason: it is the highest-risk change in the project, and a fast engine
that plays one illegal move scores worse than a slow one that never does. With three days left
and the current build already frozen, uploaded and safe as a fallback, the risk is now affordable.

**Priority 1: the numba engine.** Own board representation, own move generation, own make and
unmake, evaluation and search, all compiled, called from the same `agent.py` wrapper. python-chess
stays in the wrapper as the legality oracle and the fallback, so the safety guarantees survive
even if the compiled search is wrong.

Non-negotiable gates before it can replace anything:

1. Move generation must match python-chess exactly. Perft to depth 4 on the standard test
   positions, depth 3 on every one of the 219 curated openings, and identical legal-move sets on
   100,000 random positions including en passant, castling, checks and promotions.
2. Compilation must finish inside the 90-second start-up budget on a core three times slower than
   this laptop. Every jitted function warmed at import with the exact argument types, measured
   from the extracted zip, target under 40 seconds locally.
3. The clock must be checked inside the compiled search, with a node cap as a second mechanism in
   case the clock read misbehaves. Both, always.
4. Memory as fixed-size arrays, never a growing dictionary. Total under 500 MB.
5. Then the usual promotion rule: it beats the current version at the real time control with the
   95% interval above zero, and the fuzz and property suites pass unchanged.

If any gate fails and cannot be fixed in the time left, the plan is to stop and ship the Python
engine. That is a real outcome, not a failure state.

## The rest, in order

**Priority 2: the platform calibration.** Needs the validation log from an upload. Every time
constant in the engine is currently a guess from the brief rather than a measurement of the real
machine. This is the cheapest safety improvement available and it costs nothing but the upload.

**Priority 3: endgame tablebases.** 3, 4 and 5 piece Syzygy is far too large, but 3 and 4 piece
files are small enough to ship inside the 50 MB cap with room to spare. `chess.syzygy` is in the
base image. This fixes the measured endgame failures: the Lucena position is not converted, and
king and queen against king can still run into the fifty-move rule from an awkward start. Modest
Elo, but it removes a class of embarrassing draws.

**Priority 4: Texel tuning, done properly.** The first attempt regressed on Stockfish's evaluations
with a linear model and no logistic link, which let already-decided positions dominate the fit; it
lost 300 games and was reverted. The correct method labels positions by the result of the game they
came from, models the win probability as a logistic function of the evaluation, and minimises the
error of that against the outcome. It is also worth more once the search is deeper, because a
better leaf evaluation compounds with depth. Do it after numba, not before.

**Not doing: a neural network.** A small quantised network evaluated inside the compiled search is
the natural next step after all of the above, and there is not enough time to train one and prove
it is better. A hand-crafted evaluation that can be explained beats a rushed network that cannot.

## Schedule

| When | What |
|---|---|
| Monday | Finish and promote the current speedup. Upload for the calibration log. |
| Monday night to Tuesday | The numba engine: board, move generation, perft gates. |
| Tuesday | Compiled search and evaluation, warm-up, timing, arena runs. |
| Wednesday | Whichever engine won: tablebases, then proper tuning. Feature freeze at 22:00 London. |
| Thursday before 08:00 | Final measurement pass alone on the machine, final upload, report. |

The previous build stays valid on the platform throughout, so a failed experiment never costs a
game. Nothing gets promoted without games behind it.

## On "playing like Magnus"

Worth writing down, because it is the wrong target in an interesting way. Imitating a specific
human's moves is a solved problem: train a network to predict the move a player of a given rating
would make. The result plays in a recognisably human style and is markedly weaker than a
conventional search, because it reproduces human mistakes faithfully. Strength and imitation are
different objectives, and this competition scores only the first.
