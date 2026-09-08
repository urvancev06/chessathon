SHELL := /bin/bash

.PHONY: help setup check test gate play arena fuzz zip web report

help:            ## show this help
	@grep -hE '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/' | expand -t16

setup:           ## install the pinned dependencies
	uv sync

check:           ## lint and type-check, no games
	uv run ruff format --check .
	uv run ruff check .
	uv run mypy

test:            ## the test suite
	uv run python -m pytest -q

gate:            ## check, then two games that must finish cleanly
	$(MAKE) check
	uv run python -m harness.arena --opponent baselines/random --games 2 --base-ms 5000

play:            ## one game at the real time control; pass FEN=... to choose the position
	uv run python -m harness.play --white . --black baselines/minimax $(if $(FEN),--fen "$(FEN)")

arena:           ## a measured match against the previous version
	uv run python -m tools.arena_openings --opponent versions/v0.2 --games 100 --workers 4

fuzz:            ## many fast games that must not crash, flag or play an illegal move
	uv run python -m tools.arena_openings --opponent baselines/random --games 300 --base-ms 3000 --increment-ms 50 --workers 12 --label fuzz-random --results docs/RESULTS.md
	uv run python -m tools.arena_openings --opponent baselines/greedy --games 200 --base-ms 10000 --increment-ms 100 --workers 12 --label fuzz-greedy --results docs/RESULTS.md

zip:             ## build submission.zip and smoke it the way the platform does
	uv run python -m harness.package

web:             ## the local web app at http://localhost:8000
	uv run python -m tools.webapp.server

report:          ## compile docs/report.tex
	@if command -v tectonic >/dev/null 2>&1; then tectonic docs/report.tex; \
	elif command -v latexmk >/dev/null 2>&1; then latexmk -pdf -outdir=docs docs/report.tex; \
	else echo "no TeX found: compile docs/report.tex with Tectonic (tectonic docs/report.tex) or upload it to Overleaf"; fi
