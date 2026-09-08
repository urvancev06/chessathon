"""The tool that decides the promotion, tested on the inputs that would make it lie.

Written to the standard the evening produced (``docs/DECISIONS.md``, "the check existed and did not
check"): every test here names the input that makes the thing fail, and was confirmed to go red
against the code before the fix. Two of them exist because ``chessathon-64`` asked that question of
the tool and found answers its author had not.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.promotion_verdict import load_games, main, tally


def game(index: int, seed: int, result: str, colour: str = "white", **kw: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "index": index,
        "seed": seed,
        "opening": "x",
        "fen": "y",
        "colour": colour,
        "result": result,
        "termination": kw.get("termination", "checkmate"),
        "plies": 60,
        "agent_low_clock_ms": kw.get("clock", 30_000.0),
        "elapsed_s": 1.0,
    }
    return record


def write_chunk(path: Path, games: list[dict[str, Any]]) -> Path:
    path.write_text(json.dumps({"results": games}))
    return path


def run(capsys: Any, *paths: Path) -> str:
    main([str(p) for p in paths])
    captured: str = capsys.readouterr().out
    return captured


def test_void_games_are_excluded_from_the_sample_size(tmp_path: Path, capsys: Any) -> None:
    """The failing input: a `both_failed` game, which `harness.referee` records as `void`.

    Voids are excluded from the score by `arena_openings`, so counting them in `n` would let three
    chunks with two voids reach n == 300 on 298 scored games -- and the interim test is `n < 300`,
    so a match short of the pre-registered sample would be treated as the full look and the
    reject-only rule of amendment 4 would stop applying.
    """
    games = [game(i, i, "white" if i % 2 == 0 else "black") for i in range(298)]
    games += [game(298, 298, "void", termination="both_failed") for _ in range(1)]
    games += [game(299, 299, "void", termination="both_failed")]
    out = run(capsys, write_chunk(tmp_path / "c.json", games))

    assert "298 scored games" in out, out
    assert "2 void excluded" in out, out
    # 298 < 300, so this must still be an interim look and must refuse to promote.
    assert "INTERIM LOOK" in out, out
    assert "REJECT-ONLY" in out, out


def test_the_worst_clock_is_reported_by_a_pool_unique_identifier(
    tmp_path: Path, capsys: Any
) -> None:
    """The failing input: the minimum occurring in the second or third chunk.

    `index` is 0-based within a run and the chunks are separate runs, so there are three game 5s in
    a pooled 300. Reporting `index` points at whichever chunk was loaded first, which may not be the
    one holding the minimum -- and this line exists so a judge can go and look at that game.
    """
    a = [game(i, i, "white", clock=30_000.0) for i in range(100)]
    b = [game(i, i + 100, "white", clock=30_000.0) for i in range(100)]
    b[5]["agent_low_clock_ms"] = 1_234.0  # the minimum, in chunk B, at index 5
    c = [game(i, i + 200, "white", clock=30_000.0) for i in range(100)]

    out = run(
        capsys,
        write_chunk(tmp_path / "a.json", a),
        write_chunk(tmp_path / "b.json", b),
        write_chunk(tmp_path / "c.json", c),
    )
    # seed 105 identifies it across the pool; "game 6" (index 5 + 1) would be ambiguous between
    # three different games and would name the wrong one.
    assert "seed 105" in out, out


def test_a_partial_match_cannot_promote(tmp_path: Path, capsys: Any) -> None:
    """The failing input: fewer than 300 games with a favourable score (amendment 4)."""
    games = [game(i, i, "white" if i < 70 else "black") for i in range(100)]
    out = run(capsys, write_chunk(tmp_path / "c.json", games))
    assert "INTERIM LOOK" in out
    assert "PROMOTE" not in out.split("INTERIM LOOK")[1]


def test_a_flag_blocks_promotion_whatever_the_elo(tmp_path: Path, capsys: Any) -> None:
    """The failing input: one game lost on time in an otherwise winning match (hole 5)."""
    games = [game(i, i, "white", colour="white") for i in range(300)]  # a 100% score
    games[7]["termination"] = "flag"
    out = run(capsys, write_chunk(tmp_path / "c.json", games))
    assert "NO PROMOTION" in out, out
    assert out.count("NO PROMOTION") == 2, "both gates must block on a flag"


def test_the_two_gates_disagree_is_announced(tmp_path: Path, capsys: Any) -> None:
    """One game below 5 000 ms in 300: the minimum gate fails, the 2 % rate gate passes."""
    games = [game(i, i, "white" if i % 2 == 0 else "black") for i in range(300)]
    games[11]["agent_low_clock_ms"] = 3_729.0
    out = run(capsys, write_chunk(tmp_path / "c.json", games))
    assert "DISAGREE" in out, out


def test_tally_ignores_voids_and_counts_from_the_agents_colour() -> None:
    games = [
        game(0, 0, "white", colour="white"),  # win
        game(1, 1, "white", colour="black"),  # loss
        game(2, 2, "draw", colour="white"),  # draw
        game(3, 3, "void", colour="white"),  # neither
    ]
    assert tally(games) == (1, 1, 1)


def test_load_games_concatenates_chunks(tmp_path: Path) -> None:
    a = write_chunk(tmp_path / "a.json", [game(0, 0, "white")])
    b = write_chunk(tmp_path / "b.json", [game(0, 100, "white")])
    assert len(load_games([a, b])) == 2
