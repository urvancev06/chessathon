# The three-position replay is not a valid test

Both jobs in `handoff/NEXT-SESSION.md` assumed a stable baseline: *"v1.0 plays the losing move in
all three — that is the baseline to beat."* It does not. Two measurements below retire that
baseline, and with it the method that produced the king-safety negative result.

## 1. The search is not deterministic

The same version, the same position, the same clock, the same machine, three runs:

| run | R75 move 47 (v1.0, warm replay, platform-equivalent clock) |
|---|---|
| first | `f7e7` |
| second | `f7c7`  ← the move that threw the game |
| third | `f7g7`  ← Stockfish's move |

Three different moves, one of them the blunder under investigation and one of them the best move
in the position. Nothing was changed between runs.

The cause is structural, not a bug: the search is bounded by wall clock, so the node budget moves
with whatever else the machine is doing, the last completed iteration changes, and the move
changes with it. The platform has the same property. A single replay of a single position is
therefore a coin flip, and **a test that runs one position once cannot distinguish two versions.**

## 2. The replay does not reproduce the rated-game moves

Two methods were tried against v1.0, the version whose games these are.

*Cold* — the position alone, `STATE.__init__()` and `ENGINE.new_game()`, nothing else. This is the
method `NEXT-SESSION.md` specifies.

*Warm* — walk the game from its `start_fen`, call `get_move` at every one of our turns with that
turn's real clock (`clock_after` of the previous own move, plus the 500 ms increment), so the
transposition table and the repetition history match what the engine actually held. Note
`clock_after` in the analysis JSONs is in **seconds**; the ms figures in `NEXT-SESSION.md`'s table
are the clock *after* our move, not before it.

| position | played in the rated game | v1.0 cold | v1.0 warm |
|---|---|---|---|
| R76 move 22 | `e5c4` (Nxc4, −295) | `f8e8` | `f8e8` |
| R70 move 22 | `e2d4` (Nxd4, −834) | `e2d4` ✓ | `d8d6` |
| R75 move 47 | `f7c7` (Rc7, threw a win) | `f7g7` | `f7e7` / `f7c7` / `f7g7` |

The warm replay — the more faithful of the two — reproduces **none** of the three game moves. The
cold replay reproduces one. Whatever these replays are measuring, it is not the decision the
engine made in the rated game.

## 3. What this costs

`handoff/FINDING-king-safety.md` rejects four king-danger terms because *"every one still plays
all three losing moves."* That verdict rests on a test whose control does not play the losing
moves either, and whose output varies run to run. **The four variants were not measured. They were
sampled once each, from a distribution wide enough to contain both the blunder and the best move.**

This does not mean the variants were good. It means the evidence against them does not exist, and
the structural argument in that document — that the evaluation has no king-danger term, only
`W_KING_SHIELD` — stands on its own reasoning rather than on those runs.

## 4. What v1.1 does, stated honestly

Across 30 searches (both versions, both replay methods, platform-equivalent and full clocks), the
losing move appeared 5 times: 3 from v1.0 and 2 from v1.1. Every other search from both versions
found something else. **The replays do not separate v1.1 from v1.0 on these positions**,
and given §1 they could not have, whichever way the numbers had fallen.

The one difference worth recording, because it is consistent across every run: at R75 move 47, the
rook endgame, v1.1 played `f7g7` — Stockfish's move — in 3 of its 4 runs and v1.0 in 4 of its 6.
That is 4 samples against 6, from a position where the same version has been seen to answer three
different ways. It is not a result.

## 5. What to do instead

- **Judge a change by a match, not by a position.** The house rule in `CLAUDE.md` already says
  this. The three positions are useful for *reading* what the engine thinks, not for deciding
  whether a version is better.
- **If a deterministic regression test is wanted, bound the search by nodes, not by time.** Fixed
  depth or fixed nodes removes the clock from the loop and makes a position replayable. That is a
  new switch in the search, and it would be worth having: it is the only way these three positions
  become evidence about anything.
- **Build a king-safety suite, not a king-safety anecdote.** Three positions cannot resolve a term
  worth a few tens of Elo. A tagged set of positions where the opponent is attacking a bare king,
  scored by how often the engine finds the defensive move over many runs, would.

## Reproduce

```sh
mkdir -p /tmp/v10 && git -C ~/chessathon archive origin/main:versions/v1.0 | tar -x -C /tmp/v10
python warm.py /tmp/v10 2.3   # run it three times; watch R75 change
```

`warm.py`, whole, so this travels with the finding:

```python
"""Warm replay: walk each game from its start position, calling get_move on every
one of our turns with the real clock, so the table and history match the rated game."""
import sys, json, time
sys.path.insert(0, sys.argv[1])
SCALE = float(sys.argv[2])  # 2.3 = platform-equivalent, 1.0 = full clock
import agent  # noqa: E402

GAMES = [
    ("R76", "handoff/aichessathon-round-76-jlu.json", "Mikhail LeTal", 22, "e5c4", "a8e8"),
    ("R70", "handoff/round70-analysis.json",          "Mikhail LeTal", 22, "e2d4", "e2f4"),
    ("R75", "handoff/aichessathon-round-75-saucybeans.json", "Mikhail LeTal", 47, "f7c7", "f7g7"),
]
INC = 500
for tag, path, me, target_mn, losing, better in GAMES:
    d = json.load(open(path))
    side = "white" if d["headers"]["White"] == me else "black"
    agent.STATE.__init__(); agent.ENGINE.new_game()
    prev_clock = None
    got = None
    for p in d["plies"]:
        if p["mover"] != side:
            continue
        # clock before our move: previous clock_after plus the increment that landed after it
        clock = prev_clock if prev_clock is not None else 120000
        prev_clock = p["clock_after"] * 1000.0 + INC
        mv = agent.get_move(p["fen_before"], max(1000, int(clock / SCALE)))
        if p["move_number"] == target_mn:
            got = {"game": tag, "scale": SCALE, "move_number": target_mn, "clock_used": int(clock / SCALE),
                   "played_in_game": p["uci"], "replay_move": mv,
                   "losing": mv == losing, "sf_best": mv == better}
            print("RESULT " + json.dumps(got), flush=True)
            break
    if got is None:
        print("RESULT " + json.dumps({"game": tag, "error": "target move not reached"}), flush=True)
```
