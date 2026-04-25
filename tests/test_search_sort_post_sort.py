"""Offline unit tests for ``SearchHotels.search`` post-sort semantics.

Verifies that the library-layer stable sort applied after parsing:
  - sorts LOWEST_PRICE ascending, HIGHEST_RATING / MOST_REVIEWED descending
  - pushes None values to the end on every mode
  - is a no-op for RELEVANCE / None (preserves parser order)
  - preserves input order for exact ties (Python sort stability)

Stubs out the network + parser so only the post-sort layer is exercised.
"""

from __future__ import annotations

import pytest

from stays.models.google_hotels.base import Location, SortBy
from stays.models.google_hotels.hotels import HotelSearchFilters
from stays.models.google_hotels.result import HotelResult
from stays.search.hotels import SearchHotels


def _result(
    *, name: str, price: int | None = None, rating: float | None = None, reviews: int | None = None
) -> HotelResult:
    return HotelResult(name=name, display_price=price, overall_rating=rating, review_count=reviews)


def _make_search_hotels(parsed: list[HotelResult]) -> SearchHotels:
    class _StubClient:
        def post_rpc(self, rpc_id, inner_payload):
            return "SENTINEL"

    s = SearchHotels(client=_StubClient())

    # Monkey-patch the parser used inside s.search so we can inject parsed hotels directly.
    import stays.search.hotels as hotels_mod

    hotels_mod.parse_search_response = lambda _resp: list(parsed)  # type: ignore[assignment]
    return s


@pytest.fixture
def filters() -> HotelSearchFilters:
    return HotelSearchFilters(location=Location(query="anywhere"))


def test_lowest_price_sorts_ascending(filters, monkeypatch):
    parsed = [
        _result(name="B", price=22),
        _result(name="A", price=14),
        _result(name="C", price=18),
    ]
    s = _make_search_hotels(parsed)
    filters.sort_by = SortBy.LOWEST_PRICE
    out = s.search(filters)
    assert [h.name for h in out] == ["A", "C", "B"]
    assert [h.display_price for h in out] == [14, 18, 22]


def test_lowest_price_none_sorts_last(filters):
    parsed = [
        _result(name="withprice1", price=30),
        _result(name="noprice", price=None),
        _result(name="withprice2", price=20),
    ]
    s = _make_search_hotels(parsed)
    filters.sort_by = SortBy.LOWEST_PRICE
    out = s.search(filters)
    assert [h.name for h in out] == ["withprice2", "withprice1", "noprice"]


def test_highest_rating_sorts_descending_none_last(filters):
    parsed = [
        _result(name="mid", rating=4.3),
        _result(name="none", rating=None),
        _result(name="best", rating=4.9),
        _result(name="low", rating=3.5),
    ]
    s = _make_search_hotels(parsed)
    filters.sort_by = SortBy.HIGHEST_RATING
    out = s.search(filters)
    assert [h.name for h in out] == ["best", "mid", "low", "none"]


def test_most_reviewed_sorts_descending_none_last(filters):
    parsed = [
        _result(name="mid", reviews=500),
        _result(name="none", reviews=None),
        _result(name="biggest", reviews=10000),
        _result(name="small", reviews=50),
    ]
    s = _make_search_hotels(parsed)
    filters.sort_by = SortBy.MOST_REVIEWED
    out = s.search(filters)
    assert [h.name for h in out] == ["biggest", "mid", "small", "none"]


def test_relevance_is_noop(filters):
    parsed = [
        _result(name="first", price=30),
        _result(name="second", price=10),
        _result(name="third", price=20),
    ]
    s = _make_search_hotels(parsed)
    filters.sort_by = SortBy.RELEVANCE
    out = s.search(filters)
    assert [h.name for h in out] == ["first", "second", "third"]


def test_no_sort_by_is_noop(filters):
    parsed = [
        _result(name="first", price=30),
        _result(name="second", price=10),
    ]
    s = _make_search_hotels(parsed)
    # filters.sort_by defaults to None
    out = s.search(filters)
    assert [h.name for h in out] == ["first", "second"]


def test_sort_is_stable_for_ties(filters):
    # Two hotels at $20 — Google's order (A then C) must be preserved after sort.
    parsed = [
        _result(name="A_first_of_tie", price=20),
        _result(name="B_cheaper", price=14),
        _result(name="C_second_of_tie", price=20),
    ]
    s = _make_search_hotels(parsed)
    filters.sort_by = SortBy.LOWEST_PRICE
    out = s.search(filters)
    assert [h.name for h in out] == ["B_cheaper", "A_first_of_tie", "C_second_of_tie"]
