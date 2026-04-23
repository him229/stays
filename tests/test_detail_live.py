"""Live tests for get_details + search_with_details (hit the real endpoint)."""

from datetime import date

import pytest

from stays import DateRange, HotelSearchFilters, Location
from stays.search import EnrichedResult, SearchHotels

pytestmark = pytest.mark.live


def _sample_entity_key_and_name() -> tuple[str, str]:
    s = SearchHotels()
    results = s.search(HotelSearchFilters(location=Location(query="new york hotels")))
    with_keys = [r for r in results if r.entity_key]
    assert with_keys, "search should yield at least one hotel with an entity_key"
    return with_keys[0].entity_key, with_keys[0].name


def test_get_details_returns_hotel_detail():
    entity_key, name = _sample_entity_key_and_name()
    s = SearchHotels()
    detail = s.get_details(
        entity_key=entity_key,
        dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
    )
    assert detail.name  # extracted from the detail response's hotel entry
    # entity_key should round-trip back
    assert detail.entity_key


def test_get_details_populates_at_least_one_enrichment_field():
    entity_key, _ = _sample_entity_key_and_name()
    s = SearchHotels()
    detail = s.get_details(
        entity_key=entity_key,
        dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
    )
    # At least one of description / phone / address / rooms should populate
    populated = (
        bool(detail.description)
        or bool(detail.phone)
        or bool(detail.address)
        or bool(detail.rooms)
        or bool(detail.amenity_details)
    )
    assert populated, (
        "detail response populated no enrichment fields; parser likely not finding the right slots in the response"
    )


def test_search_with_details_returns_enriched_results():
    s = SearchHotels()
    filters = HotelSearchFilters(
        location=Location(query="new york hotels"),
        dates=DateRange(check_in=date(2026, 9, 1), check_out=date(2026, 9, 4)),
    )
    items = s.search_with_details(filters, max_hotels=3)
    assert len(items) == 3
    for item in items:
        assert isinstance(item, EnrichedResult)
        assert item.result is not None
        assert (item.detail is not None) ^ (item.error is not None), f"Exactly one of detail/error must be set: {item}"
    # Under normal conditions we expect at least one to succeed.
    ok = [i for i in items if i.ok]
    assert len(ok) >= 1, "expected at least 1/3 enrichments to succeed live"
