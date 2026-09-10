"""Iterative-deepening alpha-beta search for Mikhail LeTal (v0.2).

How the search works, in one page
---------------------------------
The engine answers "which move is best here?" with a *negamax* tree search. Every score is
measured from the side to move's point of view, so the value of a position is the negation of the
best value the opponent can reach after any reply: ``value(p) = max(-value(child))``. Alpha-beta
pruning keeps a window ``(alpha, beta)`` of scores that can still matter to the ancestors; a child
whose value falls outside the window is abandoned early because a better alternative is already
known higher up the tree.

The search is run to depth 1, then depth 2, then 3, ... (*iterative deepening*). This looks
wasteful but is not: each iteration is several times cheaper than the next, the earlier ones fill
the transposition table with good first-try moves that make the deeper ones prune far better, and
the engine always has a fully-searched answer ready when the clock runs out.

At the leaves of the tree (``depth <= 0``) the position is not simply evaluated, because a static
evaluation in the middle of a capture sequence is meaningless. A *quiescence* search continues
with captures (and queen promotions) only, until the position is quiet, and the side to move may
always choose to "stand pat" and accept the static evaluation instead of capturing.

Move ordering is the heart of alpha-beta efficiency: the sooner the best move is tried, the more
of the remaining moves can be pruned. Moves are tried in this order: the move the transposition
table remembers as best for this position, then captures by *MVV-LVA* (take the Most Valuable
Victim with the Least Valuable Attacker), then two *killer* moves (quiet moves that recently
caused cutoffs at the same distance from the root), then the remaining quiet moves ranked by the
*history heuristic* (how often each from-to move caused a cutoff anywhere in the tree) plus the
*continuation history* (how often each move caused a cutoff after the move the opponent has just
played -- the same credit, counted in the context of one previous move).

Repetition and the fifty-move rule are handled inside the tree so the engine neither drifts into
a draw when it is winning nor avoids one when it is losing. The referee's 600-ply cap is applied
the same way. *Mate-distance pruning* clamps every node's window to the best and worst a node
that far from the root could possibly be worth, which keeps a won position looking for the
shortest mate rather than any mate.

v0.2 adds five textbook ways of searching less without (in practice) missing more, each behind a
switch so its effect could be measured in games: *null-move pruning* (if passing already holds
beta, do not bother searching real moves), *late-move reductions* (quiet moves sorted late are
searched a ply shallower unless they surprise), *aspiration windows* at the root (search inside a
narrow window around the previous score, widen on failure), *futility pruning* (near the horizon,
skip quiet moves from positions far below alpha) and *delta pruning* in quiescence (skip captures
that cannot possibly reach alpha). The comments at the switches below explain each one.

Interior nodes also use *principal variation search*: only the first move of a node is searched
with the full window, and every later one is first tested with a null window that asks the much
cheaper question "is this move better than the best so far?". A move that answers yes is searched
again with the real window. It has no switch because it is not a heuristic -- it changes how the
same tree is proved, not which moves are believed.

Everything is deterministic: identical inputs and limits produce identical output. The only
clock-dependent behaviour is the abort at the hard deadline.
"""

from __future__ import annotations

import operator
import time
from collections.abc import Hashable, Iterator, Mapping
from dataclasses import dataclass
from math import log

import chess

from mikhail_letal.evaluation import (
    DRAW_SCORE,
    MATE_SCORE,
    MATE_THRESHOLD,
    TABLES,
    evaluate,
    is_mate_score,
)
from mikhail_letal.searchboard import SearchBoard
from mikhail_letal.timing import DEFAULT_PARAMS, TimeParams, should_start_next_depth

Key = Hashable

# ----------------------------------------------------------------------------- v0.2 features
# Each strength feature added in v0.2 sits behind one of these switches, plain constants (no
# environment variables are read), so a regression can be bisected feature by feature with arena
# runs. All default to on.

# Null-move pruning: before searching the moves of a node, let the side to move pass and search
# the reply at reduced depth with a zero window around beta. If even doing nothing keeps the score
# at or above beta, a real move surely does too, and the node is cut without a move search. The
# idea rests on "a move is better than no move", which fails in zugzwang, hence the guards: never
# in check (passing is illegal), never twice in a row, never without a piece (pawn endings are
# where zugzwang lives), and never trusting a mate score from the reduced search. The null move
# is only tried where the static evaluation already stands at beta or above: below it, passing
# rarely holds beta and the reduced search would be wasted (measured: in a capture-rich
# middlegame the unguarded version tripled the nodes to depth 5).
NULL_MOVE_PRUNING = True  # switch for bisection in development; the shipped value is True
# Below this remaining depth no null move is tried. At depth 2 the reduced null search is a whole
# quiescence search at nearly every node of the tree's widest layer; in a capture-rich middlegame
# that tripled the nodes to depth 5, while from depth 3 the saving is the same elsewhere (see
# DECISIONS.md).
NULL_MOVE_MIN_DEPTH = 3
NULL_MOVE_BASE_REDUCTION = 2  # plies taken off the depth of the null-move search ...
NULL_MOVE_DEPTH_DIVISOR = 6  # ... plus one more per this many plies of remaining depth

# Transposition table in the quiescence search. Quiescence is where most of the tree is, and
# until now it probed nothing and stored nothing: an identical position reached by a different
# capture order was re-searched from scratch every time. Measured +40.16 +- 11.74 in tcheran
# ("start using the transposition table in quiescence"), corroborated at +25 Elo over 4000 games
# in Arasan -- the largest cheap gain available to an engine that lacks it.
QUIESCENCE_TT = True  # switch for bisection; the shipped value is True
# The depth quiescence entries are stored at. It must be unoccupied, below every real-search
# depth, and above _HINT_DEPTH. `negamax` returns into quiescence at step (7) before its move loop
# and before any store, so nothing else writes at 0; the check extension has already fired by
# then, so a node in check becomes depth 1 and a real node rather than landing here.
_QS_DEPTH = 0

# Internal iterative reduction: at a node with no table move the ordering has nothing to lead
# with, so a full-depth search there is worth less per node than usual. Rather than pay full depth
# for a badly ordered node, take a ply off and let the shallower search leave the table entry that
# the next visit orders by. Ed Schroeder, Rebel 2020. Measured +9.66 +- 5.53 (tcheran) and, as the
# older iterative-deepening form, +10.9 +- 11.7 (Blunder).
INTERNAL_ITERATIVE_REDUCTION = False  # OFF: written and suite-green, but never screened
# Below this remaining depth the lost ply is a larger fraction of the search than the bad ordering
# costs, and at depth 1-3 the node is nearly a leaf where ordering barely matters.
IIR_MIN_DEPTH = 4

# Late-move reductions: with good ordering the best move is nearly always among the first few, so
# the quiet moves that sort late (after the table move, the captures and the killers) are searched
# one ply shallower. A reduced search that still beats alpha is repeated at full depth, so a
# surprise late move is never trusted on the shallow search alone.
LATE_MOVE_REDUCTIONS = True  # switch for bisection in development; the shipped value is True
LMR_MIN_DEPTH = 3  # reduce only where a ply of depth is worth saving
LMR_FULL_DEPTH_MOVES = 3  # this many moves of the node are searched at full depth first

# How many plies come off a late quiet move. A flat one ply treats the fortieth move of a
# twenty-ply node exactly like the fourth move of a three-ply node, and those are not the same
# bet: the deeper the node the more a ply is worth skipping, and the later a move sorts the less
# the ordering believes in it. The reduction therefore grows with both, logarithmically in each,
# which is the usual shape and the one every derivation of it argues for -- the ordering's
# confidence decays like the logarithm of the move number, not linearly.
#
#     reduction(depth, move) = trunc(LMR_BASE + log(depth) * log(move) / LMR_DIVISOR)
#
# floored at one ply (a reduction of zero is not a reduction) and capped at `depth - 2` so the
# reduced search is never shallower than depth 1: a reduced search that lands in quiescence
# proves nothing about a quiet move. The two parameters are textbook magnitudes, taken as they
# stand rather than tuned, and the table is generated from the formula below so that its origin
# is in the source rather than in a list of numbers (docs/PROVENANCE.md, weights/PROVENANCE.json).
LMR_BASE = 0.75  # what a shallow node with few moves behind it reduces by, before the log term
LMR_DIVISOR = 2.25  # how slowly the reduction grows with depth and move number
LMR_TABLE_DEPTHS = 64  # rows; a deeper node reuses the last row
LMR_TABLE_MOVES = 64  # columns; a later move reuses the last column


def _lmr_table() -> tuple[tuple[int, ...], ...]:
    """The reduction for every (remaining depth, moves already searched) the table covers.

    Row and column zero exist only so the table can be indexed without a special case; the search
    never reads them, because it reduces nothing below `LMR_MIN_DEPTH` or before
    `LMR_FULL_DEPTH_MOVES` moves have been searched at full depth.
    """
    rows = []
    for depth in range(LMR_TABLE_DEPTHS):
        row = []
        for move in range(LMR_TABLE_MOVES):
            raw = LMR_BASE + log(max(depth, 1)) * log(max(move, 1)) / LMR_DIVISOR
            row.append(min(max(int(raw), 1), max(depth - 2, 0)))
        rows.append(tuple(row))
    return tuple(rows)


LMR_TABLE = _lmr_table()


def lmr_reduction(depth: int, searched: int) -> int:
    """Plies to take off a late quiet move, from the table, with both indices clamped to it."""
    row = LMR_TABLE[depth if depth < LMR_TABLE_DEPTHS else LMR_TABLE_DEPTHS - 1]
    return row[searched if searched < LMR_TABLE_MOVES else LMR_TABLE_MOVES - 1]


# One-ply continuation history (also called counter-move history). The plain history heuristic
# above credits a quiet move by its from-square and to-square alone, so everything it knows about
# `Ng1-f3` is summed over every position in which that move was ever a cutoff. That is a lot of
# evidence about a move but none at all about *when* the move is good, and the answer is usually
# "as a reply to something specific": a knight retreat refutes one attacking move and is a
# blunder against another.
#
# This table adds exactly one bit of that context, the move the opponent has just played. It is
# indexed by (side to move, the piece the previous move moved, where it moved to, the piece this
# move moves, where it moves to) and carries the same credit, on the same cutoffs, as the plain
# table. The two are read together: a quiet move's ordering score is the sum. Nothing here is an
# evaluation term -- the table is filled only by which moves actually caused cutoffs -- so this is
# the one ordering signal that does not inherit whatever the static evaluation gets wrong.
#
# Deliberately *one* ply of context and not two. The two-ply table (the "follow-up" history) is a
# separate technique with a separate measurement, and adding both at once would leave a screen
# unable to say which one paid.
CONTINUATION_HISTORY = True  # switch for bisection in development; the shipped value is True

# Aspiration windows: from this root depth on, the iteration is searched with a narrow window
# around the previous iteration's score rather than the full one, which prunes far more. A score
# outside the window means the guess was wrong: the failing side is widened by the factor and the
# iteration repeated, and after two failures the full window is used.
ASPIRATION_WINDOWS = True  # switch for bisection in development; the shipped value is True
ASPIRATION_MIN_DEPTH = 4  # earlier iterations are too cheap and their scores too volatile
ASPIRATION_WINDOW = 40  # centipawns either side of the previous score
ASPIRATION_WIDEN = 4  # window multiplier after a failure
ASPIRATION_MAX_FAILS = 2  # failures before the full window is used

# Futility pruning: at the last two plies before the horizon, a quiet move played from a position
# whose static evaluation is well below alpha is very unlikely to get the score back above alpha
# (it wins no material, and the quiescence search that follows will not either), so it is
# skipped. Margins are per remaining depth; the deeper ply gets twice the room. Off in check and
# when a mate bound is in the window, where quiet moves decide everything.
FUTILITY_PRUNING = True  # switch for bisection in development; the shipped value is True
# Extended 9 September from (0, 150, 300) to five plies. The two-ply version prunes almost nothing
# above depth 2, and published testing puts the deeper margins among the best Elo-per-line changes
# available (+37.4 +- 13.4 over 1780 games in an engine of comparable strength). The margin grows
# roughly a minor piece a ply, because a quiet move that must recover more than that in one ply
# essentially never does.
FUTILITY_MARGINS = (0, 150, 300, 500, 750)  # indexed by remaining depth; depth 0 is quiescence

# Reverse futility ("static null move"): the mirror of futility pruning. Where futility asks
# whether a quiet move can lift a bad position to alpha, this asks whether the position is already
# so far ABOVE beta that the opponent will avoid it entirely, and returns without generating a
# move at all. The margin is material-sized, so what it tests is "am I a clear piece up here",
# which is the part of the evaluation that is reliable -- unlike the positional terms, which on
# this engine are coarse. That is why it transfers to a weak evaluation better than most pruning.
REVERSE_FUTILITY_PRUNING = True  # switch for bisection; the shipped value is True
REVERSE_FUTILITY_MAX_DEPTH = 6  # above this the static evaluation is too blunt to trust
REVERSE_FUTILITY_MARGIN = 85  # per remaining ply

# Late move pruning: past a move count that grows with depth, remaining quiet moves are not
# searched at all rather than merely reduced. It contains no evaluation term, so it is worth
# exactly what the move ordering is worth. NOTE: this originally read that the ordering puts
# 'captures by static exchange evaluation' ahead of anything this reaches -- SEE is on a branch,
# and main orders captures by MVV-LVA. The comment described the build intended rather than the
# one screened, which is plausibly why the batch measured negative. Found by chessathon-4c.
# MEASURED OFF, 9 September. With it on, reverse futility + deeper margins + late move pruning
# screened at -21 Elo against the identical build without any of them (300 games, +120 =42 -138).
# With it off, the same two survivors screened at +15 (300 games, +132 =49 -119). Same baseline,
# same sample size, one feature removed: a swing of 36 Elo. The code stays because the version
# measured had no principal-variation guard -- added in 439ff3f, after that screen -- so what was
# measured may be the defect rather than the technique. It returns only if a measurement says so.
LATE_MOVE_PRUNING = False
LATE_MOVE_PRUNING_MAX_DEPTH = 4  # deeper than this, a late quiet move is reduced but still searched
LATE_MOVE_PRUNING_COUNTS = (0, 5, 9, 15, 23)  # quiet moves searched before pruning, by depth

# Delta pruning in quiescence: a capture whose gain, even if the captured piece is simply won
# with nothing lost, plus this margin cannot lift the stand-pat score to alpha is not searched.
DELTA_PRUNING = True  # switch for bisection in development; the shipped value is True
DELTA_MARGIN = 200

# Middlegame piece values for the delta-pruning gain (index = python-chess piece type).
_PIECE_VALUE = TABLES.piece_values_mg

# How often (in nodes) the search reads the clock and checks the node limit. A clock read costs
# about 60 ns against roughly 20 us per node, so reading it every 128 nodes is free (measured: no
# change in node rate) and bounds the overshoot past the hard deadline to a few milliseconds.
# The earlier value of 1024 let the search run 25 ms on average and 65 ms at worst past the
# deadline on the dev box, and the platform's core is about three times slower.
NODE_CHECK_INTERVAL = 128

# Deepest ply the tree may reach, including quiescence and check extensions. Python's default
# recursion limit is 1000; each search ply uses a couple of frames, so 128 leaves ample room.
MAX_PLY = 128

# The platform declares any game that reaches this many plies a draw (the opening position counts).
GAME_PLY_CAP = 600

# In quiescence a side in check gets every evasion searched (there is no standing pat when doing
# nothing is illegal), but only this many quiescence plies deep. Deeper than that a check is
# handled like any other quiescence node, so a long chain of checks and captures in a dense
# position cannot blow the node count up (eight queens a side made one depth-1 iteration cost
# hundreds of thousands of nodes before this cap).
QS_EVASION_PLIES = 4

# Root tie-break (see Engine._break_draw_tie): when every root move scores a draw although the
# static evaluation says we are ahead by at least this much, the draw is a rule draw inside the
# horizon and the tied moves are told apart by the static evaluation of the positions they reach.
DRAW_TIEBREAK_MARGIN = 300

# The transposition table is emptied at the start of a search once it holds more than this share
# of its cap, so the mid-search clear (the backstop when the cap is hit) almost never fires.
TT_CLEAR_FRACTION = 0.6

# Entries kept in the static-evaluation cache (see Engine._evaluate) before it is emptied. About
# a third of the evaluations in a search are of a piece placement already evaluated (capture
# sequences transpose), and the cache turns those into a tuple build and a dict lookup.
EVAL_CACHE_MAX_ENTRIES = 100_000

# Transposition-table entry flags: what the stored score means.
EXACT = 0  # the score is the exact minimax value at the stored depth
LOWER = 1  # the true value is at least the stored score (a beta cutoff happened)
UPPER = 2  # the true value is at most the stored score (every move failed low)

# (depth, ply-independent score, flag, best move code). The move is the one to try first next
# time. Every field is an int on purpose: ``chess.Move`` objects have a ``__dict__``, and a table
# of hundreds of thousands of them made CPython's generation-2 garbage collections stall a single
# node for 100-175 ms, invisible to the clock check. Int-only tuples hold no references the
# collector has to trace, so the same collection takes about a millisecond.
TTEntry = tuple[int, int, int, int]

# Depth of a table entry kept only for its move (see Engine._store): below every real depth, so
# the probe never uses its score.
_HINT_DEPTH = -1

# One more than the largest possible score, so it is beyond every real value including mates.
_INFINITY = MATE_SCORE + 1

# Move-ordering bands. Each band is far above the next so that a history score can never
# overtake a killer, nor a killer a capture. Higher sorts first.
_ORDER_TT = 3_000_000
_ORDER_CAPTURE = 2_000_000
_ORDER_KILLER_FIRST = 1_000_001
_ORDER_KILLER_SECOND = 1_000_000
_HISTORY_MAX = _ORDER_KILLER_SECOND - 1
# Captures that static exchange evaluation says lose material sit below every quiet move, scored
# by how much they lose so the least bad is tried first. Without this a capture that hangs a queen
# is searched before a killer, because `_ORDER_CAPTURE` bands every capture above every quiet.
# Below the quiets rather than merely below the killers: a losing capture is worse than an
# untried quiet move, and the alternative would need a band that does not exist between
# `_HISTORY_MAX` and `_ORDER_KILLER_SECOND`.
_ORDER_LOSING_CAPTURE = -1_000_000

# Continuation-history geometry (see CONTINUATION_HISTORY above). One entry is addressed by
#
#     ((side * 7 + previous piece type) * 64 + previous to-square) * _CONT_ROW
#         + this piece type * 64 + this to-square
#
# and it is built in two halves on purpose: the first line is the same for every move of a node,
# so `_cont_base` computes it once when the move that led to the node is made, and `_quiet_order`
# adds only the second line per move. Piece types are python-chess's (PAWN = 1 .. KING = 6), so
# the dimension is seven and index 0 is never used; one wasted row costs less than subtracting
# one on the hot path.
#
# `fastsearch` holds the same table over its own 0x88 squares. The two encodings relabel the same
# five coordinates, so the tables are the same function of the position and neither engine ever
# reads the other's; only `CONTINUATION_HISTORY` and `_HISTORY_MAX` are shared.
_CONT_PIECE_KINDS = 7
_CONT_SQUARES = 64
_CONT_ROW = _CONT_PIECE_KINDS * _CONT_SQUARES  # entries addressed by one previous move: 448
_CONT_NONE = -1  # "no previous move": the root position, and the node directly under a null move

# Rank of each piece type for MVV-LVA, indexed by python-chess piece type (PAWN=1 .. KING=6).
# Only the order matters, not the magnitudes, so the plain ranks 1..6 are used. Index 0 is for
# "no piece" and contributes nothing.
_MVV_LVA_RANK = (0, 1, 2, 3, 4, 5, 6)

# Sentinel for "no move" in the integer move codes (see _move_code).
_NO_MOVE_CODE = -1

# Squares a pawn must stand on to promote with its next push, per colour.
_PROMOTION_RANK = {chess.WHITE: chess.BB_RANK_7, chess.BLACK: chess.BB_RANK_2}

# The two squares a promotion lands on.
_BACK_RANKS = chess.BB_RANK_1 | chess.BB_RANK_8

# python-chess's precomputed attack and ray tables, bound once. ``_capture_moves`` reads them
# directly rather than calling ``attacks_mask``, because it has to know the attacking piece's
# type for the MVV-LVA key anyway, and one branch can then produce both.
_SQUARES = chess.BB_SQUARES
_RAYS = chess.BB_RAYS  # RAYS[a][b] is the whole line through a and b, or 0 if they are not on one
_KNIGHT_ATTACKS = chess.BB_KNIGHT_ATTACKS
_KING_ATTACKS = chess.BB_KING_ATTACKS
_PAWN_ATTACKS = chess.BB_PAWN_ATTACKS
_DIAG_ATTACKS = chess.BB_DIAG_ATTACKS
_DIAG_MASKS = chess.BB_DIAG_MASKS
_RANK_ATTACKS = chess.BB_RANK_ATTACKS
_RANK_MASKS = chess.BB_RANK_MASKS
_FILE_ATTACKS = chess.BB_FILE_ATTACKS
_FILE_MASKS = chess.BB_FILE_MASKS

# Sorts the (key, move) pairs ``_capture_moves`` builds without ever comparing two moves.
_ORDER_KEY = operator.itemgetter(0)

# Which stage of Engine._staged_moves a move came from. The search loop needs to know whether a
# move is quiet (killers and history are updated for quiet cutoffs only) and the tag says so
# without asking the board again. Every tag at or above STAGE_KILLER is a quiet move.
STAGE_TT = 0
STAGE_CAPTURE = 1
STAGE_KILLER = 2
STAGE_QUIET = 3

_now = time.perf_counter


class SearchAborted(Exception):
    """Raised inside the tree when the hard deadline or the node limit is reached."""


@dataclass
class SearchResult:
    """What one call to ``Engine.search`` produced."""

    move: chess.Move | None  # None only when the root position has no legal moves
    score: int  # side-to-move perspective, from the iteration that chose ``move``
    depth: int  # last completed iteration depth
    seldepth: int  # deepest ply reached, quiescence included
    nodes: int
    elapsed: float  # seconds, measured inside search()
    aborted: bool  # the hard deadline or the node limit stopped an iteration


def _move_code(move: chess.Move) -> int:
    """Pack a move into one small int: from square, to square (6 bits each), promotion piece.

    Comparing ``chess.Move`` objects goes through a Python-level ``__eq__``; comparing ints is
    several times cheaper, and the ordering does this for every move at every node. The same
    code is what the transposition table stores (see ``TTEntry``).
    """
    return move.from_square | move.to_square << 6 | (move.promotion or 0) << 12


def _code_to_move(code: int) -> chess.Move:
    """Inverse of ``_move_code``. Castling is a king move of two files and en passant a pawn
    move to the en passant square in python-chess, so from/to/promotion identify every move."""
    return chess.Move(code & 63, code >> 6 & 63, code >> 12 or None)


def _cont_base(mover: chess.Color, piece_type: int, to_square: int) -> int:
    """Where the continuation history of every reply to this move begins.

    ``mover`` is the side that *played* the move, so the replies filed under this base belong to
    the other side, and that is the side the index carries. Called once when a move is made,
    never once per reply: the previous move is the same for every move of the node it leads to.
    """
    replier = int(not mover)
    return ((replier * _CONT_PIECE_KINDS + piece_type) * _CONT_SQUARES + to_square) * _CONT_ROW


def _quiet_order(
    history: list[int],
    cont: Mapping[int, int],
    base: int,
    piece_type: int,
    from_square: int,
    to_square: int,
) -> int:
    """The ordering score of one quiet move: plain history plus continuation history.

    The sum is clamped to ``_HISTORY_MAX``. Each table saturates there on its own, so without the
    clamp two saturated tables would add to nearly twice ``_ORDER_KILLER_SECOND`` and a quiet move
    would outrank first a killer and then a capture. The clamp changes nothing about *when* either
    table saturates; it only keeps the bands from being crossed, which is a property of the
    ordering the search relies on everywhere (see the band comment above ``_ORDER_TT``).
    """
    score = history[from_square << 6 | to_square]
    if base != _CONT_NONE:
        score += cont.get(base + piece_type * _CONT_SQUARES + to_square, 0)
        if score > _HISTORY_MAX:
            score = _HISTORY_MAX
    return score


class Engine:
    """Iterative-deepening negamax alpha-beta search with a transposition table.

    One instance lives for the whole game: its transposition table, killer moves and history
    heuristic persist from move to move (``new_game`` resets them). The per-search state (node
    counts, deadlines, the repetition path) is reset by every call to ``search``.
    """

    def __init__(self, tt_max_entries: int = 250_000) -> None:
        self.tt_max_entries = tt_max_entries
        self._tt: dict[Key, TTEntry] = {}
        # Two killer move codes per ply. Index MAX_PLY itself is reachable by the ply guard.
        self._killers: list[list[int]] = [
            [_NO_MOVE_CODE, _NO_MOVE_CODE] for _ in range(MAX_PLY + 1)
        ]
        # history[colour][from * 64 + to]: cutoff credit for quiet moves, flat for fast indexing.
        self._history_heuristic: list[list[int]] = [[0] * 4096, [0] * 4096]
        # The same credit in the context of one previous move (see CONTINUATION_HISTORY). A dict
        # rather than a flat list because the space is 2 * 7 * 64 * 7 * 64 = 401 408 entries and a
        # search fills a small corner of it, while `_age_history` would have to walk all of them
        # every move; the compiled engine, which cannot afford a dict, uses the flat array.
        self._cont_history: dict[int, int] = {}
        # Where each ply's replies are filed, written by the move that led to that ply. Index
        # MAX_PLY is reachable: a node at MAX_PLY - 1 records a base for the child it searches.
        self._cont_base: list[int] = [_CONT_NONE] * (MAX_PLY + 1)
        # Static evaluations by piece placement and side to move (see _evaluate).
        self._eval_cache: dict[tuple[int, int, int, int, int, int, int, bool], int] = {}

        # Per-search state, (re)initialised by search().
        self._game_history: Mapping[Key, int] = {}
        self._path: dict[Key, int] = {}
        self._nodes = 0
        self._seldepth = 0
        self._null_moves = 0  # null moves tried this search (a statistic the tests read)
        self._hard_deadline = 0.0
        self._node_limit: int | None = None
        self._root_game_ply = 0
        # Set when a node below the current one was scored as a draw because its position was
        # already on the current line (a "path" repetition). Such a score is true for this line
        # only, so a node that saw one must not be stored in the table with its score: another
        # line reaching the same position may not have the repetition available. Draws from the
        # game history are permanent within the game and do not set the flag.
        self._path_draw = False
        # Progress of the root iteration in flight, used to salvage a move after an abort.
        self._partial: tuple[chess.Move, int] | None = None
        self._first_root_move: chess.Move | None = None

    def new_game(self) -> None:
        """Forget everything learned in the previous game."""
        self._tt.clear()
        self._eval_cache.clear()
        for pair in self._killers:
            pair[0] = _NO_MOVE_CODE
            pair[1] = _NO_MOVE_CODE
        for table in self._history_heuristic:
            table[:] = [0] * 4096
        self._cont_history.clear()

    # ------------------------------------------------------------------ public entry point

    def search(
        self,
        board: chess.Board,
        history: Mapping[Key, int],
        soft_deadline: float,
        hard_deadline: float,
        max_depth: int = 64,
        node_limit: int | None = None,
        params: TimeParams = DEFAULT_PARAMS,
    ) -> SearchResult:
        """Search ``board`` and return the best move found within the limits.

        ``history`` holds the transposition keys of every earlier position of the game (the root
        included); any of them reached inside the tree is scored as a draw. ``soft_deadline`` is
        the target: after each completed iteration the next one is started only if it is predicted
        to finish inside it (``timing.should_start_next_depth``). ``hard_deadline`` aborts the
        search wherever it is. ``node_limit`` is a deterministic stand-in for the clock.
        """
        start = _now()
        # Work on a private copy: the caller's board is never touched, even if the search is
        # aborted in the middle of a line. ``stack=False`` drops the move history, which the
        # search does not need (repetitions come from ``history``, the ply from the counters).
        board = board.copy(stack=False)
        # The search makes and unmakes its moves through a SearchBoard, which keeps the running
        # material-plus-square sums and the phase beside the board so that a static evaluation
        # costs no per-piece loop (see mikhail_letal/searchboard.py).
        search_board = SearchBoard(board)
        root_moves = list(board.generate_legal_moves())
        self._nodes = 0
        self._seldepth = 0
        self._null_moves = 0

        if not root_moves:
            score = -MATE_SCORE if board.is_check() else DRAW_SCORE
            return SearchResult(None, score, 0, 0, 0, _now() - start, False)

        # Empty a table that is well on its way to the cap now, between moves, rather than let
        # the cap-hit clear inside _store land in the middle of a deep iteration.
        if len(self._tt) > self.tt_max_entries * TT_CLEAR_FRACTION:
            self._tt.clear()

        self._game_history = history
        self._path = {board._transposition_key(): 1}
        # The root has no previous move: the position arrives as a FEN and the opponent's last
        # move is not part of it, so root moves are ordered on the plain history alone.
        self._cont_base[0] = _CONT_NONE
        self._path_draw = False
        self._hard_deadline = hard_deadline
        self._node_limit = node_limit
        self._root_game_ply = board.ply()
        self._age_history()

        best_move: chess.Move | None = None
        best_score = DRAW_SCORE
        completed_depth = 0
        aborted = False
        # A forced move needs no deep search; one iteration gives it a score and banks the time.
        depth_limit = 1 if len(root_moves) == 1 else max(1, min(max_depth, MAX_PLY - 1))

        # What the next iteration is expected to cost is read off these: how long each completed
        # depth took, and how settled the root move is (see timing.should_start_next_depth).
        iteration_times: list[float] = []
        iteration_start = start
        stable_depths = 0

        for depth in range(1, depth_limit + 1):
            try:
                score, move = self._search_root_aspirated(
                    search_board, root_moves, depth, best_move, best_score, completed_depth
                )
            except SearchAborted:
                aborted = True
                partial = self._partial
                if partial is not None and (completed_depth == 0 or partial[0] != best_move):
                    # The previous best was searched first at this depth and a later move beat
                    # it (or there was no previous iteration at all): the new move is trusted.
                    best_move, best_score = partial
                elif best_move is None:
                    # Aborted inside the very first root move of depth 1: any legal move beats
                    # none, and the ordering has put the most promising one first.
                    best_move = self._first_root_move
                break
            # How settled the root is: iterations in a row that kept the same best move, and how
            # far the score fell at this one (negative when it rose).
            stable_depths = stable_depths + 1 if completed_depth and move == best_move else 0
            score_drop = best_score - score if completed_depth else 0
            best_move, best_score, completed_depth = move, score, depth
            now = _now()
            iteration_times.append(now - iteration_start)
            iteration_start = now
            if not should_start_next_depth(
                now - start,
                iteration_times,
                soft_deadline - start,
                hard_deadline - start,
                stable_depths,
                score_drop,
                params,
            ):
                break
            # A mate in n plies found at depth >= n cannot be shortened by searching deeper.
            if is_mate_score(score) and MATE_SCORE - abs(score) <= depth:
                break

        return SearchResult(
            best_move,
            best_score,
            completed_depth,
            self._seldepth,
            self._nodes,
            _now() - start,
            aborted,
        )

    # ------------------------------------------------------------------ root

    def _search_root_aspirated(
        self,
        board: SearchBoard,
        root_moves: list[chess.Move],
        depth: int,
        previous_best: chess.Move | None,
        previous_score: int,
        completed_depth: int,
    ) -> tuple[int, chess.Move]:
        """One root iteration, with an aspiration window when the feature is on.

        The window starts ``ASPIRATION_WINDOW`` either side of the previous iteration's score.
        A result on or outside an edge is only a bound, so the failing edge is moved out by the
        widening factor (from the bound, not the old guess) and the iteration is searched again;
        after ``ASPIRATION_MAX_FAILS`` failures the full window is used. A move that failed high
        is searched first in the repeat. Mate scores are not aspirated: their exact value is what
        the iteration is for.
        """
        if (
            not ASPIRATION_WINDOWS
            or depth < ASPIRATION_MIN_DEPTH
            or completed_depth == 0
            or is_mate_score(previous_score)
        ):
            return self._search_root(board, root_moves, depth, previous_best, -_INFINITY, _INFINITY)

        window = ASPIRATION_WINDOW
        alpha = previous_score - window
        beta = previous_score + window
        fails = 0
        while True:
            score, move = self._search_root(board, root_moves, depth, previous_best, alpha, beta)
            if alpha < score < beta:
                return score, move
            fails += 1
            if fails >= ASPIRATION_MAX_FAILS:
                alpha, beta = -_INFINITY, _INFINITY
            elif score <= alpha:
                window *= ASPIRATION_WIDEN
                alpha = score - window
            else:
                window *= ASPIRATION_WIDEN
                beta = score + window
                previous_best = move

    def _search_root(
        self,
        search_board: SearchBoard,
        root_moves: list[chess.Move],
        depth: int,
        previous_best: chess.Move | None,
        alpha: int,
        beta: int,
    ) -> tuple[int, chess.Move]:
        """One iteration at the root over every legal move, best guess first, inside
        ``(alpha, beta)``. With the full window the returned score is exact; with a narrower one
        it may be a bound, which the caller detects and re-searches."""
        self._partial = None
        board = search_board.board
        root_key = board._transposition_key()
        if previous_best is None:
            # First iteration: the table persists through the game, so it may remember this
            # position from the previous move's search. Trying that move first is the ordinary
            # "TT move first" rule applied at the root.
            entry = self._tt.get(root_key)
            if entry is not None and entry[3] != _NO_MOVE_CODE:
                previous_best = _code_to_move(entry[3])
        first_code = _move_code(previous_best) if previous_best is not None else _NO_MOVE_CODE
        ordered = self._order_moves(board, root_moves, first_code, 0)
        _queen_promotion_first(ordered)
        self._first_root_move = ordered[0]

        negamax = self._negamax
        alpha_original = alpha
        best_score = -_INFINITY
        best_move = ordered[0]
        scores: list[int] = []  # one per move of ``ordered``, for the draw tie-break below
        self._path_draw = False
        for move in ordered:
            self._push_cont_base(board, move, 1)
            search_board.push(move)
            score = -negamax(search_board, depth - 1, -beta, -alpha, 1)
            search_board.pop()
            scores.append(score)
            if score > best_score:
                best_score = score
                best_move = move
                if score > alpha:
                    # Above alpha the score is exact or a lower bound (the fail-soft argument in
                    # _negamax), so this move really is better than everything before it and can
                    # be trusted if the search is aborted before the iteration ends. A move that
                    # merely tops earlier fail-low bounds cannot.
                    self._partial = (move, score)
                    alpha = score
                    if score >= beta:
                        break  # fail high: the caller widens the window and searches again

        exact = alpha_original < best_score < beta
        if exact and best_score == DRAW_SCORE:
            best_move = self._break_draw_tie(search_board, ordered, scores, best_move)
        if best_score >= beta:
            flag = LOWER
        elif best_score <= alpha_original:
            flag = UPPER
            # Nothing raised alpha, so no move stands out; keep the old first move as the hint.
            if previous_best is not None:
                best_move = previous_best
        else:
            flag = EXACT
        self._store(root_key, depth, best_score, flag, _move_code(best_move), 0, self._path_draw)
        return best_score, best_move

    def _break_draw_tie(
        self,
        search_board: SearchBoard,
        moves: list[chess.Move],
        scores: list[int],
        best: chess.Move,
    ) -> chess.Move:
        """Choose among root moves that all score a draw when the position is clearly won.

        When the fifty-move rule or the 600-ply cap falls inside the horizon, every line ends in
        the rule draw, every root move scores exactly ``DRAW_SCORE`` and the search would pick
        one arbitrarily, move after move, until the draw arrives. If the static evaluation says
        we are well ahead, the tied moves are told apart by the static evaluation of the position
        each one reaches (a handful of ``evaluate`` calls), which keeps the mop-up progressing
        towards the mate the shallow search cannot yet see. A move that stalemates the opponent
        is never chosen this way.
        """
        board = search_board.board
        tied = [move for move, score in zip(moves, scores, strict=True) if score == DRAW_SCORE]
        if len(tied) < 2 or evaluate(board) < DRAW_TIEBREAK_MARGIN:
            return best
        best_static = -_INFINITY
        for move in tied:
            search_board.push(move)
            # ``evaluate`` is from the opponent's view after the move; negate it. A position with
            # no legal moves is never evaluated (it is stalemate here: a mate would not score 0).
            static = -evaluate(board) if any(board.generate_legal_moves()) else -_INFINITY
            search_board.pop()
            if static > best_static:
                best, best_static = move, static
        return best

    # ------------------------------------------------------------------ main search

    def _negamax(
        self,
        search_board: SearchBoard,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
        null_allowed: bool = True,
    ) -> int:
        """Fail-soft negamax alpha-beta. Returns a score from the side to move's view.

        Fail-soft means the returned score may lie outside ``(alpha, beta)``: it is then a bound
        on the true value rather than the value itself, which is what the transposition table
        records with the LOWER/UPPER flags. ``null_allowed`` is False directly after a null move,
        so two sides never pass in a row.
        """
        board = search_board.board
        nodes = self._nodes + 1
        self._nodes = nodes
        if nodes % NODE_CHECK_INTERVAL == 0:
            self._check_limits()
        if ply > self._seldepth:
            self._seldepth = ply

        # (1) The referee draws the game at the ply cap, unless the position is checkmate (the
        # referee tests for game-over conditions before the cap).
        if self._root_game_ply + ply >= GAME_PLY_CAP:
            return self._game_over_score(board, ply)

        # (2) Repetition: a position already seen in the game, or earlier on the current line,
        # is a draw by the threefold rule as far as the engine is concerned. Treating the first
        # repetition as the draw keeps the engine from drifting when it is ahead. A draw found
        # on the current line only is flagged, because it is a fact about the line, not about
        # the position (see _path_draw).
        key = board._transposition_key()
        if key in self._game_history:
            return DRAW_SCORE
        if key in self._path:
            self._path_draw = True
            return DRAW_SCORE

        # (3) Fifty-move rule, again with checkmate taking precedence.
        if board.halfmove_clock >= 100:
            return self._game_over_score(board, ply)

        # (4) Mate-distance pruning. A node ``ply`` plies from the root cannot be worth less than
        # being mated here, -(MATE_SCORE - ply), nor more than mating on this very move,
        # MATE_SCORE - ply - 1, whatever the position is. Clamping the window to that costs two
        # comparisons and ends the search of a line as soon as a shorter mate is already known
        # somewhere above it, which is what stops a mate search from wandering off looking for a
        # longer one. The clamp is safe because it only removes values the node could never return,
        # so `alpha` is a true bound on the value in both directions when the window closes.
        mated_here = -(MATE_SCORE - ply)
        mate_next = MATE_SCORE - ply - 1
        if alpha < mated_here:
            alpha = mated_here
        if beta > mate_next:
            beta = mate_next
        if alpha >= beta:
            return alpha

        # (5) Check extension: a side in check has few sensible replies and the position is
        # tactically hot, so it is searched one ply deeper rather than handed to quiescence. It
        # comes before the table probe so that the probe and the store below agree on the depth
        # of this node; otherwise an in-check node would accept an entry one ply too shallow.
        in_check = board.is_check()
        if in_check:
            depth += 1

        # (6) Transposition table probe. Stored mate scores are distances from the stored node;
        # convert them to distances from the root before comparing with this node's window.
        tt = self._tt
        entry = tt.get(key)
        tt_move: chess.Move | None = None
        if entry is not None:
            entry_depth, entry_score, entry_flag, tt_code = entry
            if tt_code != _NO_MOVE_CODE:
                tt_move = _code_to_move(tt_code)
            # A repetition hint carries a move and nothing else -- `_store` writes it at
            # _HINT_DEPTH with DRAW_SCORE and EXACT so the move survives for ordering. Without the
            # first test a node entered at depth <= _HINT_DEPTH would take that DRAW_SCORE as an
            # exact result and score a won position 0. Mirrors the guard in fastsearch.py.
            if entry_depth > _HINT_DEPTH and entry_depth >= depth:
                if entry_score >= MATE_THRESHOLD:
                    entry_score -= ply
                elif entry_score <= -MATE_THRESHOLD:
                    entry_score += ply
                if entry_flag == EXACT:
                    return entry_score
                if entry_flag == LOWER:
                    if entry_score >= beta:
                        return entry_score
                elif entry_score <= alpha:
                    return entry_score

        # Safety net: never recurse past MAX_PLY, whatever the extensions did.
        if ply >= MAX_PLY:
            return self._static_score(board, ply, in_check)

        # (7) Horizon: resolve captures before evaluating.
        if depth <= 0:
            return self._quiescence(search_board, alpha, beta, ply, in_check, 0)

        # (8) Interior node. Register the position on the current line for repetition checks,
        # and start a fresh path-draw flag for the subtree (the caller's is restored after).
        path = self._path
        path[key] = 1
        outer_path_draw = self._path_draw
        self._path_draw = False

        alpha_original = alpha
        child_depth = depth - 1
        child_ply = ply + 1
        negamax = self._negamax
        # Pruning decisions are never made where a mate bound is in the window: there quiet moves
        # and "doing nothing" are exactly what decides the position.
        mate_bounds = alpha <= -MATE_THRESHOLD or beta >= MATE_THRESHOLD

        # (8b) Reverse futility, "static null move" (see REVERSE_FUTILITY_PRUNING). The mirror of
        # futility: the position is so far above beta that the opponent will not enter it, so no
        # move is generated at all. Returns the margin-adjusted score, a valid and tighter lower
        # bound than beta. Same two guards as futility, for the same reason.
        if (
            REVERSE_FUTILITY_PRUNING
            and depth <= REVERSE_FUTILITY_MAX_DEPTH
            and not in_check
            and not mate_bounds
            and beta - alpha == 1
        ):
            margin = REVERSE_FUTILITY_MARGIN * depth
            static = self._evaluate(search_board)
            if static - margin >= beta:
                del path[key]
                self._path_draw = outer_path_draw
                return static - margin

        # (9) Null-move pruning (see NULL_MOVE_PRUNING for the idea and the guards).
        if (
            NULL_MOVE_PRUNING
            and null_allowed
            and not in_check
            and depth >= NULL_MOVE_MIN_DEPTH
            and not mate_bounds
            and board.occupied_co[board.turn] & ~(board.pawns | board.kings)
            and self._evaluate(search_board) >= beta
        ):
            reduction = NULL_MOVE_BASE_REDUCTION + depth // NULL_MOVE_DEPTH_DIVISOR
            self._null_moves += 1
            # Passing is not a move and refutes nothing, so the node below it has no previous
            # move to be a reply to. Without this it would inherit whatever base the last real
            # move of this node left behind, and credit its cutoffs to a move two plies away.
            self._cont_base[child_ply] = _CONT_NONE
            search_board.push_null()
            null_score = -negamax(
                search_board, depth - 1 - reduction, -beta, -beta + 1, child_ply, False
            )
            search_board.pop_null()
            if null_score >= beta and not is_mate_score(null_score):
                del path[key]
                tainted = self._path_draw
                self._path_draw = outer_path_draw or tainted
                tt_code = _move_code(tt_move) if tt_move is not None else _NO_MOVE_CODE
                self._store(key, depth, beta, LOWER, tt_code, ply, tainted)
                return beta

        # (9b) Internal iterative reduction (see INTERNAL_ITERATIVE_REDUCTION).
        # `not in_check` is a deliberate deviation from the published form: the check extension at
        # the top of this function has already added a ply, and reducing it back here would cancel
        # the extension silently rather than reduce a badly ordered node.
        if (
            INTERNAL_ITERATIVE_REDUCTION
            and tt_move is None
            and depth >= IIR_MIN_DEPTH
            and not in_check
        ):
            depth -= 1

        # (10) Futility: decided once for the node, applied to its quiet moves in the loop.
        futility_bound = -_INFINITY
        if FUTILITY_PRUNING and depth < len(FUTILITY_MARGINS) and not in_check and not mate_bounds:
            bound = self._evaluate(search_board) + FUTILITY_MARGINS[depth]
            if bound <= alpha:
                futility_bound = bound
        pruned_any = False

        # (10b) Late move pruning (see LATE_MOVE_PRUNING). Past a depth-scaled count the
        # remaining quiet moves are not searched at all rather than merely reduced. Consults no
        # evaluation, so it is worth exactly what the move ordering is worth.
        # Null window only, mirroring fastsearch: pruning a move out of a PV node removes it from
        # the answer entirely rather than merely mis-scoring it.
        prune_late_moves = (
            LATE_MOVE_PRUNING
            and depth <= LATE_MOVE_PRUNING_MAX_DEPTH
            and not in_check
            and not mate_bounds
            and beta - alpha == 1
        )
        lmp_count = LATE_MOVE_PRUNING_COUNTS[depth] if prune_late_moves else 0
        quiets_searched = 0

        reduce_late = LATE_MOVE_REDUCTIONS and depth >= LMR_MIN_DEPTH and not in_check
        best_score = -_INFINITY
        best_move: chess.Move | None = None
        searched = 0

        for stage, move in self._staged_moves(board, tt_move, ply, in_check):
            if stage >= STAGE_KILLER and futility_bound > -_INFINITY:
                # A quiet move from a position this far below alpha: its value is at most the
                # futility bound, which is at most alpha, so it cannot improve on what we have.
                pruned_any = True
                continue
            if (
                prune_late_moves
                and stage > STAGE_KILLER
                and searched != 0
                and quiets_searched >= lmp_count
            ):
                # `stage > STAGE_KILLER` is the quiet band: the table move, the captures and both
                # killers are all ordered ahead of anything this can reach. `searched != 0` keeps
                # futility's rule that the first move is never skipped, so "no legal move below"
                # still means mate or stalemate.
                pruned_any = True
                continue
            # After both prunes, so a move that is never searched costs nothing to record.
            self._push_cont_base(board, move, child_ply)
            search_board.push(move)
            if stage > STAGE_KILLER:
                quiets_searched += 1
            if searched == 0:
                # (11) The first move searched is the principal variation candidate: the
                # ordering believes in it, so it gets the full window and its score is what
                # every later move is measured against. It is never reduced.
                score = -negamax(search_board, child_depth, -beta, -alpha, child_ply)
            else:
                # (12) Principal variation search. Later moves are expected to be worse than the
                # first, and proving "no better than alpha" is far cheaper than measuring how
                # much better a move is: the null window (alpha, alpha + 1) cuts off at the
                # first refutation in every subtree. Only a move that beats alpha is measured
                # properly, with a re-search inside the real window.
                #
                # (13) Late-move reduction rides on the same scan, and the re-searches compose
                # in a fixed order -- reduced null window, full-depth null window, full window.
                # Skipping the middle step would spend full depth *and* the full window on a
                # move the shallow search only hinted at.
                reduction = (
                    lmr_reduction(depth, searched)
                    if reduce_late and stage == STAGE_QUIET and searched >= LMR_FULL_DEPTH_MOVES
                    else 0
                )
                score = -negamax(
                    search_board, child_depth - reduction, -alpha - 1, -alpha, child_ply
                )
                if reduction and score > alpha:
                    score = -negamax(search_board, child_depth, -alpha - 1, -alpha, child_ply)
                if alpha < score < beta:
                    # The null window only proved the move beats alpha, never by how much, and
                    # the score lands inside the real window, so this node needs the exact
                    # value. When the caller already gave a null window (beta == alpha + 1) no
                    # integer sits strictly between the two and this never fires.
                    score = -negamax(search_board, child_depth, -beta, -alpha, child_ply)
            search_board.pop()
            searched += 1
            if score > best_score:
                best_score = score
                best_move = move
                if score >= beta:
                    # Beta cutoff: the opponent would never allow this position. Remember quiet
                    # moves that do this, they tend to refute other moves in sibling positions.
                    # The stage tag says whether the move is quiet; only the table move, which
                    # comes from outside the stages, has to be asked.
                    if stage >= STAGE_KILLER or (
                        stage == STAGE_TT and move.promotion is None and not board.is_capture(move)
                    ):
                        self._reward_quiet_cutoff(board, move, depth, ply)
                    break
                if score > alpha:
                    alpha = score

        del path[key]
        tainted = self._path_draw
        self._path_draw = outer_path_draw or tainted

        if pruned_any:
            # The pruned moves are worth at most the futility bound; the node's value is at most
            # the larger of that and the best searched move (still a correct fail-soft bound).
            if futility_bound > best_score:
                best_score = futility_bound
        elif best_move is None:
            # No legal move at all. In check that is checkmate; otherwise stalemate.
            return -(MATE_SCORE - ply) if in_check else DRAW_SCORE

        if best_score >= beta:
            flag = LOWER
        elif best_score <= alpha_original:
            flag = UPPER
        else:
            flag = EXACT
        move_code = _move_code(best_move) if best_move is not None else _NO_MOVE_CODE
        self._store(key, depth, best_score, flag, move_code, ply, tainted)
        return best_score

    def _staged_moves(
        self, board: chess.Board, tt_move: chess.Move | None, ply: int, in_check: bool
    ) -> Iterator[tuple[int, chess.Move]]:
        """Yield ``(stage, move)`` pairs in search order, generating each stage only when the
        search asks for it.

        Most interior nodes end with a cutoff on the first move or two, so building and sorting
        the whole legal move list is wasted work at most nodes. Instead the moves come in four
        stages, each generated only if every move of the earlier stages has been searched:

        1. the transposition-table move, without generating anything: it is legal by
           construction (the key identifies the position exactly, and the move was legal there
           when it was stored);
        2. captures and promotions, from a generator that produces only those, sorted by MVV-LVA;
        3. the two killer moves of this ply, if they are legal quiet moves here (checked with
           ``board.is_legal``, cheaper than generating the quiet moves to look for them);
        4. the remaining quiet moves, sorted by the history heuristic.

        The order of the whole sequence is exactly the order ``_order_moves`` would give the full
        legal list (the root still uses that), so staging changes no search result, only the
        amount of generation work. Moves already handed out by an earlier stage are skipped by
        comparing integer move codes.
        """
        tt_code = _NO_MOVE_CODE
        if tt_move is not None:
            tt_code = _move_code(tt_move)
            yield STAGE_TT, tt_move

        for move in self._capture_moves(board, False, in_check):
            if move.from_square | move.to_square << 6 | (move.promotion or 0) << 12 != tt_code:
                yield STAGE_CAPTURE, move

        turn = board.turn
        own = board.occupied_co[turn]
        occupied = board.occupied
        ep_square = board.ep_square
        pawns = board.pawns & own
        killer_first, killer_second = self._killers[ply]
        for code in (killer_first, killer_second):
            if code in (_NO_MOVE_CODE, tt_code):
                continue
            from_square = code & 63
            to_square = code >> 6 & 63
            # A killer was a quiet move where it was learned. Here it is a candidate only if it
            # can still be one: our piece on the from-square, nothing on the to-square, and not
            # a pawn heading for the en passant square (that is a capture, handed out already).
            if (
                not own >> from_square & 1
                or occupied >> to_square & 1
                or (to_square == ep_square and pawns >> from_square & 1)
            ):
                continue
            move = chess.Move(from_square, to_square)
            if board.is_legal(move):
                yield STAGE_KILLER, move

        # Quiet moves. Two generator calls keep python-chess's own order (pieces, castling, then
        # pawn pushes): non-pawns may go to any square not held by the enemy (castling needs the
        # rook's square in the mask), pawns that cannot promote may push to an empty square other
        # than the en passant square. Pawns on the promotion rank were handled as promotions.
        enemy = board.occupied_co[not turn]
        quiets = list(board.generate_legal_moves(own & ~pawns, ~enemy & chess.BB_ALL))
        pushers = pawns & ~_PROMOTION_RANK[turn]
        if pushers:
            push_targets = ~occupied & chess.BB_ALL
            if ep_square is not None:
                push_targets &= ~chess.BB_SQUARES[ep_square]
            quiets.extend(board.generate_legal_moves(pushers, push_targets))
        history = self._history_heuristic[turn]
        cont = self._cont_history
        cont_base = self._cont_base[ply]
        if len(quiets) > 1:
            piece_type_at = board.piece_type_at
            quiets.sort(
                key=lambda m: _quiet_order(
                    history,
                    cont,
                    cont_base,
                    piece_type_at(m.from_square) or 0,
                    m.from_square,
                    m.to_square,
                ),
                reverse=True,
            )
        for move in quiets:
            code = move.from_square | move.to_square << 6
            if code != tt_code and code != killer_first and code != killer_second:
                yield STAGE_QUIET, move

    def _capture_moves(
        self, board: chess.Board, quiescence: bool, in_check: bool
    ) -> list[chess.Move]:
        """Legal captures and promotions, best first by MVV-LVA.

        The MVV-LVA key is ``10 * gain - attacker`` where gain is the rank of the captured piece
        plus, for a promotion, the rank of the promoted piece. In quiescence, under-promotions are
        dropped: they are almost never the point of a capture sequence.

        Where the side to move is not in check this walks the bitboards itself instead of asking
        python-chess for a masked legal-move list, because the two jobs fold into one: the branch
        that says which piece stands on the from-square gives both its attack set and its rank in
        the ordering key, so no move needs a ``piece_type_at`` afterwards, and the pawn pushes,
        castling and en passant machinery inside ``generate_pseudo_legal_moves`` is never entered.

        Legality is python-chess's own rule, not a new one. With no check on the board a move is
        legal unless it is the king walking into an attacked square, or a piece that shields the
        king from a slider stepping off that line: exactly ``Board._is_safe``. The second case is
        applied here as one mask — a pinned piece may only move along the line through the king,
        which is ``BB_RAYS[king][from_square]`` — which is the same test as ``_is_safe``'s
        ``ray(from, to) & king``, because three squares lie on a line whichever pair names it.
        In check (and in the impossible case of a board with no king) the evasion rules apply
        instead and the whole list comes from python-chess, below.

        The order is python-chess's generation order — pieces from the high square down, each
        piece's targets from the high square down, then pawn captures, then promotion pushes, then
        en passant — so the stable sort by key leaves ties exactly where the previous version left
        them, and the search tree is unchanged.
        """
        turn = board.turn
        own = board.occupied_co[turn]
        king_bb = board.kings & own
        if in_check or not king_bb:
            return self._capture_moves_in_check(board, quiescence)

        enemy = board.occupied_co[not turn]
        king = king_bb.bit_length() - 1
        blockers = board._slider_blockers(king)
        king_rays = _RAYS[king]
        occupied = board.occupied
        pawns = board.pawns
        own_pawns = pawns & own
        knights = board.knights
        bishops = board.bishops
        rooks = board.rooks
        squares = _SQUARES
        # The victim's type, tested in one place: anything of the enemy's that is none of these
        # is the queen (its king is never a legal target).
        enemy_pawns = pawns & enemy
        enemy_knights = knights & enemy
        enemy_bishops = bishops & enemy
        enemy_rooks = rooks & enemy

        scored: list[tuple[int, chess.Move]] = []
        append = scored.append

        piece_bb = own & ~own_pawns
        while piece_bb:
            from_square = piece_bb.bit_length() - 1
            from_bb = squares[from_square]
            piece_bb ^= from_bb
            if knights & from_bb:
                attacker = chess.KNIGHT
                targets = _KNIGHT_ATTACKS[from_square]
            elif bishops & from_bb:
                attacker = chess.BISHOP
                targets = _DIAG_ATTACKS[from_square][_DIAG_MASKS[from_square] & occupied]
            elif rooks & from_bb:
                attacker = chess.ROOK
                targets = _RANK_ATTACKS[from_square][_RANK_MASKS[from_square] & occupied]
                targets |= _FILE_ATTACKS[from_square][_FILE_MASKS[from_square] & occupied]
            elif board.queens & from_bb:
                attacker = chess.QUEEN
                targets = _DIAG_ATTACKS[from_square][_DIAG_MASKS[from_square] & occupied]
                targets |= _RANK_ATTACKS[from_square][_RANK_MASKS[from_square] & occupied]
                targets |= _FILE_ATTACKS[from_square][_FILE_MASKS[from_square] & occupied]
            else:
                attacker = chess.KING
                targets = _KING_ATTACKS[from_square]
            targets &= enemy
            if not targets:
                continue
            if attacker == chess.KING:
                # The king may not step onto a square the enemy attacks.
                attackers_mask = board.attackers_mask
                enemy_colour = not turn
                while targets:
                    to_square = targets.bit_length() - 1
                    to_bb = squares[to_square]
                    targets ^= to_bb
                    if attackers_mask(enemy_colour, to_square):
                        continue
                    if enemy_pawns & to_bb:
                        victim = chess.PAWN
                    elif enemy_knights & to_bb:
                        victim = chess.KNIGHT
                    elif enemy_bishops & to_bb:
                        victim = chess.BISHOP
                    elif enemy_rooks & to_bb:
                        victim = chess.ROOK
                    else:
                        victim = chess.QUEEN
                    append((10 * victim - chess.KING, chess.Move(from_square, to_square)))
                continue
            if blockers & from_bb:
                targets &= king_rays[from_square]  # pinned: only along the line through the king
            key_base = -attacker
            while targets:
                to_square = targets.bit_length() - 1
                to_bb = squares[to_square]
                targets ^= to_bb
                if enemy_pawns & to_bb:
                    victim = chess.PAWN
                elif enemy_knights & to_bb:
                    victim = chess.KNIGHT
                elif enemy_bishops & to_bb:
                    victim = chess.BISHOP
                elif enemy_rooks & to_bb:
                    victim = chess.ROOK
                else:
                    victim = chess.QUEEN
                append((key_base + 10 * victim, chess.Move(from_square, to_square)))

        pawn_attacks = _PAWN_ATTACKS[turn]
        piece_bb = own_pawns
        while piece_bb:
            from_square = piece_bb.bit_length() - 1
            from_bb = squares[from_square]
            piece_bb ^= from_bb
            targets = pawn_attacks[from_square] & enemy
            if not targets:
                continue
            if blockers & from_bb:
                targets &= king_rays[from_square]
            while targets:
                to_square = targets.bit_length() - 1
                to_bb = squares[to_square]
                targets ^= to_bb
                if enemy_pawns & to_bb:
                    victim = chess.PAWN
                elif enemy_knights & to_bb:
                    victim = chess.KNIGHT
                elif enemy_bishops & to_bb:
                    victim = chess.BISHOP
                elif enemy_rooks & to_bb:
                    victim = chess.ROOK
                else:
                    victim = chess.QUEEN
                if to_bb & _BACK_RANKS:
                    # A capture that promotes: the promoted piece counts toward the gain, and
                    # python-chess yields queen, rook, bishop, knight in that order.
                    append((10 * (victim + 5) - 1, chess.Move(from_square, to_square, chess.QUEEN)))
                    if not quiescence:
                        append(
                            (10 * (victim + 4) - 1, chess.Move(from_square, to_square, chess.ROOK))
                        )
                        append(
                            (
                                10 * (victim + 3) - 1,
                                chess.Move(from_square, to_square, chess.BISHOP),
                            )
                        )
                        append(
                            (
                                10 * (victim + 2) - 1,
                                chess.Move(from_square, to_square, chess.KNIGHT),
                            )
                        )
                else:
                    append((10 * victim - 1, chess.Move(from_square, to_square)))

        pushers = own_pawns & _PROMOTION_RANK[turn]
        if pushers:
            singles = (pushers << 8 if turn else pushers >> 8) & ~occupied
            while singles:
                to_square = singles.bit_length() - 1
                to_bb = squares[to_square]
                singles ^= to_bb
                from_square = to_square - 8 if turn else to_square + 8
                if blockers & squares[from_square] and not king_rays[from_square] & to_bb:
                    continue
                append((49, chess.Move(from_square, to_square, chess.QUEEN)))
                if not quiescence:
                    append((39, chess.Move(from_square, to_square, chess.ROOK)))
                    append((29, chess.Move(from_square, to_square, chess.BISHOP)))
                    append((19, chess.Move(from_square, to_square, chess.KNIGHT)))

        if board.ep_square is not None:
            # Rare and full of corner cases (the captured pawn is not on the target square and
            # the capture can uncover a rank check), so python-chess rules on it.
            for move in board.generate_legal_ep():
                append((9, move))  # a pawn takes a pawn

        if len(scored) > 1:
            scored.sort(key=_ORDER_KEY, reverse=True)
        return [pair[1] for pair in scored]

    def _capture_moves_in_check(self, board: chess.Board, quiescence: bool) -> list[chess.Move]:
        """``_capture_moves`` for a side in check: python-chess generates the evasions.

        Three bitboard-masked generator calls produce only the wanted moves: moves onto enemy
        pieces, pushes by pawns standing on the promotion rank, and en passant.
        """
        turn = board.turn
        moves = list(board.generate_legal_moves(chess.BB_ALL, board.occupied_co[not turn]))
        promoting = board.pawns & board.occupied_co[turn] & _PROMOTION_RANK[turn]
        if promoting:
            moves.extend(board.generate_legal_moves(promoting, ~board.occupied & chess.BB_ALL))
            if quiescence:
                moves = [m for m in moves if m.promotion is None or m.promotion == chess.QUEEN]
        ep_square = board.ep_square
        if ep_square is not None:
            moves.extend(board.generate_legal_ep())
        if len(moves) < 2:
            return moves

        piece_type_at = board.piece_type_at
        rank = _MVV_LVA_RANK

        def capture_key(move: chess.Move) -> int:
            to_square = move.to_square
            victim = piece_type_at(to_square)
            if victim is None:
                # A pawn landing on the en passant square takes a pawn standing elsewhere; a
                # promotion push takes nothing.
                victim = chess.PAWN if to_square == ep_square else 0
            gain = rank[victim] + rank[move.promotion or 0]
            return 10 * gain - rank[piece_type_at(move.from_square) or 0]

        moves.sort(key=capture_key, reverse=True)
        return moves

    # ------------------------------------------------------------------ quiescence

    def _quiescence(
        self,
        search_board: SearchBoard,
        alpha: int,
        beta: int,
        ply: int,
        in_check: bool,
        qs_ply: int,
    ) -> int:
        """Captures-only search that settles tactics before the static evaluation is trusted.

        The caller has already counted this node and computed ``in_check`` (the main search does
        this at the horizon; the capture loop below does it for each capture it makes).
        ``qs_ply`` counts how deep into the quiescence search this node is.

        In check, for the first ``QS_EVASION_PLIES`` quiescence plies, there is no standing pat,
        because doing nothing is not a legal option: every legal evasion is searched, and a
        position without one is checkmate. Otherwise the side to move may stand pat on the
        static evaluation or try captures and queen promotions, ordered by MVV-LVA. The stand-pat
        test comes before any move generation: it ends most quiescence nodes on its own, and
        generating the captures first threw that work away at seven nodes in ten. A position
        with no legal move at all is checkmate or stalemate and is scored as such, never on the
        static evaluation.
        """
        board = search_board.board
        if ply > self._seldepth:
            self._seldepth = ply
        if ply >= MAX_PLY:
            return self._static_score(board, ply, in_check)

        # Transposition probe (see QUIESCENCE_TT). Mirrors fastsearch: entries live at _QS_DEPTH,
        # which no other writer occupies, and the flag decides whether the stored bound settles
        # this window.
        key = board._transposition_key()
        if QUIESCENCE_TT:
            entry = self._tt.get(key)
            if entry is not None and entry[0] >= _QS_DEPTH:
                stored = entry[1]
                if stored >= MATE_THRESHOLD:
                    stored -= ply
                elif stored <= -MATE_THRESHOLD:
                    stored += ply
                flag = entry[2]
                if flag == EXACT:
                    return stored
                if flag == LOWER and stored >= beta:
                    return stored
                if flag == UPPER and stored <= alpha:
                    return stored
        alpha_original = alpha
        legal_seen = 0

        if in_check and qs_ply < QS_EVASION_PLIES:
            moves = list(board.generate_legal_moves())
            if not moves:
                return -(MATE_SCORE - ply)
            if len(moves) > 1:
                self._order_moves(board, moves, _NO_MOVE_CODE, ply)
            best_score = -_INFINITY
        else:
            best_score = self._evaluate(search_board)  # stand pat
            if best_score >= beta:
                # The cutoff is real only if the side to move has a move at all; without one
                # the position is over (a mate if in check, a stalemate otherwise).
                if self._has_legal_move(board, in_check):
                    return best_score
                return -(MATE_SCORE - ply) if in_check else DRAW_SCORE
            if best_score > alpha:
                alpha = best_score
            moves = self._capture_moves(board, True, in_check)
            if not moves:
                if not self._has_legal_move(board, in_check):
                    return -(MATE_SCORE - ply) if in_check else DRAW_SCORE
                return best_score

        # Delta pruning applies only where the side to move could stand pat: then a capture that
        # cannot lift the stand-pat score to alpha even in the best case is not worth searching.
        # ``delta_floor`` is the least gain a capture must promise; every capture passes when the
        # feature is off or the side is in check (its evasions are all searched).
        delta_floor = -_INFINITY
        if (
            DELTA_PRUNING
            and not in_check
            and alpha < MATE_THRESHOLD
            and alpha > best_score + DELTA_MARGIN
        ):
            delta_floor = alpha - best_score - DELTA_MARGIN
        piece_type_at = board.piece_type_at
        ep_square = board.ep_square
        values = _PIECE_VALUE
        pawn_value = values[chess.PAWN]
        promotion_gain = values[chess.QUEEN] - pawn_value

        quiescence = self._quiescence
        child_ply = ply + 1
        child_qs_ply = qs_ply + 1
        for move in moves:
            if delta_floor > -_INFINITY:
                victim = piece_type_at(move.to_square)
                if victim is not None:
                    gain = values[victim]
                else:
                    # An empty target square: en passant wins a pawn, a promotion push nothing.
                    gain = pawn_value if move.to_square == ep_square else 0
                if move.promotion is not None:
                    gain += promotion_gain
                if gain < delta_floor:
                    continue
            self._push_cont_base(board, move, child_ply)
            search_board.push(move)
            nodes = self._nodes + 1
            self._nodes = nodes
            if nodes % NODE_CHECK_INTERVAL == 0:
                self._check_limits()
            child_in_check = board.is_check()
            score = -quiescence(
                search_board, -beta, -alpha, child_ply, child_in_check, child_qs_ply
            )
            search_board.pop()
            legal_seen += 1
            if score > best_score:
                best_score = score
                if score >= beta:
                    if QUIESCENCE_TT:
                        self._store(key, _QS_DEPTH, score, LOWER, _move_code(move), ply, False)
                    return score
                if score > alpha:
                    alpha = score
        # Only when a move was actually searched; see the fastsearch comment for the three reasons.
        if QUIESCENCE_TT and legal_seen:
            flag = UPPER if best_score <= alpha_original else EXACT
            self._store(key, _QS_DEPTH, best_score, flag, _NO_MOVE_CODE, ply, False)
        return best_score

    @staticmethod
    def _has_legal_move(board: chess.Board, in_check: bool) -> bool:
        """Whether the side to move has a legal move at all.

        Quiescence asks this to tell a real stand-pat cutoff from a checkmate or a stalemate, and
        it asks at a third of all nodes, where generating one legal move costs most of a move
        generation. The answer is nearly always yes, and with no check on the board there is a
        cheap sufficient reason: a piece that is not shielding its king from a slider cannot
        expose it by moving, so any pseudo-legal move of such a piece is legal (this is exactly
        the ``not blockers & from_square`` branch of ``Board._is_safe``). One pawn that can step
        forward, or one piece with a square to go to, settles it.

        When that finds nothing — the side is in check, or every piece is pinned or has nowhere
        to go — python-chess's own generator answers, so the result is always exact.
        """
        if not in_check:
            turn = board.turn
            own = board.occupied_co[turn]
            king_bb = board.kings & own
            if king_bb:
                free = own & ~board._slider_blockers(king_bb.bit_length() - 1) & ~king_bb
                pawns = board.pawns & free
                occupied = board.occupied
                if pawns and (pawns << 8 if turn else pawns >> 8) & ~occupied:
                    return True
                not_own = ~own
                others = free & ~pawns
                while others:
                    square = others.bit_length() - 1
                    square_bb = _SQUARES[square]
                    others ^= square_bb
                    if board.knights & square_bb:
                        attacks = _KNIGHT_ATTACKS[square]
                    elif board.bishops & square_bb:
                        attacks = _DIAG_ATTACKS[square][_DIAG_MASKS[square] & occupied]
                    elif board.rooks & square_bb:
                        attacks = _RANK_ATTACKS[square][_RANK_MASKS[square] & occupied]
                        attacks |= _FILE_ATTACKS[square][_FILE_MASKS[square] & occupied]
                    else:
                        attacks = _DIAG_ATTACKS[square][_DIAG_MASKS[square] & occupied]
                        attacks |= _RANK_ATTACKS[square][_RANK_MASKS[square] & occupied]
                        attacks |= _FILE_ATTACKS[square][_FILE_MASKS[square] & occupied]
                    if attacks & not_own:
                        return True
        return any(board.generate_legal_moves())

    # ------------------------------------------------------------------ move ordering

    def _order_moves(
        self, board: chess.Board, moves: list[chess.Move], tt_code: int, ply: int
    ) -> list[chess.Move]:
        """Sort ``moves`` in place, best guess first, and return the list.

        Order: TT move, captures/promotions by MVV-LVA (victim rank x 10 - attacker rank, a
        promotion counting the promoted piece as the victim), the two killers of this ply, then
        quiet moves by history score. Python's sort is stable, so ties keep the generator's
        order and the result is deterministic.
        """
        piece_type_at = board.piece_type_at
        ep_square = board.ep_square
        killer_first, killer_second = self._killers[ply]
        history = self._history_heuristic[board.turn]
        cont = self._cont_history
        cont_base = self._cont_base[ply]
        rank = _MVV_LVA_RANK
        pawn = chess.PAWN

        def order_key(move: chess.Move) -> int:
            from_square = move.from_square
            to_square = move.to_square
            promotion = move.promotion
            code = from_square | to_square << 6 | (promotion or 0) << 12
            if code == tt_code:
                return _ORDER_TT
            victim = piece_type_at(to_square)
            # A pawn landing on the en passant square captures a pawn that is not on that square.
            if victim is None and to_square == ep_square and piece_type_at(from_square) == pawn:
                victim = pawn
            if victim is not None or promotion is not None:
                gain = rank[victim or 0] + rank[promotion or 0]
                return _ORDER_CAPTURE + 10 * gain - rank[piece_type_at(from_square) or 0]
            if code == killer_first:
                return _ORDER_KILLER_FIRST
            if code == killer_second:
                return _ORDER_KILLER_SECOND
            return _quiet_order(
                history,
                cont,
                cont_base,
                piece_type_at(from_square) or 0,
                from_square,
                to_square,
            )

        moves.sort(key=order_key, reverse=True)
        return moves

    def _push_cont_base(self, board: chess.Board, move: chess.Move, child_ply: int) -> None:
        """Record where the replies to ``move`` are filed, for the node it is about to lead to.

        Called with ``board`` still in the position ``move`` is played from, so ``board.turn`` is
        the side playing it and the from-square still holds the piece that moves. A promotion is
        filed under the pawn that left, not the piece that arrives, which is the same convention
        the plain history's from-square carries.
        """
        self._cont_base[child_ply] = (
            _cont_base(board.turn, board.piece_type_at(move.from_square) or 0, move.to_square)
            if CONTINUATION_HISTORY
            else _CONT_NONE
        )

    def _reward_quiet_cutoff(
        self, board: chess.Board, move: chess.Move, depth: int, ply: int
    ) -> None:
        """A quiet move caused a beta cutoff: make it a killer and raise its history score."""
        killers = self._killers[ply]
        code = _move_code(move)
        if killers[0] != code:
            killers[1] = killers[0]
            killers[0] = code
        history = self._history_heuristic[board.turn]
        index = move.from_square << 6 | move.to_square
        # depth * depth: cutoffs near the root are rarer and worth more than cutoffs near leaves.
        history[index] = min(history[index] + depth * depth, _HISTORY_MAX)
        # The same credit again, in the context of the move this one replied to. The caller has
        # already unmade the move, so the from-square holds the piece that played it.
        base = self._cont_base[ply]
        if base != _CONT_NONE:
            cont = self._cont_history
            piece_type = board.piece_type_at(move.from_square) or 0
            cont_index = base + piece_type * _CONT_SQUARES + move.to_square
            cont[cont_index] = min(cont.get(cont_index, 0) + depth * depth, _HISTORY_MAX)

    def _age_history(self) -> None:
        """Halve every history score so what was learned last move fades rather than saturates."""
        for table in self._history_heuristic:
            table[:] = [value >> 1 for value in table]
        # Same halving for the continuation table. An entry that would reach zero is dropped
        # instead of kept, which is the same table (a missing entry reads as zero) and stops a
        # long game from accumulating rows it no longer believes anything about.
        self._cont_history = {
            index: value >> 1 for index, value in self._cont_history.items() if value > 1
        }

    # ------------------------------------------------------------------ helpers

    def _evaluate(self, search_board: SearchBoard) -> int:
        """The static evaluation, with a cache keyed on the piece placement and the side to move.

        The static evaluation depends on nothing else (castling rights, the en passant square
        and the clocks play no part in it), so the key is exact: a hit returns precisely what
        ``evaluate`` would have computed. The cache is emptied when it reaches its cap. A miss
        costs only the structural terms and the phase blend, because the per-piece sums come
        from the SearchBoard's running totals.
        """
        board = search_board.board
        key = (
            board.pawns,
            board.knights,
            board.bishops,
            board.rooks,
            board.queens,
            board.kings,
            board.occupied_co[True],
            board.turn,
        )
        cache = self._eval_cache
        score = cache.get(key)
        if score is None:
            if len(cache) >= EVAL_CACHE_MAX_ENTRIES:
                cache.clear()
            score = cache[key] = search_board.evaluate()
        return score

    def _store(
        self, key: Key, depth: int, score: int, flag: int, move_code: int, ply: int, tainted: bool
    ) -> None:
        """Write a TT entry with the score made independent of the node's distance from the root.

        A ``tainted`` score (one that depended on a repetition along the current line) is not
        stored at all; only its move is kept, at ``_HINT_DEPTH``, as an ordering hint, and even
        that does not displace an entry whose score was earned without the repetition.
        """
        tt = self._tt
        if tainted:
            existing = tt.get(key)
            if existing is not None and existing[0] > _HINT_DEPTH:
                return
            depth, score, flag = _HINT_DEPTH, DRAW_SCORE, EXACT
        elif score >= MATE_THRESHOLD:
            score += ply
        elif score <= -MATE_THRESHOLD:
            score -= ply
        if len(tt) >= self.tt_max_entries:
            # The backstop: search() empties a table above TT_CLEAR_FRACTION between moves.
            tt.clear()
        tt[key] = (depth, score, flag, move_code)

    def _check_limits(self) -> None:
        """Every NODE_CHECK_INTERVAL nodes: abort past the node limit or the hard deadline."""
        limit = self._node_limit
        if limit is not None and self._nodes >= limit:
            raise SearchAborted
        if _now() >= self._hard_deadline:
            raise SearchAborted

    @staticmethod
    def _game_over_score(board: chess.Board, ply: int) -> int:
        """Score where the referee would stop the game: checkmate wins, anything else draws."""
        return -(MATE_SCORE - ply) if board.is_checkmate() else DRAW_SCORE

    @staticmethod
    def _static_score(board: chess.Board, ply: int, in_check: bool) -> int:
        """Score for a node that may not recurse further (the MAX_PLY guard).

        Rare enough that generating moves here costs nothing overall, and it keeps the promise
        that a position without legal moves is never handed to ``evaluate``.
        """
        if not any(board.generate_legal_moves()):
            return -(MATE_SCORE - ply) if in_check else DRAW_SCORE
        return evaluate(board)


def _queen_promotion_first(ordered: list[chess.Move]) -> None:
    """If the first root move is an under-promotion, search the queen promotion of the same pawn
    to the same square before it.

    The root keeps the first move that reaches the best score, so whichever promotion is searched
    first wins an exact tie. Normally MVV-LVA puts the queen first, but the table move (the
    previous iteration's or the previous search's choice) overrides the ordering, and once an
    under-promotion has been chosen it would keep being chosen. Searching the queen first makes
    the queen the tie winner without any comparison of scores that are only bounds.
    """
    first = ordered[0]
    if first.promotion is None or first.promotion == chess.QUEEN:
        return
    for index, move in enumerate(ordered):
        if (
            move.promotion == chess.QUEEN
            and move.from_square == first.from_square
            and move.to_square == first.to_square
        ):
            ordered.insert(0, ordered.pop(index))
            return
