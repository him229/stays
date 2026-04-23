# Browser-vs-MCP verification suite

Ten on-demand tests that drive Google Hotels in a real browser via the
`agent-browser` CLI, run the same query through `SearchHotels`, and compare
list-view and detail-view fields across prices, cancellation policies,
amenities, ratings, and reviews.

These tests are **excluded from every default test run** (unit, live, CI,
`pytest tests/`). They only execute when you explicitly opt in.

## Running

```bash
# Run all 10 browser-verification tests (takes ~3–5 minutes)
pytest tests/browser_verification/ --browser-verify -v

# Run a single case
pytest tests/browser_verification/ --browser-verify -v -k hilton-xian

# Default — browser tests are skipped automatically
pytest tests/                       # no --browser-verify flag, they don't run
pytest                              # same
```

## Prerequisites

- `agent-browser` CLI on `$PATH` (`brew install agent-browser`
  or `npm install -g agent-browser`).
- Chrome installed (`agent-browser install` downloads it if missing).
- Network access — these hit google.com and provider ad endpoints.

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
  (the prominent ``$NN`` next to the hotel name — same source as MCP's
  ``display_price``), plus informational fields (per-provider prices,
  cancellation classification, amenity keyword).

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
  rooms-block ``cheapest-per-provider`` rate in the MCP doesn't always
  map to the first row the browser UI shows.
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
  between when the browser fetched and when the MCP RPC runs.
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

- After any change to `stays/search/parse.py` (price slots, rooms
  parsing, cancellation encoding).
- Before cutting a release that touches the MCP serializer.
- When a user reports a "browser shows X but MCP shows Y" discrepancy.

These tests are **descriptive, not prescriptive** — they confirm we still
match the upstream UI, not that the parser is "right" in isolation.
