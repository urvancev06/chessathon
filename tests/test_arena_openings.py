"""Tests for tools/arena_openings.py.

Four things matter for a measuring instrument: it prints the same numbers as the harness for the
same results, its schedule is deterministic and colour-balanced, it reads the referee's clocks
correctly, and a real (tiny) run through the harness produces a well-formed record. The real run
uses two baselines that answer in microseconds, so it is quick.
"""

import io
import json
import time
from pathlib import Path

import chess
import chess.pgn
import pytest

from harness import arena as harness_arena
from harness.referee import FAILED_TERMINATIONS
from harness.rules import OPENINGS
from tools import arena_openings as tool

ROOT = Path(__file__).resolve().parent.parent
GREEDY = ROOT / "baselines" / "greedy"
RANDOM = ROOT / "baselines" / "random"


@pytest.mark.parametrize(
    ("wins", "draws", "losses"),
    [
        (1, 0, 0),  # one game: no margin
        (1, 1, 0),  # two games
        (2, 0, 0),  # zero spread: "every game had the same result"
        (0, 4, 0),  # all draws: zero spread at 50%
        (0, 0, 3),  # score 0
        (5, 3, 2),  # ordinary case with an Elo interval
        (10, 10, 10),
        (31, 0, 1),  # interval touches 100%: no Elo line
        (20, 8, 4),
    ],
)
def test_statistics_print_what_the_harness_prints(
    wins: int, draws: int, losses: int, capsys: pytest.CaptureFixture[str]
) -> None:
    # The tool re-implements the harness formulas so it needs no private import; this test is the
    # proof that the two agree, character for character, by calling the harness's own printer.
    harness_arena._report(wins, draws, losses)
    expected = capsys.readouterr().out.splitlines()
    assert tool.format_statistics(tool.statistics(wins, draws, losses)) == expected


def test_statistics_fields() -> None:
    stats = tool.statistics(5, 3, 2)
    assert stats.played == 10
    assert stats.score == pytest.approx(0.65)
    assert stats.draw_rate == pytest.approx(0.3)
    assert stats.margin is not None and 0.0 < stats.margin < 0.5
    assert stats.elo is not None and stats.elo == pytest.approx(tool.elo_from_score(0.65))
    assert stats.elo_low is not None and stats.elo_high is not None
    assert stats.elo_low < stats.elo < stats.elo_high


def test_schedule_pairs_each_opening_with_both_colours() -> None:
    openings = [tool.Opening(f"o{i}", chess.STARTING_FEN) for i in range(3)]
    plain = [tool.schedule(index, 0, openings) for index in range(6)]
    assert [seed for seed, _, _ in plain] == list(range(6))
    assert [opening.name for _, opening, _ in plain] == ["o0", "o0", "o1", "o1", "o2", "o2"]
    assert [white for _, _, white in plain] == [True, False] * 3
    # An offset shifts the schedule by whole opening pairs and wraps round the list.
    shifted = [tool.schedule(index, 4, openings) for index in range(4)]
    assert [seed for seed, _, _ in shifted] == [4, 5, 6, 7]
    assert [opening.name for _, opening, _ in shifted] == ["o2", "o2", "o0", "o0"]


def test_openings_file_is_parsed_deduplicated_and_shuffled_deterministically(
    tmp_path: Path,
) -> None:
    path = tmp_path / "openings.txt"
    lines = ["# name<TAB>fen", ""]
    for name, fen in OPENINGS:
        lines.append(f"{name}\t{fen}")
    lines.append(f"duplicate\t{OPENINGS[0][1]}")  # same FEN again: dropped
    path.write_text("\n".join(lines) + "\n")

    first, source = tool.load_openings(str(path))
    second, _ = tool.load_openings(str(path))
    assert source == str(path)
    assert first == second, "the shuffle must be the same on every load"
    assert len(first) == len(OPENINGS)
    assert {opening.fen for opening in first} == {fen for _, fen in OPENINGS}
    assert [opening.fen for opening in first] != [fen for _, fen in OPENINGS], "order is shuffled"


def test_openings_file_rejects_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "openings.txt"
    path.write_text("Fine\t" + OPENINGS[0][1] + "\nBroken\tnot a fen at all\n")
    with pytest.raises(ValueError, match=r"openings.txt:2"):
        tool.read_openings_file(path)
    path.write_text("no tab on this line\n")
    with pytest.raises(ValueError, match="name<TAB>fen"):
        tool.read_openings_file(path)


def test_missing_openings_file_falls_back_to_harness_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    openings, source = tool.load_openings(str(tmp_path / "absent.txt"))
    assert "harness.rules.OPENINGS" in source and "missing" in source
    assert {opening.fen for opening in openings} == {fen for _, fen in OPENINGS}
    assert "not found" in capsys.readouterr().out
    explicit, source = tool.load_openings("harness")
    assert source == "harness.rules.OPENINGS"
    assert explicit == openings


def test_agent_clocks_are_read_per_colour_and_before_the_increment() -> None:
    game = chess.pgn.Game.from_board(chess.Board(OPENINGS[2][1]))  # White to move
    node: chess.pgn.GameNode = game
    for uci, seconds in [("f3e5", 9.9), ("e4c5", 9.5), ("e5c6", 9.7), ("b7c6", 9.4)]:
        node = node.add_variation(chess.Move.from_uci(uci))
        node.set_clock(seconds)
    pgn = str(game)

    plies, white = tool.agent_clocks_ms(pgn, plays_white=True, increment_ms=100)
    assert plies == 4
    assert white == pytest.approx([9800.0, 9600.0])
    _, black = tool.agent_clocks_ms(pgn, plays_white=False, increment_ms=100)
    assert black == pytest.approx([9400.0, 9300.0])
    assert tool.agent_clocks_ms("", plays_white=True, increment_ms=0) == (0, [])


def test_parse_args_defaults_and_validation() -> None:
    settings = tool.parse_args([])
    assert settings.games == tool.DEFAULT_GAMES and settings.games % 2 == 0
    assert (settings.base_ms, settings.increment_ms) == (10_000, 100)
    assert settings.workers == 1 and settings.seed_offset == 0
    assert settings.openings == str(tool.DEFAULT_OPENINGS)
    real = tool.parse_args(["--real-clock"])
    assert (real.base_ms, real.increment_ms) == (120_000, 500)
    with pytest.raises(SystemExit):
        tool.parse_args(["--seed-offset", "3"])  # odd offsets split the colour pairs
    with pytest.raises(SystemExit):
        tool.parse_args(["--workers", "0"])


def test_results_row_escapes_pipes_and_handles_a_run_with_no_scored_games() -> None:
    record = tool.RunRecord(
        label="a|b",
        agent=".",
        opponent="x",
        base_ms=10_000,
        increment_ms=100,
        ply_cap=600,
        games=2,
        workers=1,
        seed_offset=0,
        openings_source="harness.rules.OPENINGS",
        openings_count=8,
        started_at="",
        finished_at="",
        load_start=None,
        load_end=None,
        results=[],
        terminations={"both_failed": 2},
        failed={"both_failed": 2},
        statistics=None,
        low_clock_ms=None,
        low_clock_game=None,
    )
    row = tool.results_row(record)
    assert row.startswith(
        "| a\\|b | . | x | 10+0.1 s | 2 | - | - | - | - | - | both_failed 2 | 1 |"
    )
    assert row.count("|") == len(tool.RESULTS_COLUMNS) + 1 + 1  # cells + edges + escaped pipe


def test_two_games_greedy_vs_random_end_to_end(tmp_path: Path) -> None:
    settings = tool.parse_args(
        [
            "--agent",
            str(GREEDY),
            "--opponent",
            str(RANDOM),
            "--games",
            "2",
            "--base-ms",
            "2000",
            "--increment-ms",
            "50",
            "--ply-cap",
            "40",
            "--openings",
            "harness",
            "--workers",
            "2",
            "--label",
            "unit test",
            "--pgn-dir",
            str(tmp_path / "pgn"),
            "--results",
            str(tmp_path / "results.md"),
            "--json",
            str(tmp_path / "run.json"),
        ]
    )
    started = time.perf_counter()
    record = tool.run(settings)
    assert time.perf_counter() - started < 40.0

    assert record.games == 2 and len(record.results) == 2
    assert [game.index for game in record.results] == [0, 1]
    assert [game.colour for game in record.results] == ["white", "black"]
    assert record.results[0].opening == record.results[1].opening
    for game in record.results:
        assert game.termination not in FAILED_TERMINATIONS
        assert game.result in {"white", "black", "draw"}
        assert 0 < game.plies <= 40
        assert chess.Board(game.fen).is_valid()
        assert game.agent_low_clock_ms is not None and game.agent_low_clock_ms <= 2000.0
    assert not record.failed
    assert sum(record.terminations.values()) == 2
    assert record.statistics is not None and record.statistics.played == 2
    assert record.openings_count == len(OPENINGS)
    assert record.openings_source == "harness.rules.OPENINGS"
    assert record.low_clock_ms is not None and record.low_clock_game in (1, 2)
    assert record.started_at and record.finished_at

    pgns = sorted(path.name for path in (tmp_path / "pgn").iterdir())
    assert pgns == ["game-0001.pgn", "game-0002.pgn"]
    for name in pgns:
        parsed = chess.pgn.read_game(io.StringIO((tmp_path / "pgn" / name).read_text()))
        assert parsed is not None and parsed.headers["Termination"] not in FAILED_TERMINATIONS

    table = (tmp_path / "results.md").read_text().splitlines()
    assert len(table) == 3  # header, separator, one row
    assert table[2].startswith("| unit test |")

    payload = json.loads((tmp_path / "run.json").read_text())
    assert payload["games"] == 2 and len(payload["results"]) == 2
    assert set(payload) >= {"statistics", "terminations", "failed", "low_clock_ms", "load_start"}


def test_main_exits_non_zero_when_a_game_did_not_finish_cleanly(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "agent.py").write_text("raise RuntimeError('boom at import')\n")
    with pytest.raises(SystemExit) as failure:
        tool.main(
            [
                "--agent",
                str(broken),
                "--opponent",
                str(RANDOM),
                "--games",
                "2",
                "--base-ms",
                "2000",
                "--ply-cap",
                "10",
                "--openings",
                "harness",
            ]
        )
    assert "crash" in str(failure.value) or "init" in str(failure.value)
