# Submission guide — Mikhail LeTal

Everything you (the operator) do by hand, in order. Claude never touches your accounts.

## 0. What you are submitting

- **Build:** v0.2.1, git tag `v0.2.1`, commit `f3392bf`, on https://github.com/urvancev06/chessathon. Engine identical to tag `v0.2`; only comments and docs differ.
- **File:** `submission.zip` in the repo root (`~/dev/chessathon/submission.zip`), 35 087 bytes,
  106 035 bytes unzipped, sha256 `4f3ac2e27dcacee259eedaab745f8e43e3b629c917044095a3b0839fce46e280`.
  Check it with `sha256sum submission.zip` before uploading.
- **Contents (nine files, `agent.py` at the root):** `agent.py`, `mikhail_letal/__init__.py`,
  `evaluation.py`, `search.py`, `timing.py`, `gamestate.py`, `fallback.py`, `weights/pst.json`,
  `weights/PROVENANCE.json`. Nothing else. No binaries, no network, no third-party engine.
- **What it is:** a Python 3.12 engine on python-chess: alpha-beta search with iterative
  deepening, transposition table, quiescence, null-move pruning, late-move reductions,
  aspiration windows, futility and delta pruning, killer and history ordering; tapered
  material + piece-square evaluation from our own generated tables plus pawn-structure,
  bishop-pair, rook-file and king-shield terms; time management from the clock; repetition,
  fifty-move and 600-ply awareness; a wrapper that can never crash or play an illegal move.

## 1. Upload (10 per day allowed)

1. Sign in at https://aichessathon.com, open your dashboard.
2. Upload `submission.zip`. The platform builds it and plays two smoke games (one per colour).
3. Read the validation log it publishes: init time, every per-move time, clock left, stderr.
   Our engine prints one line per move: `m <move> d <depth>/<seldepth> n <nodes> nps <rate>
   t <ms used> s <soft budget> h <hard budget> c <clock before the move>`.
4. Paste the whole log to Claude. That log calibrates the time constants (`docs/CALIBRATION.md`).
   If any move shows `t` far above `h`, or init above 20 s, say so first.

If validation fails, the previous valid build keeps playing; nothing is lost. Paste the log anyway.

## 2. What to expect on the ladder

- Rated rounds run hourly 08:00–22:00 London. A new build starts with a provisional rating.
- Locally v0.2 beat the starter's minimax baseline 39–1 and beat our own v0.1 by roughly
  300 Elo at the real clock. A fast-clock reading against rating-limited Stockfish put v0.1 at
  about 1500–1850 on Stockfish's scale; v0.2 is stronger, but the number for v0.2 has not been
  measured yet. Treat every rating as an estimate until the ladder reports one.
- Uploads close **Thursday 11 September 11:00 London (12:00 in Spain)**. The last valid build
  plays the 13-round Swiss that afternoon. Only the Swiss counts for qualification.

## 3. Rebuilding the zip yourself (if ever needed)

```
cd ~/dev/chessathon
git checkout v0.2            # or main for the latest
uv run python -m harness.package
unzip -l submission.zip      # nine files, agent.py at the root
sha256sum submission.zip
```

`harness.package` also plays two local smoke games from the zip; it must end with
"Nothing here fails".

## 4. Verifying the engine locally

```
uv run python -m pytest -q                       # 220 tests, about 45 s
uv run python -m harness.play --white . --black baselines/minimax   # one real-clock game
uv run python -m tools.arena_openings --opponent versions/v0.1 --games 40 --workers 4 --real-clock
```

The web app: `uv run python -m tools.webapp.server`, then http://localhost:8000/. Play the
engine, watch it against Stockfish at a chosen Elo, analyse games, read the docs and tables.

## 5. Report for the London final (Saturday 12 September)

`docs/report.tex` is the walk-through script: compile with `make report` (uses `latexmk`;
`tectonic` or Overleaf also work). Sections: competition and result; rules compliance and the
memorised-code checks; architecture; board and move generation; search; evaluation; time
management; endgames; safety; testing; rating estimate; limitations. Red `[PENDING …]` markers
show the numbers still to fill (platform validation, ladder rating, Stage 3 rating estimate).

## 6. What to say if a judge asks "did you write this?"

- The code was written with AI assistance, which the rules allow, and every design decision,
  constant and measurement is recorded: `docs/DECISIONS.md`, `docs/PROVENANCE.md`,
  `docs/RESULTS.md`, `weights/PROVENANCE.json`.
- The evaluation tables come from a parametric formula in `tools/gen_pst.py`; they match no
  published engine (compared against Sunfish, the CPW simplified tables, Rustic, TSCP, VICE).
- Stockfish was used only locally, as a sparring partner and analysis tool, never in the zip.
- The web app under `app/` and `tools/webapp/` is a development tool; nothing of it ships.

## 7. After the log arrives (Claude's side)

Calibrate `overhead_ms` and the speed factor, re-run the solo pass, and if anything changes
produce v0.3 with the same promotion rule: it replaces v0.2 only with the 95% interval above
zero at the real clock.
