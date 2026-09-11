# Submission guide — Mikhail LeTal

> **Historical, 11 September 2026.** The build named below is **v1.0**; this guide was written for
> that upload and its procedure was then followed for v1.1, v1.2, v1.3 and v1.4. **v1.4 was the
> final submission**, and `versions/v1.4/` holds it byte for byte: 14 files, 118,170 bytes zipped,
> 371,893 unzipped. Uploads are closed, so nothing here is an instruction any more -- the checks
> it describes (rebuild, compare contents rather than hashes, smoke the extracted zip) are the
> part worth keeping.

Everything you (the operator) do by hand, in order. Claude never touches your accounts.

## 0. What you are submitting

- **Build:** v1.0, git tag `v1.0`, commit `447adc5`, on https://github.com/urvancev06/chessathon.
  This is the **compiled** engine (numba), not the interpreted v0.2 line.
- **File:** `submission.zip` in the repo root (`~/dev/chessathon/submission.zip`), **14 files**,
  **85 925 bytes**, **269 589 bytes unzipped**, sha256
  `8f98cb73400f18490223f41636a0ad1189da1cd414b04261f16b9355b6ec53a1`.

  **How to use those four numbers, because they are not all the same kind of thing.** The file
  count and the two sizes are decided by the contents, so rebuilding v1.0 from its tag reproduces
  them exactly — if any of the three differs, you are looking at a different build and should stop.
  **The sha256 does not reproduce.** The zip stores each file's modification time, and a fresh
  `git checkout` stamps every file with the time you checked it out, so an identical rebuild has
  identical contents and a different hash. Verified: rebuilding v1.0 from the tag gives the same
  14 files, the same 85 925 bytes, every CRC identical — and a different sha256.

  So use the hash for one thing only: run `sha256sum submission.zip` immediately after building,
  and again before uploading, to prove the file has not been swapped or corrupted in between. **Do
  not treat a hash that differs from the one printed above as a problem** — it only means the zip
  was rebuilt. To prove the zip really is the version you think it is, compare its *contents*:

  ```
  unzip -q -d /tmp/zc submission.zip && diff -r /tmp/zc versions/v1.0 -x '__pycache__'
  ```

  That prints nothing for a correct v1.0 zip, and it is reproducible. It is the real check.
- **Contents (fourteen files, `agent.py` at the root):** `agent.py`; under `mikhail_letal/`:
  `__init__.py`, `evaluation.py`, `fallback.py`, `fastboard.py`, `fasteval.py`, `fastsearch.py`,
  `gamestate.py`, `search.py`, `searchboard.py`, `timing.py`, `warmup.py`; under `weights/`:
  `pst.json`, `PROVENANCE.json`. Nothing else. No binaries, no network, no third-party engine.
- **What it is:** a Python 3.12 engine whose board, move generation, evaluation and search are
  compiled by numba at import, inside the 90 s start-up budget. Alpha-beta with iterative
  deepening, transposition table, quiescence, null-move pruning, late-move reductions, aspiration
  windows, futility and delta pruning, killer and history ordering; tapered material +
  piece-square evaluation from our own generated tables plus pawn-structure, bishop-pair,
  rook-file and king-shield terms; time management from the clock; repetition, fifty-move and
  600-ply awareness; a wrapper that can never crash or play an illegal move.
- **Why `search.py`, `evaluation.py` and `searchboard.py` ship although they never run a rated
  move:** `search.py` is the single home of every shared search constant, which `fastsearch.py`
  imports so the two engines cannot drift, and `evaluation.py` is the oracle the compiled
  evaluation is tested against integer for integer. They are the readable reference a judge reads.

## 1. Upload (10 per day allowed)

1. Sign in at https://aichessathon.com, open your dashboard.
2. Upload `submission.zip`. The platform builds it and plays two smoke games (one per colour).
3. Read the validation log it publishes: init time, every per-move time, clock left, stderr.
   Our engine prints one line per move: `m <move> d <depth>/<seldepth> n <nodes> nps <rate>
   t <ms used> s <soft budget> h <hard budget> c <clock before the move>`.
4. Paste the whole log to Claude. That log calibrates the time constants (`docs/CALIBRATION.md`).
   If any move shows `t` far above `h`, or init above 20 s, say so first. Init is the one to watch
   on this build: the numba warm-up is what fills it. The only cold-start measurement we have is
   11.2–11.5 s on a development Mac (`handoff/FINDING-king-safety.md`), against a 90 s budget —
   the platform's core is slower, and this log is how we find out by how much.

If validation fails, the previous valid build keeps playing; nothing is lost. Paste the log anyway.

## 2. What to expect on the ladder

- Rated rounds run hourly 08:00–22:00 London. A new build starts with a provisional rating.
- v1.0 beats the interpreted v0.2 by **+560 Elo (95% interval +495 to +660)** over 300 games at
  10 s + 0.1 s (`docs/RESULTS.md`, row `numba-vs-v0.2-10s`).
- Against rating-limited Stockfish at the real time control, 16 games each
  (`docs/RESULTS.md`, rows `v1.0-vs-sf*-real`):

  | opponent | score |
  |---|---|
  | UCI_Elo 1800 | 84.4% |
  | UCI_Elo 2000 | 75.0% |
  | UCI_Elo 2200 | 65.6% |
  | UCI_Elo 2400 | 56.2% |

  Sixteen games is a wide interval — treat these as a bracket, not a rating.
- **No CCRL-scale rating is claimed for v1.0.** The ~2050 figure in older documents belongs to the
  interpreted v0.2 and has not been re-measured on the compiled build. Treat every rating as an
  estimate until the ladder reports one.
- Uploads close **Friday 11 September 11:00 London (12:00 in Spain)**. The last valid build
  plays the 13-round Swiss that afternoon. Only the Swiss counts for qualification.

## 3. Rebuilding the zip yourself (if ever needed)

**Read this first: `harness.package` zips the working tree, not the commit you checked out.** It
reads the files on disk. So a `git checkout` does *not* protect you — uncommitted edits survive a
checkout and go straight into the zip. Check the tree is clean before building:

```
cd ~/dev/chessathon
git status --porcelain -- agent.py mikhail_letal weights   # MUST print nothing
git checkout v1.0
uv run python -m harness.package
unzip -l submission.zip      # fourteen files, agent.py at the root
sha256sum submission.zip     # record it; it will NOT match section 0 after a rebuild (see there)
```

If that first command prints anything, **stop and ask Claude.** Uncommitted work in the engine is
normally a change that has not yet won a promotion match, and packaging it uploads an engine that
has never played a measured game.

**Do not upload the tip of `main` just because it is newer.** Only a version that has won its
promotion match — beaten the previous one over a real-clock match with the 95% interval above zero
— is a version. Between promotions, `main` and `v1.0` may name very different engines.

`harness.package` also plays two local smoke games from the zip; it must end with
"Nothing here fails". To confirm a zip really is frozen v1.0 rather than a working-tree build:

```
unzip -q -d /tmp/zc submission.zip && diff -r /tmp/zc versions/v1.0 -x '__pycache__'
```

That prints nothing for a correct v1.0 zip. It is the last check before uploading, and it catches
every mistake above.

## 3a. Promoting a new version (do this before uploading anything that is not v1.0)

**A change is not a version until it has won a match.** `main` may contain work that has not: at
the time of writing it carries a timing refit and a king-danger term, neither of which has beaten
`versions/v1.0` at the real clock. Uploading `main` in that state uploads an engine that has never
been measured. If in doubt, upload the last frozen version — that is what `versions/` is for.

When a match *has* been won and the 95% interval is above zero:

```
# 1. Everything that ships must be committed. The zip is built from the working tree.
git status --porcelain -- agent.py mikhail_letal weights   # MUST print nothing

# 2. Freeze it, so the next change has something to be measured against.
uv run python -m tools.freeze_version v1.1

# 3. Tag the exact commit that was frozen.
git tag v1.1 && git push origin v1.1

# 4. Build and smoke the zip.
uv run python -m harness.package

# 5. Prove the zip is that version and nothing else.
unzip -q -d /tmp/zc submission.zip && diff -r /tmp/zc versions/v1.1 -x '__pycache__'
```

`tools/freeze_version.py` takes the file list from `harness.package` itself, so the frozen version
and the zip cannot disagree about what ships. It refuses to run while shipping files are
uncommitted, refuses to overwrite an existing version without `--force`, and verifies every copied
file byte for byte. When it finishes it prints the three numbers section 0 needs — file count,
zipped size, unzipped size and sha256 — **paste them into section 0 and into the row below**, so
this guide always describes the build that is actually on disk.

| version | files | zipped | unzipped | sha256 of the build that was uploaded |
|---|---|---|---|---|
| v1.0 | 14 | 85 925 | 269 589 | `8f98cb73400f18490223f41636a0ad1189da1cd414b04261f16b9355b6ec53a1` |

The first three columns are reproducible from the tag; the sha256 is not, for the reason given in
section 0. It is recorded because the platform names each upload after it — v1.0's upload is
`aichessathon-v2-8f98cb73400f` — which is how a validation log is matched to the build that
produced it.

Do not skip step 2 because the deadline is close. The freeze is what the *next* match measures
against, and a version that was never frozen cannot be an opponent — which means the promotion
rule quietly stops working from that point on.

## 4. Verifying the engine locally

```
uv run python -m pytest -q                       # 621 tests, 2 min 41 s on this box
uv run python -m harness.play --white . --black baselines/minimax   # one real-clock game
uv run python -m tools.arena_openings --opponent versions/v1.0 --games 40 --workers 4 --real-clock
```

The web app: `uv run python -m tools.webapp.server`, then http://localhost:8000/. Play the
engine, watch it against Stockfish at a chosen Elo, analyse games, read the docs and tables.

## 5. Report for the London final (Saturday 12 September)

`docs/report.tex` is the walk-through script: compile with `make report` (uses `latexmk`;
`tectonic` or Overleaf also work). Sections: competition and result; rules compliance and the
memorised-code checks; architecture; board and move generation; search; evaluation; time
management; endgames; safety; testing; rating estimate; limitations. Two red `[PENDING …]` markers
remain. The compiled PDF is at `docs/report.pdf`.

**Known gap:** the report still describes the interpreted Stage-0 engine — 50–61k nodes per second,
depth 5–6 — throughout. It has not been rewritten for the compiled build and should not be handed
to a judge in that state. See `handoff/AUDIT-docs.md`.

## 6. What to say if a judge asks "did you write this?"

- The code was written with AI assistance, which the rules allow, and every design decision,
  constant and measurement is recorded: `docs/DECISIONS.md`, `docs/PROVENANCE.md`,
  `docs/RESULTS.md`, `weights/PROVENANCE.json`.
- The evaluation tables come from a parametric formula in `tools/gen_pst.py`; they match no
  published engine (compared against Sunfish, the CPW simplified tables, Rustic, TSCP, VICE).
- Stockfish was used only locally, as a sparring partner and analysis tool, never in the zip.
- The web app under `app/` and `tools/webapp/` is a development tool; nothing of it ships.

## 7. After the log arrives (Claude's side)

Calibrate `overhead_ms` and the speed factor, re-run the solo pass, and if anything changes produce
the next version under the same promotion rule: it replaces v1.0 only with the 95% interval above
zero at the real clock, with v1.0 kept in `versions/` as the opponent.
