"""Ten browser-vs-programmatic verification cases.

Each case drives a real Google Hotels query in both the ``agent-browser``
CLI and our ``SearchHotels`` code path, then compares the common fields
(prices, cancellation, amenities, rating, review count).

Cases intentionally span:
  * Multiple currencies (USD / EUR / GBP / JPY / AUD / SGD / HKD / CAD)
  * Multiple filter types (free_cancellation, hotel_class, amenities,
    brands, price_min/max, eco_certified)
  * Multiple regions (North America, Europe, Asia, Oceania, Middle East)

``anchor_hotel_substring`` is used to pick a specific hotel for the
detail-view deep-dive (the browser and programmatic rankings don't always
line up, so we match by name substring instead of index).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from stays.models.google_hotels.base import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    Location,
    SortBy,
)
from stays.models.google_hotels.hotels import HotelSearchFilters


# Dates: pick a stable future window so results are reproducible-ish.
# Using +90 / +92 days keeps us clear of last-minute sell-out pricing and
# far enough out that most providers have inventory loaded.
def _window(days_ahead: int = 90, nights: int = 2) -> DateRange:
    today = date.today()
    return DateRange(
        check_in=today + timedelta(days=days_ahead),
        check_out=today + timedelta(days=days_ahead + nights),
    )


@dataclass
class BrowserCase:
    label: str
    query: str
    currency: str
    filters: HotelSearchFilters
    anchor_hotel_substring: str  # pick this hotel for detail-view verification
    # Optional: substring of a required amenity to cross-check (e.g. "Pool")
    expected_amenity_keyword: str | None = None
    # Skip detail-view cross-check (some filter-heavy queries may not have a
    # reliable anchor — use False very sparingly).
    do_detail_check: bool = True
    # Optional: tuple of name tokens that EVERY programmatic result must
    # belong to. Used by brand-filter cases to catch "filter accepted but
    # silently ignored" regressions. None ⇒ no brand check. 70% default
    # floor allows for Google folding nearby non-branded curated hotels
    # into a branded result set; unfiltered would show <30%.
    brand_name_tokens: tuple[str, ...] | None = None
    brand_min_match_pct: float = 0.7


DATES = _window(days_ahead=90, nights=2)


CASES: list[BrowserCase] = [
    # --------------------------------------------------------------
    # 1. Baseline — Hilton Xi'an, USD, two adults. Confirms the
    #    display_num slot matches the browser list-view price.
    # --------------------------------------------------------------
    BrowserCase(
        label="hilton-xian-usd-baseline",
        query="Hilton Xi'an",
        currency="USD",
        filters=HotelSearchFilters(
            location=Location(query="Hilton Xi'an"),
            dates=DATES,
            currency=Currency.USD,
        ),
        anchor_hotel_substring="Hilton Xi'an",
    ),
    # --------------------------------------------------------------
    # 2. Paris, EUR, free_cancellation filter. Verifies Euro display
    #    parses correctly + refundable-only surfaces only FREE_UNTIL rates.
    # --------------------------------------------------------------
    BrowserCase(
        label="paris-eur-free-cancel",
        query="Paris hotels",
        currency="EUR",
        filters=HotelSearchFilters(
            location=Location(query="Paris hotels"),
            dates=DATES,
            currency=Currency.EUR,
            free_cancellation=True,
        ),
        anchor_hotel_substring="Hotel",  # relaxed — top Paris result varies
    ),
    # --------------------------------------------------------------
    # 3. Tokyo, JPY, 5-star filter. Verifies yen parsing + hotel_class
    #    filter application.
    # --------------------------------------------------------------
    BrowserCase(
        label="tokyo-jpy-5-star",
        query="Tokyo hotels",
        currency="JPY",
        filters=HotelSearchFilters(
            location=Location(query="Tokyo hotels"),
            dates=DATES,
            currency=Currency.JPY,
            hotel_class=[5],
        ),
        anchor_hotel_substring="Hotel",
    ),
    # --------------------------------------------------------------
    # 4. NYC, USD, price_range=(None, 250) budget cap. Exercises the
    #    price range filter + confirms results respect the cap.
    #    NOTE: HotelSearchFilters only has ``price_range: tuple[int|None,
    #    int|None] | None`` — ``price_max=250`` as a direct kwarg was
    #    silently dropped by pydantic (extra="ignore"), so the case wasn't
    #    actually filtering programmatically.
    # --------------------------------------------------------------
    BrowserCase(
        label="nyc-usd-under-250",
        query="New York hotels",
        currency="USD",
        filters=HotelSearchFilters(
            location=Location(query="New York hotels"),
            dates=DATES,
            currency=Currency.USD,
            price_range=(None, 250),
        ),
        anchor_hotel_substring="Hotel",
    ),
    # --------------------------------------------------------------
    # 5. London, GBP, 5-star + SPA amenity. Double-filter case —
    #    hotel_class AND amenity must both apply.
    # --------------------------------------------------------------
    BrowserCase(
        label="london-gbp-5star-spa",
        query="London Mayfair hotels",
        currency="GBP",
        filters=HotelSearchFilters(
            location=Location(query="London Mayfair hotels"),
            dates=DATES,
            currency=Currency.GBP,
            hotel_class=[5],
            amenities=[Amenity.SPA],
        ),
        anchor_hotel_substring="Hotel",
        expected_amenity_keyword="Spa",
    ),
    # --------------------------------------------------------------
    # 6. Rome, EUR, sort=HIGHEST_RATING. Verifies sort is applied —
    #    top hotels should be ≥4.5 stars.
    # --------------------------------------------------------------
    BrowserCase(
        label="rome-eur-sort-rating",
        query="Rome hotels",
        currency="EUR",
        filters=HotelSearchFilters(
            location=Location(query="Rome hotels"),
            dates=DATES,
            currency=Currency.EUR,
            sort_by=SortBy.HIGHEST_RATING,
        ),
        anchor_hotel_substring="Hotel",
    ),
    # --------------------------------------------------------------
    # 7. Singapore, SGD, HILTON brand filter. Single-brand scope —
    #    EVERY result must be a Hilton-family property. This catches
    #    the regression (found 2026-04-22) where ``[[brand_id, []]]`` was
    #    accepted by Google but silently dropped, returning a generic
    #    unfiltered hotel list.
    # --------------------------------------------------------------
    BrowserCase(
        label="singapore-sgd-hilton-brand",
        query="Singapore hotels",
        currency="SGD",
        filters=HotelSearchFilters(
            location=Location(query="Singapore hotels"),
            dates=DATES,
            currency=Currency.SGD,
            brands=[Brand.HILTON],
        ),
        anchor_hotel_substring="Hilton",
        brand_name_tokens=(
            "Hilton",
            "Hampton",
            "Canopy",
            "DoubleTree",
            "Waldorf",
            "Conrad",
            "Embassy",
            "Tempo",
            "Motto",
            "Tapestry",
            "Curio",
            "Tru",
        ),
    ),
    # --------------------------------------------------------------
    # 8. Sydney, AUD, family party (2 adults + 1 child age 8). Exercises
    #    GuestInfo serialization with child age buckets.
    # --------------------------------------------------------------
    BrowserCase(
        label="sydney-aud-family",
        query="Sydney hotels",
        currency="AUD",
        filters=HotelSearchFilters(
            location=Location(query="Sydney hotels"),
            dates=DATES,
            currency=Currency.AUD,
            guests=GuestInfo(adults=2, children=1, child_ages=[8]),
        ),
        anchor_hotel_substring="Hotel",
    ),
    # --------------------------------------------------------------
    # 9. Dubai luxury, USD, 5-star + POOL amenity. Another multi-filter
    #    luxury-segment check.
    # --------------------------------------------------------------
    BrowserCase(
        label="dubai-usd-5star-pool",
        query="Dubai hotels",
        currency="USD",
        filters=HotelSearchFilters(
            location=Location(query="Dubai hotels"),
            dates=DATES,
            currency=Currency.USD,
            hotel_class=[5],
            amenities=[Amenity.POOL],
        ),
        anchor_hotel_substring="Hotel",
        expected_amenity_keyword="Pool",
    ),
    # --------------------------------------------------------------
    # 10. Hong Kong, HKD, eco_certified filter. Exercises the
    #     eco-certified filter + HKD currency.
    # --------------------------------------------------------------
    BrowserCase(
        label="hongkong-hkd-eco",
        query="Hong Kong hotels",
        currency="HKD",
        filters=HotelSearchFilters(
            location=Location(query="Hong Kong hotels"),
            dates=DATES,
            currency=Currency.HKD,
            eco_certified=True,
        ),
        anchor_hotel_substring="Hotel",
    ),
]
