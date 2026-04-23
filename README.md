# 🏨 stays — Google Hotels MCP Server + Python Library

[![CI](https://github.com/victoriawei/stays/actions/workflows/test.yml/badge.svg)](https://github.com/victoriawei/stays/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/stays.svg)](https://pypi.org/project/stays/)
[![Python](https://img.shields.io/pypi/pyversions/stays.svg)](https://pypi.org/project/stays/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A single Python package that gives you Google Hotels three ways: a **CLI**, an
**MCP server** for Claude / Codex / ChatGPT, and an importable **library**.
All three talk directly to Google's internal `batchexecute` RPC — no HTML
scraping, no headless browser, no unofficial proxies.

> 🚀 **Why `stays`?**
>
> * **Fast** — direct `AtySUc` RPC calls, not page rendering
> * **Zero scraping** — no HTML parsing, no Playwright/Puppeteer at runtime
> * **Reliable** — Chrome TLS impersonation via `curl_cffi`, 10 rps rate-limit bucket, tenacity retries
> * **MCP-native** — three tools, two prompts, one resource; stdio and streamable HTTP
> * **One install, three surfaces** — `pipx install stays` gets you the CLI, the MCP server, and the library

## Quick start

```bash
# Install
pipx install stays

# Register the MCP server with whichever client(s) you use
stays setup claude        # Claude Code CLI and/or Claude Desktop
stays setup codex         # OpenAI Codex CLI
stays setup chatgpt       # Instructions for remote HTTPS + Developer Mode

# Or skip MCP and use the CLI directly
stays "tokyo hotels" --check-in 2026-07-22 --check-out 2026-07-26
```

Restart your MCP client, then try:

> *"Find me a 4-star hotel in Tokyo for July 22–26 under $120 a night."*
>
> *"Compare rooms, rates, and cancellation for the top 5 hotels near Big Ben."*
>
> *"Show me pet-friendly refundable stays in Paris for next weekend."*

Prefer a different install path? See [Install](#install) below.

## Pick your path

| You are… | Start here |
|----------|------------|
| A Claude / Codex / ChatGPT user who wants your assistant to search hotels | [MCP Clients](#mcp-clients) → [MCP Tools](#mcp-tools) |
| Running hotel searches from the terminal | [CLI Usage](#cli-usage) |
| Building a Python app on top of Google Hotels | [Python API](#python-api) |
| An AI coding agent installing `stays` for a user | [For AI Agents](#for-ai-agents) |
| Deploying `stays` as an HTTP MCP server | [Running the server directly](#running-the-server-directly) → [Docker](#docker) |

## Features

- 🔍 **List-view search** — 16 filter slots: city / brand / stars / price range / amenities / dates / guests / cancellation / eco / special offers / sort.
- 🏨 **Deep hotel detail** — rooms, per-OTA rate plans (Booking, Expedia, Hotels.com, Trip.com, direct), cancellation policies, deep-link URLs.
- ⚡ **Parallel enrichment** — search + fan-out detail fetch for the top N hotels in a single call, with per-hotel partial failure.
- 🤖 **MCP server** — FastMCP over stdio (what Claude/Codex spawn) or streamable HTTP (dev / Docker).
- 🧰 **Three-format CLI** — `text` (rich tables), `json` (single envelope), `jsonl` (stream-friendly).
- 🛡️ **Production hygiene** — rate-limited `curl_cffi` session with Chrome TLS impersonation, tenacity exponential backoff, typed pydantic v2 models, 330 offline tests.
- 🐳 **Ready for containers** — published multi-arch image at `ghcr.io/victoriawei/stays:latest`, plus `docker-compose` profiles.

## Install

```bash
# Recommended — isolated venv, `stays` on your PATH
pipx install stays

# Inside an existing environment
pip install stays

# From source (latest main)
pip install 'git+https://github.com/victoriawei/stays.git'

# Local dev checkout
git clone https://github.com/victoriawei/stays.git
cd stays
uv sync --extra dev
uv run stays --help
```

Requires Python 3.10+. There are **no optional extras** — the CLI, the MCP
stdio/HTTP server, and the Python library are all included in the single core
install.

## CLI Usage

The `stays` console script is the only entry point you need. Subcommands:

| Command | Purpose |
|---------|---------|
| `stays search <query>` | Fast list-view search (one RPC) |
| `stays details <entity_key>` | Rooms / rates / cancellation for ONE hotel |
| `stays enrich <query>` | Search + parallel detail fetch for the top N hotels |
| `stays mcp` | Stdio MCP server (what Claude / Codex spawn) |
| `stays mcp-http` | Streamable-HTTP MCP server (dev / Docker) |
| `stays setup {claude\|codex\|chatgpt}` | Register the MCP server with a client |

**Smart default**: if the first positional arg doesn't match a known
subcommand, `stays` routes to `search`. `stays "paris hotels" ...` is
equivalent to `stays search "paris hotels" ...`.

### Examples

```bash
# Rich list-view with filters
stays search "tokyo hotels" \
    --check-in 2026-07-22 --check-out 2026-07-26 \
    --stars 4 --stars 5 \
    --amenity POOL --brand HILTON \
    --price-max 300 --sort-by LOWEST_PRICE

# Smart-default form (no `search` subcommand)
stays "paris hotels" --check-in 2026-09-01 --check-out 2026-09-04

# Rooms / rates / cancellation for ONE hotel
stays details "ChkI_ENTITY_KEY_FROM_SEARCH" \
    --check-in 2026-07-22 --check-out 2026-07-26

# Search + top-5 deep detail in parallel
stays enrich "new york hotels" --max-hotels 5 \
    --check-in 2026-09-01 --check-out 2026-09-04

# Machine-readable output
stays search "tokyo" --format json    # single pretty-printed envelope
stays search "tokyo" --format jsonl   # one record per line, stream-friendly
```

### CLI options (`search` / `enrich`)

| Flag | Type | Purpose |
|------|------|---------|
| `--check-in` / `--check-out` | `YYYY-MM-DD` | Stay window (required for rate plans) |
| `--adults` / `--children` | int | Party composition (1–12 / 0–8) |
| `--child-age` | int (repeat) | One `--child-age` per child |
| `--currency` | ISO 4217 | Output currency (default `USD`) |
| `--property-type` | enum | `HOTELS` (default) or `VACATION_RENTALS` |
| `--sort-by` | enum | `RELEVANCE`, `LOWEST_PRICE`, `HIGHEST_RATING`, `MOST_REVIEWED` |
| `--stars` | 1–5 (repeat) | Hotel-class filter (`--stars 4 --stars 5`) |
| `--min-rating` | enum | `THREE_FIVE_PLUS`, `FOUR_ZERO_PLUS`, `FOUR_FIVE_PLUS` |
| `--amenity` | enum (repeat) | `POOL`, `WIFI`, `SPA`, `PET_FRIENDLY`, … |
| `--brand` | enum (repeat) | `HILTON`, `MARRIOTT`, `HYATT`, … |
| `--price-min` / `--price-max` | int | Price band (selected currency) |
| `--free-cancellation` | flag | Refundable-only |
| `--eco-certified` | flag | Eco-certified only |
| `--special-offers` | flag | Deals only |
| `--max-results` | int | `search` only — cap (1–25) |
| `--max-hotels` | int | `enrich` only — cap (1–15, default 5) |
| `--format` | enum | `text` (rich tables, default), `json`, `jsonl` |

> `--format json` / `--format jsonl` envelope shapes are stable for v0.1.x
> but may evolve in minor releases.

## MCP Clients

One command per client. If auto-registration isn't possible, each backend
prints the equivalent JSON/TOML you can paste yourself.

### Claude Code / Desktop

```bash
stays setup claude
```

Auto-detects both the `claude` CLI (Claude Code) and
`claude_desktop_config.json` (Claude Desktop) and registers with whichever it
finds. Falls through to printing the canonical JSON when neither is present.

- `--print-json` — always print, never register.
- `--desktop-only` — skip the `claude` CLI probe and force Desktop mode.
- `--replace` — overwrite any prior `stays` entry.

### Codex CLI

```bash
stays setup codex
```

Shells to `codex mcp add stays -- <abs-path>/stays mcp` when the `codex`
binary is on `$PATH`; otherwise prints the equivalent TOML block for
`~/.codex/config.toml`.

- `--print-toml` — always print, never shell out.
- `--replace` — overwrite any prior `stays` entry.

### ChatGPT

```bash
stays setup chatgpt
```

Prints setup instructions. ChatGPT requires a **public HTTPS endpoint**
implementing OAuth 2.1 + Dynamic Client Registration, registered via
Developer Mode in the ChatGPT app — no local auto-registration is possible.

- `--open` — jump to the ChatGPT Connectors settings page in your browser.

### Canonical MCP client config

If the `stays setup …` installer cannot detect your client, emit the snippet
yourself:

```bash
stays setup claude --print-json
```

A minimal version that works when the `stays` binary is on the client's
`$PATH`:

```json
{
  "mcpServers": {
    "stays": {
      "command": "/abs/path/to/stays",
      "args": ["mcp"]
    }
  }
}
```

Claude Desktop config path:

| OS      | Path |
|---------|------|
| macOS   | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Linux   | `~/.config/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

## MCP Tools

The server exposes three tools. All of them return JSON-safe dicts.

| Tool | When to use | RPC cost |
|------|-------------|----------|
| **`search_hotels`** | List-view discovery: browse / filter by city, stars, amenities, price, brand. Start here. | 1 |
| **`get_hotel_details`** | One hotel: rooms, per-OTA rates, cancellation. Needs an `entity_key` from `search_hotels`. | 1 |
| **`search_hotels_with_details`** | Compare 3–15 hotels' rooms/rates/cancellation in a single call. | 1 + N |

### `search_hotels` parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `query` *required* | string | `"tokyo hotels"`, `"Hilton Paris"`, etc. |
| `check_in` / `check_out` | string | `YYYY-MM-DD`. Omit both for flexible dates. |
| `adults` / `children` / `child_ages` | int / int / list[int] | Party composition |
| `currency` | string | ISO 4217 (default from `STAYS_MCP_DEFAULT_CURRENCY`) |
| `property_type` | enum | `HOTELS` (default) or `VACATION_RENTALS` |
| `sort_by` | enum | `RELEVANCE`, `LOWEST_PRICE`, `HIGHEST_RATING`, `MOST_REVIEWED` |
| `hotel_class` | list[int] | Star classes to include, e.g. `[4, 5]` |
| `min_guest_rating` | enum | `THREE_FIVE_PLUS`, `FOUR_ZERO_PLUS`, `FOUR_FIVE_PLUS` |
| `amenities` | list[string] | `POOL`, `WIFI`, `SPA`, `PET_FRIENDLY`, … |
| `brands` | list[string] | `HILTON`, `MARRIOTT`, `HYATT`, `IHG`, `ACCOR`, … |
| `free_cancellation` | bool | Refundable-only |
| `eco_certified` | bool | Eco-certified only |
| `special_offers` | bool | Deals only |
| `price_min` / `price_max` | int | Price band (selected currency) |
| `max_results` | int | Cap (1–25); overrides `STAYS_MCP_MAX_RESULTS` |

### `get_hotel_details` parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `entity_key` *required* | string | From a prior `search_hotels` result |
| `check_in` *required* | string | `YYYY-MM-DD` (rate plans are date-keyed) |
| `check_out` *required* | string | `YYYY-MM-DD` after `check_in` |
| `currency` | string | ISO 4217 (default `USD`) |

### `search_hotels_with_details` parameters

Same filter set as `search_hotels`, plus:

| Parameter | Type | Description |
|-----------|------|-------------|
| `max_hotels` | int | Top-N hotels to enrich (1–15, default 5) |

### Prompts & resources

The server also exposes two prompts — `when-to-deep-search` and
`compare-hotels-in-city` — that help an LLM pick the right tool, plus one
resource `resource://stays-mcp/configuration` describing the live env-var
config.

## Python API

Everything public is re-exported from the top-level `stays` package.

```python
from datetime import date
from stays import (
    SearchHotels, HotelSearchFilters, Location, DateRange, GuestInfo,
    Amenity, Brand, Currency, SortBy, MinGuestRating,
)

s = SearchHotels()

# 1. Fast list-view search — one RPC
results = s.search(HotelSearchFilters(
    location=Location(query="tokyo hotels"),
    dates=DateRange(check_in=date(2026, 7, 22), check_out=date(2026, 7, 26)),
    guests=GuestInfo(adults=2),
    hotel_class=[4, 5],
    amenities=[Amenity.POOL, Amenity.WIFI],
    brands=[Brand.HILTON],
    sort_by=SortBy.LOWEST_PRICE,
    currency=Currency.USD,
))
for hotel in results[:3]:
    print(hotel.name, hotel.display_price, hotel.overall_rating)
```

### Deep detail for one hotel

```python
first = results[0]
if first.entity_key:
    detail = s.get_details(
        entity_key=first.entity_key,
        dates=DateRange(check_in=date(2026, 7, 22), check_out=date(2026, 7, 26)),
    )
    print(detail.address, detail.phone)
    for room in detail.rooms:
        for rp in room.rates:
            print(rp.provider, rp.price, rp.cancellation.kind.value)
```

### Parallel enrichment with partial-failure handling

```python
filters = HotelSearchFilters(
    location=Location(query="new york hotels"),
    dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
)
for item in s.search_with_details(filters, max_hotels=5):
    if item.ok:
        print(item.detail.name, len(item.detail.rooms), "rooms")
    else:
        # error_kind is "transient" or "fatal"; is_retryable is True only
        # for transient failures. Unknown exceptions (parser bugs, etc.)
        # propagate — only typed BatchExecuteError / TransientBatchExecuteError
        # / MissingHotelIdError become per-item errors.
        retry_hint = " (retryable)" if item.is_retryable else ""
        print("skipped:", item.result.name, "—", item.error_kind, item.error, retry_hint)
```

`stays enrich --format json` and the MCP `search_hotels_with_details` tool
mirror this shape: each per-hotel record includes `ok`, `result`, `detail`,
`error`, `error_kind` (`"transient"` | `"fatal"` | `null`), and `is_retryable`.

### Serializer-only (no HTTP)

Useful for debugging the wire shape or building your own client on top:

```python
filters = HotelSearchFilters(
    location=Location(query="new york hotels"),
    dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
    guests=GuestInfo(adults=2, children=1, child_ages=[7]),
    price_range=(100, 300),
)
filters.format()           # Python list — inner JSON shape
filters.encode()           # URL-encoded outer envelope
filters.to_request_body()  # "f.req=..." — ready to POST
```

### Public exports

- **Models**: `Amenity`, `Brand`, `Currency`, `DateRange`, `GuestInfo`,
  `HotelSearchFilters`, `Location`, `MinGuestRating`, `PropertyType`, `SortBy`
- **Results**: `HotelResult`, `HotelDetail`, `RoomType`, `RatePlan`,
  `CancellationPolicy`, `CancellationPolicyKind`, `Review`,
  `RatingHistogram`, `CategoryRating`, `NearbyPlace`, `EnrichedResult`
  (now carries `error_kind: Literal["transient","fatal"] | None` and
  a `.is_retryable` property)
- **Search API**: `SearchHotels`, `Client`, `BatchExecuteError`,
  `TransientBatchExecuteError`, `MissingHotelIdError`
- **Serializers**: `stays.serialize` — canonical `serialize_hotel_result`,
  `serialize_hotel_detail`, plus `build_success` / `build_error` envelope
  helpers (shared by CLI + MCP; dict shapes guarded by golden-fixture tests)
- **MCP (core install only)**: `mcp`, `search_hotels`, `get_hotel_details`,
  `search_hotels_with_details`, `run_mcp`, `run_mcp_http`

## Running the server directly

```bash
# Stdio — what Claude Code / Desktop / Codex invoke on your behalf
stays mcp

# Streamable HTTP — dev or Docker runtime
stays mcp-http   # serves http://127.0.0.1:8000/mcp/
```

> The streamable-HTTP endpoint requires the MCP-spec header
> `Accept: application/json, text/event-stream`. A bare `GET /mcp/` returns
> 405/406 by design — this is not a bug.

## Docker

A published image is available from GitHub Container Registry:

```bash
# Pull the latest release image
docker run --rm -p 8000:8000 ghcr.io/victoriawei/stays:latest

# Or with compose (prod profile, healthcheck included)
docker compose --profile prod up

# Or build + run locally (dev profile)
docker compose --profile dev up --build
```

Environment variables (see [Configuration](#configuration)) are passed through
normally, e.g. `-e STAYS_RPS=5 -e STAYS_MCP_DEFAULT_CURRENCY=EUR`.

## Configuration

All configuration is via environment variables. `STAYS_RPS` tunes the shared
rate-limit bucket used by the library, CLI, and MCP server alike; everything
else is prefixed `STAYS_MCP_` and only affects MCP tool defaults.

| Env var | Default | Purpose |
|---------|---------|---------|
| `STAYS_RPS` | `10` | Rate-limiter throttle (requests per second) |
| `STAYS_MCP_DEFAULT_ADULTS` | `2` | Default adults per search |
| `STAYS_MCP_DEFAULT_CURRENCY` | `USD` | Fallback currency |
| `STAYS_MCP_DEFAULT_SORT_BY` | `RELEVANCE` | Default sort |
| `STAYS_MCP_MAX_RESULTS` | *unset* | Cap on returned list-view results (uncapped when unset) |
| `STAYS_MCP_DEFAULT_MAX_HOTELS_WITH_DETAILS` | `5` | Default N for `search_hotels_with_details` (hard cap 15) |

The live config resource is also readable at
`resource://stays-mcp/configuration` from the running MCP server.

## For AI Agents

> If you are an AI agent installing this on behalf of a human user, use
> the commands in this section verbatim. They are the canonical install path.
> `pipx install stays` is always sufficient — there are no optional
> `[mcp]` / `[cli]` extras to remember.

```bash
# Option A (recommended) — pipx: isolated venv + `stays` on PATH
pipx install stays
stays setup claude        # registers with any Claude client detected

# Option B — inside an existing Python environment
pip install stays

# Option C — local dev checkout
git clone https://github.com/victoriawei/stays.git
cd stays
uv sync --extra dev
uv run stays setup claude
```

Full agent-facing docs — verification steps, troubleshooting table, scripted
install — live in [`docs/AI_AGENTS.md`](docs/AI_AGENTS.md).

## Development

```bash
git clone https://github.com/victoriawei/stays.git
cd stays
make install-dev          # uv sync --extra dev
make test                 # offline suite
make test-live            # live Google-API tests (network + rate-limit)
make lint                 # ruff check
make format               # ruff format
make mcp                  # run stdio MCP server locally
make mcp-http             # run streamable-HTTP MCP server on :8000
make coverage             # pytest + branch coverage → htmlcov/
make build                # sdist + wheel
```

Full command list: `make help`.

### Testing

- **Offline suite** (`make test`) — 330 tests including golden-fixture
  regression guards for the parser, the canonical serializers, and the CLI
  JSON envelope shapes (`tests/test_parse_golden.py`,
  `tests/test_serialize_golden.py`, `tests/test_cli_envelope_golden.py`).
- **Live CLI E2E** (`tests/test_cli_live.py`, marker-gated: `pytest -m live`)
  — 9 subprocess-driven scenarios that exercise the real `stays` binary
  against live Google (Tokyo dates, Hilton brand family, 4/5-star Paris,
  London amenity + price band, free-cancellation differential and
  refundability, search→details roundtrip, `enrich` parallel per-item
  contract, JPY sort).
- **Browser-verify matrix** (`pytest --browser-verify`) — the
  MCP-vs-browser and CLI-vs-browser oracle suites under
  `tests/browser_verification/` (including
  `tests/browser_verification/test_cli_vs_browser.py`) diff our results
  against an authoritative browser oracle. The driver is pluggable:
  `agent-browser` is the default; set `STAYS_BROWSER_DRIVER=playwright`
  to force the Playwright fallback.

### Project layout

```
stays/
├── cli/           # typer app + subcommand bodies
├── mcp/           # FastMCP server, per-client setup backends
├── search/        # batchexecute HTTP client + search / detail / enrich
└── models/        # pydantic v2 filter + result + detail + policy models

tests/             # 330 offline + live (-m live) + browser-verify (--browser-verify)
docs/              # reverse-engineering notes, superpowers artifacts, AI_AGENTS.md
captures/          # Playwright capture oracles (gitignored where large)
```

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the dev
loop, PR checklist, and issue template.

## License

MIT — see [LICENSE](LICENSE).
