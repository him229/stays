# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`stays` is a Python library and MCP server that provides programmatic access to Google Hotels through direct API interaction (reverse engineering). The project consists of:

- **MCP server** (`stays/mcp/`) — FastMCP-based stdio + streamable-HTTP server exposing three tools. Layered into `server.py` (registration only — `@mcp.tool`/`@mcp.prompt`/`@mcp.resource` + re-exports), `_config.py` (`HotelSearchConfig`, `CONFIG`, `CONFIG_SCHEMA`, `HARD_MAX_HOTELS_WITH_DETAILS = 15`), `_params.py` (pydantic `*Params` classes + shared `_validate_child_ages`), and `_executors.py` (`_execute_*_from_params` + MCP-subset `_serialize_hotel_*` wrappers).
- **Search engine** (`stays/search/`) — hotel search, detail, and parallel enrichment
- **Core client** (`stays/search/client.py`) — rate-limited `curl_cffi` session with Chrome TLS impersonation
- **Data models** (`stays/models/google_hotels/`) — pydantic filter/result/detail models
- **Parse layer** (`stays/search/parse/`) — response parsing split across `search_parser`/`detail_parser`/`policy_parser`/`provider_parser`/`slots.py`. `slots.py` owns named slot-index constants + `safe_get(tree, *path, default)`.
- **Canonical serializers** (`stays/serialize.py`) — single source of truth for hotel → dict serialization consumed by both the CLI and MCP (the CLI-local `stays/cli/_serialize.py` is a re-export shim).
- **CLI runtime helpers** (`stays/cli/_runtime.py`) — shared `emit_result` / `emit_error` / `build_filters_from_cli_args` plumbing used by `search` / `details` / `enrich` subcommands.
- **MCP setup backends** (`stays/mcp/setup/_backend.py` + `_adapters.py`) — `SetupBackend` Protocol + `SetupReport` dataclass + `BACKENDS` registry; the legacy `stays.mcp.setup.{claude,codex,chatgpt}.register(...)` / `.build()` entry points are preserved on top.

The implementation leans heavily on reverse-engineering captures under `docs/reverse-engineering/` — slot maps and filter coverage notes are the authoritative reference for the wire format.

## Development Commands

### Core Development Tasks
```bash
# Install dependencies
uv sync --extra dev

# Tests
make test                    # Unit + offline tests (skips live network)
make test-live               # Live Google API tests (network + rate-limit sensitive)
make test-all                # Everything including browser verification
make coverage                # Tests + branch coverage report
uv run pytest -vv            # Direct pytest invocation

# Code quality
make lint                    # Ruff check
make lint-fix                # Ruff autofix
make format                  # Ruff format

# MCP server
make mcp                     # Stdio server (what Claude Code/Desktop spawn) — wraps `stays mcp`
make mcp-http                # Streamable HTTP on 127.0.0.1:8000/mcp/ — wraps `stays mcp-http`

# Docker
make docker                  # Build local image
make docker-run              # Build + run on port 8000

# Build
make build                   # sdist + wheel via uv build
make clean                   # Remove build/dist/cache artifacts
```

### Test Configuration
- Markers: `live` (hits google.com), `slow` (rate-limiter timing), `browser_verify` (opt-in browser-vs-programmatic diff, requires `--browser-verify`)
- Test tree mirrors source: `tests/test_search_hotels.py`, `tests/test_mcp_server.py`, `tests/test_hotel_serializer.py`, `tests/browser_verification/`
- **Both `live` and `browser_verify` are auto-skipped by `conftest.py` on bare `pytest`.** Opt in via flags:
  - `pytest --live` or `pytest -m live` — run live tests (hits google.com, flaky)
  - `pytest --browser-verify` — run browser-oracle suite (requires agent-browser or Playwright)
  - `pytest --live --browser-verify` — run everything
- Makefile targets mirror this: `make test` (offline), `make test-live`, `make test-browser`, `make test-all`.
- CI split: `test.yml` runs the offline suite on every PR + matrix (3.10–3.13); `test-live.yml` runs live tests on push-to-main + nightly cron + manual dispatch (continue-on-error, doesn't block merges).
- **Golden-fixture regression guards** pin byte-identical output of the parse, serialize, and CLI envelope layers: `tests/test_parse_golden.py`, `tests/test_serialize_golden.py`, `tests/test_cli_envelope_golden.py`. Updates must regenerate the fixtures deliberately, not by silently relaxing assertions.
- **Live CLI E2E suite:** `tests/test_cli_live.py` spawns the `stays` console script in 9 subprocess scenarios against the real Google API (excluded from default `make test`; run via `make test-live` or `make test-all`).
- **Narrow ImportError test:** `tests/test_init.py` locks in that `stays/__init__.py` only catches `ModuleNotFoundError` for the optional `fastmcp` import (bare `ImportError` from a broken install still surfaces).
- **Browser-verify suites** (both opt-in via `--browser-verify`):
  - `tests/browser_verification/test_browser_match.py` — Python API vs browser oracle (10 cases).
  - `tests/browser_verification/test_cli_vs_browser.py` — CLI subprocess vs browser oracle (same 10 cases, different entry point).
  - Driver is pluggable via `STAYS_BROWSER_DRIVER=agent-browser|playwright` (agent-browser preferred; Playwright is the fallback when agent-browser isn't on `$PATH`).

## Architecture Overview

### Core Components

1. **HTTP Client** (`stays/search/client.py`)
   - Rate-limited `curl_cffi` session (10 RPS default via `STAYS_RPS`)
   - Chrome TLS impersonation (`impersonate="chrome"`) to evade anti-bot detection
   - Retry stack: tenacity exponential backoff → ratelimit sleep → fixed-window bucket
   - `post_rpc(rpc_id, inner_payload)` is the one public call site

2. **Search Engine** (`stays/search/hotels.py`)
   - `SearchHotels.search(filters)` — list view, returns `list[HotelResult]`
   - `SearchHotels.get_details(entity_key, dates, *, currency, location)` — single hotel deep view
   - `SearchHotels.search_with_details(filters, max_hotels)` — parallel enrichment (thread pool of N). Only `BatchExecuteError` / `TransientBatchExecuteError` / `MissingHotelIdError` become per-hotel errors; unknown exceptions (including parser bugs) now propagate instead of being silently swallowed.
   - `EnrichedResult` carries `error_kind: Literal["transient","fatal"] | None` plus an `is_retryable` property — callers can tell retryable transient failures from fatal ones.

3. **Parse Layer** (`stays/search/parse/`)
   - `parse_search_response(inner)` → `list[HotelResult]` (in `search_parser.py`)
   - `parse_detail_response(inner)` → `HotelDetail` (in `detail_parser.py`)
   - Slot indices + a `safe_get(tree, *path, default)` helper centralized in `stays/search/parse/slots.py`; provider/policy extraction split into `provider_parser.py` / `policy_parser.py`
   - Extracts from Google's nested-array RPC response at well-known slot indices (see `docs/reverse-engineering/slot-map.md`)

4. **Filter Model** (`stays/models/google_hotels/hotels.py`)
   - `HotelSearchFilters.format()` returns the inner payload list for `batchexecute`
   - Serializes 16+ filter slots: location, dates, guests, currency, sort_by, hotel_class, amenities, brands, price_range, min_guest_rating, free_cancellation, eco_certified, special_offers, entity_key

5. **MCP Server** (`stays/mcp/`)
   - `server.py` is the registration surface only: `@mcp.tool` / `@mcp.prompt` / `@mcp.resource` definitions plus re-exports of the params/executors
   - `_config.py` owns `HotelSearchConfig`, `CONFIG`, `CONFIG_SCHEMA`, and `HARD_MAX_HOTELS_WITH_DETAILS = 15` (the canonical cap used by both the prompt copy and the `search_hotels_with_details` docstring)
   - `_params.py` owns the pydantic params classes (`SearchHotelsParams`, `GetHotelDetailsParams`, `SearchHotelsWithDetailsParams`) and the deduplicated `_validate_child_ages` helper
   - `_executors.py` owns `_execute_*_from_params` + the MCP-subset `_serialize_hotel_*` wrappers
   - `@mcp.tool` signatures use `Annotated[..., Field(...)]` for rich JSON schema; pydantic validation runs before the network call
   - Spawned as `stays mcp` (stdio) or `stays mcp-http` (streamable HTTP) by the CLI

6. **CLI** (`stays/cli/`)
   - `stays/cli/_entry.py` — console-script entry (smart-default router that treats `stays "tokyo"` as `stays search "tokyo"`)
   - `stays/cli/_app.py` — `typer.Typer` app + subcommand registration
   - `stays/cli/commands/{search,details,enrich,mcp,setup}.py` — subcommand bodies
   - `stays/cli/_runtime.py` — shared `emit_result` / `emit_error` / `build_filters_from_cli_args` plumbing the subcommands delegate to
   - `stays/cli/_serialize.py` — thin re-export shim over the canonical `stays/serialize.py`
   - Three output formats: `--format text` (rich tables, default), `--format json`, `--format jsonl`
   - CLI `enrich` surfaces each item's `error_kind` + `is_retryable` in its output envelope (matching the MCP `search_hotels_with_details` shape)

7. **MCP setup installers** (`stays/mcp/setup/`)
   - `stays/mcp/setup/_backend.py` — `SetupBackend` Protocol + `SetupReport` dataclass
   - `stays/mcp/setup/_adapters.py` — `BACKENDS` registry wiring the per-client modules to the Protocol
   - `stays/mcp/setup/{claude,codex,chatgpt}.py` — per-client MCP registration backends (the legacy `register(...)` / `build()` signatures are preserved)
   - `stays/mcp/setup/__init__.py` — shared helpers (`resolve_stays_command`, canonical JSON/TOML blocks)
   - Pure-stdlib: setup logic has zero runtime MCP dependencies (safe to import during install)

### Key Design Patterns

- **Direct API access:** no HTML scraping, no browser automation — straight `batchexecute` RPC
- **Single RPC for search + detail:** `AtySUc` handles both, driven into detail mode via `entity_key` at slot `[2][5]`
- **Explicit enums for wire values:** `Currency`, `SortBy`, `Amenity`, `Brand`, `PropertyType`, `MinGuestRating` all map to Google's integer/string IDs
- **Filter-pattern with pydantic:** all search parameters collected into `HotelSearchFilters`; `.format()` handles serialization to Google's nested-list shape
- **Rate limiting at the lowest layer:** `post_rpc` is decorated once; every caller inherits the bucket without opting in

## Key Files and Entry Points

- `stays/cli/_entry.py` — console-script entry (smart-default router)
- `stays/cli/_app.py` — `typer.Typer` app + command registration
- `stays/cli/_runtime.py` — shared `emit_result`, `emit_error`, and `build_filters_from_cli_args` helpers
- `stays/cli/_serialize.py` — re-export shim over the canonical `stays/serialize.py`
- `stays/cli/commands/{search,details,enrich,mcp,setup}.py` — subcommand bodies
- `stays/mcp/setup/_backend.py` — `SetupBackend` Protocol + `SetupReport` dataclass
- `stays/mcp/setup/_adapters.py` — `BACKENDS` registry binding per-client modules to the Protocol
- `stays/mcp/setup/{claude,codex,chatgpt}.py` — per-client MCP registration backends
- `stays/mcp/setup/__init__.py` — shared helpers (`resolve_stays_command`, canonical JSON/TOML)
- `stays/mcp/_entry.py` — MCP server entry (`run`, `run_http`)
- `stays/mcp/server.py` — FastMCP registration surface (tool/prompt/resource decorators + re-exports)
- `stays/mcp/_config.py` — `HotelSearchConfig`, `CONFIG`, `CONFIG_SCHEMA`, `HARD_MAX_HOTELS_WITH_DETAILS = 15`
- `stays/mcp/_params.py` — MCP `*Params` pydantic classes + `_validate_child_ages`
- `stays/mcp/_executors.py` — `_execute_*_from_params` + `_serialize_hotel_*` MCP wrappers
- `stays/serialize.py` — canonical hotel serializers shared by CLI and MCP
- `stays/search/client.py` — HTTP client with retry/rate-limit stack
- `stays/search/hotels.py` — high-level `SearchHotels` API + `EnrichedResult` (`error_kind`, `is_retryable`)
- `stays/search/parse/` — response parsing package (`search_parser`, `detail_parser`, `policy_parser`, `provider_parser`, `slots`)
- `stays/models/google_hotels/base.py` — shared enums + base pydantic models
- `stays/models/google_hotels/hotels.py` — `HotelSearchFilters` + serializer
- `stays/models/google_hotels/result.py` — list-view `HotelResult`
- `stays/models/google_hotels/detail.py` — detail-view `HotelDetail` + `RoomType` + `RatePlan`
- `docs/reverse-engineering/slot-map.md` — canonical slot index → meaning reference
- `pyproject.toml` — package metadata + script entry points + ruff/pytest config

## MCP Tool Reference

### `search_hotels`
Fast list-view hotel search — use this first.

**Key Parameters:**
- `query` — free text (`"tokyo hotels"`, `"Hilton Paris"`)
- `check_in` / `check_out` — `YYYY-MM-DD` (optional; omit for flexible)
- `adults`, `children`, `child_ages` — party composition
- `currency` — ISO 4217 (default from `STAYS_MCP_DEFAULT_CURRENCY`)
- `sort_by` — `RELEVANCE | LOWEST_PRICE | HIGHEST_RATING | MOST_REVIEWED`
- `hotel_class` — `[4, 5]` etc. (each entry 1–5)
- `amenities` — enum names (`POOL`, `WIFI`, `SPA`, `PET_FRIENDLY`, ...)
- `brands` — enum names (`HILTON`, `MARRIOTT`, ...)
- `min_guest_rating`, `free_cancellation`, `eco_certified`, `special_offers`
- `price_min`, `price_max`

Returns: `list[HotelResult]` with `entity_key`, price, rating, amenities, coordinates.

### `get_hotel_details`
Deep view for ONE hotel. Requires `entity_key` from `search_hotels`.

**Key Parameters:**
- `entity_key` — from a prior `search_hotels` result
- `check_in` / `check_out` — required (rate plans are date-keyed)
- `currency`

Returns: `HotelDetail` with rooms, per-OTA rate plans, cancellation policies, full amenity list.

### `search_hotels_with_details`
Search + parallel detail fetch for the top N (1–15) hotels in one call. The hard cap is `HARD_MAX_HOTELS_WITH_DETAILS = 15` (defined in `stays/mcp/_config.py`); both the `search_hotels_with_details` tool docstring and the `when-to-deep-search` prompt reference the same constant.

Use only when the user wants to compare rooms/rates/cancellation across SEVERAL hotels. Costs 1 + N RPCs. Each returned item carries `error_kind` (`"transient" | "fatal" | None`) and `is_retryable` so callers can distinguish retryable transient failures from fatal ones.

## Code Style and Standards

- **Linting:** Ruff (pycodestyle, pyflakes, isort, flake8-bugbear, pyupgrade)
- **Formatting:** Ruff formatter, 120 char line length, double quotes
- **Type hints:** Python 3.10+, `from __future__ import annotations` in module headers, pydantic v2 for runtime models
- **Docstrings:** Google-style, one-sentence summary on the first line
- **Testing:** pytest with asyncio auto mode, live tests marker-gated

## Important Implementation Notes

- **Anti-bot compliance:** every Google call requires Chrome TLS impersonation; plain `requests` gets a sorry interstitial. Do not remove the `curl_cffi` dependency.
- **Rate-limit coupling:** the retry decorator is OUTSIDE the rate-limiter, so every retry attempt costs a slot. Tune `STAYS_RPS` cautiously.
- **Detail RPC = search RPC:** both use `AtySUc`. Detail mode is activated by setting `entity_key` at outer payload slot `[2][5]`.
- **Currency is wire-level:** sent at payload slot `[1][4][0][6]`.
- **Date windows drive rate plans:** `get_details` without `dates` returns room types without prices. Always pass check-in/check-out for detail calls.
- **Captures are gitignored:** `captures/output_run*.json` are regeneration oracles; tracked files under `captures/` and `docs/reverse-engineering/` are the canonical references.
- **CONTEXT.md is the state-of-the-world:** update it whenever you finish a non-trivial chunk of work.
