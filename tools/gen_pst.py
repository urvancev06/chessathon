"""The evaluation's *prior*: piece-square tables from a parametric geometric formula, textbook piece
values and hand-chosen structural weights.

Every piece-square-table (PST) entry below is a small formula of the square's geometry (how central
it is, how far advanced, whether it sits on a rim, a long diagonal or a castled square) multiplied
by a named parameter from ``PARAMETERS``. Nothing is copied from any published engine: the numbers
are ours by construction, and re-running this script reproduces them bit for bit. The piece values
are the universal textbook 100/320/330/500/900 and the structural weights (``STRUCTURE_PRIOR``) are
hand-chosen at textbook magnitudes; all are recorded as such (untuned).

This module is what ``tools/tune_texel.py`` regularises toward: the shipped ``weights/pst.json``
and the ``STRUCTURE_WEIGHTS`` in ``mikhail_letal/evaluation.py`` are the tuner's output (v0.3),
which starts from these tables and moves each number only as far as the labelled positions
justify. Run from the repo root to print the prior and write it for inspection::

    .venv/bin/python tools/gen_pst.py                       # writes data/tuning/prior_pst.json
    .venv/bin/python tools/gen_pst.py --out weights/pst.json  # ship the untuned prior (v0.2)

The script prints every table as an 8x8 grid (rank 8 at the top, files a..h left to right) so a
human can eyeball it, then writes the JSON file (and ``weights/PROVENANCE.json`` when shipping).

Square indexing follows python-chess: ``a1 = 0``, ``h1 = 7``, ``a8 = 56``. Tables are stored from
White's point of view; the evaluation mirrors squares for Black (``square ^ 56``).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import subprocess
from pathlib import Path
from typing import NamedTuple

from mikhail_letal.timing import DEFAULT_PARAMS

ROOT = Path(__file__).resolve().parent.parent
PST_PATH = ROOT / "weights" / "pst.json"
PRIOR_PATH = ROOT / "data" / "tuning" / "prior_pst.json"
PROVENANCE_PATH = ROOT / "weights" / "PROVENANCE.json"
GENERATOR = "tools/gen_pst.py"

PIECES = "PNBRQK"

# Textbook material values (centipawns). The king carries no material value: it is never captured,
# and its table alone steers where it stands. Both phases start identical; tuning (Stage 2) may
# split them.
PIECE_VALUES_MG: dict[str, int] = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
PIECE_VALUES_EG: dict[str, int] = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}

# Game-phase weights: knights and bishops count 1, rooks 2, queens 4. With every non-pawn piece on
# the board the sum is 4*1 + 4*1 + 4*2 + 2*4 = 24, which is ``PHASE_TOTAL`` in the evaluation.
PHASE_WEIGHTS: dict[str, int] = {"N": 1, "B": 1, "R": 2, "Q": 4}


# The time-management half of the shipped provenance record. The brief (§10) asks for the
# time-management constants as well as the evaluation tables, and `weights/PROVENANCE.json` is the
# only provenance artefact inside the zip (`docs/PROVENANCE.md` does not ship). Every value here is
# read from `TimeParams` itself, so the shipped record cannot drift from the code that uses it;
# `tests/test_timing.py` asserts the file matches this function.
TIMING_RUN_ID = "2026-09-08"
LADDER_DATA = (
    "1697 finished ladder games (data/pgn/ladder-top, data/pgn/ladder-top50), collected from the "
    "public game pages; our own five rated games in data/pgn/ours as the check"
)
PLATFORM_DATA = "platform validation and rated logs, 2026-09-08 (25 moves, 452 half-moves)"
POSITIONS_DATA = (
    "6 middlegame positions from data/pgn searched at 120 s and 20 s (12 moves a variant), and "
    "10 of them at six clocks (60 moves a variant) for the before-and-after comparison"
)


def timing_rows(run_id: str = TIMING_RUN_ID) -> list[dict[str, str]]:
    """Provenance records for every constant in `mikhail_letal.timing.TimeParams`."""
    p = DEFAULT_PARAMS
    sim = "tools/sim_time.py"
    code = "code (mikhail_letal/timing.py)"
    rows: list[tuple[str, str, str, str, str]] = [
        (
            "timing.increment_ms",
            str(p.increment_ms),
            code,
            "agent contract (aichessathon.com/docs/agent-contract.md)",
            "the increment the platform adds after each of our moves; not a choice",
        ),
        (
            "timing.overhead_ms",
            str(p.overhead_ms),
            code,
            PLATFORM_DATA,
            "referee-charged minus self-measured move time was 0-2 ms, mean 1.1; docs/CALIBRATION"
            ".md's rule is max + 50, so 52, taken as 50",
        ),
        (
            "timing.moves_to_go",
            f"max {p.moves_to_go_max}, min {p.moves_to_go_min}, decay {p.moves_to_go_decay}",
            sim,
            LADDER_DATA,
            "the ladder games measure how many of our moves are left at each point (median 67 at "
            "the start, falling about one a move to 25); the divisor is that curve scaled by the "
            "0.70 of its budget a move spends. The minimum is 20 rather than 17 because at 16 the "
            "settling clock equals panic_ms and the deep tail is skewed (median 27, mean 40)",
        ),
        (
            "timing.increment_fraction",
            str(p.increment_fraction),
            code,
            "none: brief section 6.2",
            "spend most of the increment each move and keep a little; untuned",
        ),
        (
            "timing.hard_multiplier",
            str(p.hard_multiplier),
            code,
            "none: brief section 6.2",
            "an iteration may overrun the soft target by this factor before it is aborted",
        ),
        (
            "timing.hard_fraction",
            str(p.hard_fraction),
            code,
            "none: brief section 6.2",
            "no single move may spend more than this share of the clock",
        ),
        (
            "timing.floor_ms / floor_fraction",
            f"{p.floor_ms} ms, {p.floor_fraction}",
            code,
            "none: brief section 6.2",
            "the reserve the budget never plans to dip into; with hard_fraction it is what keeps "
            "the clock off the flag, and what stops a long game settling below about 2 s",
        ),
        (
            "timing.panic_ms",
            str(p.panic_ms),
            code,
            PLATFORM_DATA,
            "below this the engine is skipped and the fallback plays; kept at the value the "
            "platform measured under v1.0 even though overhead_ms + floor_ms is now 1550",
        ),
        (
            "timing.next_iteration_fraction",
            str(p.next_iteration_fraction),
            code,
            "none: brief section 6.2",
            "no longer the normal rule: only the fallback for an iteration too short to predict "
            "from, applied to the soft budget itself",
        ),
        (
            "timing.iteration_ratio",
            f"default {p.iteration_ratio_default}, clamped to "
            f"[{p.iteration_ratio_min}, {p.iteration_ratio_max}], measurable above "
            f"{p.ratio_measurable_s} s",
            code,
            PLATFORM_DATA + "; dev-box searches 2026-09-07 (median 4.3-5.2, maximum about 10)",
            "the cost of depth d+1 over depth d, measured live from the last two iterations; the "
            "clamp keeps one mis-timed iteration from stopping the search early or starting one "
            "it cannot finish",
        ),
        (
            "timing.iteration_target_factor",
            str(p.iteration_target_factor),
            code,
            POSITIONS_DATA,
            "how far past the soft budget the next iteration may be predicted to end: 1.0 spent "
            "0.70 of the budget for mean depth 10.83, 1.35 spent 0.80 for 11.17, 1.75 reached the "
            "hard ceiling. 1.35 x unstable_factor is still below hard_multiplier",
        ),
        (
            "timing.unstable_factor",
            str(p.unstable_factor),
            code,
            "none: hand-chosen at a textbook magnitude, untuned",
            "a root move that changed at the last completed depth is worth half a budget more, "
            "bounded by the hard ceiling like every other target",
        ),
        (
            "timing.easy_move",
            f"factor {p.easy_factor}, after {p.easy_stable_depths} iterations, score drop "
            f"<= {p.easy_score_drop_cp} cp",
            code,
            POSITIONS_DATA,
            "6 iterations at 0.7 costs 0.17 of a ply and banks 16 % of the time; the first "
            "attempt (4 at 0.5) fired on nearly every move and spent less than the fixed rule",
        ),
        (
            "timing.cold_finish_fraction",
            str(p.cold_finish_fraction),
            code,
            "none: same value as hard_fraction, and for the same reason",
            "the share of the clock the first move may spend finishing a warm-up the import ran "
            "out of budget for; at most one move of one game",
        ),
    ]
    return [
        {
            "parameter": parameter,
            "value_or_shape": value,
            "produced_by": produced_by,
            "data": data,
            "run_id": run_id,
            "note": note,
        }
        for parameter, value, produced_by, data, note in rows
    ]


# The search half of the shipped record. Brief §10 asks for "search margins (null-move R, LMR
# table, futility margins, aspiration window), TT size: all of them", and until this existed the
# zip documented the evaluation tables and nothing else -- leaving the constants a judge is most
# likely to suspect of being copied with no answer at all. Every value is read from the module
# that uses it, so the shipped record cannot drift; `tests/test_search_provenance.py` asserts it.
SEARCH_RUN_ID = "2026-09-08"
TEXTBOOK = "none: hand-chosen at textbook magnitude, untuned"


def search_rows(run_id: str = SEARCH_RUN_ID) -> list[dict[str, str]]:
    """Provenance records for every search constant that ships."""
    from mikhail_letal import evaluation, fastsearch, search

    code = "code (mikhail_letal/search.py)"
    compiled = "code (mikhail_letal/fastsearch.py)"
    rows: list[tuple[str, str, str, str, str]] = [
        (
            "search.null_move",
            f"min depth {search.NULL_MOVE_MIN_DEPTH}, R = {search.NULL_MOVE_BASE_REDUCTION}"
            f" + depth // {search.NULL_MOVE_DEPTH_DIVISOR}",
            code,
            "none: min depth chosen by measurement (see note)",
            "textbook reduction; min depth 3 rather than 2 because at 2 a capture-rich middlegame "
            "tripled the nodes to depth 5, null searches landing in quiescence at the widest layer",
        ),
        (
            "search.late_move_reductions",
            f"min depth {search.LMR_MIN_DEPTH}, first {search.LMR_FULL_DEPTH_MOVES} moves full,"
            f" reduction {search.LMR_REDUCTION}",
            code,
            TEXTBOOK,
            "quiet, non-killer, non-TT moves only, never in check, re-searched at full depth on a "
            "fail-high",
        ),
        (
            "search.aspiration",
            f"from depth {search.ASPIRATION_MIN_DEPTH}, window {search.ASPIRATION_WINDOW} cp,"
            f" widen x{search.ASPIRATION_WIDEN}, {search.ASPIRATION_MAX_FAILS} fails then full",
            code,
            TEXTBOOK,
            "40 cp is under half a pawn, so a stable root re-searches rarely",
        ),
        (
            "search.futility_margins",
            json.dumps(list(search.FUTILITY_MARGINS)),
            code,
            TEXTBOOK,
            "indexed by remaining depth: a minor piece at depth 1, two at depth 2; depth 0 is dead "
            "because the search goes to quiescence there",
        ),
        (
            "search.delta_margin",
            str(search.DELTA_MARGIN),
            code,
            TEXTBOOK,
            "quiescence skips a capture that cannot reach alpha even with the victim's value",
        ),
        (
            "search.qs_evasion_plies",
            str(search.QS_EVASION_PLIES),
            code,
            "none: chosen by measurement (see note)",
            "quiescence searches every evasion this deep; 4 keeps an eight-queens-a-side position "
            "under 100k nodes at depth 1, where an uncapped search never finished an iteration",
        ),
        (
            "search.draw_tiebreak_margin",
            str(search.DRAW_TIEBREAK_MARGIN),
            code,
            TEXTBOOK,
            "'clearly ahead' for the root tie-break when every move scores a rule draw: a minor",
        ),
        (
            "search.node_check_interval",
            # The COMPILED value: fastsearch.py holds its own, and it is the engine that plays a
            # rated game. Reading search.NODE_CHECK_INTERVAL here shipped 128 in a row whose note
            # says "the compiled search", which used 512. tests/test_constant_parity.py records
            # the divergence as deliberate and guards it.
            str(fastsearch.NODE_CHECK_INTERVAL),
            "code (mikhail_letal/fastsearch.py)",
            "none: chosen by measurement (see note)",
            "how often the compiled search reads the clock, in nodes. An objmode clock read costs "
            "~300 ns, so 512 nodes is well under 1 % of node cost. At the 505 286 nodes/s median "
            "measured over the round-74 rated game it bounds the overshoot past the hard deadline "
            "to 1.013 ms, and that game overshot twice, by 1 ms each time "
            "(handoff/LOG-round-74-zagreus.md). The interpreted reference engine in search.py uses "
            "128 for the same granularity at its own much lower node rate",
        ),
        (
            "search.max_ply",
            str(search.MAX_PLY),
            code,
            "none: structural",
            "recursion bound for search, quiescence and extensions together",
        ),
        (
            "search.game_ply_cap",
            str(search.GAME_PLY_CAP),
            code,
            "agent contract: a game reaching this many plies is a draw",
            "not a choice; the opening position counts toward it",
        ),
        (
            "search.transposition_table",
            f"2^{fastsearch.TT_BITS} entries, cleared at move start above "
            f"{search.TT_CLEAR_FRACTION:.0%} full",
            compiled,
            "none: sized by measurement (see note)",
            "fixed numpy arrays, depth-preferred within a move and aged across moves; int-only "
            "entries keep gen-2 GC pauses to ~14 ms where chess.Move values cost 143 ms",
        ),
        (
            "search.eval_cache",
            f"2^{fastsearch.EVAL_BITS} entries (compiled); {search.EVAL_CACHE_MAX_ENTRIES} "
            "(reference engine)",
            compiled,
            "none: sized by measurement",
            "static evaluations keyed by Zobrist; the cap holds a 20 s search under 100 MB",
        ),
        (
            "search.history_bonus",
            f"depth * depth, clamped at {search._HISTORY_MAX}",
            code,
            TEXTBOOK,
            "cutoffs near the root are rarer and worth more; the clamp keeps quiet moves below the "
            "killer band so ordering bands cannot invert",
        ),
        (
            "search.mate_scores",
            f"mate {evaluation.MATE_SCORE}, threshold {evaluation.MATE_THRESHOLD}",
            "code (mikhail_letal/evaluation.py)",
            "none: arbitrary large constants",
            "a mate at ply p scores MATE_SCORE - p, so shorter mates outrank longer ones",
        ),
    ]
    return [
        {
            "parameter": name,
            "value_or_shape": value,
            "produced_by": produced,
            "data": data,
            "run_id": run_id,
            "note": note,
        }
        for name, value, produced, data, note in rows
    ]


class Param(NamedTuple):
    """A named parameter of the prior together with the one-line reason for its magnitude."""

    value: int
    why: str


# All tunable numbers of the prior live here. Magnitudes are chosen so that the largest PST entry
# stays well under a pawn: piece-square effects are refinements of material, not rivals to it.
PARAMETERS: dict[str, Param] = {
    "pawn_adv_mg": Param(
        4, "middlegame: each step forward gains space, but pawn storms weaken the king, so small"
    ),
    "pawn_centre_mg": Param(
        12, "middlegame: d/e pawns on ranks 3-5 hold the centre; comparable to a tempo"
    ),
    "pawn_adv_eg": Param(
        14, "endgame: quadratic in steps forward (14*25/7 = 50 on the 7th), a passed-pawn shape"
    ),
    "knight_centre": Param(
        12, "knights gain most from the centre (2.5 rings * 12 = 30) and lose most on the rim"
    ),
    "knight_rim": Param(14, "a knight on the edge attacks half as many squares: extra penalty"),
    "bishop_centre": Param(
        6, "bishops act at range, so centrality matters half as much as knights"
    ),
    "bishop_long_diagonal": Param(6, "the two long diagonals see the whole board"),
    "rook_seventh": Param(20, "a rook on the 7th cuts off the king and eats pawns"),
    "rook_centre_file": Param(8, "d/e files are open most often in the middlegame"),
    "queen_centre": Param(8, "halved by the formula: the queen is strong everywhere"),
    "queen_early": Param(
        12, "middlegame: a queen past the second rank invites harassment before minors develop"
    ),
    "king_shelter": Param(
        25, "middlegame: castled squares b1/c1/g1 keep pawns in front of the king"
    ),
    "king_centre_penalty": Param(
        10, "middlegame: per rank of advancement and for the d/e files, so e8 -> -80 at most"
    ),
    "king_centre_eg": Param(
        10, "endgame: the king becomes a fighting piece; 2.5 rings * 10 = 25 in the centre"
    ),
    "mopup_edge": Param(
        10, "mop-up: per Manhattan step of the bare king from the centre (max 6 -> 60)"
    ),
    "mopup_close": Param(
        12, "mop-up: per step our king is closer than 14; exceeds one ring of king_centre_eg"
    ),
}

# Plain name -> value view, used by the formulas below.
P: dict[str, int] = {name: param.value for name, param in PARAMETERS.items()}

# Prior weights of the structural evaluation terms (see ``evaluation.STRUCTURE_WEIGHTS`` for what
# each term measures), in centipawns, at the magnitude chess textbooks give the feature.
STRUCTURE_PRIOR: dict[str, Param] = {
    "passed_pawn_mg": Param(10, "per rank advanced; modest while pieces can still blockade"),
    "passed_pawn_eg": Param(20, "per rank advanced; running the passer is usually the plan"),
    "doubled_pawn": Param(12, "per rear pawn of a doubled pair: they block each other"),
    "isolated_pawn": Param(15, "per pawn with no neighbour: only pieces can defend it"),
    "bishop_pair": Param(30, "two bishops cover both square colours"),
    "rook_open_file": Param(20, "a rook on a pawnless file reaches the enemy camp"),
    "rook_semi_open_file": Param(10, "a rook on a file without an own pawn presses the enemy pawn"),
    "king_shield": Param(10, "middlegame, per own pawn one or two ranks in front of the king"),
}


def rounded(x: float) -> int:
    """Round half away from zero, so a symmetric formula gives a symmetric integer table."""
    return int(x + 0.5) if x >= 0 else -int(-x + 0.5)


def centrality(square: int) -> float:
    """3 - max(|file - 3.5|, |rank - 3.5|): 2.5 on the four centre squares, -0.5 on the rim."""
    file, rank = square % 8, square // 8
    return 3.0 - max(abs(file - 3.5), abs(rank - 3.5))


def on_rim(square: int) -> bool:
    file, rank = square % 8, square // 8
    return file in (0, 7) or rank in (0, 7)


def on_long_diagonal(square: int) -> bool:
    file, rank = square % 8, square // 8
    return file == rank or file + rank == 7


def pawn_mg(square: int) -> int:
    file, rank = square % 8, square // 8
    if rank in (0, 7):  # no pawn can stand on its own first rank or on the promotion rank
        return 0
    steps = rank - 1  # squares moved from the home rank: an unmoved pawn scores zero
    central = 1 if file in (3, 4) and rank in (2, 3, 4) else 0  # d/e file, ranks 3-5
    return rounded(P["pawn_adv_mg"] * steps + P["pawn_centre_mg"] * central)


def pawn_eg(square: int) -> int:
    rank = square // 8
    if rank in (0, 7):
        return 0
    steps = rank - 1
    return rounded(P["pawn_adv_eg"] * steps**2 / 7)


def knight_both(square: int) -> int:
    rim = P["knight_rim"] if on_rim(square) else 0
    return rounded(P["knight_centre"] * centrality(square) - rim)


def bishop_both(square: int) -> int:
    diagonal = P["bishop_long_diagonal"] if on_long_diagonal(square) else 0
    return rounded(P["bishop_centre"] * centrality(square) + diagonal)


def rook_mg(square: int) -> int:
    file, rank = square % 8, square // 8
    seventh = P["rook_seventh"] if rank == 6 else 0
    centre_file = P["rook_centre_file"] if file in (3, 4) else 0
    return seventh + centre_file


def rook_eg(square: int) -> int:
    return 0  # flat: in the endgame the rook's best file depends on the pawns, not the geometry


def queen_both(square: int) -> int:
    return rounded(P["queen_centre"] * centrality(square) * 0.5)


def queen_mg(square: int) -> int:
    rank = square // 8
    early = P["queen_early"] if rank >= 2 else 0  # left the back two ranks
    return queen_both(square) - early


def king_mg(square: int) -> int:
    file, rank = square % 8, square // 8
    shelter = P["king_shelter"] if square in (1, 2, 6) else 0  # b1, c1, g1
    exposed = (1 if file in (3, 4) else 0) + rank  # d/e file, plus each rank of advancement
    return shelter - P["king_centre_penalty"] * exposed


def king_eg(square: int) -> int:
    return rounded(P["king_centre_eg"] * centrality(square))


def build_tables() -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    """Return (pst_mg, pst_eg): dicts piece letter -> 64 ints indexed by python-chess square."""
    squares = range(64)
    pst_mg = {
        "P": [pawn_mg(s) for s in squares],
        "N": [knight_both(s) for s in squares],
        "B": [bishop_both(s) for s in squares],
        "R": [rook_mg(s) for s in squares],
        "Q": [queen_mg(s) for s in squares],
        "K": [king_mg(s) for s in squares],
    }
    pst_eg = {
        "P": [pawn_eg(s) for s in squares],
        "N": [knight_both(s) for s in squares],
        "B": [bishop_both(s) for s in squares],
        "R": [rook_eg(s) for s in squares],
        "Q": [queen_both(s) for s in squares],
        "K": [king_eg(s) for s in squares],
    }
    return pst_mg, pst_eg


def grid(table: list[int]) -> str:
    """Format a 64-entry table as 8 rows, rank 8 at the top, files a..h left to right."""
    rows = []
    for rank in range(7, -1, -1):
        cells = " ".join(f"{table[rank * 8 + file]:4d}" for file in range(8))
        rows.append(f"  {rank + 1} |{cells}")
    rows.append("     " + " ".join(f"{f:>4}" for f in "abcdefgh"))
    return "\n".join(rows)


def display(path: Path) -> str:
    """The path relative to the repo when it lies inside it, else as given."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_provenance(path: Path) -> dict[str, object] | None:
    """The `_provenance` header of an existing tables file, or None if there is not one to read."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    header = document.get("_provenance")
    return header if isinstance(header, dict) else None


def git_commit() -> str:
    """Current commit hash, or 'unknown' when not in a git checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False, cwd=ROOT
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def dump_json(value: object, indent: int) -> str:
    """JSON with dicts one key per line and every leaf list or flat dict on a single line."""
    if (
        isinstance(value, dict)
        and value
        and any(isinstance(v, dict | list) for v in value.values())
    ):
        pad = " " * (indent + 2)
        items = [f"{pad}{json.dumps(str(k))}: {dump_json(v, indent + 2)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    return json.dumps(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Print the prior tables and write them as JSON.")
    parser.add_argument(
        "--out",
        type=Path,
        default=PRIOR_PATH,
        help="where to write the tables; weights/pst.json also rewrites weights/PROVENANCE.json",
    )
    out_path: Path = parser.parse_args().out.resolve()
    pst_mg, pst_eg = build_tables()
    mopup = {"edge": P["mopup_edge"], "close": P["mopup_close"]}
    tables = {
        "piece_values_mg": PIECE_VALUES_MG,
        "piece_values_eg": PIECE_VALUES_EG,
        "pst_mg": pst_mg,
        "pst_eg": pst_eg,
        "phase_weights": PHASE_WEIGHTS,
        "mopup": mopup,
    }
    # A hash of the table content alone (not of the date or commit) so a hand edit is detectable.
    tables_sha256 = hashlib.sha256(json.dumps(tables, sort_keys=True).encode()).hexdigest()
    today = datetime.date.today().isoformat()
    # `git_commit` and `date` describe the commit that produced *these tables*, so they may only
    # move when the tables do. Stamping HEAD unconditionally silently rewrote them on every
    # regeneration: the shipped record spent 8 September claiming the tables came from `621afb5`,
    # a documentation-only commit, while `versions/v0.2` and `versions/v1.0` both correctly name
    # `4109710`. `tables_sha256` is over the table content alone, so it is the honest test of
    # whether anything actually changed.
    commit, stamped = git_commit(), today
    previous = read_provenance(out_path)
    if previous is not None and previous.get("tables_sha256") == tables_sha256:
        commit = str(previous.get("git_commit", commit))
        stamped = str(previous.get("date", today))
    provenance = {
        "generator": GENERATOR,
        "git_commit": commit,
        "date": stamped,
        "note": (
            "textbook piece values 100/320/330/500/900, "
            "PST from parametric geometric prior, untuned"
        ),
        "tables_sha256": tables_sha256,
        "parameters": {name: {"value": p.value, "why": p.why} for name, p in PARAMETERS.items()},
    }
    document = {"_provenance": provenance, **tables}

    for phase_name, pst, values in (
        ("middlegame", pst_mg, PIECE_VALUES_MG),
        ("endgame", pst_eg, PIECE_VALUES_EG),
    ):
        for piece in PIECES:
            print(f"{phase_name} {piece} (value {values[piece]})")
            print(grid(pst[piece]))
            print()
    print(f"phase weights {PHASE_WEIGHTS}   mop-up {mopup}   tables sha256 {tables_sha256[:16]}...")

    produced_by = f"{GENERATOR} @ {commit}"
    records: list[dict[str, str]] = [
        {
            "parameter": "piece_values_mg",
            "value_or_shape": json.dumps(PIECE_VALUES_MG),
            "produced_by": produced_by,
            "data": "none: parametric prior",
            "run_id": today,
            "note": "universal textbook values, recorded as such, untuned",
        },
        {
            "parameter": "piece_values_eg",
            "value_or_shape": json.dumps(PIECE_VALUES_EG),
            "produced_by": produced_by,
            "data": "none: parametric prior",
            "run_id": today,
            "note": "identical to the middlegame values until tuned",
        },
    ]
    for phase_key, pst in (("pst_mg", pst_mg), ("pst_eg", pst_eg)):
        for piece in PIECES:
            table = pst[piece]
            records.append(
                {
                    "parameter": f"{phase_key}.{piece}",
                    "value_or_shape": f"64 ints, min {min(table)}, max {max(table)}",
                    "produced_by": produced_by,
                    "data": "none: parametric prior",
                    "run_id": today,
                    "note": "geometric formula of the square; parameters in pst.json _provenance",
                }
            )
    records.append(
        {
            "parameter": "phase_weights",
            "value_or_shape": json.dumps(PHASE_WEIGHTS),
            "produced_by": produced_by,
            "data": "none: parametric prior",
            "run_id": today,
            "note": "sum over the full board is 24 = PHASE_TOTAL",
        }
    )
    records.append(
        {
            "parameter": "mopup",
            "value_or_shape": json.dumps(mopup),
            "produced_by": produced_by,
            "data": "none: parametric prior",
            "run_id": today,
            "note": "drive the bare king to the edge, bring ours close; close beats one king ring",
        }
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(dump_json(document, 0) + "\n", encoding="utf-8")
    print(f"wrote {display(out_path)}")
    if out_path == PST_PATH:
        records += timing_rows(today)  # the time-management half; see timing_rows
        records += search_rows(today)  # the search half; see search_rows
        PROVENANCE_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {PROVENANCE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
