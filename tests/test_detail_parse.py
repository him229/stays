"""Unit tests for parse_detail_response against a fixture.

NOTE: These tests depend on a detail-response fixture carved from
captures/hotel_detail_raw.json during Task 13. If the fixture does not
exist, the tests skip so the rest of the suite stays green.
"""

import json
from pathlib import Path

import pytest

from stays.search.parse import parse_detail_response
from stays.search.parse.detail_parser import _parse_amenity_details

FIXTURE = Path(__file__).parent / "fixtures" / "detail_response_sample.json"


pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(),
    reason="detail fixture not yet carved from captures/hotel_detail_raw.json",
)


def _load():
    return json.loads(FIXTURE.read_text())


def test_parse_detail_returns_HotelDetail():
    out = parse_detail_response(_load())
    assert out.name


def test_parse_detail_populates_entity_key():
    out = parse_detail_response(_load())
    # Detail responses should surface the entity_key too (same hotel entry).
    assert out.entity_key is None or len(out.entity_key) >= 10


def test_detail_has_rooms_or_rates():
    out = parse_detail_response(_load())
    # Detail response should expose at least one RoomType OR at least one rate.
    any_rate = any(len(room.rates) >= 1 for room in out.rooms)
    assert len(out.rooms) >= 1 and any_rate, f"detail response produced {len(out.rooms)} rooms and any_rate={any_rate}"


def test_rooms_have_rate_plans_with_provider_and_price():
    out = parse_detail_response(_load())
    found = False
    for room in out.rooms:
        for rate in room.rates:
            if rate.provider and rate.price:
                found = True
                break
    assert found, "no rate plan had both provider and price"


def test_requested_currency_labels_hotel_and_provider_rates():
    out = parse_detail_response(_load(), requested_currency="GBP")

    assert out.currency == "GBP"
    rates = [rate for room in out.rooms for rate in room.rates]
    assert rates
    assert {rate.currency for rate in rates} == {"GBP"}


def test_detail_populates_description_or_phone_or_address():
    out = parse_detail_response(_load())
    # At least one of these enrichment fields should populate.
    assert out.description or out.phone or out.address


def test_detail_amenities_exclude_headings_duplicates_and_business_snippets():
    out = parse_detail_response(_load())

    assert out.amenity_details == ["LGBTQ+ friendly"]


def test_parse_amenity_details_returns_unique_plain_text_labels():
    subtree = [
        [
            [
                "Dining",
                [
                    ["<b>Breakfast</b>", True],
                    ["Breakfast", True],
                    ["Spa &amp; wellness", True],
                ],
            ]
        ],
        [],
        ["Restaurant Name | Example Hotel"],
    ]

    assert _parse_amenity_details(subtree) == ["Breakfast", "Spa & wellness"]


def test_reviews_have_sensible_ratings_if_present():
    out = parse_detail_response(_load())
    for rv in out.recent_reviews:
        assert 1 <= rv.rating <= 5
        assert rv.body


def test_detail_finds_exactly_one_hotel_entry():
    """Regression guard: after relaxing ``_find_hotel_entries``'s heuristic
    to not require a star-class tuple, the detail parser (which reuses the
    same walker and picks entries[0]) must still resolve to exactly ONE
    hotel entry — not a false-positive second entry.
    """
    from stays.search.parse.search_parser import _find_hotel_entries

    entries = _find_hotel_entries(_load())
    assert len(entries) == 1, f"detail response should yield exactly 1 hotel entry; got {len(entries)}"
