# AGENTS.md

## General instructions

`stays` is a Python library + CLI + MCP server providing programmatic access to Google Hotels via reverse-engineered API. It offers a single `stays` console script exposing subcommands for search/details/enrich and MCP stdio/HTTP servers, plus a Python API. No external services (databases, caches, etc.) are required.

For deeper reference, see `CLAUDE.md`. That file is the source of truth for architecture, commands, and tool surface.

## Development commands

All standard commands live in the `Makefile`. Key ones:

- **Install deps:** `uv sync --extra dev`  (MCP is core; `--extra dev` adds ruff + pytest)
- **Lint:** `make lint` (ruff)
- **Format:** `make format`
- **Tests (offline):** `make test`
- **Tests (live, network):** `make test-live`
- **MCP stdio server:** `uv run stays mcp`
- **MCP HTTP server:** `uv run stays mcp-http` (serves at `http://127.0.0.1:8000/mcp/`)
- **Register with Claude:** `uv run stays setup claude`
- **Register with Codex:** `uv run stays setup codex`
- **ChatGPT setup instructions:** `uv run stays setup chatgpt`
- **CLI search:** `uv run stays search "tokyo hotels" --check-in 2026-07-22 --check-out 2026-07-26`
- **CLI detail:** `uv run stays details <entity_key> --check-in ... --check-out ...`
- **Build wheel/sdist:** `make build`

## Testing caveats

- Tests under `tests/test_*_live.py` and `tests/test_mcp_live.py` hit the live Google Hotels API and are rate-limited (HTTP 429). These often fail in sandboxed/CI environments. All offline tests pass reliably.
- Run `make test` (default) to skip live tests, or `uv run pytest -vv -m "not live"` equivalently.
- Browser-verification tests under `tests/browser_verification/` require Playwright and are gated behind `--browser-verify`; they're opt-in only.

## MCP server notes

- The streamable HTTP endpoint requires `Accept: application/json, text/event-stream` header. A bare `GET /mcp/` returns 405/406.
- Registration: `stays setup claude` auto-detects Claude Code vs Claude Desktop and handles registration; `stays setup codex` wraps `codex mcp add` (TOML fallback); `stays setup chatgpt` prints remote-HTTPS instructions. For any other client, run `stays setup claude --print-json` and paste the output.
- The server spawns a `curl_cffi` session at startup — expect ~500 ms cold-start overhead.
