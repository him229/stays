# Browser-vs-programmatic verification suite

On-demand tests that drive Google Hotels in a real browser, run the same query
through `stays`, and diff list-view and detail-view fields across prices,
cancellation policies, amenities, ratings, and reviews.

Two suites share the same ten cases (`cases.py`) but differ in the
"programmatic" side:

- `test_browser_match.py` — **Python API** vs browser. Calls
  `SearchHotels` directly in-process; fastest, and the canonical oracle for
  parser / serializer changes.
- `test_cli_vs_browser.py` — **CLI subprocess** vs browser. Spawns the
  `stays` console script end-to-end; catches envelope / flag / formatting
  drift that the Python-API suite can't see (e.g. CLI `--format json` output
  shape, exit codes, help text).

These tests are **excluded from every default test run** (unit, live, CI,
`pytest tests/`). They only execute when you explicitly opt in.

## Running

```bash
# Run all browser-verification tests (both suites; ~6–10 minutes total).
# Non-USD/non-ambiguous-$ cases (EUR/GBP/JPY/CHF/INR) are SKIPPED by default —
# see "Non-USD currency limitation" below.
pytest tests/browser_verification/ --browser-verify -v

# Just the Python API oracle
pytest tests/browser_verification/test_browser_match.py --browser-verify -v

# Just the CLI-subprocess oracle
pytest tests/browser_verification/test_cli_vs_browser.py --browser-verify -v

# Run a single case across both suites
pytest tests/browser_verification/ --browser-verify -v -k hilton-xian

# Force-run non-USD cases (requires host/proxy matching the target country's IP)
STAYS_FORCE_BROWSER_LOCALE=1 pytest tests/browser_verification/ --browser-verify -v

# Default — browser tests are skipped automatically
pytest tests/                       # no --browser-verify flag, they don't run
pytest                              # same
```

## Non-USD currency limitation

On a US-locale dev machine (or any host whose public IP is not in the
target country), Google Hotels renders prices in USD regardless of the
URL's ``curr=`` / ``gl=`` / ``hl=`` params, the browser's
``Accept-Language`` header, or the GPS-geolocation override we set via
the driver. Google's server-side IP-to-country lookup takes precedence.
This turns every "non-USD, non-ambiguous-$" case into a spurious
"browser rendered USD but case requested ..." failure even when the
programmatic/CLI side is correct.

To avoid that false-positive, the suite skips the affected cases
(``paris-eur-free-cancel``, ``rome-eur-sort-rating``,
``london-gbp-5star-spa``, ``tokyo-jpy-5-star``) by default. Set
``STAYS_FORCE_BROWSER_LOCALE=1`` to opt back in — only meaningful on a
machine whose apparent geolocation (public IP) matches the target
country, e.g. a French-IP proxy for EUR or a direct JP host for JPY.

The driver-side ``set_target_locale()`` plumbing in ``harness.py``
still fires even with the env var unset. It pins the best-effort client
signals (``Accept-Language``, ``locale``, GPS) for when your IP already
matches — no harm done when it doesn't.

The "ambiguous-$" cases (AUD/SGD/HKD/CAD, which share the ``$`` glyph
with USD) always run. They pass whether Google honors the requested
currency or silently collapses to USD, because the symbol matches
either way — non-price fields (rating / review count / star class) are
the real oracles for those cases.

## Prerequisites

agent-browser OR Playwright required; agent-browser preferred.

- **agent-browser (default, preferred):** `brew install agent-browser` or
  `npm install -g agent-browser`, then `agent-browser install` to fetch
  Chrome if missing. Fastest, most accurate — supports `@eNN` accessibility
  refs for targeted element interaction.
- **Playwright (fallback):** `uv sync --extra dev` installs
  `playwright`; then `uv run playwright install chromium`. Use this on
  remote / CI hosts that can't install agent-browser. Feature parity is
  good but not complete — see "Driver selection" below.
- Network access either way — these hit google.com and provider ad
  endpoints.

## Driver selection

The browser backend is pluggable via the `STAYS_BROWSER_DRIVER` env var
(implemented in `drivers.py`):

| Value | Effect |
| --- | --- |
| unset (default) | Prefer agent-browser; fall back to Playwright if agent-browser isn't on `$PATH` |
| `agent-browser` | Force the agent-browser CLI driver (error if missing) |
| `playwright` | Force the Playwright sync driver |

### Feature parity

Both drivers implement the shared `BrowserDriver` Protocol
(`open_url`, `page_text`, `snapshot_interactive`, `screenshot`,
`eval_js`, `close`), so higher-level extraction in `harness.py` works
against either.

- **`find_ref` (agent-browser-specific):** resolves `@eNN` accessibility
  refs emitted by `agent-browser snapshot -i`. Playwright has no
  equivalent; `harness.find_ref` transparently falls back to DOM-level
  `eval_js` (querySelector-based date/filter setting) when refs aren't
  available. Functional, but slightly more brittle when Google's DOM
  shifts.
- **`snapshot_interactive`:** agent-browser returns the `@eNN`-annotated
  accessibility tree used for targeted input; Playwright returns a
  best-effort plain `accessibility.snapshot()` dump (useful for logging,
  not for element targeting).
- **Everything else** (`page_text`, `eval_js`, `screenshot`, `close`) is
  equivalent on both drivers.

## What each test checks

| Case | Query | Currency | Focus |
| --- | --- | --- | --- |
| `hilton-xian-usd-baseline` | Hilton Xi'an | USD | Price slot baseline |
| `paris-eur-free-cancel` | Paris hotels | EUR | `free_cancellation` filter, euro display |
| `tokyo-jpy-5-star` | Tokyo hotels | JPY | `hotel_class=[5]`, yen display |
| `nyc-usd-under-250` | New York hotels | USD | `price_max=250` cap |
| `london-gbp-5star-spa` | London Mayfair hotels | GBP | `hotel_class=[5]` + `amenities=[SPA]` |
| `rome-eur-sort-rating` | Rome hotels | EUR | `sort_by=HIGHEST_RATING` |
| `singapore-sgd-hilton-brand` | Singapore hotels | SGD | `brands=[HILTON]` |
| `sydney-aud-family` | Sydney hotels | AUD | Family party (2 adults + 1 child age 8) |
| `dubai-usd-5star-pool` | Dubai hotels | USD | `hotel_class=[5]` + `amenities=[POOL]` |
| `hongkong-hkd-eco` | Hong Kong hotels | HKD | `eco_certified=True` |

For every case the harness compares:

- **List view** — anchor-hotel price (when no filters applied), rating, row count.
- **Detail view** — rating, review count, star class, **headline price**
  (the prominent ``$NN`` next to the hotel name — same source as the
  programmatic ``display_price``), plus informational fields (per-provider
  prices, cancellation classification, amenity keyword).

Both suites share this oracle. `test_browser_match.py` feeds the comparison
via the in-process `SearchHotels` API; `test_cli_vs_browser.py` feeds it via
`stays search` / `stays details` subprocess invocations parsed from
`--format json` output.

### Hard-fail fields vs. informational fields

Hard failures (these catch real regressions):

- List anchor price (when currency aligned + no filter applied)
- Detail headline price
- Rating (list + detail)
- Review count
- Star class
- Cancellation free-until dates (when both sides have a clear label)

Informational only (logged but never fail the test):

- Per-provider prices in the detail view — the browser text extractor is
  heuristic about which ``$NN`` belongs to which provider row, and the
  rooms-block ``cheapest-per-provider`` rate on the programmatic side
  doesn't always map to the first row the browser UI shows.
- Per-provider cancellation labels — same reason.
- Amenity keyword presence — the browser innerText includes filter
  chips and nearby-hotel content, so a keyword hit doesn't cleanly
  prove the current hotel has that amenity.

## Tolerances

Prices come from Google's own rounded-integer display slot, so the same
entity on the same dates should match nearly exactly. Tolerances are
deliberately tight — generous tolerances would hide exactly the parser
regressions these tests are meant to catch.

- **Prices: ±$2 absolute OR ±2% relative.** Absorbs sub-minute dynamic
  pricing and integer-rounding noise (e.g. ``$97.40`` displays as ``$97``
  or ``$98`` depending on the channel). Anything wider points at a real
  discrepancy.
- **List-view price is skipped when the case applies a price-affecting
  filter** (amenities, hotel_class, brands, price_min/max,
  free_cancellation). Filters make Google surface a filter-specific rate
  in the list view (e.g. a pool-room rate for ``amenities=[POOL]``),
  which won't match the browser's unfiltered display price for the same
  hotel. Detail-view prices still compare cleanly because detail is
  entity-keyed and filter-independent.
- **Ratings: ±0.1** — ratings display to one decimal.
- **Review counts: ±5%** — counts only grow; 5% covers normal lag
  between when the browser fetched and when the programmatic RPC runs.
- **Cancellation free-until dates: exact match** — the dates are
  deterministic per check-in.

Fields without a tolerance are compared exactly (star class, review count
exact match when both sides parsed, etc.).

## Output

- Screenshots land in `tests/browser_verification/screenshots/` —
  `*-list.png` and `*-detail.png` per case. Useful when debugging.
- Each failure prints a per-field diff showing the browser value and the
  programmatic value side-by-side.

## When to run

- After any change to `stays/search/parse/` (price slots, rooms parsing,
  cancellation encoding) — run `test_browser_match.py` for fast feedback.
- After any change to the CLI envelope / serializer / `stays/cli/_runtime.py`
  — run `test_cli_vs_browser.py` to catch subprocess-only drift.
- Before cutting a release that touches the serializer.
- When a user reports a "browser shows X but programmatic output shows Y"
  discrepancy.

These tests are **descriptive, not prescriptive** — they confirm we still
match the upstream UI, not that the parser is "right" in isolation.
