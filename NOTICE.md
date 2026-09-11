# Notice

Who holds copyright over what in this repository, and the one part that is not MIT.

## MIT, and who wrote which half

`LICENSE` carries two copyright lines because this repository began as a clone of the
competition's starter and then grew an engine on top of it.

- **Copyright (c) 2026 Advit Arora** — the starter repository this project was built from:
  `harness/`, `baselines/` and the original project scaffolding.
  [advitrocks9/aichessathon-starter](https://github.com/advitrocks9/aichessathon-starter), MIT.
  `harness/` is unmodified, deliberately: it mirrors the competition platform's protocol and
  clock, and editing it would make every local measurement in `docs/RESULTS.md` meaningless.
- **Copyright (c) 2026 Alexander Urvancev** — everything else: `agent.py`, `mikhail_letal/`,
  `weights/`, `tools/`, `tests/`, `docs/`, `handoff/`, `app/` and `versions/`.

## The exception: the chess pieces

The piece images in [`app/pieces/cburnett/`](app/pieces/cburnett/) are by **Colin M.L. Burnett**
and are licensed under **Creative Commons Attribution-ShareAlike 3.0 Unported**, not under the
MIT licence above. See [`app/pieces/cburnett/LICENSE.txt`](app/pieces/cburnett/LICENSE.txt).

They are used by the local web app only. Nothing in the competition submission contains them.

## Not in this repository

Stockfish is a measuring instrument here and nothing more: a sparring partner for rating
estimates, the analysis engine behind the web app's review screen, and the labeller for two
evaluation experiments that both failed. It is installed separately, it never influences a move
at runtime, and it has never been part of any build. No table or constant in this repository was
copied from it or from any other engine; `tools/gen_pst.py` generates the piece-square tables
from a formula so that their origin is provable.
