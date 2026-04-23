# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `stays` CLI (sole console script) with subcommands `search`, `details`, `enrich`, `mcp`, `mcp-http`.
- `stays setup` group with per-client backends: `claude` (Code + Desktop auto-detect with JSON fallback), `codex` (wraps `codex mcp add` with TOML fallback), `chatgpt` (prints remote-HTTPS + Developer Mode instructions).
- Smart-default routing: `stays "tokyo"` → `stays search "tokyo"`.
- Three output formats: `--format text` (rich tables, default), `--format json` (envelope), `--format jsonl` (line-oriented).
- `typer>=0.15` and `rich>=13,<15` in core deps.
- `fastmcp>=3.2,<5`, `fastapi>=0.115.6`, `pydantic-settings>=2.0`, and `uvicorn>=0.34.0` promoted from the old `[mcp]` optional extra into core dependencies, so `pipx install stays` / `pip install stays` / `uv tool install stays` give a fully-functional CLI + MCP server out of the box with no `--with 'stays[mcp]'` needed.
- ~98 new offline tests + one `@pytest.mark.live` end-to-end smoke.
- Dockerfile + docker-compose.yml with `prod` / `dev` profiles.
- GitHub Actions: lint, test matrix (Python 3.10–3.13), Docker GHCR, PyPI publish via OIDC.
- `Makefile` for common uv-driven tasks.
- PEP 561 `py.typed` marker.
- `LICENSE` (MIT), `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/AI_AGENTS.md`, dense `CLAUDE.md`, `AGENTS.md`.

### Changed

- `pyproject.toml` upgraded to PyPI-ready metadata (classifiers, URLs, keywords, `license-files`).
- Ruff lint + format configured at 120-char line length.
- Reverse-engineering slot maps moved to `docs/reverse-engineering/`.

### Removed

- Scratch RE scripts at repo root (`test.py`, `google_hotels.py`, `header_strip.py`, `payload_strip.py`, `scope_check.py`, `slot_probe.py`, `final_verify.py`, `final_shrink.py`, `baseline.sh`, legacy `install.py`).
- `[mcp]` and `[all]` optional-dependency extras — their packages are now part of core. A bare `pipx install stays` (or equivalent) is sufficient. Existing `pip install 'stays[mcp]'` invocations will print a "WARNING: stays does not provide the extra 'mcp'" from pip but will otherwise succeed (the packages are already in core), so no user action is required.

## [0.1.0] - 2026-04-22

### Added

- Hotel search (`search_hotels`) with 16 filter slots.
- Hotel detail (`get_hotel_details`) via same `AtySUc` RPC.
- Parallel enrichment (`search_hotels_with_details`).
- FastMCP stdio server.
- Rate-limited `curl_cffi` client with tenacity retries.
- 153 offline tests + 15 live MCP tests + opt-in browser verification suite.

[Unreleased]: https://github.com/victoriawei/stays/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/victoriawei/stays/releases/tag/v0.1.0
