SHELL := /bin/bash

.PHONY: setup play arena zip gate

setup:
	uv sync

play:
	uv run python -m harness.play --white . --black baselines/greedy $(if $(FEN),--fen "$(FEN)")

arena:
	uv run python -m harness.arena --opponent baselines/greedy

zip:
	uv run python -m harness.package

gate:
	uv run ruff check .
	uv run mypy
	uv run python -m harness.arena --opponent baselines/random --games 2 --base-ms 5000

.PHONY: report test fuzz
report:
	@if command -v tectonic >/dev/null 2>&1; then tectonic docs/report.tex; \
	elif command -v latexmk >/dev/null 2>&1; then latexmk -pdf -outdir=docs docs/report.tex; \
	else echo "no TeX found: compile docs/report.tex with Tectonic (tectonic docs/report.tex) or upload it to Overleaf"; fi

test:
	uv run python -m pytest -q

fuzz:
	uv run python tools/arena_openings.py --opponent baselines/random --games 300 --base-ms 3000 --increment-ms 50 --workers 12 --label fuzz-random --results docs/RESULTS.md
	uv run python tools/arena_openings.py --opponent baselines/greedy --games 200 --base-ms 10000 --increment-ms 100 --workers 12 --label fuzz-greedy --results docs/RESULTS.md
