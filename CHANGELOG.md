# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `error_kind: Literal["transient", "fatal"]` and `is_retryable` property on `EnrichedResult` — CLI `enrich` output and the MCP `search_hotels_with_details` tool now carry both fields per item so retry-aware callers can distinguish recoverable failures.
- New module `stays.serialize` — canonical serializers (public, consumed by both CLI and MCP) for `HotelResult`, `HotelDetail`, `RoomType`, `RatePlan`, and `CancellationPolicy`. Dict shapes guarded by golden-fixture tests.
- `SetupBackend` Protocol + `SetupReport` dataclass + `BACKENDS` registry under `stays.mcp.setup` (new `_backend` module); legacy `register(...)` / `build()` entrypoints in `stays.mcp.setup.{claude,codex,chatgpt}` remain unchanged.
- New test suites: golden-fixture parse/serialize/CLI-envelope regression guards (`tests/test_parse_golden.py`, `tests/test_serialize_golden.py`, `tests/test_cli_envelope_golden.py`), subprocess CLI live E2E tests (`tests/test_cli_live.py`), and a CLI-vs-browser oracle suite (`tests/browser_verification/test_cli_vs_browser.py`). Total offline suite grew from 286 to 330 tests.
- Browser-verify driver is now pluggable — `agent-browser` default, Playwright fallback (set `STAYS_BROWSER_DRIVER=playwright` to force).
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

- Internal refactor — SOLID/DRY code-quality pass; zero observable regressions.
- `SearchHotels.search_with_details` no longer swallows unexpected exceptions; only typed `BatchExecuteError` / `TransientBatchExecuteError` / `MissingHotelIdError` become per-item errors. Parser/programming bugs now propagate instead of being silently converted to per-hotel `error` strings.
- Corrected MCP prompt drift — `when-to-deep-search` prompt and the `search_hotels_with_details` tool description now reflect the real hard cap of 15 `max_hotels_with_details` (was incorrectly documented as 10).
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
