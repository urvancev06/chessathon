# Mikhail LeTal

A chess engine written for [AI Chessathon 2026](https://aichessathon.com) in Python, with its
board, evaluation and search compiled by numba. The name is a pun on Mikhail Tal. The engine is
nowhere near as brave as he was.

The competition fixes the environment: Python 3.12, five preinstalled packages, one core of an
EPYC 9V74, 2 GB of RAM, no network, no GPU, and native binaries are rejected at upload. The
submitted build, **v1.4**, searches **430,000–580,000 positions per second** on that core and
reaches **depth 9 to 15** in a real game — 90% of 297 logged competition moves, median 11.
Compiling everything below the root cost 29 seconds of the 90-second start-up budget and bought
three to four plies over the interpreted engine it was ported from.

Every number in this repository was measured, and the measurements that came out badly were kept.
Two changes cleared the promotion bar after the engine went compiled; five substantial attempts —
including a neural network and two evaluation fits — did not. The second list is the more
interesting one and it has its own section below.

## The problem

Most of the interesting decisions follow from the environment rather than from chess:

| | |
|---|---|
| Language | Python 3.12, five preinstalled packages, nothing else installs |
| Compiled code | Native binaries are rejected. No Cython, no C extension |
| Hardware | One core of an EPYC 9V74 at 2.60 GHz, 2 GB RAM, no network |
| Clock | 120 s + 0.5 s per move, per side, wall time |
| Start-up | 90 s before the clock starts |
| Losing for free | An illegal move, a crash, running out of memory or flagging loses the game outright |

One slow core and no native binaries means node counts far below what a C engine gets. numba is
the one compiled-code route the rules leave open, and taking it was worth more than every
evaluation term put together. Everything below the root — the board, move generation, make and
unmake, the evaluation and the whole alpha-beta tree — is compiled; python-chess stays in the
wrapper as the legality oracle and the fallback, so no safety guarantee depends on the compiled
code being right.

That split is why there are two engines in `mikhail_letal/`. `search.py` and `evaluation.py` are
the readable specification, written in ordinary Python against python-chess. `fastsearch.py`,
`fasteval.py` and `fastboard.py` are the compiled port, and they are what ships.
`tests/test_fasteval.py` compares the two integer for integer over 20,000 positions, so a term
cannot exist in one and not the other without the suite going red.

## What's inside

**Search.** Negamax with alpha-beta and principal variation search, iterative deepening, and a
transposition table that survives across moves in a game (2^23 entries, and a second 2^22-entry
table caching static evaluations). Quiescence at the leaves, with its own transposition probe, so
the evaluation is never measured mid-exchange. Move ordering is the transposition move, then
captures by most-valuable-victim broken by static exchange evaluation, then two killer moves per
ply, then a history heuristic with a one-ply continuation history and a malus for quiet moves that
failed. Null-move pruning, late-move reductions, aspiration windows, reverse futility, futility
pruning at shallow depths, mate-distance pruning, check extensions and delta pruning in
quiescence. Each sits behind a named constant so a regression can be bisected feature by feature.

**Evaluation.** Tapered material and piece-square tables that blend a middlegame view into an
endgame one as pieces leave the board, plus passed, doubled and isolated pawns, the bishop pair,
rooks on open files, and a middlegame king pawn shield. There is also a mop-up term so that king
and rook against a bare king actually converts, which a shallow search will not do on its own.

The tables are not copied from anywhere. [`tools/gen_pst.py`](tools/gen_pst.py) computes every one
of the 768 entries from a formula of the square's geometry with twenty-four named parameters,
prints them as 8×8 grids to be eyeballed, and records what produced them. Piece-square tables are
the part of an engine most likely to be reproduced from something you have read, and one of the
house bots on this ladder is Sunfish, whose tables the organisers know by sight. A mechanical
comparison against Sunfish, the Chess Programming Wiki's simplified tables, Rustic, TSCP and VICE
found one coincidental row, where our formula happens to put 50 on the seventh rank of the endgame
pawn table. That is written down in [docs/DECISIONS.md](docs/DECISIONS.md) rather than quietly
fixed.

**Time management.** The budget comes from the clock the platform hands over, not from a constant.
A soft target decides whether to start another iteration; a hard deadline aborts the current one.
The search checks the clock every 128 nodes, and when the fifty-move rule or the 600-ply cap is
close it shortens its horizon so it has time to force the win before the referee calls the draw.
Over 71 logged moves in solo games the worst overshoot past the hard deadline was 2 milliseconds.

**Safety.** `get_move` cannot raise and cannot return an illegal move. Every path ends in a
validation against a fresh board built from the FEN, and anything that fails it falls back to a
one-ply capture search that answers in under a millisecond. Below a threshold on the clock the
engine skips the search entirely. If a position arrives that is not reachable from the last one we
played, the game history resets and says so in the log. Across nearly two thousand recorded games
and a 500-game fuzz gate on every frozen build there was no crash, no illegal move, no flag and no
failure to start.

## Strength

Nothing gets promoted on a hunch. A version replaces the previous one only when it wins a match
whose 95% interval is above zero, at the real 120 s + 0.5 s time control, with the previous
version kept in `versions/` as the opponent. Two changes cleared that bar after the engine went
compiled:

| Change | Games | Clock | Elo (95%) |
|---|---|---|---|
| v1.2 → v1.3 — SEE in quiescence, one-ply continuation history | 1000 | 120 s + 0.5 s | **+36** (+19 to +53) |
| v1.3 → v1.4 — quiescence TT, 4× bigger TT, tighter aspiration, history malus | 300 | 120 s + 0.5 s | **+42** (+10 to +74) |

Every frozen build then goes through a 500-game safety gate. It does not measure strength — the
opponents are trivial — it measures whether the engine can lose to something other than chess:

| Build | Opponent | Clock | Games | +W =D −L |
|---|---|---|---|---|
| v1.4 | Random mover | 3 s + 0.05 s | 300 | +300 =0 −0 |
| v1.4 | Greedy (1 ply) | 10 s + 0.1 s | 200 | +200 =0 −0 |

The only rating estimate this repository has ever made against an external yardstick was made
against the **interpreted** v0.2 build, over 300 games at the real clock:

| Opponent | Games | +W =D −L | Score |
|---|---|---|---|
| Stockfish 19, UCI_Elo 1600 | 60 | +38 =8 −14 | 70.0% |
| Stockfish 19, UCI_Elo 1800 | 60 | +44 =4 −12 | 76.7% |
| Stockfish 19, UCI_Elo 2000 | 60 | +25 =4 −31 | 45.0% |
| Stockfish 19, UCI_Elo 2200 | 60 | +16 =14 −30 | 38.3% |
| Stockfish 19, UCI_Elo 2400 | 60 | +18 =16 −26 | 43.3% |

A maximum-likelihood fit over those 300 games puts v0.2 at roughly **2050 on the CCRL 40/4 scale**
(interval 1940–2170). Note the 2200 and 2400 rows are not monotonic, which is what rating-limited
Stockfish does at 60 games a level — read the caveats in [docs/RESULTS.md](docs/RESULTS.md) before
quoting that number anywhere.

The compiled engine was never re-rated against that yardstick, so **no CCRL-scale number is claimed
for v1.4**. What is known about it is relative: it is +78 Elo above v1.2, and v1.2 sat at **#126 of
432** on the competition ladder with a platform rating of 1800.

One more calibration, because it decides what is worth buying. Playing v1.3 against itself with
one side on half the clock, over 300 games at the real control, gives **+102 Elo per doubling of
thinking time** (+71 to +136) — well above the textbook 50 to 70. A 10% speed-up is worth about
14 Elo for this engine; that ratio is what every optimisation below was judged against.

Every run is in [docs/RESULTS.md](docs/RESULTS.md) with its game count, interval, terminations and
machine load.

## What did not work

This is the more interesting table.

| Attempt | Result | Where it is written up |
|---|---|---|
| A 768→128 neural-network evaluation, trained on self-play positions labelled by Stockfish | **−67 Elo** (−106 to −29), 300 games at the real clock | [docs/NNUE-NOTES.md](docs/NNUE-NOTES.md) |
| Texel-tuning all 786 evaluation weights by ridge regression | ≈ −100 Elo, 300 games; validation error had fallen by a quarter | [docs/DECISIONS.md](docs/DECISIONS.md) |
| A seven-change "v2.0" bundle | **−42 Elo** (−74 to −10), 400 games | [docs/RESULTS.md](docs/RESULTS.md) |
| The same bundle minus its evaluation change — six search techniques: razoring, SEE pruning in the main search, internal iterative reduction, capture history, countermoves, a bigger evaluation cache | **−20 Elo** (−52 to +12), 400 games | `mikhail_letal/search.py`, five gates off |
| Rewriting `attacked()` to walk the piece lists instead of scanning rays | 4.85× **slower** than the version it replaced | [handoff/FINDING-attacked-piece-list.md](handoff/FINDING-attacked-piece-list.md) |

The network is the one worth reading about. Four separate checks said it would win, including one
built specifically to escape the circularity of the other three — outcome correlation against
12,000 held-out positions from 9,200 real ladder games, with no engine anywhere in the target. All
four were wrong. The finding is not about the network; it is that **we have no cheap proxy for
playing strength**, so every idea costs a 2.4-hour match to evaluate and cannot be iterated on.

The bundle is the second lesson, and it is the sharper one. The repository's own rule is that
changes are screened one at a time; with one screening slot left before the deadline, seven went
in together. The result was a single negative number that could not be attributed to any of them.
Reverting only the evaluation change and re-screening the remaining six moved it from −42 to −20
and still told us nothing about which one was responsible.

Five of those six are still in the tree, behind gates set to `False`, each with its published Elo
gain in the comment above it. The sixth — a sixteen-times-larger evaluation cache — was screened
on its own afterwards and kept, because on its own it was worth 0.9% of the node rate, about
1.4 Elo. That is the whole difference between the two halves of this story: one number per change.

## Where it actually loses

Traced game by game against Stockfish at depth 18, across eight losses on the competition ladder:
the evaluation is wrong by 200 to 670 centipawns for 15 to 25 consecutive moves, and the search
faithfully finds the best move inside a wrong picture. Measured move quality is 26–38 centipawns
of average loss per move with 1.8–4.5% outright blunders; the top five engines on that ladder ran
4.8–18.8 with 0.0–0.9%.

So the gap is not depth and it is not speed. It is that a hand-written evaluation of about a dozen
terms — material, piece-square tables, eight pawn-and-rook structure weights, a king-danger term
and a mop-up term — cannot see what a learned one sees, and the one attempt at a learned one lost
67 Elo. That is the honest state of it. The write-ups in [handoff/](handoff/) walk through the specific
positions.

## Playing against it

There is a small web app for playing, watching and analysing games. It runs locally with no
external dependencies, and it drives the engine through the same runner and clock the competition
uses, so what you see is what the ladder sees.

```
git clone https://github.com/urvancev06/chessathon
cd chessathon
uv sync
uv run python -m tools.webapp.server
```

Then open http://localhost:8000. The first move takes about thirty seconds while numba compiles;
after that it is at full speed for the rest of the process's life.

![Playing the engine](docs/images/play.png)

Every move it plays comes with the report it wrote about itself: the depth it reached, how many
positions it looked at, and where its time budget went.

![The evaluation weights](docs/images/weights.png)

The Weights screen reads `weights/pst.json` directly, so the twelve heatmaps are the numbers the
engine is actually using. It is the fastest way to see what it values and where the generator's
formula produced something odd.

![Analysing a finished game](docs/images/analysis.png)

If you have Stockfish installed locally, any finished game can be graded move by move: accuracy
and average centipawn loss per side, the evaluation curve, and what the engine should have played
at each ply.

Without the web app:

```
uv run python -m harness.play --white . --black baselines/minimax          # one game
uv run python -m tools.arena_openings --opponent versions/v1.4 --games 100 # a measured match
uv run python -m pytest -q                                                 # 693 tests
```

## Layout

```
agent.py              the entry point: safety wrapper, time budget, game history
mikhail_letal/        the engine. search.py and evaluation.py are the readable specification;
                      fastsearch.py, fasteval.py and fastboard.py are the compiled port that ships
weights/              the generated tables, with their provenance
tools/                table generator, opening collector, arena, Texel tuner, trainer, the web app
app/                  the web app's front end
tests/                unit, property and regression tests
docs/                 design, decisions, results, provenance, calibration, the report
handoff/              per-game post-mortems and one-off findings, including the ones that killed ideas
versions/             every uploaded build, kept as an opponent for the next one
baselines/            the starter's reference opponents
harness/              the competition's local harness (from the starter repo, unmodified)
```

`main` is one step past the submission. `versions/v1.4/` holds the build that actually played,
byte for byte; `main` carries the same engine plus five extra search techniques whose gates are
`False` because they did not clear the promotion bar. `mikhail_letal/__init__.py` says
`1.5.0-dev` for that reason.

[docs/DESIGN.md](docs/DESIGN.md) is the module contract everything was written against.
[docs/DECISIONS.md](docs/DECISIONS.md) records each decision with the alternative that was
rejected and why. [docs/PROVENANCE.md](docs/PROVENANCE.md) says where every constant came from.
[docs/report.tex](docs/report.tex) is the long-form write-up and
[docs/STRATEGY.pdf](docs/STRATEGY.pdf) is the plain-language one.

## What I would do next

Not another search technique. The measured ceiling is the evaluation, and the five techniques
sitting at `False` in `search.py` are the evidence: five standard, individually well-attested
improvements, screened together, worth nothing. Screen them one at a time at the real clock and
some of them are probably worth 10 to 25 Elo each — but that is 2.4 hours of games per answer, and
it does not touch the 200-to-670-centipawn blindness that actually loses the games.

The real list, in order of what the measurements point at:

1. **Fix the instrument before fixing the engine.** Every failed idea this week failed because
   there was no cheap, trustworthy predictor of playing strength. Until a proxy exists that
   survives a test against a screen it did not see, every idea costs 2.4 hours.
2. **A learned evaluation, done properly.** −67 Elo is not proof it cannot work; it is proof that
   *that* net, trained on *those* positions, did not. The diagnosis in
   [docs/NNUE-NOTES.md](docs/NNUE-NOTES.md) is specific: both evaluations are three to four times
   worse at search leaves than at game positions, and every metric used to select the net was
   measured on game positions. Train and validate on leaves.
3. **King safety.** The one evaluation term whose absence shows up directly in the traced losses.
   An earlier attempt at it is in [handoff/FINDING-king-safety.md](handoff/FINDING-king-safety.md).
4. **Bitboards with magic move generation**, several times faster again than the 0x88 mailbox and
   now safe to attempt, because there is a proven engine and a 693-test suite to check against. At
   +102 Elo per doubling, a 2× node rate is worth 100 Elo.

Known weaknesses, all measured rather than guessed: there are no tablebases and no opening book (a
3–4 man Syzygy set was tried and measured at about 0.03 points a game, see
[handoff/FINDING-tablebases.md](handoff/FINDING-tablebases.md)); the evaluation has never been
successfully tuned or learned; a queen ending that needs every ply before the referee's 600-ply cap
is still on a knife edge; and the compiled build's strength is known only relative to the build
before it.

## Notes

Every design decision here is written down with the alternative that was rejected, and every
constant can be traced to the script or the run that produced it. That is what
[docs/DECISIONS.md](docs/DECISIONS.md) and [docs/PROVENANCE.md](docs/PROVENANCE.md) are for.
Nothing shipped that had not won a measured match against the version before it, and nothing that
lost one was deleted from the record.

Stockfish appears in this repo only as a measuring instrument: a sparring partner for rating
estimates, an analysis engine in the web app, and a labeller for two evaluation experiments that
both failed. It is not shipped, not consulted at runtime, and its source was never read.

Credits: the harness, the baselines and the original starter code are from
[advitrocks9/aichessathon-starter](https://github.com/advitrocks9/aichessathon-starter), MIT
licensed, and `harness/` is unmodified because local results are meaningless otherwise. The board
pieces in the web app are Colin M.L. Burnett's cburnett set, CC BY-SA 3.0. Everything else is MIT
licensed; see [LICENSE](LICENSE).
