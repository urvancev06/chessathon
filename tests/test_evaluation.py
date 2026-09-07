"""Unit and property tests for ``mikhail_letal.evaluation`` and the table generator."""

from __future__ import annotations

import json
import random
from pathlib import Path

import chess
import pytest

from mikhail_letal import evaluation as ev
from mikhail_letal.evaluation import (
    DRAW_SCORE,
    MATE_SCORE,
    MATE_THRESHOLD,
    PHASE_TOTAL,
    evaluate,
    game_phase,
    is_mate_score,
)
from tools import gen_pst, tune_texel

ROOT = Path(__file__).resolve().parent.parent
PST_PATH = ROOT / "weights" / "pst.json"
RAW_TABLES = json.loads(PST_PATH.read_text())


def random_positions(count: int, seed: int) -> list[chess.Board]:
    """Boards from seeded random playouts (tests may use random; the shipped engine may not)."""
    rng = random.Random(seed)
    boards: list[chess.Board] = []
    while len(boards) < count:
        board = chess.Board()
        for _ in range(rng.randint(10, 120)):
            moves = list(board.legal_moves)
            if not moves or board.is_game_over():
                break
            board.push(rng.choice(moves))
        boards.append(board)
    return boards


# (a) start position


def test_start_position_is_balanced() -> None:
    assert evaluate(chess.Board()) == 0


# (b) colour symmetry


def test_colour_symmetry_under_mirror() -> None:
    """``board.mirror()`` swaps colours, flips the board and hands the move to the other side.

    The mirrored position is the same game seen from the other chair, so a side-to-move
    evaluation must give the same number. This exercises the tapered rounding at every phase.
    """
    for board in random_positions(25, seed=2026):
        assert evaluate(board) == evaluate(board.mirror()), board.fen()


def test_perspective_flip_negates() -> None:
    """Handing the move to the other side (same pieces) negates the score exactly."""
    for board in random_positions(25, seed=7):
        flipped = board.copy()
        flipped.turn = not flipped.turn
        assert evaluate(board) == -evaluate(flipped), board.fen()


def test_mirror_symmetry_in_a_mopup_position() -> None:
    board = chess.Board("8/8/8/8/8/2k5/8/K6R b - - 0 1")
    assert evaluate(board) == evaluate(board.mirror())


# (c) material


def test_extra_queen_is_a_large_advantage() -> None:
    fen = "rnbqkbnr/pppppppp/8/8/8/3Q4/PPPPPPPP/RNBQKBNR {turn} KQkq - 0 1"
    white_to_move = evaluate(chess.Board(fen.format(turn="w")))
    black_to_move = evaluate(chess.Board(fen.format(turn="b")))
    assert white_to_move > 800
    assert black_to_move < -800
    assert white_to_move == -black_to_move


def test_material_only_position_matches_piece_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pawnless-phase position whose king table entries cancel isolates the material value."""
    board = chess.Board("k7/8/8/8/8/8/8/K7 w - - 0 1")
    board.set_piece_at(chess.A3, chess.Piece(chess.PAWN, chess.WHITE))
    # Phase 0 (no pieces) so only the endgame table counts: the pawn's value plus its a3 entry.
    assert game_phase(board) == 0
    pawn = RAW_TABLES["piece_values_eg"]["P"] + RAW_TABLES["pst_eg"]["P"][chess.A3]
    # Kings a8 and a1 read the same (mirrored) endgame entry for both sides, cancelling out.
    monkeypatch.setattr(ev, "STRUCTURE_TERMS", False)
    assert evaluate(board) == pawn
    # With the structural terms on, the a3 pawn is passed (3rd rank: 2 x the endgame rank bonus)
    # and isolated, and nothing else applies.
    monkeypatch.setattr(ev, "STRUCTURE_TERMS", True)
    weights = ev.STRUCTURE_WEIGHTS
    assert evaluate(board) == pawn + 2 * weights["passed_pawn_eg"] - weights["isolated_pawn"]


# (c2) structural terms (v0.2). Each test isolates one term by comparing two positions that
# differ only in that feature, with the flag forced on.


@pytest.fixture
def structure_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ev, "STRUCTURE_TERMS", True)


def test_passed_pawn_bonus_grows_with_rank(structure_on: None) -> None:
    weights = ev.STRUCTURE_WEIGHTS
    # White pawn e4 against a black pawn on the a-file: passed, four ranks up (index 3).
    mg, eg = ev.pawn_structure(chess.BB_E4, chess.BB_A7)
    # Both pawns are isolated and the a7 pawn is passed too (2nd rank from Black's side, x1).
    assert eg == 3 * weights["passed_pawn_eg"] - 1 * weights["passed_pawn_eg"]
    assert mg == 3 * weights["passed_pawn_mg"] - 1 * weights["passed_pawn_mg"]
    # A black pawn on d5, f5 or e5 (ahead on an adjacent file or blocking) means not passed.
    for blocker in (chess.BB_D5, chess.BB_F5, chess.BB_E5, chess.BB_D7):
        mg_b, eg_b = ev.pawn_structure(chess.BB_E4, blocker)
        assert eg_b < eg and mg_b < mg, chess.SquareSet(blocker)
    # A black pawn behind the white pawn does not stop it: White's share (the total minus what
    # the black pawn scores on its own) is still the passed bonus less the isolated penalty.
    with_d3 = ev.pawn_structure(chess.BB_E4, chess.BB_D3)
    alone_d3 = ev.pawn_structure(0, chess.BB_D3)
    assert with_d3[1] - alone_d3[1] == 3 * weights["passed_pawn_eg"] - weights["isolated_pawn"]


def test_doubled_and_isolated_pawns_are_penalised(structure_on: None) -> None:
    weights = ev.STRUCTURE_WEIGHTS
    # Neither side has passed pawns here: every pawn faces an enemy pawn on its file.
    healthy = ev.pawn_structure(chess.BB_C2 | chess.BB_D2, chess.BB_C7 | chess.BB_D7)
    assert healthy == (0, 0)
    doubled = ev.pawn_structure(chess.BB_C2 | chess.BB_C3, chess.BB_C7 | chess.BB_D7)
    # White's c-pawns: one doubled, both isolated (no b- or d-pawn). Black's are untouched.
    assert doubled == (
        -weights["doubled_pawn"] - 2 * weights["isolated_pawn"],
        -weights["doubled_pawn"] - 2 * weights["isolated_pawn"],
    )
    # Tripled pawns cost two doubled penalties.
    tripled = ev.pawn_structure(chess.BB_C2 | chess.BB_C3 | chess.BB_C4, chess.BB_C7 | chess.BB_D7)
    assert tripled == (
        -2 * weights["doubled_pawn"] - 3 * weights["isolated_pawn"],
        -2 * weights["doubled_pawn"] - 3 * weights["isolated_pawn"],
    )
    # A pawn on an adjacent file rescues an isolated pawn even from a distance along the file.
    assert ev._isolated_count(chess.BB_A2 | chess.BB_B7) == 0
    assert ev._isolated_count(chess.BB_A2 | chess.BB_C2) == 2
    assert ev._isolated_count(chess.BB_H2 | chess.BB_G4) == 0


def test_bishop_pair_bonus(structure_on: None) -> None:
    pair = "k7/8/8/8/8/8/8/KBB4R w - - 0 1"  # the rook keeps the mop-up out of the difference
    one = "k7/8/8/8/8/8/8/KBN4R w - - 0 1"  # the c1 bishop becomes a knight: same phase
    bonus = ev.STRUCTURE_WEIGHTS["bishop_pair"]
    # The structural terms differ by exactly the bonus in both phases ...
    assert tuple(a - b for a, b in zip(structure_of(pair), structure_of(one), strict=True)) == (
        bonus,
        bonus,
    )
    # ... and the full evaluation by the bonus plus the bishop-for-knight table difference on
    # c1, up to the truncation of the two phase blends.
    table = ev.TABLES
    phase = ev.game_phase(chess.Board(pair))
    assert phase == ev.game_phase(chess.Board(one))

    def blended(piece_type: chess.PieceType) -> float:
        mg = table.mg[chess.WHITE][piece_type][chess.C1]
        eg = table.eg[chess.WHITE][piece_type][chess.C1]
        return (mg * phase + eg * (ev.PHASE_TOTAL - phase)) / ev.PHASE_TOTAL

    material = blended(chess.BISHOP) - blended(chess.KNIGHT)
    difference = evaluate(chess.Board(pair)) - evaluate(chess.Board(one))
    assert abs(difference - material - bonus) <= 1


def structure_of(fen: str) -> tuple[int, int]:
    """The (middlegame, endgame) structural terms of a position, from White's view."""
    board = chess.Board(fen)
    return ev._structure(
        board.occupied_co[chess.WHITE],
        board.occupied_co[chess.BLACK],
        board.pawns,
        board.bishops,
        board.rooks,
        board.kings,
    )


def test_rook_on_open_and_semi_open_file(structure_on: None) -> None:
    weights = ev.STRUCTURE_WEIGHTS
    isolated = weights["isolated_pawn"]
    # White rook a1; the kings stand on e1/e8 with no pawn in their shield zones. The a-file is
    # open, then semi-open (black a7 added), then closed (white a2 added too). Adding a pawn also
    # changes the isolated-pawn terms of its neighbour, which the expectations account for.
    open_file = structure_of("4k3/1p6/8/8/8/8/1P6/R3K3 w - - 0 1")  # b2 and b7 both isolated
    semi_open = structure_of("4k3/pp6/8/8/8/8/1P6/R3K3 w - - 0 1")  # a7 un-isolates b7
    closed = structure_of("4k3/pp6/8/8/8/8/PP6/R3K3 w - - 0 1")  # a2 un-isolates b2
    open_vs_semi = weights["rook_open_file"] - weights["rook_semi_open_file"] + isolated
    assert tuple(a - b for a, b in zip(open_file, semi_open, strict=True)) == (
        open_vs_semi,
        open_vs_semi,
    )
    # Closed: the rook term is gone and neither white pawn is isolated any more (b2 was).
    semi_vs_closed = weights["rook_semi_open_file"] - isolated
    assert tuple(a - b for a, b in zip(semi_open, closed, strict=True)) == (
        semi_vs_closed,
        semi_vs_closed,
    )
    # No pawn is passed in any of the three: every pawn faces an enemy pawn on its own or an
    # adjacent file, so the passed-pawn term contributed nothing above.
    assert ev.pawn_structure(chess.BB_B2, chess.BB_B7) == (0, 0)


def test_king_shield_counts_pawns_in_front_of_the_king(structure_on: None) -> None:
    weights = ev.STRUCTURE_WEIGHTS
    # White king g1 with pawns f2 g2 h2 versus the same pawns moved far away (still on the same
    # files, so the pawn-structure terms are unchanged: no passed, doubled or isolated changes
    # while the black pawns f7 g7 h7 face them). Both sides have a queen so the phase is not 0.
    shielded = "6k1/5ppp/8/8/8/8/5PPP/6KQ w - - 0 1"
    bare = "6k1/5ppp/8/8/5PPP/8/8/6KQ w - - 0 1"
    # The structural terms differ by three shield pawns, in the middlegame only.
    assert tuple(
        a - b for a, b in zip(structure_of(shielded), structure_of(bare), strict=True)
    ) == (
        3 * weights["king_shield"],
        0,
    )
    # The full evaluation adds the pawns' table values; check up to the blends' truncation.
    phase = ev.game_phase(chess.Board(shielded))
    table = ev.TABLES
    pst = sum(
        table.mg[1][chess.PAWN][s] * phase + table.eg[1][chess.PAWN][s] * (ev.PHASE_TOTAL - phase)
        for s in (chess.F2, chess.G2, chess.H2)
    ) - sum(
        table.mg[1][chess.PAWN][s] * phase + table.eg[1][chess.PAWN][s] * (ev.PHASE_TOTAL - phase)
        for s in (chess.F4, chess.G4, chess.H4)
    )
    expected = (pst + 3 * weights["king_shield"] * phase) / ev.PHASE_TOTAL
    difference = evaluate(chess.Board(shielded)) - evaluate(chess.Board(bare))
    assert abs(difference - expected) <= 1
    # The shield mask itself: g1 covers f2 g2 h2 f3 g3 h3 and nothing else.
    assert (
        ev._SHIELD[chess.WHITE][chess.G1]
        == chess.SquareSet([chess.F2, chess.G2, chess.H2, chess.F3, chess.G3, chess.H3]).mask
    )
    assert (
        ev._SHIELD[chess.BLACK][chess.G8]
        == chess.SquareSet([chess.F7, chess.G7, chess.H7, chess.F6, chess.G6, chess.H6]).mask
    )


def test_structure_terms_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    board = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R2Q1RK1 w - - 4 10")
    monkeypatch.setattr(ev, "STRUCTURE_TERMS", False)
    plain = evaluate(board)
    monkeypatch.setattr(ev, "STRUCTURE_TERMS", True)
    assert evaluate(board) != plain
    assert evaluate(board.mirror()) == evaluate(board)  # the terms keep the colour symmetry


# (d) mop-up


def test_mopup_prefers_the_enemy_king_in_the_corner() -> None:
    corner = chess.Board("k7/8/8/8/8/8/8/K6R w - - 0 1")
    centre = chess.Board("8/8/8/3k4/8/8/8/K6R w - - 0 1")
    # Both black kings are seven king-steps from a1, so only the edge term differs.
    assert evaluate(corner) > evaluate(centre)
    # Same from Black's chair: the side to move is the weak side and its score is lower.
    corner.turn = chess.BLACK
    centre.turn = chess.BLACK
    assert evaluate(corner) < evaluate(centre)


def test_mopup_prefers_our_king_close() -> None:
    far = chess.Board("k7/8/8/8/8/8/8/K6R w - - 0 1")
    near = chess.Board("k7/8/8/8/8/8/1K6/7R w - - 0 1")
    assert evaluate(near) > evaluate(far)


def test_mopup_needs_a_rook_or_two_minors_and_no_pawns() -> None:
    # A lone knight or bishop cannot mate, and K+N vs K is insufficient material anyway.
    assert evaluate(chess.Board("k7/8/8/8/8/8/8/KN6 w - - 0 1")) == DRAW_SCORE
    # Two knights are not insufficient material in python-chess and count as two minors.
    two_knights = chess.Board("k7/8/8/8/8/8/8/KNN5 w - - 0 1")
    assert (
        ev._mopup(
            two_knights,
            two_knights.occupied_co[True],
            two_knights.occupied_co[False],
            two_knights.kings,
        )
        > 0
    )
    # With a pawn on the board the mop-up is off (the pawn plans the win instead).
    with_pawn = chess.Board("k7/8/8/8/8/8/P7/K6R w - - 0 1")
    assert (
        ev._mopup(
            with_pawn, with_pawn.occupied_co[True], with_pawn.occupied_co[False], with_pawn.kings
        )
        == 0
    )
    # No bare king: nothing.
    both_armed = chess.Board("k6r/8/8/8/8/8/8/K6R w - - 0 1")
    assert (
        ev._mopup(
            both_armed,
            both_armed.occupied_co[True],
            both_armed.occupied_co[False],
            both_armed.kings,
        )
        == 0
    )


# (e) insufficient material


@pytest.mark.parametrize(
    "fen",
    [
        "k7/8/8/8/8/8/8/K7 w - - 0 1",  # K vs K
        "k7/8/8/8/8/8/8/KB6 w - - 0 1",  # KB vs K
        "k7/8/8/8/8/8/8/KN6 b - - 0 1",  # KN vs K, Black to move
        "kb6/8/8/8/8/8/8/K1B5 w - - 0 1",  # KB vs KB, bishops both on dark squares (b8, c1)
    ],
)
def test_insufficient_material_is_a_draw(fen: str) -> None:
    board = chess.Board(fen)
    assert board.is_insufficient_material()
    assert evaluate(board) == DRAW_SCORE


# (f) mate score boundaries


def test_is_mate_score_boundaries() -> None:
    assert MATE_THRESHOLD == MATE_SCORE - 1_000
    assert is_mate_score(MATE_SCORE)
    assert is_mate_score(-MATE_SCORE)
    assert is_mate_score(MATE_THRESHOLD)
    assert is_mate_score(-MATE_THRESHOLD)
    assert not is_mate_score(MATE_THRESHOLD - 1)
    assert not is_mate_score(-(MATE_THRESHOLD - 1))
    assert not is_mate_score(0)
    assert not is_mate_score(DRAW_SCORE)


# (g) game phase


def test_game_phase_extremes() -> None:
    assert game_phase(chess.Board()) == PHASE_TOTAL
    assert PHASE_TOTAL == 24
    assert game_phase(chess.Board("k7/8/8/8/8/8/8/K7 w - - 0 1")) == 0
    # Pawns do not count.
    assert game_phase(chess.Board("k7/pppppppp/8/8/8/8/PPPPPPPP/K7 w - - 0 1")) == 0


def test_game_phase_clamps_after_promotions() -> None:
    nine_queens = chess.Board("k7/8/8/8/8/8/8/K7 w - - 0 1")
    for sq in (chess.A3, chess.B3, chess.C3, chess.D3, chess.E3, chess.F3, chess.G3, chess.H3):
        nine_queens.set_piece_at(sq, chess.Piece(chess.QUEEN, chess.WHITE))
    assert game_phase(nine_queens) == PHASE_TOTAL


def test_game_phase_drops_as_pieces_leave() -> None:
    board = chess.Board()
    board.remove_piece_at(chess.D1)  # white queen
    assert game_phase(board) == PHASE_TOTAL - 4
    board.remove_piece_at(chess.A8)  # black rook
    assert game_phase(board) == PHASE_TOTAL - 6


# tables and provenance


def test_tables_have_the_right_shape() -> None:
    tables = ev.load_tables()
    for colour in (chess.BLACK, chess.WHITE):
        assert len(tables.mg[colour]) == 7 and len(tables.eg[colour]) == 7
        for piece_type in chess.PIECE_TYPES:
            assert len(tables.mg[colour][piece_type]) == 64
            assert len(tables.eg[colour][piece_type]) == 64
    # The Black table is the White table with squares mirrored.
    for piece_type in chess.PIECE_TYPES:
        for sq in range(64):
            assert (
                tables.mg[chess.BLACK][piece_type][sq]
                == tables.mg[chess.WHITE][piece_type][sq ^ 56]
            )
    # Material is folded in: a table entry is the piece value plus the square's PST entry.
    assert tables.mg[chess.WHITE][chess.PAWN][chess.E2] == (
        RAW_TABLES["piece_values_mg"]["P"] + RAW_TABLES["pst_mg"]["P"][chess.E2]
    )
    assert tables.piece_values_mg[1:] == [RAW_TABLES["piece_values_mg"][p] for p in "PNBRQK"]
    assert tables.piece_values_mg[chess.PAWN] == 100  # the scale anchor of the tuning
    assert tables.piece_values_mg[chess.KING] == 0


def test_no_square_is_worth_more_than_a_rook() -> None:
    """The tuned tables have larger entries than the geometric prior (a passed pawn on the 7th, a
    rook on the 7th), but no single square may rival a rook's material value."""
    bound = RAW_TABLES["piece_values_mg"]["R"]
    for phase_key in ("pst_mg", "pst_eg"):
        for letter, table in RAW_TABLES[phase_key].items():
            assert max(abs(v) for v in table) < bound, (phase_key, letter)


def test_pst_json_is_reproducible_from_its_recorded_generator() -> None:
    """The shipped tables are either the prior itself (tools/gen_pst.py) or a Texel fit toward
    it (tools/tune_texel.py); in both cases the file says which, and rerunning that generator
    with the recorded inputs gives exactly the shipped numbers."""
    provenance = RAW_TABLES["_provenance"]
    if provenance["generator"] == "tools/gen_pst.py":
        pst_mg, pst_eg = gen_pst.build_tables()
        assert RAW_TABLES["pst_mg"] == pst_mg
        assert RAW_TABLES["pst_eg"] == pst_eg
        assert RAW_TABLES["piece_values_mg"] == gen_pst.PIECE_VALUES_MG
        assert RAW_TABLES["piece_values_eg"] == gen_pst.PIECE_VALUES_EG
        assert {k: v["value"] for k, v in provenance["parameters"].items()} == gen_pst.P
        assert {k: p.value for k, p in gen_pst.STRUCTURE_PRIOR.items()} == ev.STRUCTURE_WEIGHTS
    else:
        assert provenance["generator"] == "tools/tune_texel.py"
        assert provenance["prior"]["generator"] == "tools/gen_pst.py"
        assert {k: v["value"] for k, v in provenance["prior"]["parameters"].items()} == gen_pst.P
        assert {k: v["value"] for k, v in provenance["prior"]["structure"].items()} == {
            k: p.value for k, p in gen_pst.STRUCTURE_PRIOR.items()
        }
        # Refit with the recorded data files and lambda (tune_texel's ``check`` command); it
        # takes a few seconds for the feature matrix of the whole position set.
        tables, structure = tune_texel.recorded_fit()
        for key in ("piece_values_mg", "piece_values_eg", "pst_mg", "pst_eg"):
            assert RAW_TABLES[key] == tables[key], key
        assert structure == ev.STRUCTURE_WEIGHTS
        assert provenance["structure_weights"] == structure
    # Phase weights and the mop-up term are never fitted: they are the prior's in both cases.
    assert RAW_TABLES["phase_weights"] == gen_pst.PHASE_WEIGHTS
    assert RAW_TABLES["mopup"] == {
        "edge": gen_pst.P["mopup_edge"],
        "close": gen_pst.P["mopup_close"],
    }


def test_tuning_features_reproduce_evaluate() -> None:
    """The tuner's feature counts times the shipped weights equal ``evaluate`` (White's view)
    to within the phase blend's truncation, on random positions with pawns."""
    shipped = tune_texel.shipped_vector()
    for board in random_positions(40, seed=11):
        if board.pawns and not board.is_game_over():
            model = float(tune_texel.features(board) @ shipped)
            assert abs(model - tune_texel.white_evaluation(board)) <= 1.0, board.fen()


def test_provenance_json_covers_every_parameter_group() -> None:
    records = json.loads((ROOT / "weights" / "PROVENANCE.json").read_text())
    names = {record["parameter"] for record in records}
    expected = {"piece_values_mg", "piece_values_eg", "phase_weights", "mopup"}
    expected |= {f"pst_mg.{p}" for p in "PNBRQK"} | {f"pst_eg.{p}" for p in "PNBRQK"}
    provenance = RAW_TABLES["_provenance"]
    tuned = provenance["generator"] == "tools/tune_texel.py"
    if tuned:
        expected.add("structure_weights")
    assert names == expected
    for record in records:
        assert set(record) == {
            "parameter",
            "value_or_shape",
            "produced_by",
            "run_id",
            "data",
            "note",
        }
        if not tuned or record["parameter"] in ("phase_weights", "mopup"):
            assert record["data"] == "none: parametric prior"
            assert record["produced_by"].startswith("tools/gen_pst.py")
        else:
            assert record["run_id"] == provenance["run_id"]
            assert record["produced_by"].startswith("tools/tune_texel.py @ ")
            assert provenance["data"]["positions"]["sha256"] in record["data"]
            assert provenance["data"]["labels"]["sha256"] in record["data"]


def test_evaluate_is_deterministic() -> None:
    board = chess.Board("r1bq1rk1/pp2bppp/2n1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R2Q1RK1 w - - 4 10")
    first = evaluate(board)
    assert all(evaluate(board) == first for _ in range(100))
