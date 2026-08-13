# Canhoto — common uv-backed recipes
# Install Just: https://github.com/casey/just
# List recipes: `just` or `just --list`

set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

# Default: show recipes
default:
    @just --list

# Install deps (incl. dev tools)
sync:
    uv sync --extra dev

# Show CLI help
help:
    uv run canhoto --help

# Create ~/.canhoto (or $CANHOTO_DATA_DIR) layout + config
init:
    uv run canhoto init

# Health report for the active data dir
doctor:
    uv run canhoto doctor

# Run CLI with arbitrary args — e.g. `just canhoto ingest ./stmt.pdf`
canhoto *args:
    uv run canhoto {{args}}

# MCP stdio server (host-spawned; blocks)
mcp:
    uv run canhoto-mcp

# Tests (use python -m: bare pytest shebang can break after renames)
test *args:
    uv run python -m pytest -q {{args}}

# Lint
lint:
    uv run ruff check src/canhoto tests

# Typecheck
typecheck:
    uv run mypy -p canhoto

# lint + typecheck + tests
check: lint typecheck test
