# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-23

Initial public release.

### Added

- Hotel search (`search_hotels`) with 16 filter slots: city / brand / stars / price range / amenities / dates / guests / cancellation / eco / special offers / sort.
- Hotel detail (`get_hotel_details`) via the same `AtySUc` RPC — rooms, per-OTA rate plans (Booking, Expedia, Hotels.com, Trip.com, direct), cancellation policies, deep-link URLs.
- Parallel enrichment (`search_hotels_with_details`) — search + fan-out detail fetch for the top N hotels (hard cap 15) in a single call, with per-hotel partial failure.
- `error_kind: Literal["transient", "fatal"]` and `is_retryable` property on `EnrichedResult` — CLI `enrich` output and the MCP `search_hotels_with_details` tool carry both fields per item so retry-aware callers can distinguish recoverable failures.
- Rate-limited `curl_cffi` client with Chrome TLS impersonation and tenacity retries.
- FastMCP server over stdio and streamable HTTP.
- `stays.serialize` — canonical serializers (public, consumed by both CLI and MCP) for `HotelResult`, `HotelDetail`, `RoomType`, `RatePlan`, and `CancellationPolicy`. Dict shapes guarded by golden-fixture tests.
- `SetupBackend` Protocol + `SetupReport` dataclass + `BACKENDS` registry under `stays.mcp.setup`; per-client `register(...)` / `build()` entrypoints in `stays.mcp.setup.{claude,codex,chatgpt}`.
- `stays` CLI (sole console script) with subcommands `search`, `details`, `enrich`, `mcp`, `mcp-http`.
- `stays setup` group with per-client backends: `claude` (Code + Desktop auto-detect with JSON fallback), `codex` (wraps `codex mcp add` with TOML fallback), `chatgpt` (prints remote-HTTPS + Developer Mode instructions).
- Smart-default routing: `stays "tokyo"` → `stays search "tokyo"`.
- Three output formats: `--format text` (rich tables, default), `--format json` (envelope), `--format jsonl` (line-oriented).
- 330 offline tests + live MCP E2E + golden-fixture parse/serialize/CLI-envelope regression guards + subprocess CLI live E2E (`tests/test_cli_live.py`) + pluggable browser-vs-programmatic oracle (`agent-browser` default, Playwright fallback via `STAYS_BROWSER_DRIVER=playwright`).
- Dockerfile + docker-compose.yml with `prod` / `dev` profiles.
- GitHub Actions: lint, test matrix (Python 3.10–3.13), Docker GHCR, PyPI publish via OIDC.
- `Makefile` for common uv-driven tasks.
- PEP 561 `py.typed` marker.
- `LICENSE` (MIT), `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/AI_AGENTS.md`, `CLAUDE.md`, `AGENTS.md`.

[Unreleased]: https://github.com/him229/stays/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/him229/stays/releases/tag/v0.1.0
