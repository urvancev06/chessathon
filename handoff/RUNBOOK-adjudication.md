# Runbook: adjudicating the v1.1 bundle match

Written because the session holding this job was renamed mid-evening (`chessathon-bb` →
`chessathon-5f`, socket 640810 → 835276) and, from outside, a renamed peer is indistinguishable
from a dead one. `chessathon-5a` reasonably concluded the session had ended and told the operator
the adjudication had lost its owner. It had not — but it could, and the decision must not depend on
one session surviving to 04:00.

**Everything needed to execute this is committed.** The rule is in `docs/DECISIONS.md`, the
arithmetic is in `tools/promotion_verdict.py`, and the sequence is below. Anyone can run it.

---

## 1. What is being decided

A 300-game real-clock match, `main` against `versions/v1.0`, in three chunks of 100 at seed offsets
0/100/200. It measures **two** changes together — the timing refit (`82b20e2`) and the king-danger
term (`897e1e2`) — which is right for the shipping question and cannot attribute the result to
either half.

## 2. Run the tool. Do not do the arithmetic by hand

```
.venv/bin/python -m tools.promotion_verdict <chunk0>.json <chunk100>.json <chunk200>.json
```

The JSONs are written by each chunk **as it finishes** (`arena_openings` writes at the end of a run,
not incrementally). `chessathon-5a` knows the path; at the time of writing it is
`/tmp/claude-1000/-home-lkmsdx-dev-chessathon/86bc896e-*/scratchpad/runs/chunk{0,100,200}.json`.

The tool enforces the rules rather than trusting the operator of it:

- it **refuses to emit a promotion verdict below 300 scored games** and evaluates only the futility
  test, because interim looks are reject-only (amendment 4);
- it excludes `void` games from `n`, so two voids cannot make 298 games look like the full look;
- it reports **both** safety gates and **announces when they disagree**, which the record requires
  be written up as a finding rather than a footnote.

## 3. The blind second read — do not skip it

`chessathon-64` authored the adopted safety gate **blind** and has seen no figure from this match.
Send it, in this order:

1. **the output with the verdict lines removed** — gates and arithmetic only. Its reasoning, which
   is better than the argument for collapsing the two passes: an arithmetic error pointing toward a
   conclusion it has already read is the hardest kind for it to see;
2. **then the whole thing**, for the holistic read — does the verdict make sense given the
   distribution, does anything in the terminations or the clock shape look unlike the rest of the
   evening.

### 3a. Who the blind reader is, and what to do if there is none

**Primary: `chessathon-64`.** It authored the adopted gate, has seen no figure from this match, and
has confirmed it is standing by with nothing outstanding.

**Most of its contribution has already happened, which lowers the risk here.** Before any data
existed it verified the gate against inputs *constructed to break it* — both sides of the n=100
boundary (2 below passes, 3 fails), the non-integer allowance at n=150, a flag disqualifying despite
a clean clock, and 300 games containing two voids correctly refused as an interim look at 298. Real
data exercises a boundary only by luck, so the gate's **logic** is already independently confirmed.
What the 04:00 pass adds is a check of the specific computation on the real numbers. Valuable, but
not the load-bearing half.

**If no blind reader is available**, run the adjudication alone and **record in the row that the
blind pass did not happen**. Do not have someone who has already seen the numbers perform it and
describe it as a blind review — that is worth less than nothing, because it puts a claim of
independent verification into the record where none exists. An honest "no second reader was
available" costs the row a sentence; a fabricated one costs it its credibility.

## 4. Writing the `RESULTS.md` row — four things it must say

- **Both gates**, with the date each was written, and the underlying distribution: count below
  5 000 ms, count below `panic_ms`, the lowest clock and the **seed** that identifies its game, p10,
  median, terminations. A judge must be able to apply their own threshold instead of trusting ours.
- **If the gates disagree**, that is a finding in the row, not a footnote.
- **The safety gate may turn on one game.** It allows 6 of 300 below 5 000 ms and chunk A's rate
  projects ≈6.3. Whichever side it falls, the outcome carries little information — a pass at 6 and
  a fail at 7 differ by one game and nothing else. The non-marginal figures are **no game below
  `panic_ms`** and **no flag**, which is the floor the safety argument rests on.
- **The row must not read as a fix for round 73.** The bundle addresses neither of that game's
  surviving candidate defects. Round 73 has five refuted explanations and no confirmed diagnosis;
  say so rather than leaving it to inference, because at 04:00 the temptation is to let a promotion
  look like it answered the loss everyone remembers.

## 5. If it promotes

`weights/`, `agent.py` and `mikhail_letal/` are frozen only while the match runs. Once the last
chunk lands, in order:

1. the `weights/PROVENANCE.json` regeneration owed from the hand-edit, plus the `ct-pvs`
   HEAD-restamping fix;
2. the `ct-warmup` merge — blocked by the freeze on two counts, it touches `agent.py` **and**
   `weights/PROVENANCE.json`;
3. freeze with `tools/freeze_version.py`, then the **fuzz gate on the frozen build** — note that
   `chessathon-64`'s session was permission-blocked from launching arena runs, so confirm it can
   before relying on it;
4. upload. The operator wants it as soon as it is frozen, not at the cutoff: ten uploads a day, the
   latest valid one plays, a failed validation costs nothing, and every rated round is a free sample
   of the start-up distribution.

## 6. The rule itself

`docs/DECISIONS.md`, amendments 4 to 7 and the pre-registration above them. Read the **operative
rule restated in full** rather than reconstructing it from the amendments: the safety gate applies
to **all three** Elo cases, the Elo decision is **one look on the pooled total**, and no chunk may
promote.
