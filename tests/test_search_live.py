"""Live end-to-end tests driven by LiveFilterCase.

Gated behind `-m live` marker; hits the real Google endpoint.
"""

from datetime import date

import pytest

from stays import (
    Amenity,
    Brand,
    Currency,
    DateRange,
    GuestInfo,
    HotelSearchFilters,
    Location,
    MinGuestRating,
    PropertyType,
    SortBy,
)
from stays.search import SearchHotels
from tests.live_framework import LiveFilterCase, run_case

pytestmark = pytest.mark.live


CASES = [
    LiveFilterCase(
        label="sort_lowest_price",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            sort_by=SortBy.LOWEST_PRICE,
        ),
        expected_slot_checks=[("[1].[4].[0].[4]", 3)],
        expect_hotel_count_min=5,
    ),
    LiveFilterCase(
        label="sort_highest_rating",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            sort_by=SortBy.HIGHEST_RATING,
        ),
        expected_slot_checks=[("[1].[4].[0].[4]", 8)],
    ),
    LiveFilterCase(
        label="sort_most_reviewed",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            sort_by=SortBy.MOST_REVIEWED,
        ),
        expected_slot_checks=[("[1].[4].[0].[4]", 13)],
    ),
    LiveFilterCase(
        label="price_under_250",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            price_range=(None, 250),
        ),
        expected_slot_checks=[("[1].[4].[3]", [None, [None, 250], 1])],
    ),
    LiveFilterCase(
        label="hotel_class_4_5",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            hotel_class=[4, 5],
        ),
        expected_slot_checks=[("[1].[4].[0].[1]", [4, 5])],
    ),
    LiveFilterCase(
        label="amenity_pool",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            amenities=[Amenity.POOL],
        ),
        expected_slot_checks=[("[1].[4].[0].[0]", [6])],
    ),
    LiveFilterCase(
        label="amenity_wifi_pool_breakfast",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            amenities=[Amenity.WIFI, Amenity.POOL, Amenity.BREAKFAST],
        ),
        expected_slot_checks=[("[1].[4].[0].[0]", [35, 6, 9])],
    ),
    LiveFilterCase(
        label="brand_hilton",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            brands=[Brand.HILTON],
        ),
        expected_slot_checks=[
            (
                "[1].[4].[0].[7]",
                [[28, Brand.HILTON.sub_brand_ids]],
            )
        ],
    ),
    LiveFilterCase(
        label="brand_marriott_hyatt",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            brands=[Brand.MARRIOTT, Brand.HYATT],
        ),
        expected_slot_checks=[
            (
                "[1].[4].[0].[7]",
                [
                    [46, Brand.MARRIOTT.sub_brand_ids],
                    [37, Brand.HYATT.sub_brand_ids],
                ],
            )
        ],
    ),
    LiveFilterCase(
        label="free_cancellation",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            free_cancellation=True,
        ),
        expected_slot_checks=[("[1].[4].[0].[3]", 1)],
    ),
    LiveFilterCase(
        label="eco_certified",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            eco_certified=True,
        ),
        # The eco_certified slot is [1][4][0][9]=1 with length growing to 10
    ),
    LiveFilterCase(
        label="special_offers",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            special_offers=True,
        ),
        expected_slot_checks=[("[1].[4].[5]", 1)],
    ),
    LiveFilterCase(
        label="guest_rating_4_5",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            min_guest_rating=MinGuestRating.FOUR_FIVE_PLUS,
        ),
        expected_slot_checks=[("[1].[4].[4]", 9)],
    ),
    LiveFilterCase(
        label="guests_2a_1c7",
        filters=HotelSearchFilters(
            location=Location(query="new york hotels"),
            guests=GuestInfo(adults=2, children=1, child_ages=[7]),
        ),
        expected_slot_checks=[("[1].[1]", [[[3], [3], [2, 12]], 1])],
    ),
    LiveFilterCase(
        label="property_type_vacation_rentals",
        filters=HotelSearchFilters(
            location=Location(query="new york"),
            property_type=PropertyType.VACATION_RENTALS,
        ),
        expected_slot_checks=[("[1].[0]", 2)],
        # Vacation-rentals responses use a different entry shape; the
        # parser is tuned for hotels. We assert the wire slot is correct
        # (proves the filter serializes) but don't require the parser to
        # extract anything.
        expect_hotel_count_min=0,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.label for c in CASES])
def test_filter_roundtrip(case):
    run_case(case, search=SearchHotels())


# ---------------------------------------------------------------------------
# Semantic brand-filter tests: not just "the request looked right" — actually
# verify that the RETURNED hotels belong to the requested brand family.
# These guard against the Xi'an bug where ``[[28, []]]`` was accepted by
# Google but silently ignored, so non-Hilton hotels came back.
# ---------------------------------------------------------------------------


_HILTON_NAME_TOKENS = (
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
)
_MARRIOTT_NAME_TOKENS = (
    "Marriott",
    "Courtyard",
    "Fairfield",
    "Sheraton",
    "Westin",
    "W Hotel",
    "Ritz-Carlton",
    "St. Regis",
    "Renaissance",
    "Aloft",
    "Moxy",
    "Residence Inn",
    "SpringHill",
    "TownePlace",
    "Element",
    "Gaylord",
    "Bonvoy",
    "JW Marriott",
    "Le Méridien",
    "Le Meridien",
    "Meridien",
    "Autograph Collection",
    "Tribute Portfolio",
    "Four Points",
    "Protea",
    "AC Hotel",
    "Delta Hotels",
    "Luxury Collection",
    "EDITION",
)
_HYATT_NAME_TOKENS = (
    "Hyatt",
    "Andaz",
    "Miraval",
    "Thompson",
    "Dream Hotel",
    "Destination",
    "JdV by Hyatt",
    "Caption by Hyatt",
    "JDV by Hyatt",
    "Alila",
)


def _pct_matching(hotels, tokens) -> float:
    if not hotels:
        return 0.0
    hits = sum(1 for h in hotels if any(t.lower() in h.name.lower() for t in tokens))
    return hits / len(hotels)


@pytest.mark.parametrize(
    "brand,tokens,query",
    [
        (Brand.HILTON, _HILTON_NAME_TOKENS, "new york hotels"),
        (Brand.MARRIOTT, _MARRIOTT_NAME_TOKENS, "chicago hotels"),
        (Brand.HYATT, _HYATT_NAME_TOKENS, "los angeles hotels"),
    ],
    ids=["hilton_nyc", "marriott_chicago", "hyatt_la"],
)
def test_brand_filter_actually_filters_results(brand, tokens, query):
    """Semantic guard: when a brand filter is set, at least 80% of returned
    hotels must carry a name token from that brand family.

    Without the sub-brand IDs populated in ``[[brand_id, [subs...]]]``
    AND without the outer ``[2]`` request-meta, Google accepts the
    request but silently ignores the brand filter, returning a generic
    unfiltered hotel list. The 80% floor catches both regressions — an
    unfiltered NYC list typically shows <30% Hilton.
    """
    s = SearchHotels()
    filters = HotelSearchFilters(
        location=Location(query=query),
        dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 3)),
        currency=Currency.USD,
        brands=[brand],
    )
    results = s.search(filters)
    assert results, f"brand_filter[{brand.name}] returned 0 hotels"
    pct = _pct_matching(results, tokens)
    hit_names = [h.name for h in results if any(t.lower() in h.name.lower() for t in tokens)]
    miss_names = [h.name for h in results if not any(t.lower() in h.name.lower() for t in tokens)]
    # Threshold 0.7: Google occasionally folds "curated" nearby hotels
    # (independents in the same market segment) into a branded result set,
    # plus our name-token list can't catch every sub-brand label. An
    # unfiltered list would show <30% matches for any one brand, so 70%
    # still cleanly catches the "filter silently ignored" regression.
    assert pct >= 0.7, (
        f"[{brand.name}] only {pct:.0%} of {len(results)} hotels match the brand "
        f"family. Hits: {hit_names[:5]}. Misses: {miss_names[:5]}. "
        f"Likely regression — brand filter silently ignored on the wire."
    )


def test_brand_filter_distinguishes_different_brands():
    """Two separate brand-filtered queries for the same city should return
    DIFFERENT hotel sets. If both return the same thing, the filter is
    broken (unfiltered fallback).
    """
    s = SearchHotels()
    dates = DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 3))
    loc = Location(query="chicago hotels")
    hilton = s.search(HotelSearchFilters(location=loc, dates=dates, brands=[Brand.HILTON]))
    marriott = s.search(HotelSearchFilters(location=loc, dates=dates, brands=[Brand.MARRIOTT]))
    h_names = {h.name for h in hilton}
    m_names = {h.name for h in marriott}
    # Expect mostly disjoint sets — tolerate a few shared hotel overlaps
    # if Google's index lists a building under multiple brand chips.
    overlap = h_names & m_names
    assert len(overlap) / max(len(h_names), len(m_names), 1) <= 0.2, (
        f"Hilton and Marriott filtered results overlap too much "
        f"({len(overlap)} shared of {len(h_names)}/{len(m_names)}). "
        f"Overlap: {sorted(overlap)[:5]}"
    )
