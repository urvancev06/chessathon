"""Correctness gates for `mikhail_letal.fastboard`.

`python-chess` is the oracle for all of it. The perft counts are not taken from a published
table: `chess_perft` below walks `python-chess`'s own legal move generator, so a disagreement is
between the compiled generator and the library the referee itself uses.

Three gates, in the order they catch things:

1. **Perft.** Node counts to depth 4 on the standard test positions and on a set of positions
   built to break a specific rule (en passant that is illegal by discovered check, castling
   through an attacked square, a rook captured on its home square), depth 3 on every curated
   opening and on positions sampled from random playouts.
2. **Move-set equality.** Not the count but the set of UCI strings, on positions sampled from
   random playouts, with the sample checked for the cases that matter (en passant available,
   every castling-rights combination, check, double check, a pawn on the seventh).
3. **Make/unmake round trip.** After making and unmaking any legal move the FEN, including both
   clocks, must be byte-identical, and the piece lists must still agree with the board.

The gates are sized by `LETAL_FULL_GATES`. Unset, they run a reduced sample so that `pytest` is
a few tens of seconds; `LETAL_FULL_GATES=1` runs the sizes `docs/PLAN.md` asks for (219 openings,
2,000 sampled positions at depth 3, 100,000 move-set comparisons). Run the tests under
`NUMBA_BOUNDSCHECK=1` to have numba check every array index in the compiled code.
"""

from __future__ import annotations

import os
import random
from collections.abc import Iterator
from pathlib import Path

import chess
import numpy as np
import pytest

from mikhail_letal import fastboard as fb

FULL_GATES = os.environ.get("LETAL_FULL_GATES") == "1"

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENINGS = REPO_ROOT / "data" / "openings.txt"

STANDARD_START = chess.STARTING_FEN
KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
ENDGAME = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
PROMOTIONS = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
TALKCHESS = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
MIDDLEGAME = "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10"

STANDARD_POSITIONS = [STANDARD_START, KIWIPETE, ENDGAME, PROMOTIONS, TALKCHESS, MIDDLEGAME]


def _castling_combinations() -> list[str]:
    """The same board with each of the sixteen castling-rights combinations, both sides to move.

    Random playouts reach most of these but not reliably all of them, and the rights are exactly
    the state that make/unmake is most likely to restore wrongly.
    """
    fens = []
    for bits in range(16):
        rights = "".join(letter for i, letter in enumerate("KQkq") if bits & (1 << i))
        for turn in ("w", "b"):
            fens.append(f"r3k2r/pp4pp/8/8/8/8/PP4PP/R3K2R {turn} {rights or '-'} - 0 1")
    return fens


# Positions that each break one rule if it is implemented carelessly. The comment says which.
TRICKY_POSITIONS = [
    # En passant capture that is illegal because it uncovers a rank check on the capturing side's
    # own king: both the capturing pawn and the captured pawn leave the fourth rank at once.
    "8/8/8/8/k1pP3R/8/8/3K4 b - d3 0 1",
    "8/8/8/K1Pp3r/8/8/8/3k4 w - d6 0 1",
    # En passant that is legal, and one where the capturing pawn is pinned along a diagonal.
    "8/8/1k6/2b5/2pP4/8/5K2/8 b - d3 0 1",
    "8/8/4k3/8/2pP4/8/B5K1/8 b - d3 0 1",
    # A double push next to two enemy pawns, so both captures have to be generated.
    "8/8/8/8/1pPp4/8/8/K5k1 b - c3 0 1",
    # Castling: rights with the rook already gone, castling out of / through / into check, and a
    # rook capture on its home square (which must clear that side's right).
    "5k2/8/8/8/8/8/8/4K2R w K - 0 1",
    "3k4/8/8/8/8/8/8/R3K3 w Q - 0 1",
    "r3k2r/1b4bq/8/8/8/8/7B/R3K2R w KQkq - 0 1",
    "r3k2r/8/3Q4/8/8/5q2/8/R3K2R b KQkq - 0 1",
    "r3k2r/p6p/8/8/8/8/P6P/R3K2R w KQkq - 0 1",
    "4k3/8/8/8/8/8/6r1/R3K2R w KQ - 0 1",
    "r3k2r/8/8/8/8/8/8/R2QK2R b KQkq - 0 1",
    # Promotions, including under-promotion with check and capture-promotion onto a rook that
    # carries a castling right.
    "2K2r2/4P3/8/8/8/8/8/3k4 w - - 0 1",
    "4k3/1P6/8/8/8/8/K7/8 w - - 0 1",
    "8/P1k5/K7/8/8/8/8/8 w - - 0 1",
    "8/k1P5/8/1K6/8/8/8/8 w - - 0 1",
    "r3k2r/1P5p/8/8/8/8/8/4K3 w kq - 0 1",
    # Pawns on the seventh for both sides at once.
    "8/PPPk4/8/8/8/8/4Kppp/8 w - - 0 1",
    # Check, double check and mate: king evasions and the fact that nothing but a king move
    # answers a double check.
    "8/8/2k5/5q2/5n2/8/5K2/8 b - - 0 1",
    "8/8/1P2K3/8/2n5/1q6/8/5k2 b - - 0 1",
    "rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3",
    "3k4/8/8/8/8/3n4/4r3/4K3 w - - 0 1",
    # Stalemate and checkmate, where the legal move set is empty.
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "7k/5q2/6K1/8/8/8/8/8 w - - 0 1",
    # Sparse endgames where a king can walk into a slider's shadow.
    "K1k5/8/P7/8/8/8/8/8 w - - 0 1",
    "8/8/8/8/8/K7/P7/k7 w - - 0 1",
    *_castling_combinations(),
]


def load_openings() -> list[str]:
    """The 219 curated opening positions, which is where rated games actually start."""
    fens = []
    for line in OPENINGS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        fens.append(line.split("\t")[-1])
    return fens


# ----------------------------------------------------------------------------- the oracle


def chess_perft(board: chess.Board, depth: int) -> int:
    """`python-chess`'s own recursive perft. The number this module produces is the gate."""
    if depth <= 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()
    total = 0
    for move in board.legal_moves:
        board.push(move)
        total += chess_perft(board, depth - 1)
        board.pop()
    return total


def fast_perft(pos: fb.Position, depth: int) -> int:
    stack = fb.new_move_stack(depth + 1)
    return int(fb.perft(pos, stack, depth, 0))


def uci_set(pos: fb.Position) -> set[str]:
    return {fb.move_to_uci(move) for move in fb.legal_moves(pos)}


# ----------------------------------------------------------------------------- sampling


def playout_boards(count: int, seed: int, starts: list[str]) -> Iterator[chess.Board]:
    """Positions from uniformly random playouts, terminal positions included.

    The same mutable `chess.Board` is yielded each time, so a consumer must use it before asking
    for the next one. That keeps a hundred thousand positions cheap.
    """
    rng = random.Random(seed)
    produced = 0
    while produced < count:
        board = chess.Board(rng.choice(starts))
        for _ in range(120):
            yield board
            produced += 1
            if produced >= count:
                return
            moves = list(board.legal_moves)
            if not moves or board.is_insufficient_material() or board.halfmove_clock >= 100:
                break
            board.push(rng.choice(moves))


def sample_starts() -> list[str]:
    """Playouts start from the standard position and from the curated openings, so the sample is
    a mix of book-shaped middlegames and whatever random play decays into."""
    return [STANDARD_START, *load_openings(), *TRICKY_POSITIONS]


def sample_boards(count: int, seed: int) -> Iterator[chess.Board]:
    """Every tricky position, then random playouts up to `count` positions in total.

    Leading with the tricky list is what makes the sample audit below pass by construction rather
    than by luck: a random playout is unlikely to visit all sixteen castling-rights combinations,
    and none of them would ever land on a hand-built double check.
    """
    for fen in TRICKY_POSITIONS:
        yield chess.Board(fen)
    remaining = count - len(TRICKY_POSITIONS)
    if remaining > 0:
        yield from playout_boards(remaining, seed, sample_starts())


# ----------------------------------------------------------------------------- gate 1: perft


# The module's own list, which `agent.py` reads too, so there is one place to keep up to date.
JITTED = list(fb.JITTED)


def test_warm_up_compiled_at_import() -> None:
    """Every jitted entry point is compiled before any test runs, as it will be on the platform."""
    assert fb.WARM_UP_SECONDS > 0.0
    assert fb.WARM_UP_SECONDS < 60.0, f"warm-up took {fb.WARM_UP_SECONDS:.1f}s"
    for name in JITTED:
        assert getattr(fb, name).signatures, f"{name} was not compiled by warm_up()"


def test_nothing_compiles_after_import() -> None:
    """No jitted function gains a signature under load.

    This is the gate that matters on the platform: compilation is free inside the 90-second
    import budget and ruinous on the clock, so `warm_up()` has to have already compiled every
    argument-type combination the engine will ever pass. numba silently compiles a *second*
    specialisation when a caller hands over an int32 where the warm-up passed an int64, which is
    exactly the kind of thing that shows up as a lost game rather than as an error.
    """
    before = {name: list(getattr(fb, name).signatures) for name in JITTED}
    pos = fb.new_position()
    stack = fb.new_move_stack(8)
    buffer = fb.new_move_buffer()
    for board in sample_boards(400, seed=27182818):
        fb.set_from_board(pos, board)
        fast_perft(pos, 2)
        fb.perft(pos, stack, 2, 0)
        fb.gen_pseudo(pos, buffer)
        fb.gen_legal(pos, buffer)
        fb.has_legal_move(pos, buffer)
        fb.in_check(pos)
        fb.attacked(pos.board, fb.E1, fb.BLACK)
        fb.hash_position(pos, fb.ZOBRIST)
        fb.to_fen(pos)
        for move in fb.legal_moves(pos)[:4]:
            fb.make_move(pos, move)
            fb.unmake_move(pos)
    after = {name: list(getattr(fb, name).signatures) for name in JITTED}
    assert after == before, {
        name: set(map(str, after[name])) - set(map(str, before[name]))
        for name in JITTED
        if after[name] != before[name]
    }


@pytest.mark.parametrize("fen", STANDARD_POSITIONS)
def test_perft_standard_positions(fen: str) -> None:
    """Depth 4 on the public test positions, against `python-chess`'s own count."""
    board = chess.Board(fen)
    pos = fb.from_board(board)
    for depth in range(1, 5):
        assert fast_perft(pos, depth) == chess_perft(board, depth), f"{fen} depth {depth}"


@pytest.mark.parametrize("fen", TRICKY_POSITIONS)
def test_perft_tricky_positions(fen: str) -> None:
    """Depth 4 on the rule-breaking positions listed above."""
    board = chess.Board(fen)
    assert board.is_valid(), fen
    pos = fb.from_board(board)
    for depth in range(1, 5):
        assert fast_perft(pos, depth) == chess_perft(board, depth), f"{fen} depth {depth}"


def test_perft_openings_depth_3() -> None:
    """Depth 3 on the curated openings, which is where rated games start."""
    fens = load_openings()
    assert len(fens) == 219
    if not FULL_GATES:
        fens = fens[::6]
    for fen in fens:
        board = chess.Board(fen)
        pos = fb.from_board(board)
        assert fast_perft(pos, 3) == chess_perft(board, 3), fen


def test_perft_random_playout_positions_depth_3() -> None:
    """Depth 3 on positions sampled from random playouts."""
    count = 2_000 if FULL_GATES else 200
    starts = sample_starts()
    pos = fb.new_position()
    compared = 0
    for board in playout_boards(count, seed=20260908, starts=starts):
        fb.set_from_board(pos, board)
        assert fast_perft(pos, 3) == chess_perft(board, 3), board.fen()
        compared += 1
    assert compared == count


# ------------------------------------------------------------------- gate 2: move-set equality


def test_move_sets_match_python_chess() -> None:
    """The set of legal moves, in UCI, is identical to `python-chess`'s on every sampled position.

    The sample is also audited: if it stopped containing en passant, castling, checks, double
    checks or pawns on the seventh, this gate would quietly stop testing what it is for.
    """
    count = 100_000 if FULL_GATES else 5_000
    pos = fb.new_position()
    seen = {
        "en_passant": 0,
        "castling_move": 0,
        "check": 0,
        "double_check": 0,
        "seventh_rank_pawn": 0,
        "terminal": 0,
        "promotion": 0,
    }
    rights_seen = set()
    compared = 0
    for board in sample_boards(count, seed=11235813):
        compared += 1
        fb.set_from_board(pos, board)
        mine = uci_set(pos)
        theirs = {move.uci() for move in board.legal_moves}
        assert mine == theirs, f"{board.fen()}: extra {mine - theirs}, missing {theirs - mine}"

        rights_seen.add(int(pos.meta[fb.M_CASTLE]))
        if board.has_legal_en_passant():
            seen["en_passant"] += 1
        if any(board.is_castling(move) for move in board.legal_moves):
            seen["castling_move"] += 1
        if board.is_check():
            seen["check"] += 1
            if len(board.checkers()) > 1:
                seen["double_check"] += 1
        if not theirs:
            seen["terminal"] += 1
        if any(move.promotion for move in board.legal_moves):
            seen["promotion"] += 1
        seventh = chess.BB_RANK_7 if board.turn == chess.WHITE else chess.BB_RANK_2
        if board.pieces_mask(chess.PAWN, board.turn) & seventh:
            seen["seventh_rank_pawn"] += 1

    assert compared == count
    for name, hits in seen.items():
        assert hits > 0, f"the sample contained no position with {name}"
    assert len(rights_seen) == 16, f"only {len(rights_seen)} castling-rights combinations sampled"


# -------------------------------------------------------------- gate 3: make/unmake round trip


def test_make_unmake_restores_the_position_exactly() -> None:
    """Making and unmaking any legal move leaves the FEN, both clocks included, byte-identical."""
    count = 20_000 if FULL_GATES else 1_500
    pos = fb.new_position()
    positions = 0
    moves_tried = 0
    for board in sample_boards(count, seed=31415926):
        fb.set_from_board(pos, board)
        before = fb.to_fen(pos)
        meta_before = pos.meta.copy()
        positions += 1
        for move in fb.legal_moves(pos):
            fb.make_move(pos, move)
            fb.unmake_move(pos)
            moves_tried += 1
            assert fb.to_fen(pos) == before, f"{before} broken by {fb.move_to_uci(move)}"
            assert np.array_equal(pos.meta, meta_before), fb.move_to_uci(move)
    assert positions == count
    assert moves_tried > 20 * count, f"only {moves_tried} moves round-tripped"


def test_make_unmake_keeps_the_piece_lists_consistent() -> None:
    """The piece list, the square->slot index and the board agree after every make and unmake.

    This is the invariant the mailbox representation buys its speed with, so it is checked
    exhaustively rather than sampled: a Python-level perft over the tricky positions, calling
    `check_invariants` at every node on the way down and on the way back up.
    """
    depth = 3 if FULL_GATES else 2
    for fen in [KIWIPETE, PROMOTIONS, *TRICKY_POSITIONS[:20]]:
        pos = fb.from_fen(fen)
        _walk_with_invariants(pos, depth)


def _walk_with_invariants(pos: fb.Position, depth: int) -> None:
    fb.check_invariants(pos)
    if depth == 0:
        return
    for move in fb.legal_moves(pos):
        fb.make_move(pos, move)
        fb.check_invariants(pos)
        _walk_with_invariants(pos, depth - 1)
        fb.unmake_move(pos)
        fb.check_invariants(pos)


def test_deep_make_unmake_stack() -> None:
    """A long line of makes unwinds exactly: the undo stack is not merely right one ply deep."""
    rng = random.Random(2718281)
    board = chess.Board()
    pos = fb.from_board(board)
    fens = []
    for _ in range(120):
        moves = fb.legal_moves(pos)
        if not moves:
            break
        fens.append(fb.to_fen(pos))
        fb.make_move(pos, rng.choice(moves))
    assert len(fens) > 40
    for expected in reversed(fens):
        fb.unmake_move(pos)
        assert fb.to_fen(pos) == expected
    assert int(pos.meta[fb.M_PLY]) == 0


# ----------------------------------------------------------------------------- conversions


@pytest.mark.parametrize("fen", [*STANDARD_POSITIONS, *TRICKY_POSITIONS])
def test_fen_round_trip(fen: str) -> None:
    """`to_fen` reproduces `chess.Board.fen()` exactly, en passant rule included."""
    board = chess.Board(fen)
    assert fb.to_fen(fb.from_board(board)) == board.fen()


def test_fen_round_trip_on_playouts() -> None:
    count = 20_000 if FULL_GATES else 2_000
    pos = fb.new_position()
    for board in sample_boards(count, seed=57721566):
        fb.set_from_board(pos, board)
        assert fb.to_fen(pos) == board.fen()


def test_square_conversions_are_inverse() -> None:
    for square in chess.SQUARES:
        assert fb.sq64(fb.sq88(square)) == square
        assert fb.sq88(square) & fb.OFF_BOARD_MASK == 0


def test_move_conversion_round_trip() -> None:
    """Every legal move survives the trip out to `chess.Move` and back, flags included."""
    pos = fb.new_position()
    for board in sample_boards(3_000, seed=16180339):
        fb.set_from_board(pos, board)
        for move in fb.legal_moves(pos):
            as_chess = fb.move_to_chess(move)
            assert as_chess.uci() == fb.move_to_uci(move)
            assert as_chess in board.legal_moves
            assert fb.move_from_chess(pos, as_chess) == move


def test_move_packing_is_reversible() -> None:
    for frm in (fb.A1, fb.E1, fb.H8, fb.sq88(chess.D5)):
        for to in (fb.A8, fb.G1, fb.sq88(chess.C7)):
            for promotion in (0, fb.QUEEN, fb.KNIGHT):
                for flag in (fb.FLAG_NORMAL, fb.FLAG_EN_PASSANT, fb.FLAG_CASTLE):
                    move = fb.pack_move(frm, to, promotion, flag)
                    assert fb.move_from(move) == frm
                    assert fb.move_to(move) == to
                    assert fb.move_promotion(move) == promotion
                    assert fb.move_flag(move) == flag


def test_rejects_impossible_material() -> None:
    """A `chess.Board` can hold more than sixteen pieces of a colour; the fixed piece lists cannot,
    so loading one has to fail rather than write past the end of the array."""
    board = chess.Board("rrrrkrrr/rrrrrrrr/rrrrrrrr/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1")
    with pytest.raises(ValueError, match="more than 16 pieces"):
        fb.from_board(board)


def test_pseudo_legal_moves_are_a_superset_of_legal_ones() -> None:
    """`gen_legal` filters `gen_pseudo`, so anything legal must have been generated first, and the
    only moves dropped must be the ones that leave the mover in check."""
    buffer = fb.new_move_buffer()
    pos = fb.new_position()
    for board in sample_boards(2_000, seed=14142135):
        fb.set_from_board(pos, board)
        pseudo_n = int(fb.gen_pseudo(pos, buffer))
        assert pseudo_n < fb.MAX_MOVES
        pseudo = {fb.move_to_uci(int(buffer[i])) for i in range(pseudo_n)}
        legal = {move.uci() for move in board.legal_moves}
        assert legal <= pseudo, f"{board.fen()} missing {legal - pseudo}"


def test_in_check_and_has_legal_move_agree_with_python_chess() -> None:
    buffer = fb.new_move_buffer()
    pos = fb.new_position()
    for board in sample_boards(5_000, seed=22360679):
        fb.set_from_board(pos, board)
        assert bool(fb.in_check(pos)) == board.is_check()
        assert bool(fb.has_legal_move(pos, buffer)) == bool(board.legal_moves.count())


# ----------------------------------------------------------------- gate 4: the overflow guards


def test_move_buffer_guard_fires_instead_of_writing_past_the_end() -> None:
    """A buffer too small for the position raises rather than corrupting whatever follows it.

    On the platform an out-of-bounds numpy write is silent and its consequences arbitrary, so the
    guard has to be a real runtime comparison. Passing a deliberately short buffer is the only
    way to reach it, since no legal position produces 256 pseudo-legal moves.
    """
    pos = fb.from_board(chess.Board())
    for size in (1, 8, 19, 40):
        short = np.zeros(size, dtype=np.int32)
        with pytest.raises(IndexError, match="move buffer too small"):
            fb.gen_pseudo(pos, short)
        assert not short[size - 1], "a move was written despite the guard"


def test_move_buffer_guard_leaves_a_big_enough_buffer_alone() -> None:
    """The guard must not fire on a real position, however wide: `MAX_MOVES` has to cover the
    worst case plus the per-piece reserve the guard demands."""
    widest = "3Q4/1Q4Q1/4Q3/2Q4R/Q4Q2/3Q4/1Q4Rp/1K1BBNNk w - - 0 1"  # 218 legal moves
    pos = fb.from_board(chess.Board(widest))
    buffer = fb.new_move_buffer()
    assert fb.gen_pseudo(pos, buffer) >= 218
    assert fb.gen_legal(pos, buffer) == 218


def test_move_buffer_guard_reserves_room_for_the_widest_piece() -> None:
    """`MOVES_PER_PIECE_MAX` must really bound one piece's contribution, or the guard leaves too
    little room. A queen alone on an empty board is the worst case."""
    pos = fb.from_board(chess.Board("8/8/8/3Q4/8/8/8/K6k w - - 0 1"))
    buffer = fb.new_move_buffer()
    queen_moves = sum(
        1
        for i in range(int(fb.gen_pseudo(pos, buffer)))
        if fb.move_from(int(buffer[i])) == fb.sq88(chess.D5)
    )
    assert queen_moves == 27
    assert queen_moves <= fb.MOVES_PER_PIECE_MAX


def test_undo_stack_guard_fires_at_max_undo() -> None:
    """`make_move` refuses the ply after the last undo slot rather than writing past the array."""
    pos = fb.from_board(chess.Board("8/8/8/8/8/8/8/K6k w - - 0 1"))
    shuffle = [
        fb.pack_move(fb.A1, fb.B1),
        fb.pack_move(fb.H1, fb.G1),
        fb.pack_move(fb.B1, fb.A1),
        fb.pack_move(fb.G1, fb.H1),
    ]
    with pytest.raises(IndexError, match="undo stack full"):
        for i in range(fb.MAX_UNDO + 8):
            fb.make_move(pos, shuffle[i % 4])
    assert int(pos.meta[fb.M_PLY]) == fb.MAX_UNDO


# ------------------------------------------------------- gate 4: the running position key


def _key_matches(pos: fb.Position) -> bool:
    """Is the key `make_move` has been maintaining the key the position actually has?"""
    return fb.running_key(pos) == int(fb.hash_position(pos, fb.ZOBRIST))


def _walk_keys(pos: fb.Position, rng: random.Random, plies: int, seen: dict[str, int]) -> int:
    """Walk one random line, checking the key after every make and every unmake on the way.

    At each ply every *pseudo-legal* move is made and unmade, not just the legal ones: a move
    that leaves its own king in check goes through exactly the same make/unmake, so it has to
    restore the key too. The line itself is then extended by one legal move without unmaking it,
    so the deeper plies are checked with a loaded undo stack; the walk unwinds at the end and the
    key must come back to what it was at the root.
    """
    buffer = fb.new_move_buffer()
    compared = 0
    played = 0
    root_key = fb.running_key(pos)
    for _ in range(plies):
        legal = []
        count = int(fb.gen_pseudo(pos, buffer))
        for i in range(count):
            move = int(buffer[i])
            ok = int(fb.make_move(pos, move))
            assert _key_matches(pos), f"after make {fb.move_to_uci(move)} in {fb.to_fen(pos)}"
            promotion = fb.move_promotion(move)
            if promotion:
                seen["promotion"] += 1
                if int(pos.undo[int(pos.meta[fb.M_PLY]) - 1, fb.U_CAPTURED]) != fb.EMPTY:
                    seen["capture_promotion"] += 1
            if fb.move_flag(move) == fb.FLAG_EN_PASSANT:
                seen["en_passant_capture"] += 1
            if fb.move_flag(move) == fb.FLAG_CASTLE:
                seen["castling"] += 1
            fb.unmake_move(pos)
            assert _key_matches(pos), f"after unmake {fb.move_to_uci(move)} in {fb.to_fen(pos)}"
            compared += 2
            if ok:
                legal.append(move)
        if not legal:
            break
        seen["rights"] |= 1 << int(pos.meta[fb.M_CASTLE])
        if int(pos.meta[fb.M_EP]) != fb.NO_SQ:
            seen["en_passant_square"] += 1
        fb.make_move(pos, rng.choice(legal))
        played += 1
    for _ in range(played):
        fb.unmake_move(pos)
        assert _key_matches(pos)
        compared += 1
    assert fb.running_key(pos) == root_key
    return compared


def test_running_key_matches_a_key_built_from_scratch() -> None:
    """The gate the incremental key rests on.

    `make_move` carries the key forward by XORing the handful of terms the move changes,
    and the search reads it instead of walking both piece lists at every node. That is only sound
    if it is *exactly* what `hash_position` would have produced, so this walks lines from the
    curated openings and from the hand-built awkward positions, forty plies each, and compares
    the two after every single make and unmake. The sample is audited afterwards, because a walk
    that stopped producing en passant captures or capture-promotions would still pass while
    testing nothing that could break. The starts are the curated openings, the hand-built
    awkward positions above, and positions sampled from random playouts of both.
    """
    openings = load_openings()
    playouts = [
        board.fen()
        for board in playout_boards(
            120 if FULL_GATES else 40, seed=27182818, starts=sample_starts()
        )
    ]
    starts = [*TRICKY_POSITIONS, *(openings if FULL_GATES else openings[::4]), *playouts]
    rng = random.Random(16180339)
    pos = fb.new_position()
    seen = {
        "promotion": 0,
        "capture_promotion": 0,
        "en_passant_capture": 0,
        "en_passant_square": 0,
        "castling": 0,
        "rights": 0,
    }
    compared = 0
    for fen in starts:
        fb.set_from_board(pos, chess.Board(fen))
        assert _key_matches(pos), fen  # set_from_board seeds it
        compared += _walk_keys(pos, rng, 40, seen)
    assert len(starts) >= (200 if FULL_GATES else 100)
    assert compared > (500_000 if FULL_GATES else 100_000), compared
    for name in ("promotion", "capture_promotion", "en_passant_capture", "castling"):
        assert seen[name] > 0, f"the walk contained no {name}"
    assert seen["en_passant_square"] > 0
    assert bin(seen["rights"]).count("1") == 16, "not every castling-rights combination was walked"


def test_the_key_ignores_an_en_passant_square_nobody_can_take() -> None:
    """The en passant term is in the key only when a capture onto the square is available, so
    `make_move` has to apply that test to the position the double push *produces*.

    Two identical double pushes, a2a4, one with a black pawn on b4 that can answer it and one
    with the pawn on h4 that cannot. The first must key differently from the same board with no
    en passant square; the second must key the same, because for the repetition rule and the
    table they really are the same position.
    """
    push = fb.pack_move(fb.A1 + 0x10, fb.A1 + 0x30, flag=fb.FLAG_DOUBLE_PUSH)

    answerable = fb.from_fen("8/8/8/8/1p6/8/P7/K6k w - - 0 1")
    fb.make_move(answerable, push)
    assert _key_matches(answerable)
    key = fb.running_key(answerable)
    assert key == fb.running_key(fb.from_fen("8/8/8/8/Pp6/8/8/K6k b - a3 0 1"))
    assert key != fb.running_key(fb.from_fen("8/8/8/8/Pp6/8/8/K6k b - - 0 1"))

    quiet = fb.from_fen("8/8/8/8/7p/8/P7/K6k w - - 0 1")
    fb.make_move(quiet, push)
    assert _key_matches(quiet)
    assert fb.running_key(quiet) == int(
        fb.running_key(fb.from_fen("8/8/8/8/P6p/8/8/K6k b - - 0 1"))
    )
