# Finding: no king-safety term, and it lost us round 70

Written 2026-09-08 from the rated ladder games. Analysis by Stockfish 18 at depth 20, multipv 3
(`tools/webapp/analysis.analyse_game`); reproductions by our own engine at HEAD `3f142e4`.

Raw data kept: `data/pgn/ladder/*.pgn` (the PGNs as the platform published them),
`handoff/round70-analysis.json`, `handoff/round68-analysis.json`.

## The game

Round 70, we are Black against **Vanish Onigiri**, Caro-Kann Exchange, **lost by checkmate on
move 30** — 23 of our moves. Our first ladder loss.

| | us | them |
|---|---|---|
| ACPL | **113.1** | 62.2 |
| accuracy | 83.9% | 90.7% |
| blunders / mistakes / inaccuracies | 1 / 0 / 3 | 0 / 1 / 2 |
| clock spent | 41.3 s of 131.5 s available | 59.5 s |
| **clock left at the end** | **90.2 s** | 72.0 s |

## What happened, in evaluations (our point of view)

| our move | played | eval before → after | cp lost | Stockfish wanted |
|---|---|---|---|---|
| 8… | `O-O-O` | −24 → −93 | 69 | `e6` |
| 9… | `Bf5` | −99 → −197 | 98 | `Bxf3` |
| 10… | `a6` | −195 → −359 | 164 | `Qe6+` |
| 13… | `Nh5` | −465 → −577 | 112 | `Ng4` |
| … | | drifts to −672 by move 16 | | |
| **16–19** | | **opponent gives it all back with repeated checks: back to 0.00** | | |
| 20… | `Ne2+` | **0 → −191** | 191 | `fxg5` |
| 22… | **`Nxd4`** | −169 → **−834** | **665** | `Nf4` |
| 24… | `Qf6` | −506 → −911 | 405 | `Kd8` |
| 25… | `h5` | −738 → −1254 | 516 | `Kd8` |
| 30. | | `Rxc6#` | | |

We castled long into a queen that was already on b3, were duly torn open by `Bb5`/`Ne5`/`Bxc6`
and `Qxa6+`, and were lost by move 16. The opponent then handed the entire advantage back with
a series of checks — **at our move 20 the position was dead level at 0.00** — and we lost it
again immediately.

## It is not a time-management failure

The two critical positions, replayed with our own engine at four budgets. Platform seconds are
converted to local seconds by the measured **2.3× speed factor** in `docs/CALIBRATION.md`:

| platform budget | local | move 20 (played `Ne2+`, best `fxg5`) | move 22 (played `Nxd4`, best `Nf4`) |
|---|---|---|---|
| 1.8 s *(what it actually spent)* | 0.78 s | `Ne2+` d7 | `Nxd4` d6 |
| 3.4 s *(its own soft budget)* | 1.48 s | `Ne2+` d7 | `Nxd4` d6 |
| 10 s *(its hard cap)* | 4.35 s | `Ne2+` d8 | `Nxd4` d6 |
| **30 s** | 13.0 s | **`Ne2+` d10** | **`Nxd4` d8** |

**At every budget, up to sixteen times what it spent, it plays both losing moves.** At move 22 it
scores `Nxd4` at **+305 for itself** while Stockfish has the position at **−834**. An eleven-pawn
disagreement that more search does not close, because the engine is not looking for the thing that
refutes it.

## It is a king-safety failure

`mikhail_letal/evaluation.py` has exactly one king-safety term:

```
"king_shield": 10,   # per own pawn on the king's file or its neighbours, one or two ranks
                     # ahead of the king. Middlegame only.
```

There is no king-*danger* term of any kind — no attacker count, no weighting by attacking piece,
no penalty for an open or half-open file bearing on our own king, no piece tropism.
`grep -in "king_danger|king_attack|king_zone|tropism" mikhail_letal/evaluation.py` returns nothing.

Both losing decisions are the same mistake in two shapes:

- **`22…Nxd4`** wins a pawn and invites `cxd4`, which opens the c-file straight onto our own king
  on c8. The mate arrives eight moves later down that file: `Rac1`, `Rb3`, `Rb7+`, `Rxc6#`.
- **`8…O-O-O`** walks the king toward a queen already posted on b3. The shield term reads the
  position as safe — a7, b7 and c7 were all still there — which is exactly the configuration
  `Bxc6` and `Qxa6+` were about to dismantle. A pawn count cannot see an attack coming.

At the platform's depth of 5–8 plies the mate is over the horizon, so the evaluation is the only
thing that could have flagged it, and it has nothing to say about the danger.

## It survives v1.0, the compiled engine

Re-run after `074c7bb` landed, driving `versions/v1.0` through the real `get_move(fen, time_left_ms)`
contract with the clock our engine actually held at each of those moves. "Platform-equivalent"
divides that clock by the 2.3x speed factor, since this Mac is that much faster than the ladder core.

| move | cp lost | v0.2 (interpreted, d6-8) | **v1.0 (compiled, platform-equivalent)** | v1.0 (full local clock) |
|---|---|---|---|---|
| `20...Ne2+` | 191 | blunder | **blunder, depth 12** | blunder, depth 13 |
| `22...Nxd4` | **665** | blunder | **blunder, depth 9** | `Rd6`, depth 10 (avoids it) |
| `24...Qf6` | 405 | blunder | **blunder, depth 11** | blunder, depth 11 |

Measured node rate in those searches: **1.00-1.08 M nps**, against roughly 66 k for the interpreted
engine. Cold start with the numba cache wiped: **11.2-11.5 s**, `skipped 0`, which is about 26 s at
the 2.3x factor against a 90 s budget.

**Sixteen times the node rate and four to five extra plies change none of the three decisions.** That
closes the question this document previously left open. It is not a horizon failure that depth
dissolves; the search is not failing to look far enough, it is failing to know what to look for.
The defect is in the evaluation, and `fasteval.py` inherits it verbatim: its own docstring says
"This is a *port*, not a redesign. Every term, every weight and every rounding decision is the one"
of `evaluation.py`, and its only king term is `W_KING_SHIELD`.

## RETRACTED: the verdict below is not supported by its own evidence

See `handoff/FINDING-replay-invalid.md`. The table below rejects four terms because "every one
still plays all three losing moves". That comparison assumed the baseline reliably plays those
moves. It does not: the search is bounded by wall clock, so the node budget moves with machine
load and the move moves with it. The same version, same position, same clock produced `f7e7`,
`f7c7` and `f7g7` on three consecutive runs — the blunder and the best move both inside the spread.
The baseline is a coin flip, so the comparison carries almost no information.

**What still stands** (none of it depends on replaying a search):

- `fasteval.py` has `W_KING_SHIELD` and no king-danger term. Code inspection.
- The two rated games were lost by the moves named here. That is Stockfish's grading of moves the
  engine *actually played on the platform*, not a replay.
- All four variants compile, and their Python-vs-compiled parity holds over 20 000-72 000 positions.
- The node-rate costs, which were measured by interleaving base and variant.
- The virtual-mobility diagnosis: for the black king on c8 the count is 6 before the move, after it,
  and after the correct move alike. That is arithmetic on the position, not a sampled search.

**What falls:** the verdict "none of these fixes the defect". The four terms were sampled a handful
of times each from a distribution wide enough to contain both the blunder and the best move.
**They were not measured.** Deciding between them needs a match, or a fixed-node search switch that
makes a position replayable in the first place.

## Four king-danger terms ported to the compiled evaluation: the runs, now retracted as a verdict

Four candidate terms were written into isolated copies of v1.0 (`variants/v10-{expo,units,files,storm}`),
each added to **both** `evaluation.py` and `fasteval.py`, then independently audited by a second
agent that re-ran every claim with its own scripts.

| variant | idea | py-vs-compiled agreement | nps cost | plays 20 / 22 / 24 |
|---|---|---|---|---|
| `expo` | king virtual mobility + queen proximity | 44 558 positions, 0 mismatches | +4.9 % | `Ne2+` / `Nxd4` / `Qf6` |
| `units` | weighted attacker units, quadratic | 20 000, 0 mismatches (+ repo gate, 283 tests) | +4.0 % | `Ne2+` / `Rd6` / `Qf6` |
| `files` | open lines toward the king | 72 314, 0 mismatches | +3.5 % | `Ne2+` / `Nxd4` / `Qf6` |
| `storm` | shield deficit + pawn storm | 20 000, 0 mismatches | **-0.6 %** | `Ne2+` / `Nxd4` / `Qf6` |

Baseline v1.0 plays `Ne2+` / `Nxd4` / `Qf6`. **Every variant reproduces every blunder.** The one
deviation, `units` playing `Rd6` at move 22, its own fixed-depth control showed is not attributable
to the term. Audits confirmed all four: gates genuinely exercise the compiled path, all are really
shield-gated, **no overfitting to the three positions** in any of them.

So the terms are cheap, correct, and do not fix what they were built for. Recorded as a negative
result rather than quietly dropped.

**Why, and this is the useful part.** For the black king on c8 the virtual mobility is **6 — exactly
the floor — both before and after `22...Nxd4 23.cxd4`, and also after `22...Nf4`.** The king sees
a6, a8, b7, b8, c7, d7 and nothing else: its own rook on d8 blocks east, its own pawn on c6 blocks
south, its own queen on e6 blocks the diagonal. Opening the c-file happens *behind* the c6 pawn from
the king's point of view, so the count never moves. The entire penalty came from the
queen-distance half, which is identical for every candidate move and so discriminates nothing.

**King-exposure terms measure where the king could walk. The danger here was a half-open file an
enemy rook could arrive down — and the king's own crowding pieces suppress the exposure count
exactly when that danger is worst.** That is a structural blind spot in the whole family, not a
weight that needs tuning.

None of these has been played in games. They are cheap enough to be worth an arena run on their own
general merits, but there is no evidence any of them addresses this defect.

### Two measurement traps found on the way, both worth keeping

1. **Sequential benchmarking on this machine is worthless.** The *unmodified* base measured
   1 090 179 nps and 940 895 nps on the same position twenty minutes apart — a 14 % spread. A first,
   non-interleaved reading put one term's cost at 15.9 %; that was drift, not the term. Every number
   above alternates base and variant in fresh subprocesses.
2. **Adding a field to the `EvalTables` NamedTuple is not free.** `ev` is threaded through every
   recursive call of the compiled search, so each extra array is more words pushed at every call
   boundary — paid by every node whether the term runs or not. Moving the new tables to module-level
   numpy globals (the pattern `fastboard` already uses for its direction tables) recovered several
   per cent.

## Suggested next step, for whoever picks it up

A king-danger term is the highest-value evaluation addition on the table, and it is the only one
whose absence shows up in a lost game rather than in a hunch. The cheapest defensible version, all
computable from bitboards already present in `evaluation.py`:

- attacks by enemy pieces into the 3×3 zone around our king, weighted by attacker type;
- a penalty for an open or half-open file through the king's file, scaled by enemy heavy pieces on it.

Both are middlegame terms and should taper out like `king_shield` does.

## What was tried on the interpreted engine, and what it cost

Four shapes of the term, each built as a copy under `variants/` and probed with `handoff/probe.py`.
Node rates are 3 s searches from the start position and from a busy middlegame.

| variant | idea | nps (start / middle) | verdict |
|---|---|---|---|
| baseline | — | 60.5k / 66.0k | — |
| `ks1` | open and half-open files on and beside the king | 50.6k / 51.0k (**-16% / -23%**) | too dear, and the wrong polarity: after `cxd4` the c-file still holds *our* pawn on c6, so "no own pawn" never fires |
| `ks2` | king virtual mobility (queen-from-king) + queen tropism | 54.5k / 51.0k (-10% / -23%) | too dear |
| **`ks3`** | `ks2`, **skipped while the king still has >= 2 shield pawns** | **61.5k / 62.5k (-0% / -5%)** | the only affordable one |
| `ks5` | weighted attacker units into a quadratic danger table (the textbook approach), attackers taken free from the king's own line of sight | 47.0k / 48.7k (**-22% / -26%**) | too dear, and no better |

The one transferable lesson is the **shield gate**: skipping the whole term while a king still sits
behind two of its own pawns takes the cost from -23% to -5%, because in ordinary middlegames it then
never runs at all. Any port to `fasteval.py` should keep that gate.

A weight sweep on `ks3` (exposure 6 -> 14 -> 24 -> 40) moved `Nxd4`'s score monotonically down
(+172 -> +290 -> +93 -> +33) without ever flipping the move, because the alternatives score badly
too. Position probes turned out to be a weak proxy and no variant was ever measured in games: the
arena screens were queued against the interpreted engine and cancelled unstarted when v1.0 landed,
so **nothing here has an Elo number attached to it.**

## Caveats, stated plainly

- **n = 1.** One loss. This is a hypothesis with a mechanism and a reproduction behind it, not a
  measured Elo claim. It earns a match, not a commit.
- **No variant has been measured in games, and none has been ported to the compiled evaluation.**
  `ks3` is a Python-side prototype against an engine that has since been superseded.
- The reproductions convert platform time by the single 2.3x factor from `docs/CALIBRATION.md`,
  which was measured on search node rate, not on everything the engine does.
- The reproduction uses this Mac's speed scaled by 2.3; the platform's actual search may differ in
  detail even at the same nominal budget.
- We also finished this game with **90 of 131 seconds unused**, because `moves_to_go` starts at 40
  and the game lasted 23 moves. It cost nothing here — more time does not fix these moves — but it
  is the same constant that starved round 68 to 4.1 s. Noted, not conflated.
