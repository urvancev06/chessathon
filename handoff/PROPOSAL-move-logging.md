# Logging why the engine chose a move

Yan's question, 2026-09-08: does the bot record *why* it played a move, and if not, what is the
best way to store it so games can be analysed afterwards?

**It records how hard it thought, but not what it thought.** Below: what exists, the constraint
that shapes any answer, and the change I would make.

## What exists today (v1.0, `agent.py`)

One line per move, via `_say`, on stdout — which the runner points at the log the platform keeps
per team:

```
m e2e4 d 12/30 n 805926 nps 1001883 t 805 s 1497 h 4491 c 44036
```

Move, depth/seldepth, nodes, node rate, milliseconds spent, soft and hard budget, clock before the
move. About 60 bytes. Plus one-off lines for the warm-up, desync, guard rejections and fallbacks.

**What is missing is the entire "why".** There is no score, no principal variation, no runner-up
move, no sign of whether the choice was close or forced. Today, establishing that the engine played
`22...Nxd4` believing it was **+305** while the truth was **-834** required re-analysing the game
with Stockfish and reproducing the position by hand. One extra token per line would have shown it
directly.

## The constraint that decides the format

From the agent contract:

> Your output is kept after validation and after every rated game, in a log only your team can read.
> **Only the first 4 KB and the last 4 KB survive it.**

And the filesystem is read-only apart from `/tmp`, which is wiped between games. So on the platform
stdout is the only channel, and the budget is 8 KB per game.

The arithmetic matters:

| bytes per line | lines that survive | longest game logged whole |
|---|---|---|
| 60 (today) | ~136 | ~136 moves |
| 90 | ~91 | ~91 moves |
| 120 (`_say`'s cap) | ~68 | ~68 moves |

Our games run long: round 68 was 113 of our moves, round 71 was 105. **Both of the games where our
time management failed were long ones**, so losing the middle of long games is exactly the wrong
trade. There is roughly **30 bytes per move of headroom** before that starts happening. Spend it
deliberately.

## What I would add, in order of value per byte

**1. The score. (~8 bytes: `e +305`)** The single highest-value field on this list. It converts
every post-game analysis from "re-run Stockfish and guess what it was thinking" into a direct
reading of what it believed. The blunder list becomes a subtraction.

**2. A surprise marker. (~6 bytes, and only on the moves that need it)** Keep the score the previous
search expected for this position (it is the second move of the last principal variation). On the
next move, compare. A large unexplained drop means either we blundered or they found something, and
either way it is the move worth looking at.

This is not hypothetical — it is precisely the shape of round 71's endgame:

```
+366 -> +93 -> +497 -> +131 -> +464 -> +110 -> +530 -> +90 -> +474 -> +48
```

Seven king moves, each throwing away 170-440 cp, each followed by the opponent giving it back. The
engine could have flagged every one of those itself, at the moment it happened, for six bytes.

**3. The runner-up and its margin. (~12 bytes: `2 Rb6 -35`)** A move chosen by 5 cp over the
alternative is a different animal from one chosen by 300, and the log cannot currently tell them
apart. This is what says whether a term change would have flipped the decision.

**4. The principal variation. (~25 bytes)** The most diagnostic and the most expensive. Do not log
it on every move — log it only on moves flagged by (2).

That is the design: **a compact line always, a verbose line only when something surprising
happened.** Bytes land where the diagnosis is, and the budget survives a 130-move game.

## Format: keep space-separated tokens, do not switch to JSON

Three reasons, and the first is decisive:

- **Truncation.** The platform cuts the middle out of the log. A truncated JSON array is
  unparseable and you lose the whole file; a truncated token log loses exactly the lines that were
  cut and every surviving line still reads.
- **Size.** Keys and quotes and commas cost roughly 40 % more bytes for the same fields, and the
  budget is the whole problem.
- **Tooling.** `grep`, `awk` and `sort` work on it now, with no parser to write.

The existing format is already the right one. It just needs more in it.

## The bigger win is local, where there is no 4 KB limit

On our own machines nothing is truncated, and this is where the leverage is.

**Write the engine's own numbers into the PGN as comments, beside the clocks the platform already
gives us:**

```
22... Nxd4 { [%clk 0:01:33.955] [%eval +3.05] [%depth 9] }
```

`python-chess` reads and writes `[%eval]` natively — `GameNode.eval()` returns a `PovScore`, and
`GameNode.set_eval()` writes it (verified). So this costs almost nothing and every existing tool
understands it immediately: `tools/webapp/analysis.py` already calls `node.clock()` on the same
nodes, and any PGN viewer will render the evaluation curve.

**Why this is the one to build.** It puts the engine's own score and Stockfish's score on the same
move, in one file. The difference between them, sorted descending, **is the blunder list** — no
manual reproduction, no guessing what the engine saw. That single subtraction is what the whole of
today's round 68, 70 and 71 analysis was doing by hand.

Where to attach it:

- `tools/arena_openings.py` already takes `--pgn-dir`, and `harness/sandbox.py` already captures the
  agent's output as `stderr_log`. Parsing the `m ... e ...` lines back and stamping them onto the
  PGN nodes closes the loop for every local game.
- For rated games, the platform's PGN (with `[%clk]`) and the team log (with our lines) are two
  halves of the same record; joining them on move number gives the same file.

## Cost and risk

The per-move cost is a formatted string, on a move that already took 800 ms. Nothing here touches
the search. The one real risk is byte budget, which is why (2) and (4) are conditional rather than
unconditional, and `_say`'s 120-byte cap already bounds the worst case.

Worth doing before more rated games are played, because every game played without it is a game that
has to be diagnosed the hard way.
