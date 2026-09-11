# The documents

What each file is for, and which one to open first depending on what you want.

## If you want to understand the engine

- **[DESIGN.md](DESIGN.md)** — the module contract. Every signature, every convention, and the
  behaviour each module owes the others. This was written before the code and the code was written
  against it, so it is the fastest way in.
- **[report.tex](report.tex)** ([PDF](report.pdf)) — the long-form write-up: the competition, the
  architecture and why, each search technique with the evidence for it, the evaluation, time
  management, endgames, safety, testing, the rating estimate, and the limitations. Eighteen pages.
  Compile it with `make report`.
- **[WEBAPP.md](WEBAPP.md)** — the local web app: what each screen shows, what the numbers in the
  thinking strip mean, where games are saved.

## If you want to know why something is the way it is

- **[DECISIONS.md](DECISIONS.md)** — every design decision, in order, with the alternative that was
  rejected and why. Including the ones that failed: the Texel tuning that fit the data better and
  lost 300 games is here.
- **[PROVENANCE.md](PROVENANCE.md)** — where every constant in the shipped engine came from. The
  machine-readable version that ships beside the code is `weights/PROVENANCE.json`.

## If you want to know what did not work

- **[NNUE-NOTES.md](NNUE-NOTES.md)** — the trained evaluation, written before the screen ran so
  that it is a prediction rather than a reading of a result already in hand. It lost 67 Elo, and
  the finding is not about the network: four separate checks said it would win, including one
  built specifically to escape the circularity of the other three. The conclusion is that we have
  no cheap proxy for playing strength.
- **[../handoff/](../handoff/)** — per-game post-mortems against Stockfish at depth 18, and the
  one-off findings that killed ideas: the piece-list rewrite that came out 4.85× slower, the
  tablebases worth 0.03 points a game, the king-safety term, the cost of every evaluation term
  considered.

## If you want the numbers

- **[RESULTS.md](RESULTS.md)** — every measurement, appended in the order it was taken. Arena runs
  carry their game count, confidence interval, terminations and the machine load at the time,
  because a match played while eleven others share the machine measures something different from
  one played alone.
- **[CALIBRATION.md](CALIBRATION.md)** — how the time-management constants are tied to what the
  competition platform actually measured, and the procedure for updating them from a validation
  log.
- **[INTEGRATION_NOTES.md](INTEGRATION_NOTES.md)** — what the first integration pass found and
  fixed. Mostly of historical interest now.

## If you want the story rather than the engineering

- **[STRATEGY.tex](STRATEGY.tex)** ([PDF](STRATEGY.pdf)) — written for a reader who is not a chess
  programmer: where the engine stands, why the network was expected to help and did not, and what
  would actually be worth doing next.
- **[PLAN.md](PLAN.md)** — what was planned on 8 September, kept unrevised. The gap between it and
  what happened is the point.

## If you are the person submitting

- **[SUBMISSION_GUIDE.md](SUBMISSION_GUIDE.md)** — what to upload, how to verify it, what to do
  with the validation log, and what to say to a judge.
- **[UPLOAD-v0.1.md](UPLOAD-v0.1.md)** — the note that accompanied the first build. Kept as a
  record of what was known at the time.

## Inherited from the starter repository

- **[IDEAS.md](IDEAS.md)** — the organisers' own notes on where engine strength comes from. Not
  ours, but it shaped the plan and is worth reading before arguing with any of it.
